FROM python:3.11-slim
WORKDIR /app
COPY phystech-trace/gateway/requirements.txt ./requirements.txt
RUN python -m pip install --no-cache-dir -r requirements.txt
COPY phystech-trace/gateway/main.py ./main.py
COPY phystech-trace/contracts ./contracts
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8084
EXPOSE 8084
HEALTHCHECK --interval=15s --timeout=5s --start-period=15s --retries=5 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8084/health', timeout=3)"
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8084"]
