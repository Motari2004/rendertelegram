FROM python:3.12-slim

# Install runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 zlib1g libreadline8 curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ FIXED: Use a release that actually publishes prebuilt binaries
RUN curl -L https://github.com/lukaszraczylo/tdlib-telegram-bot-api-docker/releases/download/v1.0.310/telegram-bot-api-linux-amd64 \
    -o /usr/local/bin/telegram-bot-api \
    && chmod +x /usr/local/bin/telegram-bot-api

# ✅ Verify the binary is real (not a "Not Found" text file)
RUN file /usr/local/bin/telegram-bot-api && \
    /usr/local/bin/telegram-bot-api --version

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/uploads /data/telegram-bot-api
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 10000
CMD ["/start.sh"]