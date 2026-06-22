# Berry Bomb Daily Ops — container image
FROM python:3.12-slim

# System deps for Pillow / image hashing
RUN apt-get update && apt-get install -y --no-install-recommends \
    libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# Most hosts inject PORT; default to 8000 locally.
ENV PORT=8000
EXPOSE 8000

# Start the single FastAPI app (webhook + Mini App + scheduler all in one).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
