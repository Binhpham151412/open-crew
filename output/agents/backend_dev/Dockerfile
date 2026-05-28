FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY shared/requirements.txt /build/shared/requirements.txt
COPY agents/backend_dev/requirements.txt /build/agent/requirements.txt

# Install Python dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r /build/shared/requirements.txt && \
    pip install --no-cache-dir -r /build/agent/requirements.txt


FROM python:3.11-slim AS runtime

LABEL maintainer="OpenCrew Team"
LABEL agent="backend-dev"
LABEL version="1.0.0"

WORKDIR /app

# Install runtime dependencies only (curl for health check, libpq for psycopg2)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual environment from builder stage
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

# Copy shared library
COPY shared/ /app/shared/

# Copy agent code
COPY agents/backend_dev/ /app/agents/backend_dev/

# Set ownership and switch to non-root user
RUN chown -R appuser:appuser /app
USER appuser

EXPOSE 8005

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8005/health || exit 1

CMD ["uvicorn", "agents.backend_dev.main:app", "--host", "0.0.0.0", "--port", "8005"]