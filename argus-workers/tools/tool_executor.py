"""
Tool Executor - End-to-end tool execution flow
Wires together: Tool Runner → Parser → Normalizer → PostgreSQL
"""

import logging
import time
import uuid

from psycopg2.extras import Json

from database.connection import connect
from models.finding import VulnerabilityFinding
from parsers.normalizer import FindingNormalizer
from parsers.parser import Parser, ParserError
from tools.models import ToolResult
from tools.scope_validator import ScopeValidator, ScopeViolationError
from tools.tool_runner import SecurityException, ToolRunner

logger = logging.getLogger(__name__)


class ToolExecutor:
    """
    Executes tools end-to-end with scope validation, parsing, normalization, and storage
    """

    def __init__(self, db_connection_string: str):
        """
        Initialize Tool Executor

        Args:
            db_connection_string: PostgreSQL connection string
        """
        self.db_conn_string = db_connection_string
        self.tool_runner = ToolRunner()
        self.parser = Parser()
        self.normalizer = FindingNormalizer()

    def execute_tool(
        self,
        tool_name: str,
        args: list[str],
        engagement_id: str,
        authorized_scope: dict,
        target_url: str,
        timeout: int = 60,
        max_retries: int = 3,
    ) -> dict:
        """
        Execute tool with full pipeline

        Args:
            tool_name: Name of tool to execute
            args: Tool arguments
            engagement_id: Engagement ID
            authorized_scope: Authorized scope dictionary
            target_url: Target URL
            timeout: Execution timeout in seconds
            max_retries: Maximum retry attempts

        Returns:
            Dictionary with execution results
        """
        start_time = time.time()

        # Validate scope
        scope_validator = ScopeValidator(engagement_id, authorized_scope)
        try:
            scope_validator.validate_target(target_url)
        except ScopeViolationError as e:
            return {
                "success": False,
                "error": "scope_violation",
                "message": str(e),
                "tool": tool_name,
            }

        # Execute tool with retries
        tool_result = self._execute_with_retries(tool_name, args, timeout, max_retries)

        if not tool_result.success:
            return {
                "success": False,
                "error": "tool_execution_failed",
                "message": tool_result.stderr or "Unknown error",
                "tool": tool_name,
                "duration_ms": int((time.time() - start_time) * 1000),
            }

        # Parse output with retries
        parsed_findings = self._parse_with_retries(
            tool_name, tool_result.stderr or tool_result.stdout, max_retries=2
        )

        if parsed_findings is None:
            # Parser failed after retries, store raw output
            self._store_raw_output(
                engagement_id,
                tool_name,
                tool_result.stdout,
                "Parser failed after retries",
            )
            return {
                "success": False,
                "error": "parser_failed",
                "message": "Failed to parse tool output",
                "tool": tool_name,
                "duration_ms": int((time.time() - start_time) * 1000),
            }

        # Normalize findings
        normalized_findings = self.normalizer.normalize_batch(
            parsed_findings, tool_name
        )

        # Store findings in PostgreSQL
        stored_count = self._store_findings(engagement_id, normalized_findings)

        duration_ms = int((time.time() - start_time) * 1000)

        return {
            "success": True,
            "tool": tool_name,
            "findings_count": stored_count,
            "duration_ms": duration_ms,
        }

    def _execute_with_retries(
        self, tool_name: str, args: list[str], timeout: int, max_retries: int
    ) -> ToolResult:
        """
        Execute tool with exponential backoff retries

        Args:
            tool_name: Tool name
            args: Tool arguments
            timeout: Timeout in seconds
            max_retries: Maximum retry attempts

        Returns:
            ToolResult
        """
        attempt = 0
        backoff_seconds = 1

        while attempt < max_retries:
            try:
                # Use circuit-breaker-wrapped execution so repeatedly failing tools
                # are short-circuited instead of wasting time on retries.
                result = self.tool_runner.run_with_circuit_breaker(tool_name, args, timeout)

                if result.success:
                    return result

                # Tool failed, retry
                attempt += 1
                if attempt < max_retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2  # Exponential backoff

            except SecurityException as e:
                logger.warning("Security violation for %s (non-retryable): %s", tool_name, e)
                return ToolResult(
                    success=False,
                    stderr=str(e),
                    tool=tool_name,
                    error=str(e),
                )
            except Exception as e:
                attempt += 1
                if attempt < max_retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2
                else:
                    logger.error("Tool %s failed after %d attempts: %s", tool_name, max_retries, e, exc_info=True)
                    return ToolResult(
                        success=False,
                        stderr=str(e),
                        tool=tool_name,
                        error=str(e),
                    )

        return ToolResult(
            success=False,
            stderr=f"Tool failed after {max_retries} attempts",
            tool=tool_name,
            error=f"Tool failed after {max_retries} attempts",
        )

    def _parse_with_retries(
        self, tool_name: str, raw_output: str, max_retries: int = 2
    ) -> list[dict] | None:
        """
        Parse tool output with linear backoff retries

        Args:
            tool_name: Tool name
            raw_output: Raw tool output
            max_retries: Maximum retry attempts

        Returns:
            List of parsed findings or None if failed
        """
        attempt = 0
        backoff_seconds = 1

        while attempt < max_retries:
            try:
                findings = self.parser.parse(tool_name, raw_output)
                return findings
            except ParserError as e:
                attempt += 1
                if attempt < max_retries:
                    time.sleep(backoff_seconds)
                    backoff_seconds += 1  # Linear backoff
                else:
                    logger.error(f"Parser failed for {tool_name} after {max_retries} attempts: {e}", exc_info=True)
                    return None

        return None

    def _store_findings(
        self, engagement_id: str, findings: list[VulnerabilityFinding]
    ) -> int:
        """
        Store findings in PostgreSQL

        Args:
            engagement_id: Engagement ID
            findings: List of normalized findings

        Returns:
            Number of findings stored
        """
        if not findings:
            return 0

        conn = connect(self.db_conn_string)
        cursor = conn.cursor()

        try:
            stored_count = 0

            for finding in findings:
                finding_id = str(uuid.uuid4())

                cursor.execute(
                    """
                    INSERT INTO findings (
                        id, engagement_id, type, severity, confidence,
                        endpoint, evidence, source_tool, cvss_score,
                        owasp_category, cwe_id, evidence_strength,
                        tool_agreement_level, fp_likelihood, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW()
                    )
                    ON CONFLICT (engagement_id, endpoint, type, source_tool)
                    DO UPDATE SET
                        severity = EXCLUDED.severity,
                        confidence = EXCLUDED.confidence,
                        evidence = EXCLUDED.evidence,
                        cvss_score = EXCLUDED.cvss_score,
                        fp_likelihood = EXCLUDED.fp_likelihood,
                        updated_at = NOW()
                    """,
                    (
                        finding_id,
                        engagement_id,
                        finding.type,
                        finding.severity.value
                        if hasattr(finding.severity, "value")
                        else finding.severity,
                        finding.confidence,
                        finding.endpoint,
                        Json(finding.evidence),
                        finding.source_tool,
                        finding.cvss_score,
                        finding.owasp_category,
                        finding.cwe_id,
                        finding.evidence_strength.value
                        if finding.evidence_strength
                        and hasattr(finding.evidence_strength, "value")
                        else (finding.evidence_strength or None),
                        finding.tool_agreement_level,
                        finding.fp_likelihood,
                    ),
                )

                stored_count += 1

            conn.commit()
            return stored_count

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store findings for engagement={engagement_id}: {e}", exc_info=True)
            return 0
        finally:
            cursor.close()
            conn.close()

    def _store_raw_output(
        self, engagement_id: str, tool_name: str, raw_output: str, error_message: str
    ):
        """
        Store raw output when parser fails

        Args:
            engagement_id: Engagement ID
            tool_name: Tool name
            raw_output: Raw tool output
            error_message: Error message
        """
        conn = connect(self.db_conn_string)
        cursor = conn.cursor()

        try:
            output_id = str(uuid.uuid4())

            cursor.execute(
                """
                INSERT INTO raw_outputs (
                    id, engagement_id, tool_name, raw_output, error_message, created_at
                ) VALUES (
                    %s, %s, %s, %s, %s, NOW()
                )
                """,
                (output_id, engagement_id, tool_name, raw_output, error_message),
            )

            conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store raw output for {tool_name} engagement={engagement_id}: {e}", exc_info=True)
        finally:
            cursor.close()
            conn.close()

    def cleanup(self):
        """Clean up resources"""
        self.tool_runner.cleanup()
