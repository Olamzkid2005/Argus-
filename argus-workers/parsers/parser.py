"""
Parser Layer - Converts CLI tool output to JSON

Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 20.5, 21.1, 21.2
"""

import logging
import os
import time
from collections.abc import Generator
from functools import lru_cache

from feature_flags import is_enabled

# Import all parser classes from the extracted parsers/parsers/ package.
# The inline definitions were moved to parsers/parsers/*.py to make the module
# easier to navigate and test in isolation.
from parsers.parsers.base import ParserError
from tracing import ExecutionSpan, StructuredLogger

logger = logging.getLogger(__name__)


class Parser:
    """
    Main parser class that routes to appropriate tool parser.

    Discovers parsers dynamically from the parsers/parsers/ registry.
    Falling back to BaseParser for tools without a dedicated parser.
    """

    @staticmethod
    @lru_cache(maxsize=1)
    def _build_parsers() -> dict:
        """Build parser registry (cached, invalidated upon request).

        Call _invalidate_parser_cache() to force re-discovery after hot-reload.
        """
        from parsers.parsers import _parser_registry
        return {tool_name: parser_cls() for tool_name, parser_cls in _parser_registry.items()}

    @staticmethod
    def _invalidate_parser_cache():
        """Invalidate the cached parser registry (fix 6.4).
        Call this after installing new parsers to force re-discovery.
        """
        Parser._build_parsers.cache_clear()

    def __init__(self, connection_string: str = None):
        """
        Initialize Parser with optional database connection for tracing.

        Args:
            connection_string: Database connection string
        """
        self.parsers = self._build_parsers()

        # Initialize tracing
        self.connection_string = connection_string or os.getenv("DATABASE_URL")
        self.logger = StructuredLogger(self.connection_string)
        self.span_recorder = ExecutionSpan(self.connection_string)

    def parse(self, tool_name: str, raw_output: str) -> list[dict]:
        """
        Route to appropriate parser based on tool name

        Args:
            tool_name: Name of the tool
            raw_output: Raw tool output

        Returns:
            List of parsed findings

        Raises:
            ParserError: If no parser exists for tool
        """
        parser = self.parsers.get(tool_name.lower())

        if not parser:
            raise ParserError(f"No parser found for tool: {tool_name}")

        # Record start time
        start_time = time.time()

        # Execute with span tracing
        with self.span_recorder.span(ExecutionSpan.SPAN_PARSING, {"tool": tool_name}):
            try:
                findings = parser.parse(raw_output)

                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser completion
                self.logger.log_parser_completed(
                    tool_name=tool_name,
                    findings_count=len(findings),
                    parse_time_ms=duration_ms,
                )

                # ── LLM Parser Fallback on empty result ──
                if not findings:
                    llm_findings = self._try_llm_fallback(
                        tool_name, raw_output
                    )
                    if llm_findings:
                        logger.info(
                            "LLM parser fallback recovered %d findings from "
                            "%s output (%d chars)",
                            len(llm_findings),
                            tool_name,
                            len(raw_output),
                        )
                        self.logger.log_parser_completed(
                            tool_name=f"{tool_name}_llm_fallback",
                            findings_count=len(llm_findings),
                            parse_time_ms=duration_ms,
                        )
                        return llm_findings

                return findings

            except Exception as e:
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser failure
                self.logger.log(
                    "parser_failed",
                    f"Parser failed for {tool_name}: {str(e)}",
                    {
                        "tool_name": tool_name,
                        "error": str(e),
                        "parse_time_ms": duration_ms,
                    },
                )

                # ── LLM Parser Fallback on ParserError ──
                findings = self._try_llm_fallback(tool_name, raw_output)
                if findings:
                    logger.info(
                        "LLM parser fallback recovered %d findings from %s "
                        "output after parser error: %s",
                        len(findings), tool_name, str(e)[:120],
                    )
                    return findings

                raise ParserError(f"Failed to parse {tool_name} output: {e}") from e

    def _try_llm_fallback(self, tool_name: str, raw_output: str) -> list[dict]:
        """Attempt LLM-powered fallback parsing when primary parser fails.

        Only activates when:
        - Feature flag "llm_parser_fallback" is enabled
        - Raw output is non-empty and long enough (> 100 chars)

        Args:
            tool_name: Name of the tool that produced the output
            raw_output: Raw tool output string

        Returns:
            List of findings if recovered, empty list otherwise.
        """
        if not is_enabled("llm_parser_fallback"):
            return []

        if not raw_output or len(raw_output.strip()) < 100:
            return []

        try:
            from llm_parser_fallback import LLMParserFallback

            fallback = LLMParserFallback()
            return fallback.extract_findings(tool_name, raw_output)
        except Exception as e:
            logger.warning(
                "LLM parser fallback failed for %s: %s", tool_name, e
            )
            return []

    def parse_stream(
        self, tool_name: str, raw_output: str, batch_size: int = 50
    ) -> Generator[list[dict], None, None]:
        """
        Parse tool output as a stream, yielding findings in batches.

        This avoids loading all findings into memory at once,
        which is useful for large tool outputs. Yields batches
        of findings that can be inserted into the database.

        Args:
            tool_name: Name of the tool
            raw_output: Raw tool output
            batch_size: Number of findings per batch (default: 50)

        Yields:
            Batches of parsed findings (List[Dict])

        Raises:
            ParserError: If no parser exists for tool

        Example:
            for batch in runner.parse_stream("nuclei", output, batch_size=50):
                db.insert_findings(batch)  # Insert 50 at a time
        """
        parser = self.parsers.get(tool_name.lower())

        if not parser:
            raise ParserError(f"No parser found for tool: {tool_name}")

        # Record start time
        start_time = time.time()
        total_count = 0
        batch = []

        # Execute with span tracing
        with self.span_recorder.span(
            ExecutionSpan.SPAN_PARSING, {"tool": tool_name, "stream": True}
        ):
            try:
                for finding in parser.parse_stream(raw_output):
                    batch.append(finding)
                    total_count += 1

                    if len(batch) >= batch_size:
                        yield batch
                        batch = []

                # Yield remaining findings
                if batch:
                    yield batch

                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser completion
                self.logger.log_parser_completed(
                    tool_name=tool_name,
                    findings_count=total_count,
                    parse_time_ms=duration_ms,
                )

            except Exception as e:
                # Calculate duration
                duration_ms = int((time.time() - start_time) * 1000)

                # Log parser failure
                self.logger.log(
                    "parser_failed",
                    f"Stream parser failed for {tool_name}: {str(e)}",
                    {
                        "tool_name": tool_name,
                        "error": str(e),
                        "parse_time_ms": duration_ms,
                    },
                )

                raise ParserError(
                    f"Failed to stream parse {tool_name} output: {e}"
                ) from e
