"""
AI/LLM Surface Detection for Reconnaissance.

Detects AI chatbot widgets, LLM provider endpoints, and AI API paths
during the reconnaissance phase. Findings are advisory-only (INFO
severity) and suggest manual AI red-team review via PyRIT or similar
tooling.

Detection categories:
    1. Chatbot widgets — Intercom/Drift/Zendesk script tags, data attributes
    2. LLM provider headers — Response headers indicating LLM providers
    3. Common AI API paths — Probe /api/chat, /v1/completions, etc.
"""

from __future__ import annotations

import logging
from typing import Any

from models.recon_context import ReconContext

logger = logging.getLogger(__name__)

# ── Known AI chatbot provider patterns ──

CHATBOT_PROVIDER_PATTERNS: dict[str, list[str]] = {
    "intercom": [
        "intercom",
        "app.intercom",
        "widget.intercom",
    ],
    "drift": [
        "drift",
        "js.drift",
        "driftwidget",
    ],
    "zendesk": [
        "zopim",
        "zendesk_chat",
        "zendesk_web_widget",
    ],
    "crisp": [
        "crisp.chat",
        "client.crisp",
    ],
    "tawk": [
        "tawk.to",
        "embed.tawk",
    ],
    "livechat": [
        "livechatinc",
        "chat.livechat",
        "lc.js",
    ],
    "freshchat": [
        "freshchat",
        "freshworks",
    ],
    "olark": [
        "olark",
        "static.olark",
    ],
}

# ── Common AI API paths to probe ──

AI_API_PATHS = [
    "/api/chat",
    "/api/chat/completions",
    "/v1/chat/completions",
    "/v1/completions",
    "/api/ai",
    "/api/ask",
    "/api/query",
    "/api/generate",
    "/api/inference",
    "/api/llm",
    "/api/complete",
    "/openai",
    "/api/openai",
]

# ── LLM provider identifiers in response headers ──

LLM_PROVIDER_HEADERS: dict[str, list[str]] = {
    "openai": ["x-request-id", "openai-"],
    "anthropic": ["x-amzn-requestid", "anthropic"],
    "azure": ["x-azure-"],
    "google": ["x-google-"],
    "aws-bedrock": ["x-amzn-bedrock"],
}

# ── LLM provider keywords in page content ──

LLM_CONTENT_PATTERNS: dict[str, list[str]] = {
    "openai": ["chatgpt", "openai", "gpt-", "powered by ai"],
    "anthropic": ["claude", "anthropic"],
    "google": ["gemini", "bard", "palm"],
}


def detect_ai_surface(
    recon_ctx: ReconContext,
    html_content: str | None = None,
    response_headers: dict[str, str] | None = None,
) -> ReconContext:
    """
    Detect AI/LLM surface indicators and update the ReconContext in place.

    Checks HTML for chatbot widgets, response headers for LLM provider
    signatures, and recon context api_endpoints for common AI API paths.

    Args:
        recon_ctx: ReconContext to update with AI findings
        html_content: Optional HTML page content to scan for chatbot widgets
        response_headers: Optional HTTP response headers to scan for LLM providers

    Returns:
        The updated ReconContext (modified in place, also returned for chaining)
    """
    detected_providers: set[str] = set()
    detected_ai_endpoints: list[str] = []

    # ── 1. Check for chatbot widgets in HTML ──
    if html_content:
        html_lower = html_content.lower()
        for provider, patterns in CHATBOT_PROVIDER_PATTERNS.items():
            for pattern in patterns:
                if pattern in html_lower:
                    detected_providers.add(provider)
                    logger.debug(
                        "AI surface: detected %s chatbot widget (pattern: %s)",
                        provider,
                        pattern,
                    )
                    break

    # ── 2. Check response headers for LLM provider signatures ──
    if response_headers:
        headers_lower = {k.lower(): v.lower() for k, v in response_headers.items()}
        for provider, header_patterns in LLM_PROVIDER_HEADERS.items():
            for pattern in header_patterns:
                if any(pattern in k or pattern in v for k, v in headers_lower.items()):
                    detected_providers.add(provider)
                    logger.debug(
                        "AI surface: detected %s provider from headers (pattern: %s)",
                        provider,
                        pattern,
                    )
                    break

    # ── 3. Check existing api_endpoints for known AI API paths ──
    for endpoint in recon_ctx.api_endpoints:
        endpoint_lower = endpoint.lower()
        for ai_path in AI_API_PATHS:
            if ai_path in endpoint_lower:
                if endpoint not in detected_ai_endpoints:
                    detected_ai_endpoints.append(endpoint)
                break

    # ── 4. Check crawled paths for AI-related content ──
    if html_content:
        html_lower = html_content.lower()
        for provider, content_patterns in LLM_CONTENT_PATTERNS.items():
            for pattern in content_patterns:
                if pattern in html_lower:
                    detected_providers.add(provider)
                    logger.debug(
                        "AI surface: detected %s reference in page content (pattern: %s)",
                        provider,
                        pattern,
                    )
                    break

    # ── Update ReconContext ──
    has_ai_indicator = bool(detected_providers) or bool(detected_ai_endpoints)
    if has_ai_indicator:
        recon_ctx.has_ai_chatbot = True
        # Use the most prominent provider (prefer known LLM providers over chat widgets)
        provider_priority = ["openai", "anthropic", "google", "aws-bedrock", "azure"]
        for p in provider_priority:
            if p in detected_providers:
                recon_ctx.llm_provider_detected = p
                break
        if not recon_ctx.llm_provider_detected and detected_providers:
            recon_ctx.llm_provider_detected = next(iter(detected_providers))
        logger.info(
            "AI surface detected: provider=%s, endpoints=%s",
            recon_ctx.llm_provider_detected or "unknown",
            detected_ai_endpoints,
        )
    else:
        logger.debug("AI surface: no indicators detected")

    # Extend (don't replace) any previously detected AI endpoints
    existing_ai = set(recon_ctx.ai_endpoints)
    existing_ai.update(detected_ai_endpoints)
    recon_ctx.ai_endpoints = sorted(existing_ai)

    return recon_ctx


def build_ai_advisory_finding(
    recon_ctx: ReconContext, target_url: str
) -> dict[str, Any] | None:
    """
    Build an advisory finding if AI surface was detected.

    Args:
        recon_ctx: ReconContext with AI detection results
        target_url: The target URL being assessed

    Returns:
        Finding dict with INFO severity, or None if no AI surface detected
    """
    if not recon_ctx.has_ai_chatbot and not recon_ctx.ai_endpoints:
        return None

    evidence: dict[str, Any] = {
        "llm_provider": recon_ctx.llm_provider_detected,
        "ai_endpoints": recon_ctx.ai_endpoints,
        "detection_method": "html_widget_pattern_match"
        if recon_ctx.has_ai_chatbot
        else "api_path_probe",
    }

    if recon_ctx.has_ai_chatbot:
        evidence["chatbot_provider"] = recon_ctx.llm_provider_detected

    provider_info = (
        f" ({recon_ctx.llm_provider_detected})"
        if recon_ctx.llm_provider_detected
        else ""
    )

    return {
        "type": "AI_SURFACE_DETECTED",
        "severity": "INFO",
        "confidence": 0.9 if recon_ctx.has_ai_chatbot else 0.6,
        "endpoint": target_url,
        "source_tool": "ai_surface_detector",
        "evidence": evidence,
        "title": (
            f"AI/LLM Surface Detected{provider_info}"
        ),
        "description": (
            f"The target {target_url} appears to use AI/LLM components. "
            f"Detected provider: {recon_ctx.llm_provider_detected or 'Unknown'}. "
            f"AI-related endpoints: {', '.join(recon_ctx.ai_endpoints) or 'None discovered'}. "
            "Manual AI red-team review (e.g. using PyRIT) is recommended."
        ),
        "remediation": (
            "Conduct a manual AI red-team security assessment using dedicated "
            "AI testing tools such as PyRIT, Garak, or similar. Test for: "
            "prompt injection, data leakage via chat interfaces, "
            "insecure LLM API access controls, and excessive agency in "
            "AI agent configurations."
        ),
    }
