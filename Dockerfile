FROM mirror.gcr.io/library/python:3.13-slim-bookworm@sha256:a1165e272e578941b84abc79e4ab38a0305cd12803a5c4247979ac7655f4d641
ENV PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/zar-browsers
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && python -m playwright install --with-deps chromium && useradd --create-home zarbrowser
COPY . .
CMD ["sh", "-c", "exec gunicorn --bind 0.0.0.0:${PORT:-8080} --workers 1 --threads 4 --timeout 300 app.main:app"]
