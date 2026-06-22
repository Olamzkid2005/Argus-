# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm@sha256:3b5425af5eb30e2753a40a3c2cf1e22a7b4a20335a80b0e24b05bfca01b290ef AS base

WORKDIR /app

# Install system dependencies for security tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    nmap \
    nikto \
    git \
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Go (version-pinned with checksum verification from official source)
RUN set -eux; \
    GO_VERSION="1.22.10"; \
    GO_TARBALL="go${GO_VERSION}.linux-amd64.tar.gz"; \
    curl -fsSL "https://go.dev/dl/${GO_TARBALL}" -o /tmp/go.tar.gz; \
    curl -fsSL "https://go.dev/dl/${GO_TARBALL}.sha256" -o /tmp/go.tar.gz.sha256; \
    sha256sum -c /tmp/go.tar.gz.sha256; \
    tar -C /usr/local -xzf /tmp/go.tar.gz; \
    rm /tmp/go.tar.gz /tmp/go.tar.gz.sha256; \
    go version
ENV PATH=$PATH:/usr/local/go/bin:/root/go/bin

# Install Go tools with pinned versions for supply-chain safety
RUN go install github.com/projectdiscovery/nuclei/v3/cmd/nuclei@v3.2.0 && \
    go install github.com/projectdiscovery/httpx/cmd/httpx@v1.6.0 && \
    go install github.com/projectdiscovery/subfinder/v2/cmd/subfinder@v2.6.6 && \
    go install github.com/projectdiscovery/katana/cmd/katana@v1.1.0 && \
    go install github.com/projectdiscovery/naabu/v2/cmd/naabu@v2.1.0 && \
    go install github.com/projectdiscovery/alterx/cmd/alterx@v0.0.1 && \
    go install github.com/tomnomnom/waybackurls@v0.1.0 && \
    go install github.com/lc/gau/v2/cmd/gau@v2.2.0 && \
    go install github.com/ffuf/ffuf/v2@v2.1.0 && \
    go install github.com/hahwul/dalfox/v2@v2.10.0

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install sqlmap (pinned version)
# NOTE: sqlmap is disabled by default in argus.config.yaml (tools.disabled: [sqlmap])
# to avoid running invasive SQL injection scans without explicit opt-in.
# Users can enable it by removing "sqlmap" from the disabled list in their config.
# We still install it in the Docker image so it's available when enabled.
RUN pip install --no-cache-dir sqlmap==1.8

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
