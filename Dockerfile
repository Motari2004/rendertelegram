FROM python:3.12-slim

# Install runtime libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 zlib1g libreadline8 curl \
    && rm -rf /var/lib/apt/lists/*

# ✅ FIXED: Download the official prebuilt binary (glibc-compatible)
# The Alpine-based images won't work — their binaries need musl libc
RUN curl -L https://github.com/tdlib/telegram-bot-api/releases/download/v7.10.0/telegram-bot-api-linux-amd64 \
    -o /usr/local/bin/telegram-bot-api \
    && chmod +x /usr/local/bin/telegram-bot-api

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads /data/telegram-bot-api

COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 10000

CMD ["/start.sh"]