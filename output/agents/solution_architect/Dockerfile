# Stage 1: Builder — install dependencies
FROM python:3.11-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python packages
COPY agents/solution_architect/requirements.txt .
RUN pip install --no-cache-dir --timeout=120 --retries=5 --upgrade pip && \
    pip install --no-cache-dir --timeout=120 --retries=5 --prefix=/install -r requirements.txt

# Stage 2: Runtime — lean image
FROM python:3.11-slim

# Install curl for health check
RUN apt-get update && apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Set up non-root user
RUN groupadd --gid 1001 agentuser && \
    useradd --uid 1001 --gid agentuser --shell /bin/bash --create-home agentuser

WORKDIR /app

# Copy shared code
COPY shared/ /app/shared/

# Copy agent code
COPY agents/solution_architect/main.py /app/main.py
COPY agents/solution_architect/prompts.py /app/prompts.py
COPY agents/solution_architect/tools.py /app/tools.py
COPY agents/solution_architect/agent.json /app/agent.json
COPY agents/solution_architect/__init__.py /app/__init__.py

# Set proper ownership
RUN chown -R agentuser:agentuser /app

# Switch to non-root user
USER agentuser

# Set environment variables
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Expose the solution architect port
EXPOSE 8003

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8003/health || exit 1

# Run the FastAPI application with uvicorn
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]