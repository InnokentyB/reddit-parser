FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install --with-deps chromium

COPY . .
RUN chmod +x /app/bin/start && useradd --create-home --shell /bin/sh appuser && chown -R appuser:appuser /app

USER appuser

CMD ["./bin/start", "api"]
