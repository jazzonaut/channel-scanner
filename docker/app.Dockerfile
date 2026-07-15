# syntax=docker/dockerfile:1
#
# rtl-sdr-channel-detector — application image (multi-stage).
#
# Stage 1 (frontend-build): builds the React/Vite frontend into /frontend/dist.
# Stage 2 (runtime):        python:3.12-slim with RTL-SDR userland tools, the
#                           FastAPI backend, and the built frontend copied to
#                           /app/static (served by the backend at "/").
#
# The image is RECEIVE-ONLY. It ships RTL-SDR *reception* userland only; no
# transmit tooling is installed.

# ---------------------------------------------------------------------------
# Stage 1: build the frontend
# ---------------------------------------------------------------------------
FROM node:20-slim AS frontend-build

WORKDIR /frontend

# Copy manifests first so `npm ci` layer is cached until deps change.
COPY frontend/package.json frontend/package-lock.json* ./
# Use npm ci when a lockfile exists (reproducible); fall back to npm install.
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

# Copy the rest of the frontend source and build.
COPY frontend/ ./
RUN npm run build
# Result: /frontend/dist (static assets).

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# ---- System dependencies --------------------------------------------------
# REQUIRED (core reception): rtl-sdr + librtlsdr-dev give us rtl_test, rtl_power,
#   rtl_sdr, rtl_fm and the shared library that pyrtlsdr binds to.
# REQUIRED (runtime helpers): curl (healthcheck), usbutils (lsusb), procps (ps),
#   ca-certificates.
# These MUST succeed — the build fails if the core reception stack is missing.
RUN apt-get update && apt-get install -y --no-install-recommends \
        rtl-sdr \
        librtlsdr-dev \
        libusb-1.0-0 \
        curl \
        usbutils \
        procps \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# OPTIONAL decoder / SDR tooling. These are genuinely optional: the app runs
# without them (they enable extra opaque-payload decoding and SoapySDR probing).
# We therefore tolerate their absence with `|| true` so an image still builds on
# base images / mirrors where a package name differs or is unavailable.
#
#   rtl-433                 : generic ISM-band decoder (apt package name: "rtl-433"
#                             on Debian bookworm; may be absent on some mirrors).
#   soapysdr-tools          : provides SoapySDRUtil (device probing). On some
#                             Debian releases this is "soapysdr-tools", on others
#                             "soapysdr0.8-module-rtlsdr" ships the module only.
#   soapysdr-module-rtlsdr  : SoapySDR RTL-SDR plugin (enables SDR_BACKEND=soapy).
RUN apt-get update && \
    ( apt-get install -y --no-install-recommends rtl-433 || true ) && \
    ( apt-get install -y --no-install-recommends soapysdr-tools || true ) && \
    ( apt-get install -y --no-install-recommends soapysdr-module-rtlsdr || true ) && \
    rm -rf /var/lib/apt/lists/*

# ---- Non-root user --------------------------------------------------------
# Create an unprivileged user. USB access is granted at runtime by the host
# (see docs/usb-passthrough.md); we do not need root to talk to the dongle when
# device permissions / cgroup rules are set up correctly.
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid 1000 --create-home --home-dir /home/appuser appuser \
    # plugdev is the conventional group for USB device access via udev rules.
    && groupadd --system plugdev 2>/dev/null || true \
    && usermod -aG plugdev appuser || true

WORKDIR /app

# ---- Python dependencies --------------------------------------------------
# Copy only requirements first for layer caching.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt \
    # pyrtlsdr is the Python binding for the system librtlsdr installed above.
    # It is an optional extra in pyproject, but this image ships USB passthrough
    # support, so we install it here so SDR_BACKEND=rtlsdr works out of the box.
    # (Without it the app logs "No module named 'rtlsdr'" and falls back to sim.)
    # setuptools provides pkg_resources, which pyrtlsdr 0.3.0 imports at import
    # time; python:3.12-slim does not ship it, so install it explicitly.
    && pip install --no-cache-dir "setuptools>=70" "pyrtlsdr==0.3.0"

# ---- Application code ------------------------------------------------------
COPY backend/ /app/

# Copy the built frontend into the static directory the backend serves.
COPY --from=frontend-build /frontend/dist /app/static

# Data directory (mounted as a volume in compose, but create it for standalone runs).
RUN mkdir -p /data/db /data/recordings /data/logs \
    && chown -R appuser:appuser /app /data

# ---- Environment defaults (mirrors .env.example / CONTRACT) ---------------
ENV WEB_PORT=8080 \
    SDR_BACKEND=sim \
    SIMULATION_MODE=true \
    DATABASE_PATH=/data/db/channel_detector.sqlite3 \
    RECORDING_PATH=/data/recordings \
    LOG_LEVEL=INFO \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER appuser

EXPOSE 8080

# Healthcheck hits the FastAPI health endpoint. Uses the same WEB_PORT the app
# binds to (default 8080).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f "http://localhost:${WEB_PORT:-8080}/api/health" || exit 1

# Start the ASGI server. Shell form so ${WEB_PORT} is expanded at runtime.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${WEB_PORT:-8080}"]
