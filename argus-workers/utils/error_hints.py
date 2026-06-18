"""
User-facing error hints for security tool failures.

Consumes error_classifier.py (Classification / CodeBasedClassification) and
translates operational error classifications into actionable user-facing hints.

Architecture (ADR-001):
    error_hints.py is a PURE presentation layer — it does NOT re-implement
    error detection logic. It receives Classification from error_classifier.py
    and maps ErrorCode → ErrorCategory → generic fallback to user text.

    The ONLY exception is _tool_specific_hint(), which inspects stderr for
    tool-specific remediation guidance (nuclei templates missing, nmap
    permissions, etc.) — this is remediation, not classification.
"""

import logging
import re
from dataclasses import dataclass

from error_classifier import (
    CodeBasedClassification,
    ErrorCategory,
    ErrorCode,
    classify_error_with_code,
)

logger = logging.getLogger(__name__)


# ── ErrorHint data class ──


@dataclass
class ErrorHint:
    """User-facing hint for a classified error.

    Attributes:
        summary: Short one-line summary of what went wrong (e.g., "Rate limit hit").
        detail: Longer explanation of the error context.
        remediation: Actionable guidance for the user to resolve the issue.
        hint_command: Optional shell command the user can run (e.g., "pip install nuclei").
        docs_url: Optional link to relevant documentation.
        tool: Optional tool name this hint is associated with.
        error_id: Optional ErrorCode string for correlation.
    """

    summary: str
    detail: str = ""
    remediation: str = ""
    hint_command: str | None = None
    docs_url: str | None = None
    tool: str | None = None
    error_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "summary": self.summary,
            "detail": self.detail,
            "remediation": self.remediation,
            "hint_command": self.hint_command,
            "docs_url": self.docs_url,
            "tool": self.tool,
            "error_id": self.error_id,
        }


# ── ErrorCode → Hint mapping ──
# Maps each known ErrorCode to a user-facing hint template.
# This is the preferred (most specific) path in hint_for_classification().

_ERROR_CODE_HINTS: dict[ErrorCode, ErrorHint] = {
    # ── Config errors ──
    ErrorCode.CONFIG_NOT_FOUND: ErrorHint(
        summary="Configuration file not found",
        detail="Argus could not find its configuration file at the expected location.",
        remediation="Ensure argus.config.yaml exists in the project root or set the ARGUS_CONFIG_PATH environment variable.",
        docs_url="https://docs.argus.io/setup/configuration",
    ),
    ErrorCode.CONFIG_VALIDATION_FAILED: ErrorHint(
        summary="Configuration validation failed",
        detail="The configuration file contains invalid or missing values.",
        remediation="Review your argus.config.yaml against the schema. Check for typos, missing required fields, and correct value types.",
        docs_url="https://docs.argus.io/setup/configuration#schema",
    ),
    ErrorCode.CONFIG_PARSE_ERROR: ErrorHint(
        summary="Could not parse configuration file",
        detail="The configuration file is not valid YAML or contains syntax errors.",
        remediation="Run 'argus config validate' to check your config file. Look for missing colons, incorrect indentation, or unclosed quotes.",
        hint_command="argus config validate",
        docs_url="https://docs.argus.io/setup/configuration#validation",
    ),
    # ── Tool execution errors ──
    ErrorCode.TOOL_NOT_FOUND: ErrorHint(
        summary="Security tool not found",
        detail="A required security scanning tool is not installed or not on the PATH.",
        remediation="Install the missing tool using your package manager. For Go-based tools, run 'go install <tool>@latest'.",
        docs_url="https://docs.argus.io/setup/installation#tools",
    ),
    ErrorCode.TOOL_EXECUTION_FAILED: ErrorHint(
        summary="Tool execution failed",
        detail="A security tool returned a non-zero exit code or encountered an unexpected error.",
        remediation="Check the tool's stderr output above for specific error details. Try running the tool manually with the same arguments to reproduce.",
    ),
    ErrorCode.TOOL_TIMED_OUT: ErrorHint(
        summary="Tool timed out",
        detail="A security tool exceeded its maximum execution time and was killed.",
        remediation="Increase the timeout with '--timeout <seconds>' or reduce the scan scope (fewer targets, narrower port range, specific templates).",
        docs_url="https://docs.argus.io/usage/scan#timeouts",
    ),
    ErrorCode.TOOL_OUTPUT_EMPTY: ErrorHint(
        summary="Tool produced no output",
        detail="The security tool ran successfully but returned no results.",
        remediation="This may be expected if no vulnerabilities were found. If you expected findings, try adjusting the tool's scope or parameters.",
    ),
    ErrorCode.TOOL_SCHEMA_MISMATCH: ErrorHint(
        summary="Tool output format mismatch",
        detail="The tool returned output in an unexpected format that could not be parsed.",
        remediation="This may be due to a tool version update. Try updating the tool or checking if a newer version of Argus supports the new format.",
        docs_url="https://docs.argus.io/troubleshooting/tool-schema",
    ),
    # ── Pipeline execution errors ──
    ErrorCode.STEP_EXECUTION_FAILED: ErrorHint(
        summary="Scan step failed",
        detail="A step in the scan pipeline encountered an error and could not complete.",
        remediation="Check the logs above for more context. Try running the scan with '--verbose' for detailed output.",
    ),
    ErrorCode.OUTPUT_VALIDATION_FAILED: ErrorHint(
        summary="Output validation failed",
        detail="The output from a pipeline step failed validation checks.",
        remediation="This is likely an internal issue. Check the debug logs and consider filing a bug report.",
        docs_url="https://docs.argus.io/contributing/bug-reports",
    ),
    ErrorCode.PREREQUISITE_FAILED: ErrorHint(
        summary="Prerequisite check failed",
        detail="A required prerequisite (tool, file, or configuration) was not met before running this step.",
        remediation="Check the error message for which prerequisite failed. Install required tools or fix configuration issues before retrying.",
    ),
    ErrorCode.PHASE_TIMED_OUT: ErrorHint(
        summary="Scan phase timed out",
        detail="A scan phase exceeded its time budget and was terminated.",
        remediation="Increase the phase timeout with '--phase-timeout <seconds>' or reduce the scan scope. For large targets, consider splitting the scan.",
    ),
    # ── Resource errors ──
    ErrorCode.RATE_LIMITED: ErrorHint(
        summary="Rate limit hit",
        detail="The target server is rate-limiting requests. This is common with aggressive scanning.",
        remediation="Reduce scan aggressiveness with '--aggressiveness low' or add delays between requests with '--rate-limit <requests/sec>'.",
        hint_command="argus scan <target> --aggressiveness low",
        docs_url="https://docs.argus.io/usage/scan#rate-limiting",
    ),
    ErrorCode.QUOTA_EXCEEDED: ErrorHint(
        summary="Resource quota exceeded",
        detail="A resource quota (API calls, concurrent scans, storage) has been exceeded.",
        remediation="Wait for the quota to reset, or upgrade your plan for higher limits. Check your usage with 'argus usage stats'.",
        docs_url="https://docs.argus.io/account/plans",
    ),
    # ── I/O errors ──
    ErrorCode.FILE_NOT_FOUND: ErrorHint(
        summary="Required file not found",
        detail="A file required for the scan could not be found at the expected path.",
        remediation="Verify the file path is correct. Use absolute paths or ensure relative paths are resolved from the project root.",
    ),
    ErrorCode.DATABASE_ERROR: ErrorHint(
        summary="Database connection error",
        detail="Could not connect to the database. The database may be down or unreachable.",
        remediation="Verify your database is running and accessible. Check DATABASE_URL environment variable and network connectivity.",
        docs_url="https://docs.argus.io/setup/database",
    ),
    ErrorCode.CHECKPOINT_FAILED: ErrorHint(
        summary="Checkpoint save failed",
        detail="Could not save scan progress checkpoint. Progress may not be recoverable if interrupted.",
        remediation="Check disk space and database connectivity. The scan will continue but may not resume if interrupted.",
    ),
    # ── Preflight errors ──
    ErrorCode.INVALID_INPUT: ErrorHint(
        summary="Invalid input provided",
        detail="The provided input does not match the expected format or constraints.",
        remediation="Check the input format and try again. For targets, ensure URLs include the scheme (http:// or https://).",
    ),
    ErrorCode.TARGET_UNREACHABLE: ErrorHint(
        summary="Target is unreachable",
        detail="Could not establish a connection to the target. The target may be down, blocking connections, or the address may be wrong.",
        remediation="Verify the target is online and accessible. Try 'ping <target>' or 'curl -I <target>' to test connectivity. If using a firewall, ensure the target allows your IP.",
        hint_command="curl -I <target>",
    ),
    ErrorCode.DNS_RESOLUTION_FAILED: ErrorHint(
        summary="DNS resolution failed",
        detail="Could not resolve the target hostname to an IP address.",
        remediation="Check that the hostname is spelled correctly. Try 'nslookup <target>' to test DNS resolution. If the target is internal, ensure you are on the correct network/VPN.",
        hint_command="nslookup <target>",
    ),
}


# ── ErrorCategory → Fallback Hint mapping ──
# Used when no specific ErrorCode match exists — provides category-level guidance.

_CATEGORY_FALLBACK_HINTS: dict[ErrorCategory, ErrorHint] = {
    ErrorCategory.TRANSIENT: ErrorHint(
        summary="Temporary error occurred",
        detail="A transient error occurred. These are usually temporary and may resolve on retry.",
        remediation="Try running the scan again. If the error persists, check network connectivity and target availability.",
    ),
    ErrorCategory.PERMANENT: ErrorHint(
        summary="Non-retryable error",
        detail="This error will not resolve with retries and requires intervention.",
        remediation="Check the error details above. This may require a configuration change, tool update, or code fix.",
    ),
    ErrorCategory.INFRASTRUCTURE: ErrorHint(
        summary="Infrastructure error",
        detail="An infrastructure dependency (database, Redis, network) is unavailable or misconfigured.",
        remediation="Verify that all required services (database, Redis, message queue) are running and accessible. Check connection strings in your environment.",
    ),
    ErrorCategory.EXTERNAL: ErrorHint(
        summary="External service error",
        detail="A third-party service (API, webhook) returned an error or is unavailable.",
        remediation="Check if the external service is operational. Verify API keys and endpoint URLs in your configuration.",
    ),
    ErrorCategory.VALIDATION: ErrorHint(
        summary="Input validation error",
        detail="The provided input failed validation checks.",
        remediation="Review the input format and ensure all required fields are provided with correct values.",
    ),
    ErrorCategory.RATE_LIMIT: ErrorHint(
        summary="Rate limit exceeded",
        detail="A rate limit has been exceeded on the target or an API endpoint.",
        remediation="Reduce request frequency with '--aggressiveness low' or '--rate-limit <n>'. Add delays between requests.",
        docs_url="https://docs.argus.io/usage/scan#rate-limiting",
    ),
    ErrorCategory.SECURITY: ErrorHint(
        summary="Authentication or authorization error",
        detail="Access was denied due to missing or invalid credentials.",
        remediation="Verify your API keys, tokens, and credentials are correct and have the required permissions.",
    ),
    ErrorCategory.RESOURCE: ErrorHint(
        summary="Resource limit reached",
        detail="A system resource limit (memory, disk, connections) has been reached.",
        remediation="Free up system resources: close other applications, check disk space, or increase resource limits.",
    ),
    ErrorCategory.TIMEOUT: ErrorHint(
        summary="Operation timed out",
        detail="An operation exceeded its time limit and was terminated.",
        remediation="Increase the applicable timeout setting or reduce the scope of the operation.",
    ),
    ErrorCategory.UNKNOWN: ErrorHint(
        summary="Unknown error",
        detail="An unexpected error occurred that could not be classified.",
        remediation="Check the error details above. If this persists, consider filing a bug report with the full error output.",
        docs_url="https://docs.argus.io/contributing/bug-reports",
    ),
}


# ── Tool-specific remediation ──

# Patterns for matching tool stderr to remediation hints.
# These are remediation-specific, NOT classification — they map observed
# error messages in tool output to user-facing fix guidance.
_TOOL_SPECIFIC_PATTERNS: dict[str, list[tuple[re.Pattern, str, str, str | None]]] = {
    "nuclei": [
        (
            re.compile(r"(?:template|templates?).*not found", re.IGNORECASE),
            "Nuclei templates not found",
            "Nuclei requires template files to run scans. Install them with 'nuclei -update-templates'.",
            "nuclei -update-templates",
        ),
        (
            re.compile(r"failed to load.*template", re.IGNORECASE),
            "Failed to load Nuclei template",
            "The specified template path is invalid or the template file is malformed. Check the template path and file format.",
            None,
        ),
    ],
    "nmap": [
        (
            re.compile(
                r"you (?:don't have|need).*root|permission denied|requires root privileges",
                re.IGNORECASE,
            ),
            "Nmap requires elevated permissions",
            "Nmap's SYN scan and OS detection require root privileges. Use 'sudo' or adjust the scan type.",
            "sudo nmap <target>",
        ),
        (
            re.compile(r"failed to open.*(?:interface|device)", re.IGNORECASE),
            "Nmap could not open network interface",
            "Nmap could not access the network interface. Check that the interface exists and you have the necessary permissions.",
            None,
        ),
    ],
    "sqlmap": [
        (
            re.compile(r"connection refused|failed to connect", re.IGNORECASE),
            "SQLmap could not connect to target",
            "The target URL is unreachable or refusing connections. Verify the target is online and the URL is correct.",
            None,
        ),
        (
            re.compile(r"no parameter.*found|no.*injectable", re.IGNORECASE),
            "SQLmap found no injectable parameters",
            "SQLmap did not find any injectable parameters. This may mean the target is not vulnerable, or you need to specify parameters manually with '-p'.",
            None,
        ),
    ],
    "semgrep": [
        (
            re.compile(r"no (?:rules?|config) found", re.IGNORECASE),
            "Semgrep rules not found",
            "Semgrep requires rule files to scan. Specify rules with '--config' or ensure your project has a .semgrep directory.",
            "semgrep --config auto .",
        ),
    ],
    "gitleaks": [
        (
            re.compile(r"no.*git.*(?:repo|directory)", re.IGNORECASE),
            "Gitleaks requires a git repository",
            "Gitleaks scans git repositories. Ensure the target is a valid git repository or use '--no-git' for filesystem scanning.",
            "gitleaks detect --no-git -s <path>",
        ),
    ],
}


def _tool_specific_hint(
    tool_name: str,
    exit_code: int,
    stderr: str,
) -> ErrorHint | None:
    """Generate a tool-specific remediation hint by inspecting stderr.

    This is the ONLY function in this module that inspects raw error text.
    It is remediation-only — it maps specific tool error patterns to
    actionable user guidance without re-classifying the error type.

    Args:
        tool_name: Name of the tool that failed.
        exit_code: Tool's exit code.
        stderr: Tool's stderr output.

    Returns:
        ErrorHint if a pattern matched, None otherwise.
    """
    if not stderr or tool_name not in _TOOL_SPECIFIC_PATTERNS:
        return None

    for pattern, summary, remediation, hint_command in _TOOL_SPECIFIC_PATTERNS[
        tool_name
    ]:
        if pattern.search(stderr):
            return ErrorHint(
                summary=summary,
                detail=f"Tool '{tool_name}' exited with code {exit_code}.",
                remediation=remediation,
                hint_command=hint_command,
                tool=tool_name,
            )

    return None


def _hint_for_error_code(code: ErrorCode) -> ErrorHint | None:
    """Look up a hint by ErrorCode (most specific path)."""
    return _ERROR_CODE_HINTS.get(code)


def _hint_for_category(category: ErrorCategory) -> ErrorHint | None:
    """Look up a fallback hint by ErrorCategory (less specific path)."""
    return _CATEGORY_FALLBACK_HINTS.get(category)


# ── Generic fallback hint ──

_GENERIC_FALLBACK_HINT = ErrorHint(
    summary="An unexpected error occurred",
    detail="Argus encountered an error that could not be specifically classified.",
    remediation="Check the error details above. If the problem persists, try running with '--verbose' for more information.",
)


def hint_for_classification(
    classification: CodeBasedClassification,
    *,
    error: Exception,
    tool_name: str | None = None,
    target: str | None = None,
) -> ErrorHint | None:
    """Translate a CodeBasedClassification into a user-facing ErrorHint.

    Priority order:
      1. ErrorCode match (most specific — from _ERROR_CODE_HINTS)
      2. ErrorCategory match (fallback — from _CATEGORY_FALLBACK_HINTS)
      3. Generic fallback

    Args:
        classification: The CodeBasedClassification from error_classifier.py.
        error: The original exception (used for context, not re-classification).
        tool_name: Optional tool name for context and tool-specific hints.
        target: Optional target for context.

    Returns:
        ErrorHint, or None if the classification is empty/unclassifiable.
    """
    if classification is None:
        return None

    # Priority 1: ErrorCode match (most specific)
    if classification.error_code is not None:
        hint = _hint_for_error_code(classification.error_code)
        if hint is not None:
            hint = ErrorHint(
                summary=hint.summary,
                detail=hint.detail,
                remediation=hint.remediation,
                hint_command=hint.hint_command,
                docs_url=hint.docs_url,
                tool=tool_name,
                error_id=classification.error_code.value,
            )
            return hint

    # Priority 2: ErrorCategory match (fallback)
    hint = _hint_for_category(classification.category)
    if hint is not None:
        hint = ErrorHint(
            summary=hint.summary,
            detail=hint.detail,
            remediation=hint.remediation,
            hint_command=hint.hint_command,
            docs_url=hint.docs_url,
            tool=tool_name,
            error_id=getattr(classification.error_code, "value", None),
        )
        return hint

    # Priority 3: Generic fallback
    return ErrorHint(
        summary=_GENERIC_FALLBACK_HINT.summary,
        detail=str(error)[:500] if error else "",
        remediation=_GENERIC_FALLBACK_HINT.remediation,
        tool=tool_name,
    )


def build_error_hint(
    error: Exception,
    *,
    error_code: ErrorCode | None = None,
    tool_name: str | None = None,
    target: str | None = None,
    stderr: str | None = None,
    exit_code: int | None = None,
    task_name: str | None = None,
    retry_count: int = 0,
) -> ErrorHint | None:
    """Convenience: classify an error and produce a user-facing hint.

    This is the primary entry point for callers (e.g., tool_runner.py).
    It classifies the error via error_classifier.py, then translates the
    classification to a user-facing hint.

    If tool_name and stderr are provided, tool-specific stderr patterns
    are checked as an additional remediation source.

    Args:
        error: The exception that occurred.
        error_code: Optional ErrorCode for precise classification.
        tool_name: Optional tool name.
        target: Optional scan target.
        stderr: Optional tool stderr output (for tool-specific hints).
        exit_code: Optional tool exit code.
        task_name: Optional task name for classification context.
        retry_count: Retry attempt number.

    Returns:
        ErrorHint if classifiable, None if not (no crash).
    """
    try:
        classification = classify_error_with_code(
            error,
            error_code=error_code,
            task_name=task_name,
            retry_count=retry_count,
        )

        hint = hint_for_classification(
            classification,
            error=error,
            tool_name=tool_name,
            target=target,
        )

        # Check for tool-specific remediation from stderr
        if hint and tool_name and stderr:
            tool_hint = _tool_specific_hint(tool_name, exit_code or -1, stderr)
            if tool_hint is not None:
                # Merge: use tool-specific remediation over the generic one
                hint.remediation = tool_hint.remediation or hint.remediation
                if tool_hint.summary:
                    hint.summary = tool_hint.summary
                if tool_hint.hint_command:
                    hint.hint_command = tool_hint.hint_command

        return hint
    except Exception:
        logger.warning("Failed to build error hint", exc_info=True)
        return None
