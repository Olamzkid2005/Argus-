"""
EmbeddingService — unified embedding API calls and pgvector similarity search.

Extracted from Orchestrator._save_findings() closures and PGVectorRepository
to eliminate duplicated embedding logic across the codebase.

Handles:
  - Embedding API calls (OpenAI / OpenRouter)
  - Input validation
  - pgvector similarity search (deduplication)
  - Embedding storage
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class EmbeddingService:
    """Unified service for embedding generation and vector similarity operations."""

    def __init__(self, engagement_id: str):
        self.engagement_id = engagement_id
        self._llm_client = None
        self._pgvector = None

    # ── Validation ─────────────────────────────────────────────────────────

    @staticmethod
    def is_valid_embedding(emb: list) -> bool:
        return (
            isinstance(emb, list)
            and len(emb) > 0
            and all(isinstance(v, (int, float)) for v in emb)
        )

    # ── Embedding API ──────────────────────────────────────────────────────

    def get_embedding(self, text: str) -> list[float] | None:
        """Generate embedding vector for text via OpenAI or OpenRouter.

        Caches the LLMClient on first call.
        """
        api_key = None
        try:
            if self._llm_client is None:
                from llm_client import LLMClient
                self._llm_client = LLMClient()
            api_key = self._llm_client.api_key
        except Exception:
            pass

        if api_key:
            try:
                import httpx

                if api_key.startswith("sk-or-"):
                    url = "https://openrouter.ai/api/v1/embeddings"
                    model = "openai/text-embedding-3-small"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": os.getenv("NEXT_PUBLIC_APP_URL", "http://localhost:3000"),
                        "X-Title": "Argus Pentest Platform",
                    }
                else:
                    url = "https://api.openai.com/v1/embeddings"
                    model = "text-embedding-3-small"
                    headers = {
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    }

                resp = httpx.post(
                    url,
                    headers=headers,
                    json={"model": model, "input": text},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return data["data"][0]["embedding"]
            except Exception as e:
                logger.debug("Embedding API failed (non-fatal): %s", e)

        from database.repositories.pgvector_repository import PGVectorRepository
        return PGVectorRepository()._generate_embedding_fallback(text)

    # ── Similarity Search ──────────────────────────────────────────────────

    def find_existing_similar(
        self, text: str, threshold: float = 0.92
    ) -> dict | None:
        """Find an existing finding with similar embedding vector.

        Returns dict with 'id' and 'similarity' keys, or None.
        """
        if self._pgvector is None:
            from database.repositories.pgvector_repository import PGVectorRepository
            self._pgvector = PGVectorRepository()

        if not self._pgvector.check_pgvector_available():
            return None

        embedding = self.get_embedding(text)
        if not embedding or not self.is_valid_embedding(embedding):
            return None

        try:
            from database.connection import db_cursor
            emb_str = "[" + ",".join(map(str, embedding)) + "]"
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT f.id, f.type, f.severity, f.endpoint,
                           1 - (f.embedding <=> %s::vector) AS similarity
                    FROM findings f
                    WHERE f.engagement_id = %s AND f.embedding IS NOT NULL
                      AND (f.embedding <=> %s::vector) <= (1 - %s)
                    ORDER BY f.embedding <=> %s::vector LIMIT 1
                    """,
                    (emb_str, self.engagement_id, emb_str, threshold, emb_str),
                )
                row = cursor.fetchone()
                if row and float(row[4]) >= threshold:
                    return {"id": str(row[0]), "similarity": float(row[4])}
        except Exception as e:
            logger.debug("Similarity check failed (non-fatal): %s", e)

        return None

    # ── Storage ────────────────────────────────────────────────────────────

    @staticmethod
    def store_embedding(
        finding_id: str,
        engagement_id: str,
        embedding: list[float],
        text: str,
    ) -> None:
        """Store embedding vector for a finding via PGVectorRepository."""
        if not EmbeddingService.is_valid_embedding(embedding):
            return
        from database.repositories.pgvector_repository import PGVectorRepository
        PGVectorRepository().store_embedding(finding_id, engagement_id, embedding, text)
