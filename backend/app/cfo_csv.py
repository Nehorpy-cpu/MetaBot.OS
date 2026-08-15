"""Carga de una planilla exportada del sistema del cliente.

Es el primer conector a propósito: un comercio paraguayo no tiene una API,
tiene un botón de "exportar" en su sistema de facturación. Si el CFO exige
integraciones para empezar a servir, no empieza nunca.

Todo lo de acá está escrito contra archivos reales, no contra un CSV ideal:

- El separador puede ser `;`. Excel en configuración regional castellana
  exporta así, y el archivo se ve perfecto al abrirlo.
- Los montos vienen `1.234.567` o `1.234.567,00`. El punto es separador de
  miles, no decimal. Leerlo al revés convierte un millón doscientos en uno.
- Las fechas vienen `dd/mm/aaaa`. Interpretarlas al modo estadounidense pasa
  el 3 de julio al 7 de marzo, sin error y sin aviso.
- El archivo puede venir en cp1252, y entonces "Días" llega roto.

La decisión de fondo: **si una fila no se entiende, no se carga NINGUNA.**
Cargar 98 de 100 filas da un total que se ve bien, cierra mal y nadie sabe
por qué. Es preferible devolver los renglones con problema y que el dueño
arregle su archivo.
"""
import csv
import io
import json
import re
from datetime import date, datetime

from sqlalchemy.orm import Session

from .cfo_metricas import Fuente
from .models import FinanceConnector, FinanceRecord

# 5 MB. Una exportación de un año de un comercio mediano no llega ni cerca;
# lo que llega a este tamaño es un error o alguien probando el límite.
MAXIMO_BYTES = 5 * 1024 * 1024
MAXIMO_FILAS = 50_000

COLUMNAS = ("fecha", "monto", "categoria", "referencia")

_SOLO_NUMERO = re.compile(r"[^0-9,.\-]")


class PlanillaInvalida(Exception):
    """Trae los renglones con problema, no un 'formato incorrecto'."""

    def __init__(self, motivo: str, renglones: list[str] | None = None):
        super().__init__(motivo)
        self.motivo = motivo
        self.renglones = renglones or []


def _decodificar(datos: bytes) -> str:
    """utf-8, con o sin BOM; y si no, cp1252, que es lo que exporta Excel."""
    for codec in ("utf-8-sig", "utf-8", "cp1252"):
        try:
            return datos.decode(codec)
        except UnicodeDecodeError:
            continue
    raise PlanillaInvalida(
        "No se pudo leer el archivo. Guardalo como CSV UTF-8 y volvé a subirlo."
    )


def _separador(muestra: str) -> str:
    """`;` si hay más punto y coma que comas en el encabezado.

    Adivinar con `csv.Sniffer` falla justo en el caso paraguayo: un archivo
    con `;` y montos con coma decimal lo confunde y elige `,`.
    """
    encabezado = muestra.splitlines()[0] if muestra.splitlines() else ""
    return ";" if encabezado.count(";") > encabezado.count(",") else ","


def leer_monto(crudo: str) -> int:
    """A guaraníes enteros. `1.234.567,00` y `1234567` dan lo mismo.

    Los guaraníes no tienen centavos en la práctica: si viene una parte
    decimal, se descarta. Redondearla haría que la suma de las partes deje de
    dar el total, y eso es peor que perder un céntimo que no existe.
    """
    texto = _SOLO_NUMERO.sub("", (crudo or "").strip())
    if not texto:
        raise ValueError("monto vacío")
    negativo = texto.startswith("-")
    texto = texto.lstrip("-")

    if "," in texto and "." in texto:
        # El último que aparece manda: `1.234,56` es coma decimal y
        # `1,234.56` es punto decimal.
        decimal = "," if texto.rfind(",") > texto.rfind(".") else "."
        miles = "." if decimal == "," else ","
        texto = texto.replace(miles, "").split(decimal)[0]
    elif "," in texto:
        partes = texto.split(",")
        # `1,234,567` son miles; `1234,56` es decimal.
        texto = "".join(partes) if all(len(p) == 3 for p in partes[1:]) else partes[0]
    elif "." in texto:
        partes = texto.split(".")
        texto = "".join(partes) if all(len(p) == 3 for p in partes[1:]) else partes[0]

    if not texto.isdigit():
        raise ValueError(f"no es un monto: {crudo!r}")
    return -int(texto) if negativo else int(texto)


def leer_fecha(crudo: str) -> date:
    """dd/mm/aaaa primero: es lo que se usa acá."""
    texto = (crudo or "").strip()[:19]
    if not texto:
        raise ValueError("fecha vacía")
    for formato in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y",
                    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    raise ValueError(f"no es una fecha: {crudo!r}")


def analizar(datos: bytes) -> list[dict]:
    """Del archivo a filas normalizadas. Explota con los renglones que fallan."""
    if len(datos) > MAXIMO_BYTES:
        raise PlanillaInvalida(
            f"El archivo pesa más de {MAXIMO_BYTES // (1024 * 1024)} MB."
        )
    texto = _decodificar(datos)
    if not texto.strip():
        raise PlanillaInvalida("El archivo está vacío.")

    lector = csv.DictReader(io.StringIO(texto), delimiter=_separador(texto))
    campos = [(c or "").strip().lower() for c in (lector.fieldnames or [])]
    faltan = [c for c in ("fecha", "monto") if c not in campos]
    if faltan:
        raise PlanillaInvalida(
            "Al archivo le faltan columnas: " + ", ".join(faltan) + ". "
            "Se esperan: " + ", ".join(COLUMNAS) + " (categoría y referencia "
            "son opcionales)."
        )

    filas, problemas = [], []
    for numero, cruda in enumerate(lector, start=2):  # 1 es el encabezado
        if numero - 1 > MAXIMO_FILAS:
            raise PlanillaInvalida(f"El archivo tiene más de {MAXIMO_FILAS} filas.")
        limpia = {(k or "").strip().lower(): (v or "") for k, v in cruda.items()}
        if not any(v.strip() for v in limpia.values()):
            continue  # línea en blanco al final, no es un error
        try:
            fila = {
                "fecha": leer_fecha(limpia.get("fecha", "")),
                "monto_gs": leer_monto(limpia.get("monto", "")),
                "categoria": limpia.get("categoria", "").strip()[:120],
                "referencia": limpia.get("referencia", "").strip()[:120],
            }
        except ValueError as exc:
            problemas.append(f"Fila {numero}: {exc}")
            if len(problemas) >= 20:
                problemas.append("… y puede haber más.")
                break
            continue
        filas.append(fila)

    if problemas:
        raise PlanillaInvalida(
            "Hay filas que no se entienden, así que no se cargó ninguna. "
            "Cargar solo una parte daría un total que se ve bien y cierra mal.",
            problemas,
        )
    if not filas:
        raise PlanillaInvalida("El archivo no tiene ninguna fila con datos.")
    return filas


def cargar(db: Session, conector: FinanceConnector, datos: bytes) -> dict:
    """Carga la planilla en `finance_records`. Idempotente por referencia.

    Volver a subir el mismo archivo no duplica: las filas con la misma
    referencia se pisan. Las que no traen referencia reciben una derivada de
    su contenido, así que subir dos veces lo mismo tampoco las duplica.
    """
    filas = analizar(datos)
    nuevas = actualizadas = 0
    for fila in filas:
        referencia = fila["referencia"] or (
            f"{fila['fecha'].isoformat()}|{fila['monto_gs']}|{fila['categoria']}"
        )
        existente = (
            db.query(FinanceRecord)
            .filter(
                FinanceRecord.company_id == conector.company_id,
                FinanceRecord.connector_id == conector.id,
                FinanceRecord.referencia == referencia,
            )
            .first()
        )
        if existente:
            existente.fecha = fila["fecha"]
            existente.monto_gs = fila["monto_gs"]
            existente.categoria = fila["categoria"]
            actualizadas += 1
            continue
        db.add(FinanceRecord(
            company_id=conector.company_id,
            connector_id=conector.id,
            fuente=conector.fuente,
            fecha=fila["fecha"],
            monto_gs=fila["monto_gs"],
            categoria=fila["categoria"],
            referencia=referencia,
            detalle=json.dumps({"origen": "csv"}),
        ))
        nuevas += 1
    db.commit()
    return {"nuevas": nuevas, "actualizadas": actualizadas, "leidas": len(filas)}


def fuentes_validas() -> tuple[str, ...]:
    """Todas menos la interna: esa no se sube, ya está adentro."""
    return tuple(f.value for f in Fuente if f != Fuente.INTERNA)
