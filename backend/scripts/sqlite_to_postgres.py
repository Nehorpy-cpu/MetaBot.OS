"""Traspasa los datos de la base SQLite legada a PostgreSQL.

Uso (dentro del contenedor backend, con DATABASE_URL apuntando a Postgres):
    python scripts/sqlite_to_postgres.py /data/metabot.db

Idempotente por tabla: si la tabla destino ya tiene filas, la saltea (no
duplica). Respeta el orden de dependencias de claves foráneas.
"""
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, insert, select, text  # noqa: E402

from app.config import DATABASE_URL  # noqa: E402
from app.db import Base  # noqa: E402
from app import models  # noqa: F401,E402

# Orden: padres antes que hijos
ORDEN = [
    "companies", "agents", "doctors", "services", "doctor_services",
    "appointments", "conversations", "messages", "products",
    "glossary_terms", "reports", "audit_findings", "competitor_sources",
    "creatives", "campaigns", "prompt_suggestions",
]


def main(sqlite_path: str) -> None:
    if not Path(sqlite_path).exists():
        print(f"No existe {sqlite_path}: nada que migrar.")
        return
    if DATABASE_URL.startswith("sqlite"):
        print("DATABASE_URL apunta a SQLite; este script migra HACIA PostgreSQL.")
        return

    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    src_tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    dest = create_engine(DATABASE_URL)
    total = 0
    with dest.begin() as conn:
        for table_name in ORDEN:
            table = Base.metadata.tables.get(table_name)
            if table is None or table_name not in src_tables:
                continue
            existing = conn.execute(select(text("count(*)")).select_from(table)).scalar() or 0
            if existing:
                print(f"  {table_name}: ya tiene {existing} filas, se saltea")
                continue
            src_cols = {r[1] for r in src.execute(f"PRAGMA table_info({table_name})")}
            cols = [c.name for c in table.columns if c.name in src_cols]
            rows = [
                {c: r[c] for c in cols}
                for r in src.execute(f"SELECT {', '.join(cols)} FROM {table_name}")
            ]
            if rows:
                conn.execute(insert(table), rows)
                total += len(rows)
                print(f"  {table_name}: {len(rows)} filas migradas")

        # Reajustar las secuencias de id de PostgreSQL al máximo actual
        for table_name in ORDEN:
            table = Base.metadata.tables.get(table_name)
            if table is None or "id" not in table.columns:
                continue
            conn.execute(text(
                f"SELECT setval(pg_get_serial_sequence('{table_name}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {table_name}), 1), true)"
            ))
    print(f"Listo: {total} filas migradas en total.")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "/data/metabot.db")
