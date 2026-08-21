# ==============================================================================
# Stage 1: Build & Dependency Preparation
# ==============================================================================
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ==============================================================================
# Stage 2: Minimal Secure Production Runtime
# ==============================================================================
FROM python:3.12-slim AS runtime

# System runtime dependencies: Tesseract OCR (FR, DE, EN), curl, CA certificates
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-deu \
    tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# Copy pre-built Python packages from builder stage
COPY --from=builder /install /usr/local

WORKDIR /app

# Create non-root dedicated application user
RUN groupadd -g 10001 appgroup && \
    useradd -u 10001 -g appgroup -s /bin/bash -m appuser

# Copy application source code
COPY . .

# Ensure data directories exist and permissions are granted to non-root user
RUN mkdir -p data/document-storage data/resa-artifacts data/nace-imports && \
    chmod +x start.sh scripts/*.py && \
    chown -R appuser:appgroup /app

# Runtime configuration
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV NACELUX_ENV=production
ENV DOCUMENT_STORAGE_PROVIDER=supabase
ENV PDF_OCR_ENABLED=true
ENV PDF_OCR_LANGUAGES=fra+deu+eng

USER appuser

EXPOSE 8000

# Container health readiness check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/health || exit 1

CMD ["./start.sh"]
