# Full PathwayGPS app (FastAPI backend + built React frontend) in one container.
FROM node:20-slim AS web
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PATHWAYGPS_CACHE_TTL=604800
COPY backend/requirements.txt backend/requirements-ai.txt backend/
RUN pip install --no-cache-dir -r backend/requirements.txt -r backend/requirements-ai.txt
COPY backend/ backend/
COPY --from=web /app/frontend/dist frontend/dist
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port ${PORT:-8000}"]
