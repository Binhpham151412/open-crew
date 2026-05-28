FROM python:3.11-slim AS builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

COPY agents/qa/requirements.txt /build/requirements.txt
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim

# Install runtime dependencies (curl for healthcheck)
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd -r agentuser && useradd -r -g agentuser -d /home/agentuser -s /sbin/nologin agentuser

WORKDIR /app

# Copy shared libraries
COPY shared/ /app/shared/

# Copy agent code
COPY agents/qa/ /app/agents/qa/

# Set ownership
RUN chown -R agentuser:agentuser /app

# Switch to non-root user
USER agentuser

# Set Python path to include shared and agent directories
ENV PYTHONPATH=/app:/app/agents/qa

# Expose port 8008
EXPOSE 8008

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8008/health || exit 1

# Run the application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]