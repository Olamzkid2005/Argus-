# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm@sha256:3b5425af5eb30e2753a40a3c2cf1e22a7b4a20335a80b0e24b05bfca01b290ef AS base
ARG AIRGAP=0

WORKDIR /app

# Install system dependencies for security tools
# In air-gap mode (AIRGAP=1), system packages must be pre-installed or cached.
RUN if [ "$AIRGAP" = "0" ]; then \
      apt-get update && apt-get install -y --no-install-recommends \
        nmap \
        nikto \
        git \
        curl \
        ca-certificates \
      && rm -rf /var/lib/apt/lists/*; \
    fi

# Install Go (version-pinned with embedded checksum verification)
# The SHA256 hash below is the official checksum from go.dev for this version.
# When upgrading Go version, update the hash by running:
#   curl -fsSL "https://go.dev/dl/go${GO_VERSION}.linux-amd64.tar.gz.sha256"
# In air-gap mode, Go must be pre-installed or provided via vendor/.
# Multi-stage build alternative (recommended for production):
#   FROM golang:${GO_VERSION}-bookworm AS go-builder
#   ... build tools in golang image, then COPY --from=go-builder ...
RUN set -eux; \
    GO_VERSION="1.22.10"; \
    GO_TARBALL="go${GO_VERSION}.linux-amd64.tar.gz"; \
    GO_CHECKSUM="a2fcc609e3dc4916ea6c3c1acc7977d3daa605bcab3438042ada4ef41e5d1ff5"; \
    if [ "$AIRGAP" = "0" ]; then \
      curl -fsSL "https://go.dev/dl/${GO_TARBALL}" -o /tmp/go.tar.gz; \
      echo "${GO_CHECKSUM}  /tmp/go.tar.gz" | sha256sum -c; \
      tar -C /usr/local -xzf /tmp/go.tar.gz; \
      rm /tmp/go.tar.gz; \
      go version; \
    fi
ENV PATH=$PATH:/usr/local/go/bin:/root/go/bin

# Install Go tools with pinned versions for supply-chain safety
# In air-gap mode, Go tools must be pre-installed and available via vendor/ or PATH.
RUN if [ "$AIRGAP" = "0" ]; then \
      go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@v3.2.0 && \
      go install github.com/projectdiscovery/httpx/cmd/httpx@v1.6.0 && \
      go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@v2.6.6 && \
      go install github.com/projectdiscovery/katana/cmd/katana@v1.1.0 && \
      go install github.com/projectdiscovery/naabu/v2/cmd/naabu@v2.1.0 && \
      go install github.com/projectdiscovery/alterx/cmd/alterx@v0.0.1 && \
      go install github.com/tomnomnom/waybackurls@v0.1.0 && \
      go install github.com/lc/gau/v2/cmd/gau@v2.2.0 && \
      go install github.com/ffuf/ffuf/v2@v2.1.0 && \
      go install github.com/hahwul/dalfox/v2@v2.10.0; \
    fi

# Install Python dependencies
# In air-gap mode, Python packages must be pre-installed or provided via vendor/.
COPY requirements.txt .
RUN if [ "$AIRGAP" = "0" ]; then \
      pip install --no-cache-dir -r requirements.txt; \
    fi

# Install sqlmap (pinned version)
# NOTE: sqlmap is disabled by default in argus.config.yaml (tools.disabled: [sqlmap])
# to avoid running invasive SQL injection scans without explicit opt-in.
# Users can enable it by removing "sqlmap" from the disabled list in their config.
# We still install it in the Docker image so it's available when enabled.
# In air-gap mode, sqlmap must be pre-installed or provided via vendor/.
RUN if [ "$AIRGAP" = "0" ]; then \
      pip install --no-cache-dir sqlmap==1.8; \
    fi

# Copy the application code. For air-gap builds, pre-populate ./vendor/
# in the build context before running the build. The vendor/ directory
# will be included automatically by COPY . . if it exists.
#   cp -r /path/to/pre-fetched/binaries ./vendor/
#   docker build --build-arg AIRGAP=1 -t argus-airgap .
COPY . .

# Create a non-root user and switch to it for security
RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 --ingroup appgroup appuser && \
    chown -R appuser:appgroup /app

USER appuser

# Health check to verify the worker process is alive
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD celery -A celery_app status --timeout=5 || exit 1

CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info", "--concurrency=4"]
