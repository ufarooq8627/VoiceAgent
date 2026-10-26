_client = None

def get_gemini_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=settings.llm_api_key)
    return _client

from dataclasses import dataclass, field
from app.agent.receptionist_tools import ReceptionistTools
from app.config import settings


@dataclass
class AgentTurnResult:
    spoken_response: str
    tools_invoked: list[str] = field(default_factory=list)
    actions_taken: list[dict] = field(default_factory=list)


class GeminiReceptionistAgent:

    def __init__(self, business_name: str, tools: ReceptionistTools, caller_number: str | None = None):
        self.business_name = business_name
        self.tools = tools
        self.caller_number = caller_number

    def get_opening_greeting(self) -> str:
        return f"Hello, thank you for calling {self.business_name}. I am an AI voice receptionist. How may I help you today?"

    def process_turn(self, history: list[dict], caller_message: str) -> AgentTurnResult:
        """
        Processes a caller turn using Retrieval-Augmented Generation (RAG)
        powered by Google Gemini multimodal/LLM API.
        """
        msg_clean = caller_message.strip()
        msg_lower = msg_clean.lower()
        tools_invoked = []
        actions_taken = []

        # 1. Safety and Operational Boundary Checks
        if any(w in msg_lower for w in ["ignore all previous", "ignore your instructions", "system instructions", "system prompt"]):
            return AgentTurnResult(
                spoken_response="I am an AI assistant for this business and cannot ignore my operational guidelines. How may I assist you with your enquiry today?",
                tools_invoked=[],
                actions_taken=[]
            )

        if any(w in msg_lower for w in ["home address", "personal cell", "personal number", "personal phone"]):
            return AgentTurnResult(
                spoken_response="That information is private and confidential. I cannot share personal details of our owners or staff.",
                tools_invoked=[],
                actions_taken=[]
            )

        # 2. Check for callback confirmation flow
        affirmative = ["yes that's correct", "yes, that is correct", "correct", "that's right", "please do", "yes call me", "call me back", "call me", "yes please", "yes", "sure", "please"]
        if any(w in msg_lower for w in affirmative):
            last_agent = next((h["content"] for h in reversed(history) if h.get("role") in ["agent", "assistant"]), "")
            if "callback" in last_agent.lower() or "team" in last_agent.lower():
                resolved_phone = self.caller_number or self.tools.get_caller_number()
                if not resolved_phone or str(resolved_phone).strip().lower() in ("", "none", "unknown", "anonymous"):
                    return AgentTurnResult(
                        spoken_response="I would be happy to schedule a callback for you. Could you please provide your best contact phone number so our team can reach you?",
                        tools_invoked=[],
                        actions_taken=[]
                    )
                res = self.tools.schedule_callback(
                    customer_name="Caller",
                    phone_number=str(resolved_phone).strip(),
                    confirmed_by_caller=True
                )
                tools_invoked.append("schedule_callback")
                actions_taken.append(res)
                return AgentTurnResult(
                    spoken_response=f"Thank you! I have confirmed your callback request at {str(resolved_phone).strip()}. Our team will contact you shortly.",
                    tools_invoked=tools_invoked,
                    actions_taken=actions_taken
                )

        # 3. Retrieve relevant business knowledge via RAG
        faq_res = self.tools.search_faq(msg_clean)
        tools_invoked.append("search_faq")
        actions_taken.append(faq_res)

        # Build verified context
        if faq_res["found"]:
            context_snippets = [f"- {r['question']}: {r['answer']}" for r in faq_res["results"]]
            context_text = "\n".join(context_snippets)
        else:
            context_text = f"No specific verified business knowledge found for this query regarding {self.business_name}." 

        # 4. Generate Grounded Response via Gemini
        try:
            client = get_gemini_client()

            prompt = f"""You are the AI voice receptionist for {self.business_name}.
Verified Business Knowledge:
{context_text}

Caller: "{msg_clean}"

Instructions:
1. Speak in 1-2 natural, polite sentences as a telephone receptionist.
2. Ground your answer strictly in the verified knowledge above.
3. If the caller asks about something outside our services or scope, state clearly that we do not offer that service and ask if they would like our team to give them a callback.
"""
            response = client.models.generate_content(
                model=settings.llm_model or "gemini-3.5-flash-lite",
                contents=prompt
            )
            answer_text = response.text.strip() if response.text else ""

            # Check if answer indicates an unhandled enquiry
            if any(w in answer_text.lower() for w in ["callback", "do not have", "don't have", "not provide", "not offer"]):
                log_res = self.tools.record_unanswered_question(msg_clean, "unhandled_or_callback_offered")
                tools_invoked.append("record_unanswered_question")
                actions_taken.append(log_res)

            return AgentTurnResult(
                spoken_response=answer_text,
                tools_invoked=tools_invoked,
                actions_taken=actions_taken
            )
        except Exception as e:
            print(f"[Gemini Agent Error] {e}")
            if faq_res["found"]:
                return AgentTurnResult(
                    spoken_response=faq_res["results"][0]["answer"],
                    tools_invoked=tools_invoked,
                    actions_taken=actions_taken
                )
            log_res = self.tools.record_unanswered_question(msg_clean, "llm_fallback")
            tools_invoked.append("record_unanswered_question")
            actions_taken.append(log_res)
            return AgentTurnResult(
                spoken_response="I don't have that information on file currently. Would you like our team to give you a callback with the answer?",
                tools_invoked=tools_invoked,
                actions_taken=actions_taken
            )
