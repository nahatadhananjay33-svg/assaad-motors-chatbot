# Vasant Oasis inbound chatbot backend — production image.
# Deterministic Python backend (no LLM). Serves the chat API on :8000;
# put nginx in front for TLS (see deployment/nginx.conf).
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8

WORKDIR /app

# 1) dependencies first (better layer caching)
COPY app/inventory_system/requirements.txt ./inventory_system/requirements.txt
RUN pip install --no-cache-dir -r app/inventory_system/requirements.txt

# 2) application code + inventory workbook
COPY app/inventory_system/ ./inventory_system/
COPY app/IVR_Sheet.xlsx ./IVR_Sheet.xlsx

# 3) non-root user + writable data dir (mounted as a volume in prod)
RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && chown -R app:app /app /data
USER app

# runtime config (override via env / .env)
ENV CHAT_DATA_DIR=/data \
    CHAT_XLSX=/app/IVR_Sheet.xlsx \
    CHAT_HOST=0.0.0.0 \
    CHAT_API_PORT=8000

WORKDIR /app/inventory_system
EXPOSE 8000

# container is healthy only when /health returns 200
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status==200 else 1)"

CMD ["python", "-X", "utf8", "chat_api.py"]
