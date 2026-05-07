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
