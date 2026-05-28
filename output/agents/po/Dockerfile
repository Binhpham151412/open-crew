# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY shared/requirements.txt ./shared-requirements.txt
COPY agents/po/requirements.txt ./agent-requirements.txt

# Merge and install all dependencies into a virtual env
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r shared-requirements.txt -r agent-requirements.txt

# ---- Runtime stage ----
FROM python:3.11-slim AS runtime

LABEL maintainer="OpenCrew Team"
LABEL agent="po"
LABEL description="Product Owner agent for OpenCrew"

# Install runtime dependencies (curl for health check, libpq for psycopg)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy virtual env from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/bash --create-home appuser

WORKDIR /app

# Copy shared library
COPY shared/ ./shared/

# Copy agent source code
COPY agents/po/ ./

# Ensure shared is importable as a package
RUN touch shared/__init__.py && \
    touch __init__.py 2>/dev/null || true

# Set ownership
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]