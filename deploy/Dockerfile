# ── AgentOS Multi-stage Dockerfile ──
# Stage 1: Builder
FROM python:3.11-slim-bookworm AS builder
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip hatchling

COPY pyproject.toml README.md ./
COPY agentos/ ./agentos/
RUN pip wheel --no-cache-dir --wheel-dir /wheels .

# Stage 2: Runtime
FROM python:3.11-slim-bookworm AS runtime
LABEL org.opencontainers.image.title="nexus-agentos"
LABEL org.opencontainers.image.description="Agent Operating System — Production-ready multi-model agent framework"
LABEL org.opencontainers.image.version="1.10.0"

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --shell /bin/bash agentos

COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

USER agentos
WORKDIR /home/agentos

ENV PYTHONUNBUFFERED=1
ENV AGENTOS_ENV=production

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "from agentos import __version__; print(__version__)" || exit 1

ENTRYPOINT ["python", "-m", "agentos"]
CMD ["serve"]
