"""
CustomRulesService — loads custom rules from the database.

Extracted from Orchestrator._load_custom_rules().
The method had zero self.* references, making it a pure function.
"""

import logging

logger = logging.getLogger(__name__)


class CustomRulesService:
    """Loads custom rules for an engagement (engagement-specific → org-level fallback)."""

    @staticmethod
    def load(engagement_id: str) -> list[dict]:
        """Load custom rules for an engagement.

        Checks for engagement-specific rules first via the engagement_custom_rules
        junction table. Falls back to org-level rules when no engagement-specific
        rules exist.

        Args:
            engagement_id: The engagement UUID.

        Returns:
            List of custom rule dicts, or empty list if none found or on error.
        """
        from database.connection import db_cursor
        try:
            with db_cursor() as cursor:
                cursor.execute("SELECT org_id FROM engagements WHERE id = %s", (engagement_id,))
                row = cursor.fetchone()
                if not row:
                    return []
                org_id = row[0]

                # First check for engagement-specific rules via junction table
                cursor.execute("""
                    SELECT cr.id, cr.name, cr.description, cr.severity,
                           cr.category, cr.rule_yaml, cr.tags
                    FROM custom_rules cr
                    INNER JOIN engagement_custom_rules ecr
                        ON cr.id = ecr.rule_id
                    WHERE ecr.engagement_id = %s
                      AND cr.status = 'active'
                    ORDER BY cr.created_at DESC
                """, (engagement_id,))
                columns = [desc[0] for desc in cursor.description]
                engagement_rules = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

                if engagement_rules:
                    logger.info(
                        "Loaded %d engagement-specific custom rule(s) for engagement %s",
                        len(engagement_rules), engagement_id,
                    )
                    return engagement_rules

                # Fallback: load org-level rules when no engagement-specific rules exist
                logger.info(
                    "No engagement-specific custom rules for %s, falling back to org-level rules",
                    engagement_id,
                )
                cursor.execute("""
                    SELECT id, name, description, severity, category, rule_yaml, tags
                    FROM custom_rules WHERE org_id = %s AND status = 'active'
                    ORDER BY created_at DESC
                """, (org_id,))
                org_rules = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]
                logger.info(
                    "Loaded %d org-level custom rule(s) for org %s", len(org_rules), org_id,
                )
                return org_rules
        except Exception as e:
            logger.warning(f"Failed to load custom rules: {e}")
            return []
