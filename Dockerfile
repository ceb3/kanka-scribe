FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY vendor ./vendor

ENV KANKA_API_DOCS=/app/vendor/kanka-api-docs

RUN pip install --upgrade pip && pip install .

EXPOSE 8000
CMD ["uvicorn", "kanka_scribe.main:app", "--host", "0.0.0.0", "--port", "8000"]
