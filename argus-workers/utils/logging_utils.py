"""
Secrets redaction utilities for logging.

Redacts sensitive information from logs to prevent credential leakage.
"""
import logging
import re
from typing import Any

# Patterns for sensitive data that should be redacted
SECRET_PATTERNS = {
    # API keys and tokens
    'api_key': re.compile(r'(?i)(api[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-]{8,})'),
    'bearer_token': re.compile(r'(?i)(bearer\s+)([a-zA-Z0-9_\-\.]{10,})'),
    'auth_token': re.compile(r'(?i)(auth[_-]?token["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{10,})'),

    # Passwords (including in URLs) - must check before JWT
    'password': re.compile(r'(?i)(password["\']?\s*[:=]\s*["\']?)([^\s"\'<>]{4,})'),
    'url_password': re.compile(r'((?:mysql|postgres|postgresql|mongodb|redis|amqp)://[^:]+):([^@]+)@'),

    # AWS credentials
    'aws_access': re.compile(r'(AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}'),
    'aws_secret': re.compile(r'(?i)(aws[_-]?secret[_-]?access[_-]?key["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9/+=]{20,})'),

    # JWT tokens
    'jwt': re.compile(r'eyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+'),

    # Private keys
    'private_key': re.compile(r'-----BEGIN\s+(?:RSA\s+|EC\s+|DSA\s+|OPENSSH\s+|ENCRYPTED\s+)?PRIVATE\s+KEY-----'),

    # Database URLs
    'db_url': re.compile(r'(?i)(database[_-]?url|db[_-]?url|connection[_-]?string["\']?\s*[:=]\s*["\']?)((?:mysql|postgres|postgresql|mongodb)://[^\s"\'<>]+)'),

    # Generic secret patterns
    'secret': re.compile(r'(?i)(secret["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-]{8,})'),
    'token': re.compile(r'(?i)(token["\']?\s*[:=]\s*["\']?)([a-zA-Z0-9_\-\.]{10,})'),
}


def redact_string(text: str) -> str:
    """
    Redact sensitive information from a string.

    Args:
        text: Input text that may contain secrets

    Returns:
        Text with secrets redacted
    """
    if not text:
        return text

    result = text

    # Order matters: check specific patterns first, then generic ones
    # URL password must come after JWT/private_key to avoid false matches
    for name, pattern in SECRET_PATTERNS.items():
        if name in ['jwt', 'private_key', 'aws_access']:
            # Full value redaction for these patterns
            result = pattern.sub('[REDACTED]', result)
        elif name == 'url_password':
            # URL password redaction
            result = pattern.sub('://****:****@', result)
        else:
            # Partial redaction (show first few chars)
            result = pattern.sub(r'\1****', result)

    return result


def redact_dict(data: dict[str, Any]) -> dict[str, Any]:
    """
    Recursively redact secrets from a dictionary.

    Args:
        data: Dictionary that may contain secrets

    Returns:
        Dictionary with secrets redacted
    """
    if not data:
        return data

    # Keys that are always sensitive
    SENSITIVE_KEYS = {
        'password', 'secret', 'token', 'api_key', 'apikey', 'private_key',
        'access_token', 'refresh_token', 'auth_token', 'bearer_token',
        'connection_string', 'database_url', 'db_url', 'credential',
        'aws_access_key', 'aws_secret_key', 'session_id', 'session_token',
    }

    result = {}

    for key, value in data.items():
        # Check if this key is sensitive
        key_lower = key.lower()

        if key_lower in SENSITIVE_KEYS:
            # Redact the value
            if isinstance(value, str):
                result[key] = '[REDACTED]'
            elif isinstance(value, dict):
                result[key] = redact_dict(value)
            else:
                result[key] = value
        elif isinstance(value, str):
            # Check if the string contains secrets
            result[key] = redact_string(value)
        elif isinstance(value, dict):
            # Recursively process nested dicts
            result[key] = redact_dict(value)
        elif isinstance(value, list):
            # Process list items
            result[key] = [
                redact_string(v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            result[key] = value

    return result


class SecretsRedactionFilter(logging.Filter):
    """
    Logging filter that automatically redacts secrets from log records.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        # Redact from message
        record.msg = redact_string(str(record.msg))

        # Redact from args if they're strings or dicts
        if record.args:
            new_args = []
            for arg in record.args:
                if isinstance(arg, str):
                    new_args.append(redact_string(arg))
                elif isinstance(arg, dict):
                    new_args.append(redact_dict(arg))
                else:
                    new_args.append(arg)
            record.args = tuple(new_args)

        return True


class RedactedLogger:
    """
    Logger wrapper that automatically redacts secrets from log output.
    """

    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def _redact_message(self, message: str, metadata: dict = None) -> str:
        """Redact secrets from message and metadata."""
        message = redact_string(message)
        if metadata:
            metadata = redact_dict(metadata)
        return message, metadata

    def debug(self, message: str, **kwargs):
        msg, meta = self._redact_message(message, kwargs)
        self.logger.debug(msg, **(meta if meta else {}))

    def info(self, message: str, **kwargs):
        msg, meta = self._redact_message(message, kwargs)
        self.logger.info(msg, **(meta if meta else {}))

    def warning(self, message: str, **kwargs):
        msg, meta = self._redact_message(message, kwargs)
        self.logger.warning(msg, **(meta if meta else {}))

    def error(self, message: str, **kwargs):
        msg, meta = self._redact_message(message, kwargs)
        self.logger.error(msg, **(meta if meta else {}))


def get_redacted_logger(name: str) -> RedactedLogger:
    """Get a logger that automatically redacts secrets."""
    return RedactedLogger(logging.getLogger(name))


def setup_logging():
    """
    Setup global logging with secrets redaction filter.
    Call this once at application startup to enable automatic redaction
    for all loggers.
    """
    # Get the root logger
    root_logger = logging.getLogger()

    # Add our filter if not already added
    filter_name = 'SecretsRedactionFilter'
    if not any(f.name == filter_name for f in root_logger.filters):
        secret_filter = SecretsRedactionFilter(filter_name)
        root_logger.addFilter(secret_filter)

    # Also add to common loggers that might be created before root logger setup
    for logger_name in ['argus', 'celery', 'uvicorn']:
        logger = logging.getLogger(logger_name)
        if not any(f.name == filter_name for f in logger.filters):
            # Add filter directly to ensure it works before propagation
            logger.addFilter(SecretsRedactionFilter(filter_name))
            # Ensure propagate is on (default is True, but be explicit)
            logger.propagate = True


# ── Standardized Console Logging Utilities ──────────────────────────────

import time as _time


class ScanLogger:
    """
    Standardized console logger for the scan pipeline.

    Provides banner-style logging for phase boundaries, tool start/complete,
    and LLM call tracing — all with a consistent visual format.

    Usage:
        slog = ScanLogger("recon", engagement_id="abc-123")
        slog.phase_start("Reconnaissance", target="https://example.com")
        slog.tool_start("nuclei", ["-u", "target", "-severity", "high"])
        slog.tool_complete("nuclei", success=True, findings=5, duration_ms=12000)
        slog.phase_complete("recon", status="completed", findings=12)
    """

    # ANSI color codes for terminal output
    _CYAN = "\033[36m"
    _GREEN = "\033[32m"
    _YELLOW = "\033[33m"
    _RED = "\033[31m"
    _MAGENTA = "\033[35m"
    _BLUE = "\033[34m"
    _BOLD = "\033[1m"
    _RESET = "\033[0m"
    _DIM = "\033[2m"

    def __init__(self, phase: str, engagement_id: str = ""):
        self.phase = phase
        self.engagement_id = engagement_id[:8] if engagement_id else ""
        self._start_time = _time.time()
        self._logger = logging.getLogger(f"argus.scan.{phase}")

    def _elapsed(self) -> str:
        seconds = _time.time() - self._start_time
        if seconds < 60:
            return f"{seconds:.1f}s"
        return f"{seconds/60:.1f}m"

    def _prefix(self) -> str:
        tag = self.phase.upper()
        eid = f"[{self.engagement_id}]" if self.engagement_id else ""
        return f"{self._DIM}{self._elapsed():>8}{self._RESET} {self._BLUE}{tag:>10}{self._RESET} {eid}"

    def phase_start(self, phase_label: str, **details):
        """Log a phase boundary start — emits a prominent banner.

        Args:
            phase_label: Human-readable phase name (e.g. "Reconnaissance")
            **details: Key-value pairs appended as context (target, budget, etc.)
        """
        detail_str = " ".join(f"{k}={v}" for k, v in details.items())
        msg = f"{self._prefix()} {self._CYAN}{self._BOLD}=== {phase_label.upper()} START ==={self._RESET}"
        if detail_str:
            msg += f"  ({detail_str})"
        self._logger.info(msg)

    def phase_complete(self, phase_label: str, status: str = "completed", **details):
        """Log a phase boundary completion.

        Args:
            phase_label: Human-readable phase name
            status: "completed", "failed", or "skipped"
            **details: Key-value pairs (findings, duration, etc.)
        """
        detail_str = " ".join(f"{k}={v}" for k, v in details.items())
        color = self._GREEN if status == "completed" else self._RED if status == "failed" else self._YELLOW
        msg = f"{self._prefix()} {color}{self._BOLD}=== {phase_label.upper()} {status.upper()} ==={self._RESET}"
        if detail_str:
            msg += f"  ({detail_str})"
        self._logger.info(msg)

    def phase_header(self, phase_label: str, detail: str = "", **details):
        """Log a phase entry header (less prominent than phase_start).

        Used for sub-phases within a larger phase.

        Args:
            phase_label: Human-readable phase name (e.g. "Port Scan")
            detail: Optional positional detail string (legacy format, e.g. "target=x, ports=y")
            **details: Optional key=value pairs appended as context
        """
        detail_str = " ".join(f"{k}={v}" for k, v in details.items())
        if detail and detail_str:
            detail_str = detail + " | " + detail_str
        elif detail:
            detail_str = detail
        msg = f"{self._prefix()} {self._CYAN}>>> {phase_label}{self._RESET}"
        if detail_str:
            msg += f"  {self._DIM}({detail_str}){self._RESET}"
        self._logger.info(msg)

    def tool_start(self, tool: str, args: list | None = None, **details):
        """Log a tool execution start.

        Args:
            tool: Tool name (e.g. "nuclei", "browser_scan")
            args: Optional list of argument strings (legacy format)
            **details: Optional key=value pairs appended as context
        """
        arg_summary = " ".join(str(a) for a in (args or [])[:4])
        if len(args or []) > 4:
            arg_summary += "..."
        if details:
            detail_str = " ".join(f"{k}={v}" for k, v in details.items())
            if arg_summary:
                arg_summary += " | " + detail_str
            else:
                arg_summary = detail_str
        msg = f"{self._prefix()}   {self._BOLD}├─{self._RESET} [{tool}] Starting"
        if arg_summary:
            msg += f"  {self._DIM}{arg_summary}{self._RESET}"
        self._logger.info(msg)

    def tool_complete(self, tool: str, success: bool = True, findings: int = 0, duration_ms: int = 0, **details):
        """Log a tool execution completion with findings count and duration.

        Args:
            tool: Tool name (e.g. "nuclei", "browser_scan")
            success: Whether the tool completed successfully
            findings: Number of findings discovered
            duration_ms: Execution duration in milliseconds
            **details: Optional key=value pairs appended as context
        """
        status_icon = self._GREEN + "✓" + self._RESET if success else self._RED + "✗" + self._RESET
        dur_str = f"{duration_ms}ms" if duration_ms < 10000 else f"{duration_ms/1000:.1f}s"
        msg = f"{self._prefix()}   {self._BOLD}└─{self._RESET} [{tool}] {status_icon}  "
        parts = []
        if findings:
            parts.append(f"{findings} finding(s)")
        parts.append(f"{dur_str}")
        if details:
            detail_str = " ".join(f"{k}={v}" for k, v in details.items())
            parts.append(detail_str)
        msg += ", ".join(parts)
        self._logger.info(msg)

    def tool_result(self, tool: str, detail: str):
        """Log a tool result detail line (indented under a tool)."""
        msg = f"{self._prefix()}   {self._DIM}  -> [{tool}] {detail}{self._RESET}"
        self._logger.info(msg)

    def llm_start(self, model: str, action: str):
        """Log an LLM call start."""
        msg = f"{self._prefix()}   {self._MAGENTA}┌─ LLM [{model}] {action}{self._RESET}"
        self._logger.info(msg)

    def llm_complete(self, model: str, duration_ms: int = 0, tokens: int = 0, cost: float = 0.0):
        """Log an LLM call completion."""
        dur_str = f"{duration_ms}ms" if duration_ms < 10000 else f"{duration_ms/1000:.1f}s"
        msg = f"{self._prefix()}   {self._MAGENTA}└─ LLM [{model}] ✓ {dur_str}"
        if tokens:
            msg += f", {tokens} tokens"
        if cost:
            msg += f", ${cost:.6f}"
        msg += self._RESET
        self._logger.info(msg)

    def llm_result(self, detail: str):
        """Log an LLM result detail."""
        msg = f"{self._prefix()}   {self._DIM}  -> {detail}{self._RESET}"
        self._logger.info(msg)

    def info(self, message: str):
        """Log a simple info message with the standard prefix."""
        msg = f"{self._prefix()}  {message}"
        self._logger.info(msg)

    def warn(self, message: str):
        """Log a warning message with the standard prefix."""
        msg = f"{self._prefix()}  {self._YELLOW}{message}{self._RESET}"
        self._logger.warning(msg)

    def error(self, message: str):
        """Log an error message with the standard prefix."""
        msg = f"{self._prefix()}  {self._RED}{self._BOLD}ERROR: {message}{self._RESET}"
        self._logger.error(msg)

    def target_start(self, target: str, index: int = 0, total: int = 1):
        """Log the start of processing a specific target."""
        label = f"[{index}/{total}]" if total > 1 else ""
        msg = f"{self._prefix()}   {self._BOLD}┌─ Target{label}: {target}{self._RESET}"
        self._logger.info(msg)

    def target_complete(self, target: str, findings: int = 0, tools: int = 0):
        """Log the completion of processing a target."""
        msg = f"{self._prefix()}   {self._BOLD}└─ Target: {target}{self._RESET} — {findings} findings, {tools} tools"
        self._logger.info(msg)

    def agent_iteration(self, iteration: int, tool: str, reasoning: str = "", cost: float = 0.0):
        """Log an agent loop iteration."""
        rsn = f" — {reasoning[:80]}" if reasoning else ""
        cost_str = f" [${cost:.6f}]" if cost else ""
        msg = f"{self._prefix()}   {self._BLUE}├─ Iter {iteration}:{self._RESET} [{tool}]{rsn}{cost_str}"
        self._logger.info(msg)

    def agent_complete(self, tools_ran: int, total_cost: float = 0.0):
        """Log agent completion summary."""
        msg = f"{self._prefix()}   {self._BLUE}└─ AGENT: ran {tools_ran} tools"
        if total_cost:
            msg += f", total cost=${total_cost:.4f}"
        self._logger.info(msg)

    def swarm_activate(self, agents: list[str]):
        """Log swarm agent activations."""
        msg = f"{self._prefix()}   {self._MAGENTA}SWARM: activated {len(agents)} specialist(s): {', '.join(agents)}{self._RESET}"
        self._logger.info(msg)

    def swarm_complete(self, raw: int, deduped: int):
        """Log swarm completion with dedup stats."""
        msg = f"{self._prefix()}   {self._MAGENTA}SWARM: {raw} raw → {deduped} deduped findings{self._RESET}"
        self._logger.info(msg)

    def dispatch(self, task_name: str, task_id: str = ""):
        """Log a downstream task dispatch."""
        tid = f" (id={task_id})" if task_id else ""
        msg = f"{self._prefix()}  {self._GREEN}-> Dispatching: {task_name}{tid}{self._RESET}"
        self._logger.info(msg)

    def transition(self, from_state: str, to_state: str, reason: str = ""):
        """Log a state transition."""
        rsn = f": {reason}" if reason else ""
        msg = f"{self._prefix()}  {self._YELLOW}~> State: {from_state} -> {to_state}{rsn}{self._RESET}"
        self._logger.info(msg)
