FROM python:3.12-slim

WORKDIR /app

# System deps for optional Playwright / OCR (lightweight for core SaaS)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway / Render / Fly inject PORT
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV NACELUX_ENV=production

EXPOSE 8000

CMD ["python3", "backend/app.py"]
