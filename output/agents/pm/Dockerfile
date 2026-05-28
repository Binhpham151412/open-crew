# Stage 1: Builder
FROM python:3.11-slim AS builder

WORKDIR /build

COPY agents/pm/requirements.txt requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim

LABEL maintainer="OpenCrew Team"
LABEL agent="pm"
LABEL port="8001"

# Install curl for healthcheck
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --create-home appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy shared library
COPY shared/ /app/shared/

# Copy agent code
COPY agents/pm/ /app/agents/pm/

# Ensure non-root user owns the files
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

CMD ["uvicorn", "agents.pm.main:app", "--host", "0.0.0.0", "--port", "8001"]