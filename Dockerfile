# ==============================================================================
# Smart Emergency Drone Delivery System - Production Dockerfile
# ==============================================================================
# Multi-stage / lightweight Debian-slim container running with non-root security.
# ==============================================================================

FROM python:3.11-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered standard I/O
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

# Install minimal OS runtime dependencies and curl for Docker health checks
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    default-libmysqlclient-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python package dependencies
COPY requirements.txt /app/
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir gunicorn

# Copy project source code into container
COPY . /app/

# Create a non-root system user and adjust file permissions
RUN useradd -u 1001 -m -s /bin/bash appuser && \
    mkdir -p /app/instance /app/logs && \
    chown -R appuser:appuser /app

# Ensure entrypoint script is executable
RUN chmod +x /app/docker-entrypoint.sh

USER appuser

# Expose internal WSGI port
EXPOSE 5000

# Docker healthcheck querying the /api/health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:5000/api/health || exit 1

# Launch container via production entrypoint
ENTRYPOINT ["/app/docker-entrypoint.sh"]
