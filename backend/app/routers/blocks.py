"""El catálogo de bloques: qué se vende y qué trae cada uno.

Existe para que haya UNA sola fuente de verdad. Si el panel tuviera su propia
lista de bloques, el día que se agregue uno habría que acordarse de tocar dos
lados, y lo que se le ofrece al cliente empezaría a no coincidir con lo que el
servidor le habilita.
"""
from fastapi import APIRouter

from ..packs import PACKS

router = APIRouter(prefix="/packs", tags=["packs"])


# Qué le decimos al cliente que hace cada bloque. Vive acá y no en `packs.py`
# porque es texto de venta —cambia con el pitch, no con el código— mientras
# que `Pack.description` es la definición técnica.
_ARGUMENTO: dict[str, list[str]] = {
    "core": [
        "Atiende el WhatsApp las 24 horas, con el tono de tu negocio",
        "Responde por tus servicios y tu catálogo con precios reales",
        "Bandeja de entrada con todas las conversaciones",
        "Informes de qué te preguntan y qué se te escapa",
    ],
    "booking": [
        "Turnos por WhatsApp contra la agenda real del profesional",
        "Horarios, licencias y ausencias por profesional",
        "Recordatorio automático el día antes",
        "Nunca dos pacientes en el mismo horario",
    ],
    "healthcare": [
        "Recetas digitales y recordatorio de cada toma",
        "Convenios y cobertura de seguros médicos",
        "Padrón de profesionales del Círculo de Médicos del Paraguay",
        "Reglas sanitarias: sin diagnósticos por chat, urgencias derivadas",
    ],
    "practitioner": [
        "Cada profesional entra con su propio usuario",
        "Ve solo SUS pacientes, nunca los de otro colega",
        "Resumen del paciente antes de que entre al consultorio",
        "Ficha completa con lo recetado en cada visita",
    ],
}

# El orden en que se muestran y se venden: de abajo hacia arriba.
_ORDEN = ("core", "booking", "healthcare", "practitioner")


@router.get("")
def list_packs():
    """Los bloques vendibles, en orden, con lo que incluye cada uno.

    No es tenant: es el catálogo de la plataforma. Cualquier usuario
    autenticado lo puede leer —es justamente lo que le queremos mostrar al
    que todavía no compró—.
    """
    salida = []
    for clave in _ORDEN:
        pack = PACKS[clave]
        salida.append(
            {
                "key": pack.key,
                "name": pack.name,
                "description": pack.description,
                "modules": list(pack.modules),
                "requires": list(pack.requires),
                # `core` no se vende: viene con cualquier contratación.
                "incluido": pack.key == "core",
                "incluye": _ARGUMENTO.get(pack.key, []),
            }
        )
    return salida
