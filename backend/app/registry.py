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


def clave_de_especialidad(especialidad: str) -> str:
    """Clave de comparación de especialidades: sin tildes, sin doble espacio.

    NO ordena las palabras, a diferencia de `clave_de_nombre`. En un nombre el
    orden varía ("Báez, Alexis" y "Alexis Báez" son la misma persona), pero en
    una especialidad el orden es parte del término: ordenar convertiría
    "Cirugía Cardiovascular" en "cardiovascular cirugia" y buscar "cirugía"
    dejaría de encontrarla.
    """
    limpio = unicodedata.normalize("NFD", (especialidad or "").lower())
    limpio = "".join(c for c in limpio if unicodedata.category(c) != "Mn")
    return " ".join(re.split(r"[^a-z0-9]+", limpio)).strip()


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
        especialidad = (f.get("Especialidad") or "").strip()[:120]
        db.add(MedicalRegistry(
            full_name=nombre[:200],
            match_key=clave_de_nombre(nombre)[:200],
            specialty=especialidad,
            specialty_key=clave_de_especialidad(especialidad)[:120],
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


# --- Búsqueda asistida para dar de alta profesionales ---

TOPE_BUSQUEDA = 25


def _consulta(db: Session, texto: str, especialidad: str):
    """La consulta filtrada, o None si no vino ningún criterio.

    Todo el filtrado va en SQL a propósito: filtrar en Python obliga a traer
    un tope de filas primero, y ese tope decide en silencio a quién se puede
    encontrar y a quién no.
    """
    texto = (texto or "").strip()
    especialidad = (especialidad or "").strip()
    if not texto and not especialidad:
        return None

    q = db.query(MedicalRegistry)
    if especialidad:
        # Por la clave normalizada, no por el texto: el padrón escribe la misma
        # especialidad de varias formas ("Cirugía General" 327 filas, "Cirugia
        # General" 19) y filtrar por el texto tal cual dejaba fuera a esos 19
        # sin decir nada. Sigue siendo "contiene" para que elegir "Cardiología"
        # traiga también "Cardiología Pediátrica".
        q = q.filter(MedicalRegistry.specialty_key.like(
            f"%{clave_de_especialidad(especialidad)}%"))

    if texto:
        # Contra `match_key`, que ya está indexada y guarda el nombre sin
        # tildes y con las palabras ordenadas: "baez martinez" encuentra
        # "Alexis Roberto Báez Martínez", y "echague carmen" encuentra
        # "Echagüe Lezcano, Carmen Elisa".
        clave = clave_de_nombre(texto)
        palabras = [w for w in clave.split() if len(w) > 2] or ([clave] if clave else [])
        for palabra in palabras:
            q = q.filter(MedicalRegistry.match_key.like(f"%{palabra}%"))
    return q


def contar(db: Session, texto: str = "", especialidad: str = "") -> int:
    """Cuántos coinciden en total, para poder decir que hay más de los que se
    muestran en vez de dar a entender que eso es todo lo que existe."""
    q = _consulta(db, texto, especialidad)
    return q.count() if q is not None else 0


def buscar(db: Session, texto: str = "", especialidad: str = "",
           limite: int = TOPE_BUSQUEDA) -> list[dict]:
    """Busca en el padrón para que la clínica marque a SUS profesionales.

    Exige un criterio: sin texto ni especialidad devuelve vacío. El padrón no
    es un directorio de médicos para navegar —son 4.772 personas reales—, es
    una ayuda para que quien da de alta no tipee mal un nombre ni invente una
    especialidad. Por eso también está solo en el panel y nunca como
    herramienta del bot.

    Todo el filtrado ocurre en SQL. Antes el nombre se filtraba en Python
    sobre las primeras 600 filas ordenadas alfabéticamente, y como el padrón
    llega hasta la "C" en esas 600, buscar "Giménez" devolvía 0 de los 57 que
    existen: la clínica leía "no hay coincidencias" y concluía que su médico no
    estaba certificado.
    """
    q = _consulta(db, texto, especialidad)
    if q is None:
        return []

    # Los vigentes primero: de 4.773 certificaciones del padrón, 4.223 ya
    # vencieron en la copia que tenemos. Ordenar solo por nombre llenaba la
    # pantalla de vencidos y escondía justo lo que la clínica busca.
    filas = (
        q.order_by(MedicalRegistry.expires_at.desc().nullslast(),
                   MedicalRegistry.full_name)
        .limit(limite)
        .all()
    )
    filas.sort(key=lambda m: m.full_name)

    hoy = datetime.now(timezone.utc).date()
    return [
        {
            "registry_id": m.id,
            "full_name": m.full_name,
            "specialty": m.specialty,
            "cert_number": m.cert_number,
            "expires_at": m.expires_at.isoformat() if m.expires_at else None,
            "vigente": bool(m.expires_at and m.expires_at >= hoy),
        }
        for m in filas[:limite]
    ]


def especialidades(db: Session) -> list[dict]:
    """Las especialidades del padrón, agrupando las variantes de escritura.

    Los 169 valores distintos del CSV son 136 especialidades reales: el resto
    son la misma escrita de otra forma ("Cardiologia"/"Cardiología",
    "Pediatria General"/"Pediatría General"/"Pediátria General"). Mostrarlas
    por separado obligaría a la clínica a elegir bien y a adivinar cuál tiene a
    su gente. Se muestra una sola opción por especialidad, etiquetada con la
    forma más frecuente, y se busca por la clave.
    """
    filas = db.query(MedicalRegistry.specialty, MedicalRegistry.specialty_key).all()
    grupos: dict[str, dict[str, int]] = {}
    for texto, clave in filas:
        if not texto:
            continue
        clave = clave or clave_de_especialidad(texto)
        variantes = grupos.setdefault(clave, {})
        variantes[texto] = variantes.get(texto, 0) + 1

    salida = [
        {
            "clave": clave,
            # La forma más usada gana; con empate, la que trae tildes, que en
            # castellano es la correcta.
            "etiqueta": max(variantes.items(), key=lambda v: (v[1], len(v[0])))[0],
            "cantidad": sum(variantes.values()),
        }
        for clave, variantes in grupos.items()
    ]
    return sorted(salida, key=lambda e: e["etiqueta"])


def alta_desde_padron(db: Session, company_id: int, registry_id: int,
                      schedule: str = "", phone: str = "", email: str = "") -> dict:
    """Da de alta un profesional tomando sus datos del padrón.

    Queda verificado de entrada, con su número de certificado y su
    vencimiento: es la diferencia entre "lo tipeó la recepcionista" y "figura
    en el registro con este número".
    """
    entrada = db.get(MedicalRegistry, registry_id)
    if not entrada:
        return {"ok": False, "error": "Ese profesional no está en el padrón"}

    existente = (
        db.query(Doctor)
        .filter(Doctor.company_id == company_id, Doctor.name == entrada.full_name)
        .first()
    )
    if existente:
        return {"ok": False, "error": f"{entrada.full_name} ya está cargado"}

    doctor = Doctor(
        company_id=company_id, name=entrada.full_name[:200],
        specialty=entrada.specialty[:200], schedule=schedule[:100],
        phone=phone[:50], email=email[:200],
    )
    db.add(doctor)
    db.flush()
    verificar(db, doctor)
    db.commit()
    return {
        "ok": True, "id": doctor.id, "name": doctor.name,
        "specialty": doctor.specialty, "verification": doctor.verification,
        "cert_number": doctor.cert_number,
    }
