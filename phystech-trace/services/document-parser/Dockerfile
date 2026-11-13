FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BIND_HOST=0.0.0.0 \
    PORT=18765 \
    DOCLING_OCR_CACHE=/models

WORKDIR /app
COPY backend/requirements.txt /tmp/backend-requirements.txt
COPY phystech-trace/services/document-parser/constraints-cpu.txt /tmp/constraints-cpu.txt
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu \
       --constraint /tmp/constraints-cpu.txt -r /tmp/backend-requirements.txt
COPY backend /app/backend
COPY phystech-trace/services/document-parser /app/phystech-trace/services/document-parser
RUN mkdir -p /app/backend/uploads /models

WORKDIR /app/backend
EXPOSE 18765
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=5 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18765/health', timeout=3)"
CMD ["python", "server.py"]
