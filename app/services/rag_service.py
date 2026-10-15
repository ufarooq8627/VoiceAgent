import math
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.models.receptionist import KnowledgeItem
from app.config import settings

# In-memory vector cache: item_id -> list of float embeddings
_EMBEDDING_CACHE: Dict[str, List[float]] = {}


def _cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """Calculate cosine similarity between two float vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0
    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot_product / (norm_a * norm_b)


class RAGService:
    """
    Semantic Retrieval-Augmented Generation (RAG) Service
    powered by Gemini Embeddings.
    """

    @classmethod
    def get_embedding(cls, text: str) -> Optional[List[float]]:
        """Compute 3072-dim vector embedding using Gemini API."""
        try:
            from google import genai
            client = genai.Client(api_key=settings.llm_api_key)
            resp = client.models.embed_content(
                model="gemini-embedding-001",
                contents=text.strip(),
            )
            if hasattr(resp, "embedding") and resp.embedding:
                return resp.embedding.values
            elif hasattr(resp, "embeddings") and resp.embeddings:
                return resp.embeddings[0].values
            return None
        except Exception as e:
            print(f"[RAG Embedding Error] {e}")
            return None

    @classmethod
    def search_knowledge(
        cls,
        db: Session,
        business_id: str,
        query: str,
        threshold: float = 0.65,
        top_k: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search using Gemini embeddings with cosine similarity.
        Falls back to keyword matching only if embedding API is unavailable.
        """
        now = datetime.now(timezone.utc)
        items = (
            db.query(KnowledgeItem)
            .filter(
                KnowledgeItem.business_id == business_id,
                KnowledgeItem.status == "approved",
                KnowledgeItem.valid_from <= now,
                or_(
                    KnowledgeItem.valid_until.is_(None),
                    KnowledgeItem.valid_until >= now,
                ),
            )
            .all()
        )

        if not items:
            return []

        # 1. Try Semantic Embedding Search
        query_embedding = cls.get_embedding(query)
        if query_embedding:
            scored_items = []
            for item in items:
                # Check cache for item embedding
                cache_key = f"{item.id}_{item.question}"
                if cache_key not in _EMBEDDING_CACHE:
                    item_text = f"Question: {item.question}\nAnswer: {item.answer}"
                    item_emb = cls.get_embedding(item_text)
                    if item_emb:
                        _EMBEDDING_CACHE[cache_key] = item_emb

                item_emb = _EMBEDDING_CACHE.get(cache_key)
                if item_emb:
                    score = _cosine_similarity(query_embedding, item_emb)
                    if score >= threshold:
                        scored_items.append((score, item))

            scored_items.sort(key=lambda x: x[0], reverse=True)
            if scored_items:
                results = []
                for score, item in scored_items[:top_k]:
                    print(f"[RAG Match] '{query}' matched '{item.question}' with score {score:.3f}")
                    results.append({
                        "id": item.id,
                        "question": item.question,
                        "answer": item.answer,
                        "category": item.category,
                        "score": round(score, 3),
                    })
                return results

            # If semantic search completed but highest score was below threshold:
            print(f"[RAG Miss] Query '{query}' did not meet similarity threshold {threshold}")
            return []

        # 2. Strict Fallback: Only if embedding API fails, use high-precision token intersection
        # (NOT single word match to prevent "or" matching "New York")
        query_tokens = set(t.lower() for t in query.split() if len(t) > 3)
        fallback_results = []
        for item in items:
            q_tokens = set(t.lower() for t in item.question.split() if len(t) > 3)
            intersection = query_tokens.intersection(q_tokens)
            # Require at least 2 meaningful keyword overlaps
            if len(intersection) >= 2 or (len(query_tokens) == 1 and len(intersection) == 1):
                fallback_results.append({
                    "id": item.id,
                    "question": item.question,
                    "answer": item.answer,
                    "category": item.category,
                    "score": 0.5,
                })
        return fallback_results
