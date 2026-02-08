FROM python:3.12-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    POETRY_VERSION=1.7.1 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1

# Add Poetry to PATH
ENV PATH="$POETRY_HOME/bin:$PATH"

WORKDIR /app

# Install system dependencies (curl for poetry, ffmpeg for media worker)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        build-essential \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Copy dependency definitions
COPY pyproject.toml poetry.lock* ./

# Install dependencies
RUN poetry install --no-root --only main

# Copy application code
COPY . .

# Create non-root user
RUN addgroup --system --gid 1001 app \
    && adduser --system --uid 1001 --gid 1001 app \
    && chown -R app:app /app

USER app

# Command to run Celery worker
CMD ["poetry", "run", "celery", "-A", "celery_app", "worker", "--loglevel=info"]
