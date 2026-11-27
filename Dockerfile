# Multi-stage build: Vue 3 SPA + Python 3.12 Flask/Socket.IO Hub
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OPEN_BROWSER=0 \
    HOST=0.0.0.0 \
    PORT=5001

RUN apt-get update && apt-get install -y --no-install-recommends \
    android-tools-adb \
    usbmuxd \
    ffmpeg \
    openssh-client \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

RUN mkdir -p /app/data /app/logs
EXPOSE 5001

CMD ["sh", "-c", "python scripts/init_db.py init && python app.py"]
