# ==============================================================================
# Production Dockerfile — Cybernauts Integrated Platform
# Combines Team A (Lead Intelligence & Discovery) and Team B (Voice AI & Telephony)
# Python 3.11-slim + FFmpeg + Playwright Chromium + Non-root Execution
# ==============================================================================

FROM python:3.11-slim

# Set environment variables for Python and Playwright
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PORT=8000 \
    HOST=0.0.0.0

# Install required system packages:
# - ffmpeg: Real-time audio stream decoding, resampling, and PyAV codec support
# - libasound2 & libportaudio2: Low-level audio device and driver compatibility
# - curl: Container health checks and HTTP diagnostics
# - build-essential & python3-dev: C-extension compilation support
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ffmpeg \
    libasound2 \
    libportaudio2 \
    build-essential \
    python3-dev \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create dedicated non-root application user and group (UID/GID 1000)
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -m -s /bin/bash appuser

# Set working directory
WORKDIR /app

# Upgrade pip and install Python dependencies in a cached layer
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium and required OS browser dependencies for Team A scraping
RUN python -m playwright install --with-deps chromium && \
    chmod -R 755 /ms-playwright

# Copy application source code
COPY server.py recording_manager.py /app/
COPY routers/ /app/routers/
COPY static/ /app/static/
COPY "Team A/" "/app/Team A/"
COPY "Team B/" "/app/Team B/"

# Create runtime directories for persistent SQLite databases, call recordings, and logs
RUN mkdir -p /app/static/recordings /app/logs /app/data && \
    touch /app/leads.db && \
    chown -R appuser:appuser /app /ms-playwright && \
    chmod -R 775 /app/static/recordings /app/logs /app/data && \
    chmod 664 /app/leads.db

# Switch to non-root user
USER appuser

# Expose FastAPI application port
EXPOSE 8000

# Container healthcheck using verified /health endpoint
HEALTHCHECK --interval=20s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Production startup command using uvicorn with graceful signal handling
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
