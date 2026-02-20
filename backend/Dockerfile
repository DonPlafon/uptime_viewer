FROM python:3.11-slim

WORKDIR /app

# Install dependencies required for mariadb/mysql client compilation if needed
RUN apt-get update && apt-get install -y \
    gcc \
    default-libmysqlclient-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Run unbuffered so logs work
ENV PYTHONUNBUFFERED=1

CMD ["python", "app.py"]
