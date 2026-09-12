# BAROGROOVE container image — Cloud Run, europe-west1.
#
# The ancestor of this file was three lines long and its CMD invoked
# `.shipped/run.sh`, a script that was never committed to the repository. The
# image had therefore never built. This one does.
#
# Two stages: wheels get built once against build tooling we do not want in the
# runtime layer, then a slim runtime image installs them and drops root.

# ---------------------------------------------------------------------------
# Stage 1 — build wheels
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS builder

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# gcc//rust are needed by cryptography's build path on some platforms; they stay
# in this stage and never reach the runtime image.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip wheel --wheel-dir /wheels -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — runtime
# ---------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    BG_ENVIRONMENT=prod \
    BG_GCP_REGION=europe-west1 \
    PYTHONPATH=/app \
    PORT=8080

WORKDIR /app

COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-index --find-links=/wheels -r requirements.txt \
    && rm -rf /wheels

# Application code. Ordered after the dependency install so that editing source
# does not invalidate the (expensive) wheel layer.
COPY app.py ./
COPY backend ./backend
COPY fixtures ./fixtures
COPY CNAME ./

# Cloud Run runs as an arbitrary UID; be explicit rather than lucky.
RUN useradd --create-home --uid 1001 barogroove \
    && chown -R barogroove:barogroove /app
USER barogroove

EXPOSE 8080

# /healthz is dependency-free and does no I/O, so a failing upstream (Open-Meteo,
# Last.fm, Spotify) can never take the container down. Degradation is reported at
# /api/health instead, which is a richer, deliberately non-fatal endpoint.
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,os;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\",\"8080\")}/healthz').read()" || exit 1

# Single worker: Cloud Run scales by instance, not by process, and the app is
# async throughout. Two workers here would just double the memory floor.
CMD exec uvicorn app:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log
