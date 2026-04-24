"""Named constants for the Argus worker system."""

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
MAX_ENDOINTS_PER_SCAN = 1000         # Max endpoints to process

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
