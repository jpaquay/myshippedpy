# BAROGROOVE container image — Cloud Run, europe-west1.
#
# Single-stage slim runtime with uv for instant dependency resolution and 100%
# Docker layer caching via --cache-from on Cloud Build.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    BG_ENVIRONMENT=prod \
    BG_GCP_REGION=europe-west1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

# Copy uv binary for ultra-fast wheel installation
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install runtime dependencies (cached layer unless requirements.txt changes)
COPY requirements.txt .
RUN uv pip install --system --no-cache -r requirements.txt

# Application code. Ordered after dependency install so editing source
# never invalidates the cached dependency layer.
COPY app.py ./
COPY backend ./backend
COPY fixtures ./fixtures
COPY CNAME ./

# Cloud Run runs as an non-root user
RUN useradd --create-home --uid 1001 barogroove \
    && chown -R barogroove:barogroove /app
USER barogroove

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz').read()" || exit 1

CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log
