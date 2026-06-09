FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by some Python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps first — separate layer so code changes don't bust the cache.
# We copy src/ alongside pyproject.toml because setuptools needs the package
# present at install time even for a non-editable install.
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Runtime files (change more often than deps)
COPY web/ ./web/
COPY fixtures/ ./fixtures/

# SQLite data directory — mount a named volume here in production
RUN mkdir -p /data

# Non-root user
RUN useradd -m r8n && chown -R r8n /app /data
USER r8n

# DB lives on the mounted volume, not inside the image layer
ENV DB_PATH=/data/r8n.sqlite
ENV PORT=8000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "web.main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--workers", "1", \
     "--log-level", "info"]
