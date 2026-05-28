# ---- Stage 1: Build dependencies ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build-time system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY agents/security_reviewer/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout=120 --retries=5 --prefix=/install -r requirements.txt

# ---- Stage 2: Production image ----
FROM python:3.11-slim AS production

LABEL maintainer="OpenCrew Team" \
      agent="security-reviewer" \
      version="1.0.0"

# Install only runtime system libraries + curl for health check
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/false --create-home appuser

WORKDIR /app

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy shared library
COPY shared/ /app/shared/

# Copy agent source code
COPY agents/security_reviewer/main.py /app/main.py
COPY agents/security_reviewer/prompts.py /app/prompts.py
COPY agents/security_reviewer/tools.py /app/tools.py
COPY agents/security_reviewer/agent.json /app/agent.json
COPY agents/security_reviewer/__init__.py /app/__init__.py

# Ensure the shared package is importable
ENV PYTHONPATH="/app" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Set ownership to non-root user
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8007

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8007/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8007"]