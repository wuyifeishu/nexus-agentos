# syntax=docker/dockerfile:1.6
# ── AgentOS Production Docker Image ────────────────────────────────────────────
# Multi-stage build optimized for size, security, and fast startup.
#
# Build:  docker build -t agentos:latest .
# Run:    docker run -p 8000:8000 -v ./data:/app/data agentos:latest

# ── Stage 1: Builder ──────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install dependencies to a venv
COPY pyproject.toml ./
RUN python -m venv /opt/venv && \
    . /opt/venv/bin/activate && \
    pip install --upgrade pip && \
    pip install .[server,all] || pip install -r requirements.txt 2>/dev/null; \
    pip install uvicorn[standard] gunicorn

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM python:3.11-slim-bookworm AS runtime

LABEL org.opencontainers.image.title="AgentOS"
LABEL org.opencontainers.image.description="Production-grade multi-agent framework"
LABEL org.opencontainers.image.version="1.18.0"
LABEL org.opencontainers.image.authors="AgentOS Team"

# Security: run as non-root
RUN groupadd -r agentos && useradd -r -g agentos -d /app -s /sbin/nologin agentos

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    AGENTOS_HOME="/app"

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl && \
    rm -rf /var/lib/apt/lists/*

# Copy venv from builder
COPY --from=builder --chown=agentos:agentos /opt/venv /opt/venv

WORKDIR /app
COPY --chown=agentos:agentos . .

RUN mkdir -p /app/data /app/logs /app/temp && \
    chown -R agentos:agentos /app

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -sf http://localhost:8000/health || exit 1

USER agentos
EXPOSE 8000

# Use gunicorn + uvicorn workers for production
CMD ["gunicorn", "agentos.api.server:app", \
     "--workers", "4", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--bind", "0.0.0.0:8000", \
     "--access-logfile", "/app/logs/access.log", \
     "--error-logfile", "/app/logs/error.log", \
     "--graceful-timeout", "30", \
     "--keep-alive", "5", \
     "--max-requests", "10000", \
     "--max-requests-jitter", "1000"]
