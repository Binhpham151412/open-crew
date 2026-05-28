FROM python:3.11-slim AS builder

WORKDIR /build

COPY agents/uiux_reviewer/requirements.txt ./requirements.txt
COPY shared/ ./shared/

RUN pip install --no-cache-dir --timeout=120 --retries=5 --prefix=/install --no-warn-script-location -r requirements.txt

FROM python:3.11-slim

LABEL maintainer="OpenCrew Team"
LABEL agent="uiux-reviewer"
LABEL version="1.0.0"

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

COPY --from=builder /install /usr/local

WORKDIR /app

COPY shared/ ./shared/

# Copy agent code directly to /app/
COPY agents/uiux_reviewer/main.py /app/main.py
COPY agents/uiux_reviewer/prompts.py /app/prompts.py
COPY agents/uiux_reviewer/tools.py /app/tools.py
COPY agents/uiux_reviewer/agent.json /app/agent.json
COPY agents/uiux_reviewer/__init__.py /app/__init__.py

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8006/health || exit 1

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8006"]