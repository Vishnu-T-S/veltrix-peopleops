FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

# Tesseract is the OCR engine for scanned pages. It is a system program, not a Python package.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml .python-version uv.lock* ./
RUN uv sync --no-dev --no-install-project

COPY app ./app
COPY vendor ./vendor

EXPOSE 8000
# Ingestion runs in the background at start-up; /health returns 503 until it has finished.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
