# MetaBot.OS — imagen del backend + panel (multi-stage)

# Etapa 1: compilar el panel React
FROM node:22-slim AS panel
WORKDIR /panel
COPY frontend/panel/package.json frontend/panel/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY frontend/panel/ ./
RUN npm run build

# Etapa 2: backend Python sirviendo API + panel + media
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/app ./app
COPY --from=panel /panel/dist ./panel-dist
ENV PANEL_DIST=/app/panel-dist
# La base y las imágenes viven en /data (volumen)
ENV DATABASE_URL=sqlite:////data/metabot.db
RUN mkdir -p /data /app/media
VOLUME ["/data", "/app/media"]
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
