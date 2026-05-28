FROM python:3.11-slim AS builder

WORKDIR /build

COPY agents/uiux_reviewer/requirements.txt ./requirements.txt
COPY shared/ ./shared/

RUN pip install --no-cache-dir --prefix=/install --no-warn-script-location -r requirements.txt

FROM python:3.11-slim

LABEL maintainer="OpenCrew Team"
LABEL agent="uiux-reviewer"
LABEL version="1.0.0"

RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid appuser --create-home --shell /bin/bash appuser

COPY --from=builder /install /usr/local

WORKDIR /app

COPY shared/ ./shared/
COPY agents/uiux_reviewer/ ./agents/uiux_reviewer/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

RUN chown -R appuser:appuser /app

USER appuser

EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8006/health || exit 1

CMD ["uvicorn", "agents.uiux_reviewer.main:app", "--host", "0.0.0.0", "--port", "8006"]