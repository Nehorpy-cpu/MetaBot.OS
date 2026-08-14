"""Los Business Packs son el mecanismo con el que se venden bloques.

Si se resuelven mal, un cliente que pagó se queda sin una función y nadie se
entera hasta que llama.
"""
import pytest

from app import packs
from app.packs import PACKS, VERTICAL_PACKS, active_packs


class _EmpresaFalsa:
    def __init__(self, packs_str, vertical="medical"):
        self.packs = packs_str
        self.vertical = vertical


def test_las_dependencias_se_resuelven_en_cadena():
    """Antes se miraba UN solo nivel de `requires`. Con una cadena de tres
    —el portal del profesional necesita el clínico, que necesita la agenda—
    el de abajo quedaba afuera y la empresa perdía la agenda sin aviso."""
    # Se arma una cadena de 3 sin tocar los packs reales.
    a = packs.Pack(key="_a", name="A", description="", modules=("ma",), tools=("ta",))
    b = packs.Pack(key="_b", name="B", description="", modules=("mb",), tools=("tb",),
                   requires=("_a",))
    c = packs.Pack(key="_c", name="C", description="", modules=("mc",), tools=("tc",),
                   requires=("_b",))
    originales = dict(PACKS)
    PACKS.update({p.key: p for p in (a, b, c)})
    try:
        resueltos = [p.key for p in active_packs(_EmpresaFalsa("_c"))]
        # `core` va siempre adelante; lo que importa es el orden de la cadena.
        assert resueltos[-3:] == ["_a", "_b", "_c"], f"cadena mal resuelta: {resueltos}"
    finally:
        PACKS.clear()
        PACKS.update(originales)


def test_no_se_repite_un_pack_pedido_dos_veces():
    e = _EmpresaFalsa("booking,healthcare,booking")
    claves = [p.key for p in active_packs(e)]
    assert len(claves) == len(set(claves)), f"packs repetidos: {claves}"


def test_una_dependencia_circular_no_cuelga():
    """Si alguien escribe A→B y B→A, el sistema no puede quedarse colgado."""
    a = packs.Pack(key="_x", name="X", description="", modules=(), tools=(), requires=("_y",))
    b = packs.Pack(key="_y", name="Y", description="", modules=(), tools=(), requires=("_x",))
    originales = dict(PACKS)
    PACKS.update({p.key: p for p in (a, b)})
    try:
        claves = [p.key for p in active_packs(_EmpresaFalsa("_x"))]
        assert {"_x", "_y"} <= set(claves)
    finally:
        PACKS.clear()
        PACKS.update(originales)


def test_todo_vertical_apunta_a_packs_que_existen():
    """Un vertical que apunta a un pack borrado resuelve a CERO packs: el
    cliente nuevo de ese rubro se queda sin nada y el error es mudo."""
    for vertical, claves in VERTICAL_PACKS.items():
        for clave in claves:
            assert clave in PACKS, (
                f"el vertical '{vertical}' pide el pack '{clave}', que no existe"
            )


def test_salud_arrastra_la_agenda():
    """Sin agenda no hay a qué colgarle una receta."""
    claves = [p.key for p in active_packs(_EmpresaFalsa("healthcare"))]
    assert "booking" in claves
    assert claves.index("booking") < claves.index("healthcare")


def test_cada_modulo_declarado_tiene_algo_detras():
    """Un módulo que se declara y no tiene ni tabla, ni endpoint, ni vista es
    una casilla vendible de una función que no existe. Cuando el corte por
    bloques exista, además va a apagar la nada.

    La evidencia va explícita a propósito: si mañana alguien agrega un módulo
    tiene que decir acá dónde vive, y eso es exactamente la pregunta que hay
    que hacerse antes de ponerle precio.
    """
    evidencia = {
        "inbox": "tabla conversations/messages + ChatView",
        "dashboard": "routers/dashboard.py + DashboardView",
        "agents": "tabla agents + AgentsView",
        "catalog": "tabla products + CatalogView",
        "services": "tabla services + ServicesView",
        "agenda": "tabla appointments/doctor_schedules + MedicalAgendaView",
        "reminders": "job_handlers.REMINDER_KIND",
        "insurance": "tabla insurers + service_coverages",
        "prescriptions": "tabla prescriptions + ClinicalView",
        "registry": "tabla medical_registry + registry.py",
        "medication": "medication.py + job_handlers MEDICATION",
        "previsita": "previsita.py + PreVisitModal",
        "portal": "routers/portal.py (bloque 4)",
    }
    declarados = {m for p in PACKS.values() for m in p.modules}
    sin_evidencia = declarados - set(evidencia)
    assert not sin_evidencia, (
        f"módulos sin evidencia declarada: {sorted(sin_evidencia)}. "
        "Antes de venderlos, decí acá dónde viven."
    )
