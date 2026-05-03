"""Named constants for the Argus worker system."""

import os

# Timeouts (seconds)
HARD_TIMEOUT_SECONDS = 3600          # 1 hour max engagement time
TOOL_TIMEOUT_DEFAULT = 180           # 3 minutes default tool timeout
TOOL_TIMEOUT_SHORT = 60              # 1 minute for quick tools
TOOL_TIMEOUT_LONG = 300              # 5 minutes for heavy tools

# Rate limiting
RATE_LIMIT_DELAY_MS = 100            # 100ms between requests
MAX_CONCURRENT_REQUESTS = 5          # Max parallel requests

# Content limits
MAX_CONTENT_LENGTH = 1000            # Max chars to store in evidence
MAX_FINDINGS_PER_BATCH = 50          # Batch insert size
MAX_ENDPOINTS_PER_SCAN = 1000         # Max endpoints to process

# Retries
MAX_TOOL_RETRIES = 2                 # Number of retry attempts
RETRY_BACKOFF_BASE = 2               # Exponential backoff base

# Scanning
DEFAULT_AGGRESSIVENESS = "default"   # Default scan aggressiveness
MAX_PAGES_TO_CRAWL = 10              # Max pages for parameter discovery
MAX_PARAMETERS_TO_FUZZ = 20          # Max params to fuzz

# Circuit breaker
CIRCUIT_BREAKER_THRESHOLD = 3        # Failures before opening
CIRCUIT_BREAKER_COOLDOWN = 300       # 5 minutes cooldown

# SSL/TLS
SSL_TIMEOUT = 10                     # SSL verification timeout
TLS_MINIMUM_VERSION = "TLSv1.2"      # Minimum acceptable TLS version

# ── LLM General ──
LLM_MAX_RETRIES = 2

# ── LLM Response Analysis ──
LLM_REVIEW_ENABLED = True
LLM_REVIEW_CONFIDENCE_THRESHOLD = 0.7    # only review findings below this
LLM_REVIEW_MIN_CONFIDENCE = 0.3           # skip findings below this (too noisy)
LLM_REVIEW_MAX_RESPONSE_CHARS = 3000      # truncate response body
LLM_REVIEW_MAX_PER_ENGAGEMENT = 20        # cap total analyses per engagement
LLM_RESPONSE_ANALYSIS_MODEL = "gpt-4o-mini"

# ── LLM Payload Generation ──
LLM_PAYLOAD_GENERATION_ENABLED = True
LLM_PAYLOAD_CACHE_TTL = 3600              # 1 hour cache TTL
LLM_MAX_GENERATED_PAYLOADS = 2            # max LLM payloads per probe context
LLM_PAYLOAD_GENERATION_MODEL = "gpt-4o-mini"

# ── Budget ──
LLM_MAX_COST_PER_ENGAGEMENT = 0.50        # $0.50 max LLM spend per engagement

# ── LLM Agent (ReAct Loop) ──────────────────────────────────────────────
LLM_AGENT_ENABLED = True
LLM_AGENT_MODEL = os.getenv("LLM_AGENT_MODEL", "gpt-4o-mini")
LLM_AGENT_MAX_ITERATIONS = int(os.getenv("LLM_AGENT_MAX_ITERATIONS", "10"))
LLM_AGENT_TEMPERATURE = float(os.getenv("LLM_AGENT_TEMPERATURE", "0.1"))
LLM_AGENT_MAX_TOKENS_PLAN = 300            # tokens per tool selection call
LLM_AGENT_MAX_TOKENS_SYNTH = 2000          # tokens for findings synthesis
LLM_AGENT_MAX_TOKENS_REPORT = 3000         # tokens for final report
LLM_AGENT_CONTEXT_MAX_TOKENS = 3500        # max context passed to LLM

# ── LLM Agent Cost Guard ────────────────────────────────────────────────
LLM_AGENT_MAX_COST_USD = float(os.getenv("LLM_AGENT_MAX_COST_USD", "0.25"))
LLM_AGENT_COST_PER_1K_INPUT = 0.000150     # gpt-4o-mini input cost
LLM_AGENT_COST_PER_1K_OUTPUT = 0.000600    # gpt-4o-mini output cost

# ── Mitigations: Timeout & Retry ────────────────────────────────────────
LLM_AGENT_TIMEOUT_SECONDS = int(os.getenv("LLM_AGENT_TIMEOUT_SECONDS", "30"))
LLM_AGENT_MAX_RETRIES = int(os.getenv("LLM_AGENT_MAX_RETRIES", "2"))
LLM_AGENT_ZERO_FINDING_STOP = int(os.getenv("LLM_AGENT_ZERO_FINDING_STOP", "4"))
