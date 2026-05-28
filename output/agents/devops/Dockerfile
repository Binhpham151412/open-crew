# ---- Stage 1: Build dependencies ----
FROM python:3.11-slim AS builder

WORKDIR /build

# Install build-time system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

COPY agents/devops/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --timeout=120 --retries=5 --prefix=/install -r requirements.txt

# ---- Stage 2: Production image ----
FROM python:3.11-slim

LABEL maintainer="OpenCrew Team" \
      agent="devops" \
      version="1.0.0" \
      port="8009"

# Install only runtime system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl libpq5 && \
    rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user
RUN groupadd --gid 1000 agent && \
    useradd --uid 1000 --gid agent --create-home --shell /bin/bash agent

WORKDIR /app

# Copy shared library
COPY shared/ ./shared/

# Copy agent source code
COPY agents/devops/main.py ./main.py
COPY agents/devops/tools.py ./tools.py
COPY agents/devops/prompts.py ./prompts.py

# Ensure shared/ is importable as a package
RUN touch ./shared/__init__.py

# Set ownership to non-root user
RUN chown -R agent:agent /app

USER agent

EXPOSE 8009

# Health check every 30s, 3 retries, timeout 5s, start after 10s
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8009/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]