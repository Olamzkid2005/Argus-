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

    def _api_key(self) -> str | None:
        """Lazy-load and cache the LLM API key."""
        if self._llm_client is None:
            try:
                from llm_client import LLMClient
                self._llm_client = LLMClient()
            except Exception:
                return None
        return getattr(self._llm_client, "api_key", None)

    @staticmethod
    def _build_embedding_request(api_key: str) -> dict:
        """Build URL, headers for embedding API based on API key prefix."""
        if api_key.startswith("sk-or-"):
            return {
                "url": "https://openrouter.ai/api/v1/embeddings",
                "model": "openai/text-embedding-3-small",
                "headers": {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": os.getenv("NEXT_PUBLIC_APP_URL", "http://localhost:3000"),
                    "X-Title": "Argus Pentest Platform",
                },
            }
        return {
            "url": "https://api.openai.com/v1/embeddings",
            "model": "text-embedding-3-small",
            "headers": {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        }

    def _call_embedding_api(self, text: str) -> list[float] | None:
        """Call the embedding API and return embedding or None."""
        api_key = self._api_key()
        if not api_key:
            return None
        try:
            import httpx

            req = self._build_embedding_request(api_key)
            resp = httpx.post(
                req["url"],
                headers=req["headers"],
                json={"model": req["model"], "input": text},
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["data"][0]["embedding"]
        except Exception as e:
            logger.debug("Embedding API failed (non-fatal): %s", e)
        return None

    def _pgvector_repo(self):
        """Lazy-loaded PGVectorRepository instance."""
        if self._pgvector is None:
            from database.repositories.pgvector_repository import PGVectorRepository
            self._pgvector = PGVectorRepository()
        return self._pgvector

    def get_embedding(self, text: str) -> list[float] | None:
        """Generate embedding vector for text via OpenAI or OpenRouter.

        Falls back to PGVectorRepository's hash-based fallback if the API
        call fails or no API key is configured.
        """
        embedding = self._call_embedding_api(text)
        if embedding:
            return embedding

        pg = self._pgvector_repo()
        return pg.generate_embedding_fallback(text) if hasattr(pg, 'generate_embedding_fallback') else None

    def get_embeddings_batch(self, texts: list[str]) -> list[list[float] | None]:
        """Generate embedding vectors for multiple texts in a single API call.

        OpenAI embeddings API supports `input: [...]` for batch requests.
        Returns a list the same length as texts; failed items fall back to
        individual API calls, then to hash-based fallback.
        """
        if not texts:
            return []

        # Try batch API call
        api_key = self._api_key()
        if api_key:
            try:
                import httpx

                req = self._build_embedding_request(api_key)
                resp = httpx.post(
                    req["url"],
                    headers=req["headers"],
                    json={"model": req["model"], "input": texts},
                    timeout=30,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    return [d["embedding"] for d in data["data"]]
            except Exception as e:
                logger.debug("Batch embedding API failed (non-fatal): %s", e)

        # Fall back to individual calls (which each fall back to hash)
        return [self.get_embedding(t) for t in texts]

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
