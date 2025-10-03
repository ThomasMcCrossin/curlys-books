FROM python:3.11-slim

# Install system dependencies including Tesseract OCR
RUN apt-get update && apt-get install -y \
    postgresql-client \
    curl \
    build-essential \
    tesseract-ocr \
    tesseract-ocr-eng \
    libtesseract-dev \
    libleptonica-dev \
    libpng-dev \
    libjpeg-dev \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Install OpenCV dependencies
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependency files
COPY pyproject.toml poetry.lock* ./

# Install Poetry
RUN pip install --no-cache-dir poetry==1.7.1

# Configure Poetry
RUN poetry config virtualenvs.create false

# Install dependencies
RUN poetry install --no-interaction --no-ansi --no-root

# Copy application code
COPY services/worker ./services/worker
COPY packages ./packages
COPY infra/db ./infra/db

# Install the app package
RUN poetry install --no-interaction --no-ansi

# Create non-root user
RUN useradd -m -u 1000 curlys && chown -R curlys:curlys /app

# Create cache directory for OCR
RUN mkdir -p /tmp/ocr_cache && chown curlys:curlys /tmp/ocr_cache

USER curlys

# Verify Tesseract installation
RUN tesseract --version

# Run Celery worker
CMD ["celery", "-A", "services.worker.celery_app", "worker", \
     "--loglevel=info", \
     "--concurrency=2", \
     "--max-tasks-per-child=50", \
     "--task-events", \
     "--without-gossip", \
     "--without-mingle"]