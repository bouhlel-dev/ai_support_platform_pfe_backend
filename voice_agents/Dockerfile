# ── Voice Agents — LiveKit agent process ──────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System deps (ffmpeg for audio processing, libpq for asyncpg)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python deps — voice agents requirements ONLY
COPY voice_agents/requirements.txt ./voice_agents/requirements.txt
RUN pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir -r voice_agents/requirements.txt && \
    pip install --no-cache-dir fastapi uvicorn pydantic

# Copy the full project (voice_agents imports app.db.models for persistence)
COPY . .

# Create recordings and uploads directories
RUN mkdir -p /app/recordings /app/uploads

# Expose control API port
EXPOSE 9001

# ── Runtime ─────────────────────────────────────
# Uses the project's control_api.py to expose /start and /stop
# which the main backend proxy calls via HTTP.
CMD ["python", "voice_agents/control_api.py"]
