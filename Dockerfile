FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/uploads

EXPOSE 10000

CMD ["gunicorn", "--workers", "2", "--timeout", "600", "--bind", "0.0.0.0:10000", "app:app"]