import time
"""
Evaluation script for GeminiLLMProvider against labeled replies.
Target: No false 'choose' decisions on ambiguous, adversarial, or out-of-range replies.
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta

# Ensure project root is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.providers.llm_provider import GeminiLLMProvider, NoOpLLMProvider, LLMTransientError
from app.schemas.agent import AgentDecision


def run_eval():
    fixtures_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests",
        "fixtures",
        "replies.json",
    )
    if not os.path.exists(fixtures_path):
        print(f"Error: Fixtures file not found at {fixtures_path}")
        sys.exit(1)

    with open(fixtures_path, "r", encoding="utf-8") as f:
        dataset = json.load(f)

    api_key = settings.llm_api_key or os.getenv("LLM_API_KEY", "")
    if not api_key:
        print("[SKIP] LLM_API_KEY is not configured in .env or environment.")
        print("Set LLM_API_KEY to run live evaluations against Gemini API.")
        return 0

    provider = GeminiLLMProvider()
    print(f"Starting LLM Evaluation on {len(dataset)} examples using {settings.llm_model}...")
    print("=" * 75)

    base_time = datetime.now(timezone.utc)
    slots = [
        {"label": "A", "when": (base_time + timedelta(days=2)).strftime("%A, %b %d at 10:00 UTC"), "mode": "virtual"},
        {"label": "B", "when": (base_time + timedelta(days=2)).strftime("%A, %b %d at 14:00 UTC"), "mode": "virtual"},
        {"label": "C", "when": (base_time + timedelta(days=3)).strftime("%A, %b %d at 11:00 UTC"), "mode": "virtual"},
    ]

    total = len(dataset)
    passed = 0
    failures = []
    false_positives = 0  # Crucial safety check: choose when it should NOT be choose

    for item in dataset:
        item_id = item["id"]
        text = item["text"]
        expected_intent = item["expected_intent"]
        expected_slot = item.get("expected_slot")
        category = item.get("category", "")

        context = {
            "candidate_id": f"eval-cand-{item_id}",
            "first_name": "TestCandidate",
            "job_title": "Senior Distributed Systems Engineer",
            "timezone": "Asia/Kolkata",
            "offered_slots": slots,
            "history": [
                {"direction": "outbound", "summary": "Please choose from Option A, Option B, or Option C."}
            ],
            "reply_text": text,
        }

        try:
            decision = None
            for attempt in range(4):
                try:
                    decision = provider.classify(text, context)
                    break
                except LLMTransientError as te:
                    if "429" in str(te) or "ResourceExhausted" in str(te):
                        time.sleep(6 * (attempt + 1))
                    elif attempt < 3:
                        time.sleep(2)
                    else:
                        raise te

            actual_intent = decision.intent
            actual_slot = decision.slot_label
            confidence = decision.confidence

            # Verification logic
            intent_ok = (actual_intent == expected_intent) or (category == "recruiter_query" and actual_intent in ("question", "none_fit"))
            slot_ok = (expected_slot is None) or (actual_slot == expected_slot)

            # Strict guard: Ambiguous or adversarial MUST NOT be 'choose'
            if category in ("ambiguous", "adversarial", "invalid_slot") and actual_intent == "choose":
                false_positives += 1
                intent_ok = False

            if intent_ok and slot_ok:
                passed += 1
                status = "PASS"
            else:
                failures.append({
                    "id": item_id,
                    "text": text,
                    "category": category,
                    "expected": f"intent={expected_intent}, slot={expected_slot}",
                    "actual": f"intent={actual_intent}, slot={actual_slot}, conf={confidence:.2f}",
                })
                status = "FAIL"

            print(f"[{status}] #{item_id} ({category}): {actual_intent.upper()} (conf={confidence:.2f}) | text: '{text}'")

        except Exception as e:
            failures.append({
                "id": item_id,
                "text": text,
                "category": category,
                "expected": f"intent={expected_intent}",
                "actual": f"EXCEPTION: {type(e).__name__} - {e}",
            })
            print(f"[ERR] #{item_id}: {type(e).__name__}: {e}")

    print("=" * 75)
    print(f"Evaluation Summary: {passed}/{total} Passed ({passed/total*100:.1f}%)")
    print(f"False 'choose' count (Safety violations): {false_positives}")

    if failures:
        print("\nFailures:")
        for f in failures:
            print(f"  - #{f['id']} [{f['category']}]: expected [{f['expected']}] got [{f['actual']}]")
            print(f"    input: {f['text']}")

    if false_positives > 0:
        print("\nSAFETY ALERT: Model classified ambiguous or adversarial input as 'choose'!")
        return 1

    return 0 if (passed / total) >= 0.85 else 1


if __name__ == "__main__":
    sys.exit(run_eval())
