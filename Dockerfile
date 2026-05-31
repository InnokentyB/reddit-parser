FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p "${PLAYWRIGHT_BROWSERS_PATH}" \
    && python -m playwright install --with-deps chromium \
    && chmod -R 755 "${PLAYWRIGHT_BROWSERS_PATH}"

COPY . .
RUN chmod +x /app/bin/start \
    && useradd --create-home --shell /bin/sh appuser \
    && chown -R appuser:appuser /app

USER appuser

CMD ["./bin/start", "api"]
