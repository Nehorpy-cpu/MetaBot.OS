"""Carga el padrón de especialistas certificados del CPM.

El CSV NO se versiona: son datos personales de personas reales. Vive en el
servidor y se carga a la base para poder verificar profesionales.

Uso (dentro del contenedor del backend):
    python scripts/importar_padron_cpm.py /ruta/al/medicos_certificados_cpm.csv
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import db as db_module  # noqa: E402
from app import registry  # noqa: E402
from app.models import Company, MedicalRegistry  # noqa: E402


def main(ruta: str) -> None:
    archivo = Path(ruta)
    if not archivo.exists():
        raise SystemExit(f"No existe el archivo: {archivo}")

    db = db_module.SessionLocal()
    try:
        r = registry.importar_csv(db, archivo)
        print(f"Padrón cargado: {r['cargados']} profesionales de {r['filas']} filas")
        if r["sin_vencimiento"]:
            print(f"  {r['sin_vencimiento']} sin fecha de vencimiento legible (se dejó vacía)")

        total = db.query(MedicalRegistry).count()
        especialidades = db.query(MedicalRegistry.specialty).distinct().count()
        print(f"  en base: {total} registros, {especialidades} especialidades")

        print()
        print("Verificando los profesionales cargados en cada empresa:")
        for company in db.query(Company).order_by(Company.id).all():
            res = registry.verificar_empresa(db, company.id)
            if res["total"]:
                estados = ", ".join(f"{k}={v}" for k, v in sorted(res["por_estado"].items()))
                print(f"  [{company.id}] {company.name}: {res['total']} profesionales ({estados})")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    main(sys.argv[1])
