"""Padrón público de especialistas certificados y verificación de profesionales.

Para qué sirve: cuando una clínica carga un profesional, confirmar que su
certificación existe, en qué especialidad, y si sigue vigente. Ese es el
motivo por el que la certificación médica es pública: para poder verificarla.

Para qué NO sirve: poblar plantillas de clínicas. Son personas reales e
identificables; afirmar que trabajan donde nunca pisaron sería fabricar un
dato sobre alguien. Tampoco se expone como directorio consultable por el bot:
eso convertiría el padrón en una guía telefónica de médicos.
"""
import csv
import logging
import re
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from .models import Doctor, MedicalRegistry

logger = logging.getLogger("metabot.registry")

# El archivo del CPM trae DOS formatos de fecha en la misma fila. Medido sobre
# las 4.772 filas: "Fecha Acreditacion" tiene 2.968 filas con día > 12 y CERO
# con mes > 12, o sea dd/mm/aaaa. "Vencimiento" y "Fecha Sociedad" tienen
# 3.180 filas con mes > 12 y CERO con día > 12, o sea mm/dd/aaaa.
#
# Parsearlas todas igual dejaría ~1.593 vencimientos mal en silencio, y el
# vencimiento es justo el dato que dice si el profesional sigue certificado.
FORMATO_POR_COLUMNA = {
    "Fecha Acreditacion": "dmy",
    "Fecha Sociedad": "mdy",
    "Vencimiento": "mdy",
}


def _fecha(valor: str, formato: str) -> date | None:
    """Parsea una fecha con el orden declarado. Devuelve None si no se puede.

    Nunca adivina: si el valor no encaja con el formato de SU columna, se
    descarta. Una fecha inventada en un padrón médico es peor que un dato
    ausente.
    """
    valor = (valor or "").strip()
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", valor)
    if not m:
        return None
    a, b, anio = int(m.group(1)), int(m.group(2)), int(m.group(3))
    dia, mes = (a, b) if formato == "dmy" else (b, a)
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def clave_de_nombre(nombre: str) -> str:
    """Clave de comparación: minúsculas, sin tildes, palabras ORDENADAS.

    El padrón mezcla dos órdenes —"Alexis Roberto Báez Martínez" y "Echagüe
    Lezcano, Carmen Elisa"— y las clínicas escriben "Dr. Báez" o "Baez
    Martinez, Alexis". Ordenar las palabras hace que todas esas formas caigan
    en la misma clave.
    """
    limpio = unicodedata.normalize("NFD", (nombre or "").lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    # Tratamientos y títulos no identifican a nadie.
    limpio = re.sub(r"\b(dr|dra|lic|prof|mgtr|md)\.?\b", " ", limpio)
    palabras = sorted(w for w in re.split(r"[^a-z0-9]+", limpio) if len(w) > 1)
    return " ".join(palabras)


def importar_csv(db: Session, ruta: Path, source: str = "CPM") -> dict:
    """Carga el padrón. Idempotente: reemplaza lo que había de esa fuente."""
    filas = list(csv.DictReader(Path(ruta).open(encoding="utf-8-sig")))
    db.query(MedicalRegistry).filter(MedicalRegistry.source == source).delete()

    cargados = sin_vencimiento = 0
    for f in filas:
        nombre = (f.get("Apellido y Nombre") or "").strip()
        if not nombre:
            continue
        vence = _fecha(f.get("Vencimiento", ""), FORMATO_POR_COLUMNA["Vencimiento"])
        if not vence:
            sin_vencimiento += 1
        db.add(MedicalRegistry(
            full_name=nombre[:200],
            match_key=clave_de_nombre(nombre)[:200],
            specialty=(f.get("Especialidad") or "").strip()[:120],
            cert_number=(f.get("Cert N") or "").strip()[:30],
            accredited_at=_fecha(f.get("Fecha Acreditacion", ""), FORMATO_POR_COLUMNA["Fecha Acreditacion"]),
            expires_at=vence,
            source=source,
        ))
        cargados += 1
    db.commit()
    logger.info("padrón %s: %s profesionales", source, cargados)
    return {"cargados": cargados, "sin_vencimiento": sin_vencimiento, "filas": len(filas)}


def verificar(db: Session, doctor: Doctor, hoy: date | None = None) -> dict:
    """Busca al profesional en el padrón y guarda el resultado en su ficha.

    Cuatro estados posibles, y la diferencia entre ellos importa:
      verified   → figura y su certificación está vigente
      expired    → figura pero la certificación venció
      not_found  → se buscó y no figura (puede ser un no-especialista, una
                   licenciada en bioquímica o un veterinario: el padrón del
                   CPM es solo de médicos especialistas)
      unverified → todavía no se buscó
    """
    hoy = hoy or datetime.now(timezone.utc).date()
    clave = clave_de_nombre(doctor.name)
    coincidencias = (
        db.query(MedicalRegistry).filter(MedicalRegistry.match_key == clave).all()
        if clave else []
    )
    if not coincidencias:
        doctor.verification = "not_found"
        doctor.cert_number = ""
        doctor.cert_specialty = ""
        doctor.cert_expires_at = None
        doctor.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
        return {"verification": "not_found"}

    # Un mismo profesional puede estar certificado en varias especialidades.
    # Si la clínica declaró una, se prefiere esa; si no, la de vencimiento más
    # lejano, que es la que mejor representa "sigue certificado".
    declarada = clave_de_nombre(doctor.specialty)
    preferida = next(
        (m for m in coincidencias if declarada and clave_de_nombre(m.specialty) == declarada),
        None,
    )
    elegida = preferida or max(
        coincidencias, key=lambda m: m.expires_at or date.min
    )
    vigente = bool(elegida.expires_at and elegida.expires_at >= hoy)

    doctor.verification = "verified" if vigente else "expired"
    doctor.cert_number = elegida.cert_number
    doctor.cert_specialty = elegida.specialty
    doctor.cert_expires_at = elegida.expires_at
    doctor.verified_at = datetime.now(timezone.utc).replace(tzinfo=None)
    return {
        "verification": doctor.verification,
        "cert_number": elegida.cert_number,
        "cert_specialty": elegida.specialty,
        "expires_at": elegida.expires_at.isoformat() if elegida.expires_at else None,
        "otras_especialidades": sorted(
            {m.specialty for m in coincidencias if m.specialty != elegida.specialty}
        ),
    }


def verificar_empresa(db: Session, company_id: int) -> dict:
    """Verifica de una todos los profesionales de una empresa."""
    doctores = db.query(Doctor).filter(Doctor.company_id == company_id).all()
    conteo: dict[str, int] = {}
    for doc in doctores:
        r = verificar(db, doc)
        conteo[r["verification"]] = conteo.get(r["verification"], 0) + 1
    db.commit()
    return {"total": len(doctores), "por_estado": conteo}
