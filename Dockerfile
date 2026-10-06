FROM ghcr.io/lukaszraczylo/tdlib-telegram-bot-api-docker/telegram-api-server:1.0.331 AS bot-api

FROM python:3.12-slim

# Install runtime libraries (no 'file' package needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 zlib1g libreadline8 curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ Copy the binary from the official Docker image
COPY --from=bot-api /usr/local/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /data/telegram-bot-api

COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 10000

CMD ["/start.sh"]