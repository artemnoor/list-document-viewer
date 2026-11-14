FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VERIFICATION_DB_PATH=/data/verification.sqlite3

WORKDIR /service
COPY pyproject.toml README.md ./
COPY app ./app
COPY contracts ./contracts
RUN pip install --no-cache-dir .

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
