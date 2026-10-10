# Image de production : frontend compilé par Node, servi avec l'API par FastAPI.

# ---- 1. Frontend (React + Vite) ---------------------------------------------
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. Application Python --------------------------------------------------
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000 \
    NO_BROWSER=1
WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist

# Classements SJR et CORE : téléchargés à la construction si les sites l'acceptent,
# sinon importables depuis l'onglet Réglages.
RUN python -m quality.update_rankings || true

# Exécution sans privilèges root.
RUN useradd --create-home appuser && mkdir -p data && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/api/health')"
CMD ["python", "-m", "api"]
