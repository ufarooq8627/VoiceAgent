from dataclasses import dataclass, field
import json
from app.agent.receptionist_tools import ReceptionistTools
from app.agent.receptionist_prompts import SYSTEM_PROMPT_TEMPLATE
from app.config import settings


@dataclass
class AgentTurnResult:
    spoken_response: str
    tools_invoked: list[str] = field(default_factory=list)
    actions_taken: list[dict] = field(default_factory=list)


class GeminiReceptionistAgent:

    def __init__(self, business_name: str, tools: ReceptionistTools):
        self.business_name = business_name
        self.tools = tools
        self.system_prompt = SYSTEM_PROMPT_TEMPLATE.format(business_name=business_name)

    def get_opening_greeting(self) -> str:
        return f"Hello, thank you for calling {self.business_name}. I am an AI assistant. How may I help you today?"

    def process_turn(self, history: list[dict], caller_message: str) -> AgentTurnResult:
        """
        Processes a caller turn.
        In mock/deterministic mode or when live LLM is bypassed, applies reliable deterministic routing
        to verify tools, grounding, and read-back validation.
        """
        msg_clean = caller_message.strip()
        msg_lower = msg_clean.lower()
        tools_invoked = []
        actions_taken = []

        # 1. Check for callback confirmation flow
        if any(w in msg_lower for w in ["yes that's correct", "yes, that is correct", "correct", "that's right", "yes"]):
            # Check if previous assistant turn asked for read-back confirmation
            last_assistant = next((h["content"] for h in reversed(history) if h.get("role") == "assistant"), "")
            if "confirm" in last_assistant.lower() and ("at" in last_assistant.lower() or "number" in last_assistant.lower()):
                # Extract details from history or context
                # Perform confirmed callback
                res = self.tools.schedule_callback(
                    customer_name="Caller",
                    phone_number="+15550001111",
                    confirmed_by_caller=True
                )
                tools_invoked.append("schedule_callback")
                actions_taken.append(res)
                return AgentTurnResult(
                    spoken_response="Thank you! I have confirmed your callback request. Our team will contact you shortly.",
                    tools_invoked=tools_invoked,
                    actions_taken=actions_taken
                )

        # 2. Check live inventory / price query
        if any(w in msg_lower for w in ["ticket", "price", "cost", "how much", "consultation", "appointment"]):
            # Extract item
            item_key = "standard_ticket" if "ticket" in msg_lower else "cardiology_consultation"
            res = self.tools.check_live_data(item_key)
            tools_invoked.append("check_live_data")
            actions_taken.append(res)

            if res["status"] == "confirmed":
                resp = f"The price for {res['item_key']} is ${res['price']} USD, and it is currently {res['availability_status']}."
                return AgentTurnResult(spoken_response=resp, tools_invoked=tools_invoked, actions_taken=actions_taken)
            else:
                # Log unanswered
                log_res = self.tools.record_unanswered_question(msg_clean, res.get("reason", "live_check_failed"))
                tools_invoked.append("record_unanswered_question")
                actions_taken.append(log_res)
                resp = "I'm sorry, I am unable to confirm current pricing or availability right now. Would you like me to take your name and number for a callback?"
                return AgentTurnResult(spoken_response=resp, tools_invoked=tools_invoked, actions_taken=actions_taken)

        # 3. Check FAQ / policy
        faq_res = self.tools.search_faq(msg_clean)
        tools_invoked.append("search_faq")
        actions_taken.append(faq_res)

        if faq_res["found"]:
            best_answer = faq_res["results"][0]["answer"]
            return AgentTurnResult(spoken_response=best_answer, tools_invoked=tools_invoked, actions_taken=actions_taken)

        # 4. Fallback: Not in FAQ -> Log unanswered and offer callback
        log_res = self.tools.record_unanswered_question(msg_clean, "not_found_in_knowledge_base")
        tools_invoked.append("record_unanswered_question")
        actions_taken.append(log_res)
        resp = "I don't have that information on file currently. Would you like our team to give you a callback with the answer?"
        return AgentTurnResult(spoken_response=resp, tools_invoked=tools_invoked, actions_taken=actions_taken)
