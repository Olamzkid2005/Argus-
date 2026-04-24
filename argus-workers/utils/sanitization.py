"""
Input sanitization utilities for security.
Sanitizes HTML/JS in evidence before DB storage.
"""
import re
import html
from typing import Any, Dict


# Patterns that indicate potentially dangerous content
DANGEROUS_PATTERNS = [
    (r'<script[^>]*>.*?</script>', 'script tag'),
    (r'javascript:', 'javascript: protocol'),
    (r'on\w+\s*=', 'event handler'),
    (r'<iframe[^>]*>.*?</iframe>', 'iframe'),
    (r'<object[^>]*>.*?</object>', 'object'),
    (r'<embed[^>]*>', 'embed'),
    (r'<applet[^>]*>.*?</applet>', 'applet'),
    (r'<svg[^>]*>.*?</svg>', 'svg'),
    (r'<meta[^>]*>', 'meta refresh'),
    (r'eval\s*\(', 'eval()'),
    (r'document\.', 'document access'),
    (r'window\.', 'window access'),
]


def sanitize_string(value: str) -> str:
    """
    Sanitize a string value by escaping HTML entities.
    
    Args:
        value: Input string
        
    Returns:
        Sanitized string with HTML entities escaped
    """
    # Escape HTML entities
    return html.escape(value)


def sanitize_evidence(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sanitize evidence dictionary for safe storage.
    
    Recursively sanitizes all string values in the evidence dict
    to prevent XSS when displayed in the UI.
    
    Args:
        evidence: Evidence dictionary from scanner
        
    Returns:
        Sanitized evidence dictionary
    """
    if not evidence:
        return {}
    
    sanitized = {}
    
    for key, value in evidence.items():
        if isinstance(value, str):
            sanitized[key] = sanitize_string(value)
        elif isinstance(value, dict):
            sanitized[key] = sanitize_evidence(value)
        elif isinstance(value, list):
            sanitized[key] = [
                sanitize_string(v) if isinstance(v, str) else v
                for v in value
            ]
        else:
            # Keep non-string values as-is
            sanitized[key] = value
    
    return sanitized


def check_for_dangerous_content(value: str) -> list:
    """
    Check if a string contains potentially dangerous patterns.
    
    Args:
        value: String to check
        
    Returns:
        List of detected dangerous patterns
    """
    detected = []
    
    for pattern, description in DANGEROUS_PATTERNS:
        if re.search(pattern, value, re.IGNORECASE | re.DOTALL):
            detected.append(description)
    
    return detected


def strip_dangerous_tags(value: str) -> str:
    """
    Remove dangerous HTML/JS tags from a string.
    
    Args:
        value: Input string
        
    Returns:
        String with dangerous tags stripped
    """
    result = value
    
    for pattern, _ in DANGEROUS_PATTERNS:
        result = re.sub(pattern, '[removed]', result, flags=re.IGNORECASE | re.DOTALL)
    
    return result
