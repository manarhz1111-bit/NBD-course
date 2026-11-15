FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PROMETHEUS_DISABLE_CREATED_SERIES=True

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY bookcache ./bookcache
USER app

EXPOSE 8000
CMD ["uvicorn", "bookcache.main:app", "--host", "0.0.0.0", "--port", "8000", \
     "--no-access-log", "--loop", "uvloop", "--http", "httptools", "--limit-concurrency", "300"]
