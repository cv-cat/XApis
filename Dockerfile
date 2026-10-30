FROM node:22-bookworm-slim AS node
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./frontend/
COPY frontend/vendor ./frontend/vendor
RUN npm ci --prefix frontend --ignore-scripts
COPY frontend ./frontend
RUN npm run build --prefix frontend
FROM python:3.12-slim-bookworm
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 CONSOLE_DATA_DIR=/app/data
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock \
    && groupadd --gid 10001 xapis \
    && useradd --uid 10001 --gid xapis --no-create-home xapis \
    && mkdir -p /app/data /shared /secrets/mysql /secrets/root && chown -R 10001:10001 /app/data /shared /secrets
COPY --chown=10001:10001 . .
COPY --from=node --chown=10001:10001 /build/console/static/vendor ./console/static/vendor
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"
CMD ["uvicorn", "console.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log", "--no-proxy-headers"]
