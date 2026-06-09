FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e ".[dev]"

# Copy source
COPY src/ ./src/
COPY web/ ./web/
COPY fixtures/ ./fixtures/

# Non-root user
RUN useradd -m r8n && chown -R r8n /app
USER r8n

ENV PORT=8000
EXPOSE 8000

CMD ["sh", "-c", "uvicorn web.main:app --host 0.0.0.0 --port $PORT --workers 1 --log-level info"]
