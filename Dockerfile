FROM python:3.11-slim

LABEL org.opencontainers.image.title="TalentLens"
LABEL org.opencontainers.image.description="AI CV Screener — FastAPI backend"
LABEL org.opencontainers.image.authors="Rzq12"

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-ind \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml requirements.lock ./

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -e ".[dev]"

COPY serving/ serving/
COPY tests/ tests/

ENV PYTHONPATH=/app/serving
ENV PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "7860", "--app-dir", "serving"]
