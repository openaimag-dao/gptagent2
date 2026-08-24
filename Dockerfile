FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8000

# Shell form (not exec-array) so $PORT actually expands -- Railway (and
# similar PaaS hosts) inject a dynamic PORT env var and route their proxy
# to it; a hardcoded port means the platform's health check/proxy can
# never reach the container, which is exactly Railway's "Application
# failed to respond" error. Defaults to 8000 when PORT isn't set (e.g.
# docker-compose, which doesn't set it).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
