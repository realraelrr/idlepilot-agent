FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash \
    chromium \
    novnc \
    supervisor \
    websockify \
    x11vnc \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY browser_refresh/requirements.txt /app/browser_refresh/requirements.txt
RUN pip install --no-cache-dir -r /app/browser_refresh/requirements.txt

COPY browser_refresh /app/browser_refresh

RUN mkdir -p /browser-profile /browser-state \
    && chmod +x /app/browser_refresh/start-chromium.sh

CMD ["supervisord", "-c", "/app/browser_refresh/supervisord.conf"]
