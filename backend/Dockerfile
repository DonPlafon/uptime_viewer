FROM python:3.11-slim

WORKDIR /app

COPY backend/requirements.txt ./backend/
RUN python -m pip install --no-cache-dir --upgrade pip==26.2.1
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Run unbuffered so logs work
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app/backend
USER 10001:10001
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 CMD ["python", "healthcheck.py"]
CMD ["python", "app.py"]
