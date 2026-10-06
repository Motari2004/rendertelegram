FROM ragnarok22/telegram-bot-api-docker AS bot-api

FROM python:3.12-slim

# Copy the telegram-bot-api binary from the official image
COPY --from=bot-api-builder /telegram-bot-api/bin/telegram-bot-api /usr/local/bin/telegram-bot-api

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy your application
COPY . .

# Create directories for bot API data
RUN mkdir -p /data/telegram-bot-api

# Start script
COPY start.sh /start.sh
RUN chmod +x /start.sh

EXPOSE 10000

CMD ["/start.sh"]