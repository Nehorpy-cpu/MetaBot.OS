#!/bin/sh
# Arranque del backend: primero aplica migraciones, después sirve.
set -e

echo "[entrypoint] aplicando migraciones..."
alembic upgrade head

# Traspaso único desde la base SQLite legada (idempotente: si Postgres ya
# tiene datos, no hace nada).
if [ -f /data/metabot.db ]; then
  echo "[entrypoint] verificando datos legados de SQLite..."
  python scripts/sqlite_to_postgres.py /data/metabot.db || echo "[entrypoint] traspaso omitido"
fi

echo "[entrypoint] iniciando uvicorn..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
