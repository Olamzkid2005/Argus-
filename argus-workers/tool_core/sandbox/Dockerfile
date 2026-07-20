# tool_core/sandbox/Dockerfile
# Minimal sandbox image for isolated exploit verification.
# Built from python:3.12-slim-bookworm for a small footprint.
FROM python:3.12-slim-bookworm

# Install only what's needed for exploit verification
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for sandbox execution
RUN useradd -m -u 1000 sandbox
USER sandbox
WORKDIR /workspace

# Copy the sandbox runner script
COPY --chown=sandbox:sandbox runner.py /usr/local/bin/sandbox_runner.py
ENTRYPOINT ["python3", "/usr/local/bin/sandbox_runner.py"]
