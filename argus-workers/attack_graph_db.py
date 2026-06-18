"""
Attack Graph Database Repository

Persists and loads AttackGraph instances to/from the `attack_paths` table.
Follows the same connection patterns as other repositories in database/repositories/.
"""

from __future__ import annotations

import json
import logging
import uuid

from attack_graph import AttackGraph
from database.connection import connect, get_db

logger = logging.getLogger(__name__)


class AttackGraphRepository:
    """
    Persistence layer for AttackGraph objects.

    Saves attack paths to the `attack_paths` table and reconstructs
    AttackGraph instances from persisted data.
    """

    TABLE_NAME = "attack_paths"

    def __init__(self, db_connection_string: str | None = None):
        """
        Initialize repository.

        Args:
            db_connection_string: Optional database connection string.
                                  If not provided, uses the shared connection pool.
        """
        self.db_conn_string = db_connection_string

    def _get_connection(self):
        """Get a database connection."""
        if self.db_conn_string:
            return connect(self.db_conn_string)
        return get_db().get_connection()

    def _release_connection(self, conn, owned: bool = True):
        """Release connection back to pool."""
        if conn:
            if owned and not self.db_conn_string:
                get_db().release_connection(conn)
            elif self.db_conn_string:
                try:
                    conn.close()
                except Exception:
                    logger.debug("Failed to close connection")

    def save_paths(self, engagement_id: str, graph: AttackGraph) -> int:
        """
        Persist all attack paths from the graph to the database.

        Deletes old paths for this engagement first, then inserts fresh ones.
        This is intentionally a full replace (not incremental) to keep the
        attack_paths table consistent with the in-memory graph state.

        Args:
            engagement_id: Engagement ID
            graph: AttackGraph instance with populated nodes/edges

        Returns:
            Number of paths saved
        """
        from attack_graph import AttackGraph as AG

        graph: AG = graph  # type hint for IDE

        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # ── Preserve existing chain_exploit_script values ──
            # AttackGraphRepository.save_paths is a full replace (delete + re-insert).
            # We need to preserve any existing chain_exploit_script entries that were
            # saved by ChainExploitGenerator so they aren't lost on path re-save.
            cursor.execute(
                "SELECT id, path_nodes, chain_exploit_script FROM attack_paths "
                "WHERE engagement_id = %s AND chain_exploit_script IS NOT NULL",
                (engagement_id,),
            )
            existing_scripts: dict[str, str] = {}  # fingerprint -> script JSON
            for row in cursor.fetchall():
                old_path_id, old_path_nodes_json, script = row
                if script:
                    # Build a fingerprint from the path node types to match across re-saves
                    try:
                        old_nodes = (
                            json.loads(old_path_nodes_json)
                            if isinstance(old_path_nodes_json, str)
                            else old_path_nodes_json
                        )
                        # Use finding type from node.data (e.g. "XSS", "SQL_INJECTION")
                        # not the generic node.type field ("vulnerability"/"endpoint")
                        # to prevent chain scripts from being restored to wrong paths.
                        node_types = tuple(
                            n.get("data", {}).get("type", "")
                            for n in (old_nodes.get("nodes") or [])
                        )
                        existing_scripts[str(node_types)] = script
                    except (json.JSONDecodeError, AttributeError):
                        pass

            # Delete old paths for this engagement
            cursor.execute(
                "DELETE FROM attack_paths WHERE engagement_id = %s",
                (engagement_id,),
            )

            # Compute all paths with their risk scores
            paths = graph.get_all_paths_with_chains()
            saved_count = 0

            for path in paths:
                risk = graph.compute_risk(path)
                # Serialize path to JSONB-compatible dict
                path_nodes = {
                    "nodes": [
                        {
                            "id": node.id,
                            "type": node.type,
                            "data": node.data,
                            "cvss": node.cvss,
                            "confidence": node.confidence,
                            "prerequisites": list(getattr(node, "prerequisites", [])),
                            "downstream_impacts": list(
                                getattr(node, "downstream_impacts", [])
                            ),
                        }
                        for node in path.nodes
                    ],
                    "edges": [
                        {
                            "from_node": edge.from_node,
                            "to_node": edge.to_node,
                            "type": edge.type,
                            "correlation_factor": edge.correlation_factor,
                            "relationship_type": str(
                                getattr(edge, "relationship_type", "independent")
                            ),
                        }
                        for edge in path.edges
                    ],
                }

                normalized_severity = self._risk_to_normalized_severity(risk)

                # Re-associate any previously-saved chain_exploit_script
                # Use finding type for matching (same fingerprint as above)
                node_types = tuple(
                    n.get("data", {}).get("type", "") for n in path_nodes["nodes"]
                )
                chain_script = existing_scripts.get(str(node_types))

                if chain_script:
                    cursor.execute(
                        """
                        INSERT INTO attack_paths
                            (id, engagement_id, path_nodes, risk_score, normalized_severity, chain_exploit_script)
                        VALUES (%s, %s, %s::jsonb, %s, %s, %s)
                        """,
                        (
                            str(uuid.uuid4()),
                            engagement_id,
                            json.dumps(path_nodes),
                            round(risk, 2),
                            normalized_severity,
                            chain_script,
                        ),
                    )
                else:
                    cursor.execute(
                        """
                        INSERT INTO attack_paths
                            (id, engagement_id, path_nodes, risk_score, normalized_severity)
                        VALUES (%s, %s, %s::jsonb, %s, %s)
                        """,
                        (
                            str(uuid.uuid4()),
                            engagement_id,
                            json.dumps(path_nodes),
                            round(risk, 2),
                            normalized_severity,
                        ),
                    )
                saved_count += 1

            conn.commit()
            logger.info(
                "Saved %d attack paths (with %d preserved chain scripts) for engagement %s",
                saved_count,
                len(existing_scripts),
                engagement_id,
            )
            return saved_count

        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception as rb_e:
                    logger.debug(
                        "Rollback failed after save error for %s: %s",
                        engagement_id,
                        rb_e,
                    )
            logger.exception(
                "Failed to save attack paths for engagement %s: %s",
                engagement_id,
                e,
            )
            raise
        finally:
            if cursor:
                cursor.close()
            if conn:
                self._release_connection(conn)

    def load_graph(self, engagement_id: str) -> AttackGraph | None:
        """
        Reconstruct an AttackGraph from persisted attack_paths rows.

        Loads all paths for the engagement and rebuilds the Node/Edge/Path
        objects from the stored JSONB data.

        Args:
            engagement_id: Engagement ID

        Returns:
            AttackGraph instance with restored nodes/edges, or None if no paths exist
        """
        from attack_graph import AttackGraph, Edge, Node

        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT path_nodes, risk_score
                FROM attack_paths
                WHERE engagement_id = %s
                ORDER BY risk_score DESC
                """,
                (engagement_id,),
            )

            rows = cursor.fetchall()
            if not rows:
                return None

            graph = AttackGraph(engagement_id)

            for row in rows:
                path_data = row[0]
                if isinstance(path_data, str):
                    path_data = json.loads(path_data)

                # Rebuild nodes
                for node_data in path_data.get("nodes", []):
                    node_id = node_data.get("id", "")
                    if node_id not in graph.nodes:
                        node = Node(
                            node_id=node_id,
                            node_type=node_data.get("type", "vulnerability"),
                            data=node_data.get("data", {}),
                            cvss=node_data.get("cvss"),
                            confidence=node_data.get("confidence"),
                            prerequisites=node_data.get("prerequisites", []),
                            downstream_impacts=node_data.get("downstream_impacts", []),
                        )
                        graph.nodes[node_id] = node

                # Rebuild edges (deduplicate by from+to+type)
                existing_edges = {(e.from_node, e.to_node, e.type) for e in graph.edges}
                for edge_data in path_data.get("edges", []):
                    edge_key = (
                        edge_data.get("from_node", ""),
                        edge_data.get("to_node", ""),
                        edge_data.get("type", ""),
                    )
                    if edge_key not in existing_edges:
                        from attack_graph import RelationshipType

                        rel_type_str = edge_data.get("relationship_type", "independent")
                        try:
                            rel_type = RelationshipType(rel_type_str)
                        except (ValueError, TypeError):
                            rel_type = RelationshipType.INDEPENDENT

                        edge = Edge(
                            from_node=edge_key[0],
                            to_node=edge_key[1],
                            edge_type=edge_key[2],
                            correlation_factor=edge_data.get("correlation_factor", 1.0),
                            relationship_type=rel_type,
                        )
                        graph.edges.append(edge)
                        existing_edges.add(edge_key)

            logger.info(
                "Loaded attack graph for engagement %s: %d nodes, %d edges",
                engagement_id,
                len(graph.nodes),
                len(graph.edges),
            )
            return graph

        except Exception as e:
            logger.exception(
                "Failed to load attack graph for engagement %s: %s",
                engagement_id,
                e,
            )
            return None
        finally:
            if cursor:
                cursor.close()
            if conn:
                self._release_connection(conn)

    def delete_for_engagement(self, engagement_id: str) -> bool:
        """
        Delete all attack paths for an engagement.

        Args:
            engagement_id: Engagement ID

        Returns:
            True if any rows were deleted
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM attack_paths WHERE engagement_id = %s",
                (engagement_id,),
            )
            conn.commit()
            deleted = cursor.rowcount > 0
            if deleted:
                logger.info(
                    "Deleted attack paths for engagement %s",
                    engagement_id,
                )
            return deleted
        except Exception as e:
            if conn:
                try:
                    conn.rollback()
                except Exception as rb_e:
                    logger.debug(
                        "Rollback failed after delete error for %s: %s",
                        engagement_id,
                        rb_e,
                    )
            logger.error(
                "Failed to delete attack paths for engagement %s: %s",
                engagement_id,
                e,
            )
            return False
        finally:
            if cursor:
                cursor.close()
            if conn:
                self._release_connection(conn)

    def count_paths(self, engagement_id: str) -> int:
        """
        Count attack paths for an engagement.

        Args:
            engagement_id: Engagement ID

        Returns:
            Number of attack paths
        """
        conn = None
        cursor = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM attack_paths WHERE engagement_id = %s",
                (engagement_id,),
            )
            return cursor.fetchone()[0]
        except Exception as e:
            logger.error(
                "Failed to count attack paths for engagement %s: %s",
                engagement_id,
                e,
            )
            return 0
        finally:
            if cursor:
                cursor.close()
            if conn:
                self._release_connection(conn)

    @staticmethod
    def _risk_to_normalized_severity(risk: float) -> float:
        """Map a risk score (0.0-10.0) to a normalized severity (0.0-10.0)."""
        return round(min(10.0, max(0.0, risk)), 2)
