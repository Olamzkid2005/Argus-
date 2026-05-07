"""
pgvector Repository for Finding Similarity Search

Stores and queries vector embeddings for vulnerability findings,
enabling semantic similarity search across engagements.

Requires: pgvector extension installed on PostgreSQL
"""
import logging
import os

logger = logging.getLogger(__name__)

from database.connection import db_cursor, get_db


class PGVectorRepository:
    """
    Repository for storing and querying finding embeddings
    using pgvector for semantic similarity search.
    """

    # Embedding dimensions for OpenAI text-embedding-3-small
    EMBEDDING_DIMENSIONS = 1536

    # Similarity threshold for considering findings "similar"
    SIMILARITY_THRESHOLD = 0.85

    def __init__(self, db_connection_string: str | None = None):
        """
        Initialize PGVector repository

        Args:
            db_connection_string: Database connection string
        """
        self.db_connection_string = db_connection_string or os.getenv("DATABASE_URL")
        self._db = get_db() if self.db_connection_string else None

    def check_pgvector_available(self) -> bool:
        """
        Check if pgvector extension is available

        Returns:
            True if pgvector is available
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                )
                result = cursor.fetchone()
                return result is not None
        except Exception as e:
            logger.warning(f"pgvector not available: {e}")
            return False

    def store_embedding(
        self,
        finding_id: str,
        engagement_id: str,
        embedding: list[float],
        text_content: str,
    ) -> bool:
        """
        Store embedding for a finding

        Args:
            finding_id: Finding ID
            engagement_id: Engagement ID
            embedding: Vector embedding as list of floats
            text_content: Original text used to generate embedding

        Returns:
            True if stored successfully
        """
        if not self.check_pgvector_available():
            logger.warning("pgvector not available, skipping embedding storage")
            return False

        if len(embedding) != self.EMBEDDING_DIMENSIONS:
            logger.error(
                f"Invalid embedding dimensions: {len(embedding)} "
                f"(expected {self.EMBEDDING_DIMENSIONS})"
            )
            return False

        try:
            with db_cursor() as cursor:
                # Convert list to PostgreSQL array format
                embedding_array = "[" + ",".join(map(str, embedding)) + "]"

                cursor.execute(
                    """
                    UPDATE findings
                    SET embedding = %s::vector
                    WHERE id = %s AND engagement_id = %s
                    """,
                    (embedding_array, finding_id, engagement_id)
                )

                if cursor.rowcount == 0:
                    logger.warning(f"Finding {finding_id} not found")
                    return False

                logger.info(f"Stored embedding for finding {finding_id}")
                return True

        except Exception as e:
            logger.error(f"Failed to store embedding: {e}")
            return False

    def find_similar_findings(
        self,
        finding_id: str,
        engagement_id: str,
        threshold: float = SIMILARITY_THRESHOLD,
        limit: int = 10,
    ) -> list[dict]:
        """
        Find similar findings using vector similarity

        Args:
            finding_id: Finding ID to find similarities for
            engagement_id: Engagement ID (to exclude from results)
            threshold: Minimum similarity threshold (0.0-1.0)
            limit: Maximum number of results

        Returns:
            List of similar finding dictionaries
        """
        if not self.check_pgvector_available():
            logger.warning("pgvector not available, returning empty results")
            return []

        try:
            with db_cursor() as cursor:
                # Get embedding for the source finding
                cursor.execute(
                    """
                    SELECT embedding
                    FROM findings
                    WHERE id = %s AND engagement_id = %s
                    """,
                    (finding_id, engagement_id)
                )

                row = cursor.fetchone()
                if not row or row[0] is None:
                    logger.warning(f"No embedding found for finding {finding_id}")
                    return []

                # Find similar findings using cosine distance
                # (embedding <=> embedding) returns cosine distance
                # so similarity = 1 - distance
                cursor.execute(
                    """
                    SELECT
                        f.id,
                        f.type,
                        f.severity,
                        f.endpoint,
                        f.engagement_id,
                        1 - (f.embedding <=> %s::vector) AS similarity
                    FROM findings f
                    WHERE f.engagement_id != %s
                      AND f.embedding IS NOT NULL
                      AND (f.embedding <=> %s::vector) <= (1 - %s)
                    ORDER BY f.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        str(row[0]),  # source embedding
                        engagement_id,
                        str(row[0]),  # source embedding
                        threshold,
                        str(row[0]),  # source embedding
                        limit,
                    )
                )

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": str(row[0]),
                        "type": row[1],
                        "severity": row[2],
                        "endpoint": row[3],
                        "engagement_id": str(row[4]),
                        "similarity": float(row[5]),
                    })

                logger.info(f"Found {len(results)} similar findings for {finding_id}")
                return results

        except Exception as e:
            logger.error(f"Failed to find similar findings: {e}")
            return []

    def find_similar_by_text(
        self,
        text_content: str,
        engagement_id: str,
        threshold: float = SIMILARITY_THRESHOLD,
        limit: int = 10,
    ) -> list[dict]:
        """
        Find similar findings by text content

        Note: This requires generate_embedding() to be implemented or
        an external embedding service.

        Args:
            text_content: Text to find similar findings for
            engagement_id: Engagement ID (to exclude from results)
            threshold: Minimum similarity threshold
            limit: Maximum number of results

        Returns:
            List of similar finding dictionaries
        """
        # Generate embedding for text (would call external service in production)
        embedding = self._generate_embedding_fallback(text_content)

        if embedding is None:
            logger.warning("Could not generate embedding, using fallback")
            return self._find_similar_fallback(text_content, engagement_id, threshold, limit)

        try:
            with db_cursor() as cursor:
                embedding_array = "[" + ",".join(map(str, embedding)) + "]"

                cursor.execute(
                    """
                    SELECT
                        f.id,
                        f.type,
                        f.severity,
                        f.endpoint,
                        f.engagement_id,
                        1 - (f.embedding <=> %s::vector) AS similarity
                    FROM findings f
                    WHERE f.engagement_id != %s
                      AND f.embedding IS NOT NULL
                      AND (f.embedding <=> %s::vector) <= (1 - %s)
                    ORDER BY f.embedding <=> %s::vector
                    LIMIT %s
                    """,
                    (
                        embedding_array,
                        engagement_id,
                        embedding_array,
                        threshold,
                        embedding_array,
                        limit,
                    )
                )

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": str(row[0]),
                        "type": row[1],
                        "severity": row[2],
                        "endpoint": row[3],
                        "engagement_id": str(row[4]),
                        "similarity": float(row[5]),
                    })

                return results

        except Exception as e:
            logger.error(f"Failed to find similar findings: {e}")
            return []

    def _generate_embedding_fallback(self, text: str) -> list[float] | None:
        """
        Fallback embedding generation using simple hash

        Note: This is NOT a real embedding - just a placeholder
        for when OpenAI API is not available.
        """
        # Simple hash-based embedding for testing
        import hashlib

        # Generate deterministic "random" numbers from text hash
        hash_bytes = hashlib.sha256(text.encode()).digest()
        embedding = []

        for i in range(0, min(len(hash_bytes), self.EMBEDDING_DIMENSIONS), 4):
            if i + 3 < len(hash_bytes):
                value = int.from_bytes(hash_bytes[i:i+4], 'big')
                normalized = (value % 10000) / 10000.0
                embedding.append(normalized)

        # Pad to required dimensions
        while len(embedding) < self.EMBEDDING_DIMENSIONS:
            embedding.append(0.0)

        return embedding[:self.EMBEDDING_DIMENSIONS]

    def _find_similar_fallback(
        self,
        text_content: str,
        engagement_id: str,
        threshold: float,
        limit: int,
    ) -> list[dict]:
        """
        Fallback similarity search using keyword matching
        """
        try:
            with db_cursor() as cursor:
                # Extract keywords from text
                keywords = [w.lower() for w in text_content.split() if len(w) > 3]

                if not keywords:
                    return []

                # Build parameterized ILIKE ANY query
                kw_patterns = [f"%{kw}%" for kw in keywords[:5]]
                placeholders = ", ".join("%s" for _ in kw_patterns)

                cursor.execute(
                    f"""
                    SELECT
                        f.id,
                        f.type,
                        f.severity,
                        f.endpoint,
                        f.engagement_id,
                        0.5 AS similarity
                    FROM findings f
                    WHERE f.engagement_id != %s
                      AND f.evidence::text ILIKE ANY(ARRAY[{placeholders}])
                    LIMIT %s
                    """,
                    [engagement_id] + kw_patterns + [limit]
                )

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": str(row[0]),
                        "type": row[1],
                        "severity": row[2],
                        "endpoint": row[3],
                        "engagement_id": str(row[4]),
                        "similarity": float(row[5]),
                        "match_type": "keyword_fallback",
                    })

                return results

        except Exception as e:
            logger.error(f"Fallback search failed: {e}")
            return []

    def get_findings_with_embeddings(self, engagement_id: str) -> list[dict]:
        """
        Get all findings in an engagement that have embeddings

        Args:
            engagement_id: Engagement ID

        Returns:
            List of findings with embeddings
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    SELECT id, type, severity, endpoint, embedding
                    FROM findings
                    WHERE engagement_id = %s AND embedding IS NOT NULL
                    """,
                    (engagement_id,)
                )

                results = []
                for row in cursor.fetchall():
                    results.append({
                        "id": str(row[0]),
                        "type": row[1],
                        "severity": row[2],
                        "endpoint": row[3],
                        "has_embedding": row[4] is not None,
                    })

                return results

        except Exception as e:
            logger.error(f"Failed to get findings: {e}")
            return []

    def delete_embeddings(self, engagement_id: str) -> int:
        """
        Delete all embeddings for an engagement

        Args:
            engagement_id: Engagement ID

        Returns:
            Number of embeddings deleted
        """
        try:
            with db_cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE findings
                    SET embedding = NULL
                    WHERE engagement_id = %s AND embedding IS NOT NULL
                    """,
                    (engagement_id,)
                )

                deleted = cursor.rowcount
                logger.info(f"Deleted {deleted} embeddings for {engagement_id}")
                return deleted

        except Exception as e:
            logger.error(f"Failed to delete embeddings: {e}")
            return 0
