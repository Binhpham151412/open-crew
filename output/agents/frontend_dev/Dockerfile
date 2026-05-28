# ---- Build stage ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY shared/requirements.txt /build/shared/requirements.txt
COPY agents/frontend_dev/requirements.txt /build/agent/requirements.txt

# Install Python dependencies into a virtual environment
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --no-cache-dir --timeout=120 --retries=5 --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --timeout=120 --retries=5 -r /build/shared/requirements.txt && \
    pip install --no-cache-dir --timeout=120 --retries=5 -r /build/agent/requirements.txt


# ---- Runtime stage ----
FROM python:3.11-slim AS runtime

LABEL maintainer="OpenCrew" \
      agent="frontend-dev" \
      port="8004"

# Install curl for healthcheck (removed in slim image)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --shell /bin/false --create-home appuser

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy shared library
COPY shared/ /app/shared/

# Copy agent code directly to /app/
COPY agents/frontend_dev/main.py /app/main.py
COPY agents/frontend_dev/prompts.py /app/prompts.py
COPY agents/frontend_dev/tools.py /app/tools.py
COPY agents/frontend_dev/agent.json /app/agent.json
COPY agents/frontend_dev/__init__.py /app/__init__.py

# Ensure shared is importable as a package
RUN touch /app/shared/__init__.py 2>/dev/null || true

# Ownership
RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8004/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]