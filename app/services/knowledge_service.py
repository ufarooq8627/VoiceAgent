import csv
import io
from datetime import datetime, timezone
from sqlalchemy import or_
from sqlalchemy.orm import Session
from app.models.receptionist import KnowledgeItem


class KnowledgeService:

    @classmethod
    def search_static(cls, db: Session, business_id: str, query: str) -> list[dict]:
        """Semantic RAG search using Gemini vector embeddings."""
        from app.services.rag_service import RAGService
        return RAGService.search_knowledge(db, business_id, query)

    @classmethod
    def bulk_import_csv(cls, db: Session, business_id: str, csv_text: str) -> dict:
        reader = csv.DictReader(io.StringIO(csv_text.strip()))
        imported_count = 0
        errors = []
        seen_questions = set()

        for idx, row in enumerate(reader, start=1):
            question = row.get("question", "").strip()
            answer = row.get("answer", "").strip()
            category = row.get("category", "general").strip() or "general"
            source = row.get("source", "csv_import").strip() or "csv_import"

            if not question or not answer:
                errors.append(f"Row {idx}: missing question or answer")
                continue

            if question.lower() in seen_questions:
                errors.append(f"Row {idx}: duplicate question '{question}'")
                continue

            seen_questions.add(question.lower())

            item = KnowledgeItem(
                business_id=business_id,
                question=question,
                answer=answer,
                category=category,
                source=source,
                status="pending_approval",
                valid_from=datetime.now(timezone.utc),
            )
            db.add(item)
            imported_count += 1

        db.commit()
        return {
            "success": imported_count > 0 or len(errors) == 0,
            "imported_count": imported_count,
            "errors": errors
        }

    @classmethod
    def approve_item(cls, db: Session, business_id: str, item_id: str) -> KnowledgeItem | None:
        item = db.query(KnowledgeItem).filter_by(id=item_id, business_id=business_id).first()
        if item:
            item.status = "approved"
            item.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(item)
        return item
