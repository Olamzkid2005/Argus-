"""Named constants for the Argus worker system — organized into dataclass groups.

B.12: Refactored from flat module-level constants into grouped dataclasses
for discoverability, type safety, and IDE autocompletion.
"""

import os
from dataclasses import dataclass, field


# ──────────────────────────────────────────────
# Timeouts
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class TimeoutConfig:
    hard_timeout_seconds: int = (
        7200  # 2 hours — recon + scan + analyze can exceed 1 hour
    )
    tool_timeout_default: int = 180  # 3 minutes default tool timeout
    tool_timeout_short: int = 60  # 1 minute for quick tools
    tool_timeout_long: int = 300  # 5 minutes for heavy tools
    web_scanner_check_timeout: int = 600  # 10 min for all checks batch
    scope_validation_timeout: int = 5  # 5s for scope DB lookup
    ssl_timeout: int = 10  # SSL verification timeout
    llm_review_timeout: int = 60  # per-finding LLM analysis timeout in seconds
    llm_agent_timeout_seconds: int = 30  # LLM agent timeout

    @classmethod
    def from_env(cls) -> "TimeoutConfig":
        return cls(
            web_scanner_check_timeout=int(
                os.getenv("ARGUS_WEB_SCANNER_CHECK_TIMEOUT", "600")
            ),
            scope_validation_timeout=int(
                os.getenv("ARGUS_SCOPE_VALIDATION_TIMEOUT", "5")
            ),
            llm_agent_timeout_seconds=int(os.getenv("LLM_AGENT_TIMEOUT_SECONDS", "30")),
        )


# ──────────────────────────────────────────────
# Rate limiting
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class RateLimitConfig:
    delay_ms: int = 200
    max_concurrent_requests: int = 20

    @classmethod
    def from_env(cls) -> "RateLimitConfig":
        return cls(
            delay_ms=int(os.getenv("ARGUS_RATE_LIMIT_DELAY_MS", "200")),
            max_concurrent_requests=int(os.getenv("ARGUS_MAX_CONCURRENT", "20")),
        )


# ──────────────────────────────────────────────
# Content & batch limits
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class ContentLimits:
    max_content_length: int = 1000  # Max chars to store in evidence
    max_findings_per_batch: int = 50  # Batch insert size
    max_endpoints_per_scan: int = 1000  # Max endpoints to process
    max_tool_output_bytes: int = 100 * 1024 * 1024  # 100MB max tool output


# ──────────────────────────────────────────────
# Retries
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class RetryConfig:
    max_tool_retries: int = 2  # Number of retry attempts
    retry_backoff_base: int = 2  # Exponential backoff base
    llm_max_retries: int = 2
    llm_agent_max_retries: int = 2


# ──────────────────────────────────────────────
# Scanning
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class ScanConfig:
    default_aggressiveness: str = "default"
    max_pages_to_crawl: int = 10
    max_parameters_to_fuzz: int = 20


# ──────────────────────────────────────────────
# SSRF prevention (Git clone)
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class GitSSRFConfig:
    allowed_git_schemes: tuple[str, ...] = ("https", "http", "ssh")
    host_allowlist: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            sorted(
                {
                    "github.com",
                    "gitlab.com",
                    "gitlab.freedesktop.org",
                    "bitbucket.org",
                    "gist.github.com",
                    "git.sr.ht",
                    "git.kernel.org",
                    "git.savannah.gnu.org",
                    "git.savannah.nongnu.org",
                    "gitlab.gnome.org",
                    "gitlab.kitware.com",
                    "gitlab.xfce.org",
                    "gitlab.archlinux.org",
                }
            )
        )
    )

    @classmethod
    def from_env(cls) -> "GitSSRFConfig":
        base = cls()
        extra = os.getenv("ARGUS_ALLOWED_GIT_HOSTS", "")
        if extra.strip():
            extra_hosts = tuple(
                sorted(h.strip() for h in extra.split(",") if h.strip())
            )
            return cls(
                host_allowlist=tuple(
                    sorted(set(base.host_allowlist) | set(extra_hosts))
                )
            )
        return base


# ──────────────────────────────────────────────
# Circuit breaker
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 3
    cooldown_seconds: int = 300


# ──────────────────────────────────────────────
# SSL/TLS
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class TLSConfig:
    minimum_version: str = "TLSv1.2"


# ──────────────────────────────────────────────
# LLM — General
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class LLMGeneralConfig:
    max_retries: int = 2
    max_cost_per_engagement: float = 0.50  # $0.50 max LLM spend per engagement


# ──────────────────────────────────────────────
# LLM — Response Analysis
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class LLMReviewConfig:
    enabled: bool = True
    confidence_threshold: float = 0.7  # only review findings below this
    min_confidence: float = 0.3  # skip findings below this (too noisy)
    max_response_chars: int = 3000  # truncate response body
    max_per_engagement: int = 20  # cap total analyses per engagement
    timeout: int = 60  # per-finding LLM analysis timeout in seconds
    model: str = "gpt-4o-mini"


# ──────────────────────────────────────────────
# LLM — Payload Generation
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class LLMPayloadConfig:
    enabled: bool = True
    cache_ttl: int = 3600  # 1 hour cache TTL
    max_generated_payloads: int = 2  # max LLM payloads per probe context
    model: str = "gpt-4o-mini"


# ──────────────────────────────────────────────
# LLM — Agent (ReAct Loop)
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class LLMAgentConfig:
    enabled: bool = True
    model: str = "gpt-4o-mini"
    max_iterations: int = 10
    temperature: float = 0.1
    max_tokens_plan: int = 300  # tokens per tool selection call
    max_tokens_synth: int = 2000  # tokens for findings synthesis
    max_tokens_report: int = 3000  # tokens for final report
    context_max_tokens: int = 3500  # max context passed to LLM
    zero_finding_stop: int = 4  # stop after N zero-finding iterations

    @classmethod
    def from_env(cls) -> "LLMAgentConfig":
        return cls(
            model=os.getenv("LLM_AGENT_MODEL", "gpt-4o-mini"),
            max_iterations=int(os.getenv("LLM_AGENT_MAX_ITERATIONS", "10")),
            temperature=float(os.getenv("LLM_AGENT_TEMPERATURE", "0.1")),
            zero_finding_stop=int(os.getenv("LLM_AGENT_ZERO_FINDING_STOP", "4")),
        )


# ──────────────────────────────────────────────
# LLM — Cost Guard
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class LLMCostConfig:
    max_cost_usd: float = 0.25
    cost_per_1k_input: float = 0.000150  # gpt-4o-mini input cost
    cost_per_1k_output: float = 0.000600  # gpt-4o-mini output cost

    @classmethod
    def from_env(cls) -> "LLMCostConfig":
        return cls(
            max_cost_usd=float(os.getenv("LLM_AGENT_MAX_COST_USD", "0.25")),
            cost_per_1k_input=float(
                os.getenv("LLM_AGENT_COST_PER_1K_INPUT", "0.000150")
            ),
            cost_per_1k_output=float(
                os.getenv("LLM_AGENT_COST_PER_1K_OUTPUT", "0.000600")
            ),
        )


# ──────────────────────────────────────────────
# Top-level config singleton — all groups merged
# ──────────────────────────────────────────────
@dataclass(frozen=True)
class ArgusConfig:
    timeouts: TimeoutConfig = field(default_factory=TimeoutConfig)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig.from_env)
    content: ContentLimits = field(default_factory=ContentLimits)
    retries: RetryConfig = field(default_factory=RetryConfig)
    scan: ScanConfig = field(default_factory=ScanConfig)
    git_ssrf: GitSSRFConfig = field(default_factory=GitSSRFConfig.from_env)
    circuit_breaker: CircuitBreakerConfig = field(default_factory=CircuitBreakerConfig)
    tls: TLSConfig = field(default_factory=TLSConfig)
    llm: LLMGeneralConfig = field(default_factory=LLMGeneralConfig)
    llm_review: LLMReviewConfig = field(default_factory=LLMReviewConfig)
    llm_payload: LLMPayloadConfig = field(default_factory=LLMPayloadConfig)
    llm_agent: LLMAgentConfig = field(default_factory=LLMAgentConfig.from_env)
    llm_cost: LLMCostConfig = field(default_factory=LLMCostConfig.from_env)


# Instantiate the single source of truth
CONFIG = ArgusConfig()

# ── Legacy flat-constant aliases (for backward compat during migration) ──
HARD_TIMEOUT_SECONDS = CONFIG.timeouts.hard_timeout_seconds
TOOL_TIMEOUT_DEFAULT = CONFIG.timeouts.tool_timeout_default
TOOL_TIMEOUT_SHORT = CONFIG.timeouts.tool_timeout_short
TOOL_TIMEOUT_LONG = CONFIG.timeouts.tool_timeout_long
RATE_LIMIT_DELAY_MS = CONFIG.rate_limit.delay_ms
MAX_CONCURRENT_REQUESTS = CONFIG.rate_limit.max_concurrent_requests
MAX_CONTENT_LENGTH = CONFIG.content.max_content_length
MAX_FINDINGS_PER_BATCH = CONFIG.content.max_findings_per_batch
MAX_ENDPOINTS_PER_SCAN = CONFIG.content.max_endpoints_per_scan
MAX_TOOL_RETRIES = CONFIG.retries.max_tool_retries
RETRY_BACKOFF_BASE = CONFIG.retries.retry_backoff_base
DEFAULT_AGGRESSIVENESS = CONFIG.scan.default_aggressiveness
MAX_PAGES_TO_CRAWL = CONFIG.scan.max_pages_to_crawl
MAX_PARAMETERS_TO_FUZZ = CONFIG.scan.max_parameters_to_fuzz
WEB_SCANNER_CHECK_TIMEOUT = CONFIG.timeouts.web_scanner_check_timeout
SCOPE_VALIDATION_TIMEOUT = CONFIG.timeouts.scope_validation_timeout
ALLOWED_GIT_SCHEMES = CONFIG.git_ssrf.allowed_git_schemes
GIT_HOST_ALLOWLIST = CONFIG.git_ssrf.host_allowlist
MAX_TOOL_OUTPUT_BYTES = CONFIG.content.max_tool_output_bytes
CIRCUIT_BREAKER_THRESHOLD = CONFIG.circuit_breaker.failure_threshold
CIRCUIT_BREAKER_COOLDOWN = CONFIG.circuit_breaker.cooldown_seconds
SSL_TIMEOUT = CONFIG.timeouts.ssl_timeout
TLS_MINIMUM_VERSION = CONFIG.tls.minimum_version
LLM_MAX_RETRIES = CONFIG.llm.max_retries
LLM_REVIEW_ENABLED = CONFIG.llm_review.enabled
LLM_REVIEW_CONFIDENCE_THRESHOLD = CONFIG.llm_review.confidence_threshold
LLM_REVIEW_MIN_CONFIDENCE = CONFIG.llm_review.min_confidence
LLM_REVIEW_MAX_RESPONSE_CHARS = CONFIG.llm_review.max_response_chars
LLM_REVIEW_MAX_PER_ENGAGEMENT = CONFIG.llm_review.max_per_engagement
LLM_REVIEW_TIMEOUT = CONFIG.timeouts.llm_review_timeout
LLM_RESPONSE_ANALYSIS_MODEL = CONFIG.llm_review.model
LLM_PAYLOAD_GENERATION_ENABLED = CONFIG.llm_payload.enabled
LLM_PAYLOAD_CACHE_TTL = CONFIG.llm_payload.cache_ttl
LLM_MAX_GENERATED_PAYLOADS = CONFIG.llm_payload.max_generated_payloads
LLM_PAYLOAD_GENERATION_MODEL = CONFIG.llm_payload.model
LLM_MAX_COST_PER_ENGAGEMENT = CONFIG.llm.max_cost_per_engagement
LLM_AGENT_ENABLED = CONFIG.llm_agent.enabled
LLM_AGENT_MODEL = CONFIG.llm_agent.model
LLM_AGENT_MAX_ITERATIONS = CONFIG.llm_agent.max_iterations
LLM_AGENT_TEMPERATURE = CONFIG.llm_agent.temperature
LLM_AGENT_MAX_TOKENS_PLAN = CONFIG.llm_agent.max_tokens_plan
LLM_AGENT_MAX_TOKENS_SYNTH = CONFIG.llm_agent.max_tokens_synth
LLM_AGENT_MAX_TOKENS_REPORT = CONFIG.llm_agent.max_tokens_report
LLM_AGENT_CONTEXT_MAX_TOKENS = CONFIG.llm_agent.context_max_tokens
LLM_AGENT_MAX_COST_USD = CONFIG.llm_cost.max_cost_usd
LLM_AGENT_COST_PER_1K_INPUT = CONFIG.llm_cost.cost_per_1k_input
LLM_AGENT_COST_PER_1K_OUTPUT = CONFIG.llm_cost.cost_per_1k_output
LLM_AGENT_TIMEOUT_SECONDS = CONFIG.timeouts.llm_agent_timeout_seconds
LLM_AGENT_MAX_RETRIES = CONFIG.retries.llm_agent_max_retries
LLM_AGENT_ZERO_FINDING_STOP = CONFIG.llm_agent.zero_finding_stop
