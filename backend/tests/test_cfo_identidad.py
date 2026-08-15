"""CFO de Finanzas — Fase 1: quién puede preguntar, y con qué prueba.

Del otro lado de este módulo se contestan saldos bancarios. Un WhatsApp se
clona, se hereda con un chip reciclado y se pierde en un taxi: todo lo de acá
prueba que el número solo, sin PIN, no alcanza para lo sensible.
"""
from datetime import datetime, timedelta

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login, _make_user

from app import cfo
from app.cfo import Riesgo
from app.db import SessionLocal
from app.models import FinanceIdentity

FINANZAS = ["finance"]


def _empresa(nombre: str, packs=FINANZAS):
    return _create_company(name=nombre, packs=packs)


def _identidad(cid: int, phone: str, sensibilidad="baja", nombre="Dueño"):
    r = client.post(f"/api/companies/{cid}/cfo/identidades",
                    json={"phone": phone, "nombre": nombre,
                          "sensibilidad_max": sensibilidad})
    assert r.status_code == 201, r.text
    return r.json()


def _pin(cid: int, ident_id: int, pin: str):
    r = client.put(f"/api/companies/{cid}/cfo/identidades/{ident_id}/pin",
                   json={"pin": pin})
    assert r.status_code == 200, r.text


def _autorizar(cid: int, telefono: str, riesgo: Riesgo, pin=None):
    db = SessionLocal()
    try:
        return cfo.autorizar(db, cid, telefono, riesgo, pin)
    finally:
        db.close()


# ─── El bloque se vende solo ─────────────────────────────────────────────


def test_una_empresa_puede_contratar_solo_el_cfo():
    """El modo Finance Only. `finance` no depende de agenda ni de salud: una
    empresa puede comprar el CFO y nada más."""
    c = _empresa("Distribuidora Solo Finanzas")
    assert set(c["packs"].split(",")) == {"core", "finance"}
    modulos = set(c["modules"])
    assert "cfo" in modulos
    # Y NO tiene nada de los otros bloques.
    assert not {"agenda", "prescriptions", "previsita", "portal"} & modulos


def test_sin_el_bloque_no_hay_cfo():
    """El corte lo aplica el servidor, no el panel: quien sepa la URL igual
    recibe 402."""
    c = _create_company(name="Comercio Sin CFO")
    r = client.get(f"/api/companies/{c['id']}/cfo/identidades")
    assert r.status_code == 402
    assert r.json()["detail"]["bloque"] == "finance"


def test_el_cfo_no_le_abre_la_agenda_a_la_empresa_financiera():
    """Finance Only corta para los dos lados: contratar el CFO no regala los
    otros bloques."""
    c = _empresa("Ferretería Solo CFO")
    cid = c["id"]
    assert client.get(f"/api/companies/{cid}/doctors").status_code == 402
    assert client.get(f"/api/companies/{cid}/prescriptions").status_code == 402
    # Lo del núcleo sí: el bot y el catálogo van con cualquier contratación.
    assert client.get(f"/api/companies/{cid}/services").status_code == 200


# ─── La identidad ────────────────────────────────────────────────────────


def test_un_numero_desconocido_no_consulta_nada():
    c = _empresa("Empresa Número Ajeno")
    v = _autorizar(c["id"], "595999888777", Riesgo.BAJA)
    assert not v.ok
    assert v.codigo == "no_autorizado"


def test_el_numero_se_guarda_normalizado():
    """`+595 981 123-456` y `595981123456` son la misma persona. Guardarlos
    distinto deja dos filas con permisos distintos y nadie sabe cuál manda."""
    c = _empresa("Empresa Formatos")
    ident = _identidad(c["id"], "+595 981 123-456")
    assert ident["phone"] == "595981123456"
    # Y consulta escribiendo de cualquier forma.
    assert _autorizar(c["id"], "595981123456", Riesgo.BAJA).ok
    assert _autorizar(c["id"], "+595-981-123456", Riesgo.BAJA).ok


def test_no_se_puede_autorizar_dos_veces_el_mismo_numero():
    c = _empresa("Empresa Repetida")
    _identidad(c["id"], "595981000001")
    r = client.post(f"/api/companies/{c['id']}/cfo/identidades",
                    json={"phone": "+595 981 000001", "nombre": "El mismo"})
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "numero_repetido"


def test_el_mismo_numero_ve_distinto_en_cada_empresa():
    """Un dueño de tres negocios no tiene 'un permiso': tiene uno por empresa.

    Si el permiso fuera del número, subirle el techo en la empresa chica se lo
    subiría en la grande.
    """
    a = _empresa("Grupo Empresa A")
    b = _empresa("Grupo Empresa B")
    telefono = "595981555444"
    _identidad(a["id"], telefono, sensibilidad="alta")
    ident_b = _identidad(b["id"], telefono, sensibilidad="baja")
    _pin(a["id"], _identidad_id(a["id"], telefono), "9182")
    _pin(b["id"], ident_b["id"], "9182")

    assert _autorizar(a["id"], telefono, Riesgo.ALTA, "9182").ok
    v = _autorizar(b["id"], telefono, Riesgo.ALTA, "9182")
    assert not v.ok
    assert v.codigo == "sensibilidad_insuficiente"


def _identidad_id(cid: int, telefono: str) -> int:
    db = SessionLocal()
    try:
        return cfo.identidad_de(db, cid, telefono).id
    finally:
        db.close()


def test_las_empresas_del_numero_salen_del_servidor():
    """Para "¿cuál de tus tres empresas querés consultar?". La lista la arma
    el servidor: el modelo no elige la empresa."""
    a = _empresa("Multi Uno")
    b = _empresa("Multi Dos")
    _empresa("Multi Tres")  # esta NO lo autoriza
    telefono = "595981777666"
    _identidad(a["id"], telefono)
    _identidad(b["id"], telefono)

    db = SessionLocal()
    try:
        nombres = [n for _, n in cfo.empresas_de(db, telefono)]
    finally:
        db.close()
    assert nombres == ["Multi Dos", "Multi Uno"]


# ─── El riesgo ───────────────────────────────────────────────────────────


def test_una_metrica_sin_clasificar_es_de_riesgo_alto():
    """Una consulta nueva no puede nacer siendo pública porque nadie se
    acordó de clasificarla."""
    assert cfo.riesgo_de(["metrica_que_nadie_clasifico"]) is Riesgo.ALTA


def test_el_riesgo_de_la_consulta_es_el_de_su_peor_metrica():
    """"Ventas y saldo bancario" en un mismo mensaje no se cuela como consulta
    de riesgo bajo porque la primera lo sea."""
    assert cfo.riesgo_de(["ventas_del_dia"]) is Riesgo.BAJA
    assert cfo.riesgo_de(["ventas_del_dia", "margen_bruto"]) is Riesgo.MEDIA
    assert cfo.riesgo_de(["ventas_del_dia", "saldos_bancarios"]) is Riesgo.ALTA
    assert cfo.riesgo_de([]) is Riesgo.BAJA


def test_el_techo_se_compara_por_peso_y_no_alfabeticamente():
    """"media" > "baja" alfabéticamente da la respuesta correcta por
    casualidad; "alta" < "baja" la da al revés."""
    assert cfo.alcanza("alta", Riesgo.BAJA)
    assert cfo.alcanza("alta", Riesgo.ALTA)
    assert not cfo.alcanza("baja", Riesgo.MEDIA)
    assert not cfo.alcanza("media", Riesgo.ALTA)
    # Un valor corrupto en la base no se interpreta como permisivo.
    assert not cfo.alcanza("loquesea", Riesgo.ALTA)


# ─── El PIN ──────────────────────────────────────────────────────────────


def test_sin_pin_no_hay_consulta_sensible():
    c = _empresa("Empresa Sin PIN")
    ident = _identidad(c["id"], "595981222111", sensibilidad="alta")
    assert not ident["tiene_pin"]

    assert _autorizar(c["id"], "595981222111", Riesgo.BAJA).ok
    v = _autorizar(c["id"], "595981222111", Riesgo.MEDIA)
    assert not v.ok
    assert v.codigo == "pin_no_configurado"


def test_el_pin_se_pide_y_se_verifica():
    c = _empresa("Empresa Con PIN")
    cid = c["id"]
    ident = _identidad(cid, "595981333222", sensibilidad="alta")
    _pin(cid, ident["id"], "4721")

    # Sin mandarlo: se pide, no se rechaza.
    v = _autorizar(cid, "595981333222", Riesgo.ALTA)
    assert not v.ok and v.codigo == "pin_requerido"
    # Equivocado.
    assert _autorizar(cid, "595981333222", Riesgo.ALTA, "0000").codigo == "pin_incorrecto"
    # Correcto.
    assert _autorizar(cid, "595981333222", Riesgo.ALTA, "4721").ok


def test_el_pin_nunca_sale_de_la_base():
    """Ni el PIN ni su hash. La API dice si TIENE, no cuál es."""
    c = _empresa("Empresa Hash")
    cid = c["id"]
    ident = _identidad(cid, "595981444333", sensibilidad="media")
    _pin(cid, ident["id"], "8265")

    filas = client.get(f"/api/companies/{cid}/cfo/identidades").json()
    fila = next(i for i in filas if i["id"] == ident["id"])
    assert fila["tiene_pin"] is True
    assert "pin" not in fila and "pin_hash" not in fila
    assert "8265" not in str(fila)

    # Y en la base está hasheado, no en claro.
    db = SessionLocal()
    try:
        guardado = db.get(FinanceIdentity, ident["id"]).pin_hash
    finally:
        db.close()
    assert guardado.startswith("scrypt$")
    assert "8265" not in guardado


def test_el_pin_se_bloquea_despues_de_varios_intentos():
    """Un número robado no puede probar PINes de a mil."""
    c = _empresa("Empresa Fuerza Bruta")
    cid = c["id"]
    ident = _identidad(cid, "595981555111", sensibilidad="alta")
    _pin(cid, ident["id"], "1379")

    for _ in range(cfo.INTENTOS_DE_PIN):
        assert _autorizar(cid, "595981555111", Riesgo.ALTA, "0001").codigo == "pin_incorrecto"

    # Y ahora ni con el correcto, por un rato.
    v = _autorizar(cid, "595981555111", Riesgo.ALTA, "1379")
    assert not v.ok
    assert v.codigo == "pin_bloqueado"

    # Se bloquea el PIN, NO la identidad: lo de riesgo bajo sigue andando, así
    # que un atacante no puede dejar al dueño afuera del todo.
    assert _autorizar(cid, "595981555111", Riesgo.BAJA).ok


def test_el_bloqueo_vence():
    c = _empresa("Empresa Bloqueo Vence")
    cid = c["id"]
    ident = _identidad(cid, "595981666222", sensibilidad="alta")
    _pin(cid, ident["id"], "2468")

    db = SessionLocal()
    try:
        fila = db.get(FinanceIdentity, ident["id"])
        fila.pin_bloqueado_hasta = datetime.utcnow() - timedelta(minutes=1)
        db.commit()
    finally:
        db.close()
    assert _autorizar(cid, "595981666222", Riesgo.ALTA, "2468").ok


def test_un_pin_corto_o_con_letras_no_se_guarda():
    c = _empresa("Empresa PIN Débil")
    cid = c["id"]
    ident = _identidad(cid, "595981777333")
    assert client.put(f"/api/companies/{cid}/cfo/identidades/{ident['id']}/pin",
                      json={"pin": "12"}).status_code == 422
    assert client.put(f"/api/companies/{cid}/cfo/identidades/{ident['id']}/pin",
                      json={"pin": "abcd"}).status_code == 422


def test_no_se_le_pide_pin_a_quien_igual_no_tiene_permiso():
    """Pedirle el PIN a alguien sin permiso le confirma que el número está
    dado de alta en algún lado. Primero se descarta el permiso."""
    c = _empresa("Empresa Orden")
    cid = c["id"]
    ident = _identidad(cid, "595981888444", sensibilidad="baja")
    _pin(cid, ident["id"], "5555")
    v = _autorizar(cid, "595981888444", Riesgo.ALTA, "5555")
    assert v.codigo == "sensibilidad_insuficiente"


def test_una_identidad_desactivada_no_consulta():
    c = _empresa("Empresa Baja")
    cid = c["id"]
    ident = _identidad(cid, "595981999555")
    assert client.patch(f"/api/companies/{cid}/cfo/identidades/{ident['id']}",
                        json={"activo": False}).status_code == 200
    assert _autorizar(cid, "595981999555", Riesgo.BAJA).codigo == "no_autorizado"


# ─── Quién administra ────────────────────────────────────────────────────


def test_un_operador_no_autoriza_numeros():
    """Dar de alta un número que consulta saldos es exactamente la operación
    que un atacante querría hacer."""
    c = _empresa("Empresa Permisos CFO")
    cid = c["id"]
    _make_user("operador-cfo@test.py", cid, role="operator")
    operador = _login("operador-cfo@test.py")

    assert operador.get(f"/api/companies/{cid}/cfo/identidades").status_code == 403
    assert operador.post(f"/api/companies/{cid}/cfo/identidades",
                         json={"phone": "595981000999"}).status_code == 403

    _make_user("dueno-cfo@test.py", cid, role="owner")
    dueno = _login("dueno-cfo@test.py")
    assert dueno.get(f"/api/companies/{cid}/cfo/identidades").status_code == 200


def test_no_se_vincula_un_usuario_de_otra_empresa():
    a = _empresa("Empresa Vínculo A")
    b = _empresa("Empresa Vínculo B")
    _make_user("ajeno-cfo@test.py", b["id"], role="owner")
    db = SessionLocal()
    try:
        from app.models import User
        ajeno = db.query(User).filter(User.email == "ajeno-cfo@test.py").first().id
    finally:
        db.close()

    r = client.post(f"/api/companies/{a['id']}/cfo/identidades",
                    json={"phone": "595981111999", "user_id": ajeno})
    assert r.status_code == 422


def test_la_identidad_de_otra_empresa_no_se_toca():
    a = _empresa("Empresa Cruce A")
    b = _empresa("Empresa Cruce B")
    ident = _identidad(a["id"], "595981222999")
    assert client.patch(f"/api/companies/{b['id']}/cfo/identidades/{ident['id']}",
                        json={"activo": False}).status_code == 404
    assert client.delete(
        f"/api/companies/{b['id']}/cfo/identidades/{ident['id']}").status_code == 404


def test_el_catalogo_de_riesgos_es_de_solo_lectura():
    """La clasificación vive en código y cambia por commit. No hay endpoint
    para moverla desde un panel."""
    c = _empresa("Empresa Catálogo")
    cid = c["id"]
    datos = client.get(f"/api/companies/{cid}/cfo/riesgos").json()
    assert "saldos_bancarios" in datos["niveles"]["alta"]
    assert "ventas_del_dia" in datos["niveles"]["baja"]
    # No existe forma de escribirlo.
    assert client.put(f"/api/companies/{cid}/cfo/riesgos", json={}).status_code in (404, 405)
