from sqlalchemy.orm import Session
from app.models import InboundMessage
from app.providers.llm_provider import get_llm_provider, BaseLLMProvider
from app.agent.loop import process_candidate_messages


class AgentService:
    @staticmethod
    def process_reply(
        db: Session,
        inbound_message_id: str,
        provider: BaseLLMProvider | None = None,
    ) -> None:
        msg = db.query(InboundMessage).filter(InboundMessage.id == inbound_message_id).first()
        if not msg or not msg.candidate_id:
            return
        if provider is None:
            provider = get_llm_provider()
        process_candidate_messages(db, msg.candidate_id, provider)
