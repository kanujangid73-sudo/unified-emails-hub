FROM python:3.13-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY app ./app

# Without a DATABASE_URL, SQLite lives on a volume so data survives container restarts.
ENV DATABASE_URL=sqlite:////data/mailhub.db
RUN mkdir -p /data
VOLUME /data

# Hosts such as Render, Railway and Fly set PORT; 8000 otherwise.
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips '*'"]
