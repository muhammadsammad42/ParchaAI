

FROM python:3.11-slim as base

# Install system dependencies required for OpenCV, audio processing, and NLTK
# - ffmpeg: Required by pydub for audio format conversion
# - libgomp1: Required by OpenCV for optimized computations
# - libglib2.0-0, libsm6, libxext6, libxrender-dev: OpenCV dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download NLTK data at build time (required by g2p_en for pronunciation)
# - averaged_perceptron_tagger_eng: POS tagger used by g2p_en
# - cmudict: CMU Pronouncing Dictionary for phoneme lookup
RUN python -c "import nltk; \
    nltk.download('averaged_perceptron_tagger_eng', quiet=True); \
    nltk.download('cmudict', quiet=True)"

# Copy application code
COPY parcha_ai_backend/ /app/parcha_ai_backend/
COPY drug_database/ /app/drug_database/

# Create necessary directories for runtime (data will be on mounted volume)
RUN mkdir -p /app/data /app/outputs/audio /app/cache /app/logs

# Expose port 8080 (Fly.io default)
EXPOSE 8080

# Health check endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8080/health', timeout=5)"

# Run FastAPI with uvicorn
CMD ["sh", "-c", "uvicorn parcha_ai_backend.api:app --host 0.0.0.0 --port $PORT --workers 2 --no-access-log"]
