FROM python:3.12-slim

# Install runtime libraries needed by telegram-bot-api
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 zlib1g libreadline8 curl \
    && rm -rf /var/lib/apt/lists/*

# Copy the prebuilt telegram-bot-api binary from the public image
COPY --from=ragnarok22/telegram-bot-api-docker:latest /telegram-bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create directories for uploads and bot API data
RUN mkdir -p /app/uploads /data/telegram-bot-api

# Start script
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 10000

CMD ["/start.sh"]