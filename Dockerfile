# Bot image
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py /app/app.py
COPY docker/entrypoint.sh /entrypoint.sh

# Data volume for state/cache
VOLUME ["/data"]

ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["/entrypoint.sh"]
