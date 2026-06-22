# Lightweight screener — production image.
FROM python:3.12-slim

# tzdata: the download logic uses America/New_York market hours.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install pinned deps first so the layer caches across code changes.
COPY requirements.lock pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.lock

COPY . .

ENV SCREENER_HOST=0.0.0.0 \
    SCREENER_PORT=8000 \
    SCREENER_DATA_DIR=/app/data \
    SCREENER_LOG_LEVEL=INFO

EXPOSE 8000

# Single worker is plenty for a personal dashboard; raise with --workers N.
# Data refresh runs separately (see DEPLOY.md) via `python run.py pipeline`.
CMD ["uvicorn", "server.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
