FROM python:3.11-slim AS builder

WORKDIR /build

COPY agents/techlead/requirements.txt .

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r agent \
    && useradd -r -g agent -m -d /app -s /sbin/nologin agent

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV PYTHONPATH="/app"

COPY shared/ /app/shared/
COPY agents/techlead/ /app/agents/techlead/

RUN chown -R agent:agent /app

USER agent

EXPOSE 8010

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8010/health || exit 1

CMD ["uvicorn", "agents.techlead.main:app", "--host", "0.0.0.0", "--port", "8010"]