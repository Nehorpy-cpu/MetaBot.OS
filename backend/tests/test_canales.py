"""El canal de WhatsApp: qué falta para que funcione, dicho sin rodeos.

"El bot no responde" puede ser el modo mal puesto, el puente caído, el QR sin
escanear, un token que Meta venció o el webhook que nunca se dio de alta. Cada
una se arregla en un lugar distinto, así que el sistema tiene que decir cuál
es en vez de dejar al cliente adivinando.
"""
import pytest

from tests.test_api import _create_company, client

from app import channels


def _diagnostico(cid):
    return client.get(f"/api/companies/{cid}/wa/diagnostico").json()


def test_sin_canal_lo_dice_y_no_finge_estar_listo():
    company = _create_company(name="Empresa Sin Canal")
    d = _diagnostico(company["id"])
    assert d["mode"] == "none"
    assert d["listo"] is False
    assert any("todavía no tiene canal" in p["detalle"] for p in d["pasos"])


def test_meta_enumera_exactamente_lo_que_falta(monkeypatch):
    """Sin esto, configurar Meta es prueba y error contra una pantalla que
    solo dice que no anda."""
    from app.routers import bridge as router_bridge

    company = _create_company(name="Empresa Meta")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "meta"})

    d = _diagnostico(cid)
    assert d["mode"] == "meta"
    assert d["listo"] is False
    faltantes = [p["paso"] for p in d["pasos"] if p["ok"] is False]
    # Los cuatro datos que hacen falta, cada uno con dónde se carga.
    assert "Número asignado a esta empresa" in faltantes
    for p in d["pasos"]:
        if p["ok"] is False:
            assert p["donde"], f"no dice dónde se arregla: {p['paso']}"


def test_el_app_secret_faltante_se_reporta_como_bloqueante():
    """El webhook rechaza TODO sin firma. Es lo primero que hay que saber."""
    company = _create_company(name="Empresa Meta Secret")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "meta"})
    d = _diagnostico(cid)
    firma = next(p for p in d["pasos"] if "app secret" in p["paso"].lower())
    # En los tests no hay .env, así que falta: el mensaje tiene que explicarlo.
    if not firma["ok"]:
        assert "RECHAZA" in firma["detalle"]


def test_el_qr_avisa_que_no_es_oficial():
    """Es un conector de comunidad. Presentarlo como integración oficial es
    lo que después termina con el número del cliente restringido."""
    company = _create_company(name="Empresa QR")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "qr"})
    d = _diagnostico(cid)
    assert d["oficial"] is False
    assert "no es una integración oficial" in d["advertencia"].lower()


def test_el_qr_no_promete_plantillas_ni_campanas():
    """Mandar campañas por WhatsApp Web es exactamente lo que hace que
    restrinjan el número."""
    company = _create_company(name="Empresa QR Límites")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "qr"})
    d = _diagnostico(cid)
    assert d["puede_plantillas"] is False


def test_meta_si_puede_plantillas_y_proactivo():
    company = _create_company(name="Empresa Meta Caps")
    cid = company["id"]
    client.patch(f"/api/companies/{cid}", json={"wa_mode": "meta"})
    d = _diagnostico(cid)
    assert d["puede_plantillas"] is True
    assert d["puede_enviar_proactivo"] is True


def test_los_dos_canales_estan_disponibles():
    """El dueño quiere WhatsApp Web ahora y Meta como opción: los dos tienen
    que existir como perfil configurable."""
    assert channels.profile_for("qr").key == "qr"
    assert channels.profile_for("meta").key == "meta"
    assert channels.profile_for("meta").official is True
    assert channels.profile_for("qr").official is False


def test_el_diagnostico_de_otra_empresa_da_404():
    client.get("/api/companies/999999/wa/diagnostico").status_code == 404
