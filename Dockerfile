# ── Build stage ──────────────────────────────────
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r requirements.txt

# App code
COPY . .

# ── Runtime ─────────────────────────────────────
EXPOSE 9000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9000", "--workers", "4"]

# Install voice agent dependencies into the same image to avoid having a separate build stage and image for voice agents, which simplifies deployment and reduces overhead.
COPY voice_agents/requirements.txt /tmp/voice_agents_requirements.txt
RUN pip install -r /tmp/voice_agents_requirements.txt