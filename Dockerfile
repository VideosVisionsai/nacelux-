FROM python:3.12-slim

WORKDIR /app

# Install system dependencies for Tesseract OCR (FR, DE, EN), curl (healthcheck), and CA certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Ensure data directories exist and scripts are executable
RUN mkdir -p data/document-storage data/resa-artifacts data/nace-imports \
    && chmod +x start.sh scripts/*.py

# Runtime environment configuration
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV NACELUX_ENV=production
ENV DOCUMENT_STORAGE_PROVIDER=local
ENV PDF_OCR_ENABLED=true
ENV PDF_OCR_LANGUAGES=fra+deu+eng

EXPOSE 8000

# Container healthcheck using standard health API endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/v1/health || exit 1

CMD ["./start.sh"]
