FROM python:3.13-slim-bookworm
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/zar-browsers
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium && useradd --create-home zarbrowser
COPY . .
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 300 app.main:app"]
