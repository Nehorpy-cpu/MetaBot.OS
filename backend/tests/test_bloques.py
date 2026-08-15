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
        "cfo": "app/cfo.py + routers/cfo.py (bloque 5)",
    }
    declarados = {m for p in PACKS.values() for m in p.modules}
    sin_evidencia = declarados - set(evidencia)
    assert not sin_evidencia, (
        f"módulos sin evidencia declarada: {sorted(sin_evidencia)}. "
        "Antes de venderlos, decí acá dónde viven."
    )


# ─── El gate del servidor ────────────────────────────────────────────────

_PREFIJO = "/api/companies/{company_id}"


def _rutas_de_tenant():
    """Sufijos de todas las rutas que cuelgan de una empresa, del app real."""
    from app.main import app
    sufijos = set()
    for ruta in app.openapi()["paths"]:
        if ruta.startswith(_PREFIJO):
            sufijos.add(ruta[len(_PREFIJO):])
    return sufijos


def test_ninguna_ruta_de_empresa_queda_sin_bloque():
    """LA condición para desplegar el corte por bloques.

    Si alguien agrega mañana `/lab-results` y no lo clasifica, sin este test
    la ruta se regalaría a todos en silencio —el agujero exacto que el gate
    viene a tapar—. Con este test, el despliegue se frena y la pregunta
    "¿de qué bloque es esto?" se contesta ANTES de venderlo.
    """
    sin_clasificar = sorted(
        s for s in _rutas_de_tenant() if packs.modulo_de_ruta(s) is None
    )
    assert not sin_clasificar, (
        "rutas de empresa sin bloque asignado: "
        f"{sin_clasificar}. Agregalas a _RUTAS_POR_MODULO (si son de un "
        "bloque vendible) o a _RUTAS_DEL_NUCLEO (si van con todos), en "
        "app/packs.py. No hay tercera opción: sin clasificar la API las "
        "rechaza con 403."
    )


def test_hay_al_menos_una_ruta_por_modulo_gateado():
    """Un módulo que no gatea ninguna ruta es una casilla que no apaga nada.

    Se excluyen los que por diseño no exponen API propia: `inbox`,
    `dashboard` y compañía viven en rutas del núcleo, y `medication` es una
    cola de trabajos sin endpoint todavía.
    """
    sufijos = _rutas_de_tenant()
    gateados = {packs.modulo_de_ruta(s) for s in sufijos} - {packs.NUCLEO, None}
    vendibles = {
        m
        for clave, p in PACKS.items()
        if clave != "core"
        for m in p.modules
    }
    sin_ruta = vendibles - gateados - {"medication", "portal"}
    assert not sin_ruta, (
        f"módulos vendibles que no gatean ninguna ruta: {sorted(sin_ruta)}"
    )


def test_la_pre_visita_no_cae_en_la_agenda():
    """El orden del mapa es la prioridad. `/doctors/7/pre-visit` es del
    bloque 4 y `/doctors/7/schedule` del 2, y viven en el mismo prefijo: si
    se invierte el orden de las reglas, el que compró la agenda se lleva
    gratis el resumen clínico de sus pacientes."""
    assert packs.modulo_de_ruta("/doctors/7/pre-visit") == "previsita"
    assert packs.modulo_de_ruta("/doctors/7/pre-visit/send") == "previsita"
    assert packs.modulo_de_ruta("/doctors/{doctor_id}/pre-visit") == "previsita"
    assert packs.modulo_de_ruta("/doctors/7/schedule") == "agenda"
    assert packs.modulo_de_ruta("/doctors") == "agenda"
    # El padrón del Círculo de Médicos es del bloque de salud, aunque cuelgue
    # de /doctors: son 4.772 personas reales que no vienen con la agenda.
    assert packs.modulo_de_ruta("/doctors/verify") == "registry"
    assert packs.modulo_de_ruta("/doctors/from-registry") == "registry"
    assert packs.modulo_de_ruta("/registry/search") == "registry"


def test_una_ruta_inventada_no_es_nucleo():
    """Sin clasificar ≠ permitido."""
    assert packs.modulo_de_ruta("/lab-results") is None
    assert packs.modulo_de_ruta("/facturacion/emitir") is None


def test_packs_vacio_es_solo_el_nucleo():
    """El fail-open se fue: `packs` vacío significa lo que dice.

    Mientras se derivaba del rubro, sacarle la agenda a una clínica no hacía
    nada —volvía sola en la request siguiente— y no había forma de vender
    por bloques.
    """
    claves = [p.key for p in active_packs(_EmpresaFalsa("", vertical="medical"))]
    assert claves == ["core"], f"una empresa sin packs recuperó bloques: {claves}"


# ─── El gate, a nivel HTTP ───────────────────────────────────────────────


def test_una_empresa_sin_el_bloque_recibe_402():
    """Lo que hace vendible el corte: la ruta se rechaza en el servidor.

    Esconder el botón en el panel no alcanza —el que sabe la URL entra
    igual—, y este endpoint devuelve datos clínicos de los pacientes.
    """
    from tests.test_api import _create_company, client

    c = _create_company(name="Clínica Sin Bloque 4")
    r = client.get(f"/api/companies/{c['id']}/doctors/1/pre-visit")
    assert r.status_code == 402, r.text
    detalle = r.json()["detail"]
    # El panel decide por `codigo`. Si mirara el texto, mejorar la redacción
    # del mensaje desarmaría la guardia en silencio: ya nos pasó una vez.
    assert detalle["codigo"] == "modulo_no_contratado"
    assert detalle["modulo"] == "previsita"
    assert detalle["bloque"] == "practitioner"
    # Y dice CUÁL bloque hay que comprar, que es lo que el panel ofrece.
    assert detalle["bloque_nombre"] == "Portal del Profesional"


def test_el_comercio_no_entra_a_la_agenda_ni_al_padron():
    """Una tienda compró el núcleo. Turnos y padrón médico son otros bloques."""
    from tests.test_api import _create_company, client

    c = _create_company("ecommerce", name="Tienda Sin Agenda")
    cid = c["id"]
    assert client.get(f"/api/companies/{cid}/doctors").status_code == 402
    assert client.get(f"/api/companies/{cid}/appointments").status_code == 402
    assert client.get(f"/api/companies/{cid}/registry/search?q=x").status_code == 402
    assert client.get(f"/api/companies/{cid}/prescriptions").status_code == 402
    # …pero el núcleo que sí compró funciona igual.
    assert client.get(f"/api/companies/{cid}/services").status_code == 200
    assert client.get(f"/api/companies/{cid}/dashboard").status_code == 200


def test_el_cliente_no_puede_regalarse_bloques():
    """El dueño de la empresa NO puede activarse un bloque que no pagó."""
    from tests.test_api import _create_company
    from tests.test_tenancy import _login, _make_user

    c = _create_company(name="Clínica Autoservicio")
    _make_user("dueno-packs@test.py", c["id"], role="owner")
    cliente = _login("dueno-packs@test.py")

    r = cliente.put(
        f"/api/companies/{c['id']}/packs",
        json={"packs": ["booking", "healthcare", "practitioner"]},
    )
    assert r.status_code == 403, r.text
    # Y el bloque sigue apagado de verdad, no solo en la respuesta.
    assert cliente.get(f"/api/companies/{c['id']}/doctors/1/pre-visit").status_code == 402


def test_un_bloque_inventado_no_se_guarda():
    """Guardar un pack que no existe deja al cliente pagando por nada."""
    from tests.test_api import _create_company, client

    c = _create_company(name="Clínica Pack Fantasma")
    r = client.put(f"/api/companies/{c['id']}/packs", json={"packs": ["telepatia"]})
    assert r.status_code == 422
    assert "telepatia" in r.text


def test_activar_un_bloque_lo_prende_de_verdad():
    """El camino comercial completo: se contrata y la ruta pasa a responder."""
    from tests.test_api import _create_company, client

    c = _create_company(name="Clínica Que Compra El Portal")
    cid = c["id"]
    assert client.get(f"/api/companies/{cid}/doctors/1/pre-visit").status_code == 402

    r = client.put(
        f"/api/companies/{cid}/packs",
        json={"packs": ["booking", "healthcare", "practitioner"]},
    )
    assert r.status_code == 200, r.text
    assert "previsita" in r.json()["modules"]
    # 404 = el doctor 1 no existe. Lo que importa es que ya NO es 402.
    assert client.get(f"/api/companies/{cid}/doctors/1/pre-visit").status_code == 404


def test_el_catalogo_lista_TODOS_los_bloques():
    """El panel arma la oferta con esto. Si un bloque no tiene qué decir, no
    se puede vender.

    La lista se deriva de PACKS y no se fija a mano: cuando se agregó
    `finance`, este test comparaba contra cuatro claves literales, así que
    pasó en verde mientras el catálogo omitía en silencio un bloque vendible.
    Un bloque invisible es un bloque que no se vende.
    """
    from tests.test_api import client

    r = client.get("/api/packs")
    assert r.status_code == 200, r.text
    datos = r.json()
    assert {b["key"] for b in datos} == set(PACKS), "el catálogo se comió un bloque"
    # El núcleo primero: es la base de la escalera comercial.
    assert datos[0]["key"] == "core"
    for b in datos:
        assert b["incluye"], f"el bloque '{b['key']}' no dice qué incluye"
    assert datos[0]["incluido"] is True          # el núcleo va con todo
    assert all(not b["incluido"] for b in datos[1:])
    # Y el catálogo no puede prometer un módulo que los packs no habilitan.
    for b in datos:
        assert set(b["modules"]) == set(PACKS[b["key"]].modules)


# ─── El gate en la cola de trabajos ──────────────────────────────────────


def test_el_mapa_de_trabajos_no_tiene_claves_muertas():
    """Un `kind` mal escrito en el mapa no gatea NADA y no avisa.

    Pasó al escribirlo: se mapeó un `next_visit` que no existe. El mapa se
    veía completo y el trabajo real seguía saliendo igual.
    """
    from app import job_handlers, medication  # noqa: F401 — registran handlers
    from app.jobs import HANDLERS, MODULO_POR_TRABAJO

    fantasmas = sorted(set(MODULO_POR_TRABAJO) - set(HANDLERS))
    assert not fantasmas, (
        f"tipos de trabajo que no existen: {fantasmas}. "
        f"Los registrados son: {sorted(HANDLERS)}"
    )
    # Y cada módulo al que apuntan tiene que ser un módulo real.
    reales = {m for p in PACKS.values() for m in p.modules}
    invalidos = sorted(set(MODULO_POR_TRABAJO.values()) - reales)
    assert not invalidos, f"módulos que no existen: {invalidos}"


def test_no_se_encola_un_envio_de_un_bloque_no_contratado():
    """El middleware solo mira las requests. Estos envíos salen solos horas
    después: sin gate acá, una clínica que dio de baja el bloque le seguiría
    mandando el resumen clínico a sus médicos toda la semana."""
    from datetime import datetime, timedelta, timezone

    from app import jobs
    from app.db import SessionLocal
    from tests.test_api import _create_company

    # Una clínica arranca con salud por su rubro: para el caso "no lo tiene"
    # hace falta un rubro que NO lo traiga.
    sin = _create_company("ecommerce", name="Tienda Sin Recetas")
    con = _create_company(name="Clínica Con Todo", packs=["booking", "healthcare"])
    cuando = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=2)

    db = SessionLocal()
    try:
        # `medication` es del bloque 3, que la primera no tiene.
        assert jobs.enqueue(db, company_id=sin["id"], kind="medication_dose",
                            run_at=cuando, payload={}) is None
        assert jobs.enqueue(db, company_id=con["id"], kind="medication_dose",
                            run_at=cuando, payload={}) is not None
        # Un trabajo del núcleo pasa siempre, tenga lo que tenga.
        assert jobs.enqueue(db, company_id=sin["id"], kind="whatsapp_inbound",
                            run_at=cuando, payload={}) is not None
    finally:
        db.close()
