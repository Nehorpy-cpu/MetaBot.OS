"""Planes, consumo y la clave de OpenAI de cada empresa.

Lo que se prueba acá es plata: que nadie use más de lo que compró, que el
costo se mida en vez de suponerse, y que la clave de un cliente ni se pueda
cargar sola ni salga por ninguna parte.

El escenario que esto existe para evitar: un cliente de plan chico con un
integrador mal escrito consume el margen de diez clientes buenos, y nadie se
entera hasta la factura.
"""
from datetime import datetime, timedelta

import pytest

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_tenancy import _login, _make_user

from app import cfo_secretos, consumo, planes
from app.db import SessionLocal
from app.models import AgentRun, Company


def _empresa(nombre: str, plan="basico") -> int:
    cid = _create_company(name=nombre)["id"]
    db = SessionLocal()
    try:
        db.get(Company, cid).plan = plan
        db.commit()
    finally:
        db.close()
    return cid


def _gastar(cid: int, turnos: int, modelo="gpt-4o-mini",
            entrada=1200, salida=200):
    db = SessionLocal()
    try:
        for _ in range(turnos):
            db.add(AgentRun(company_id=cid, agent_slug="cx", model=modelo,
                            tokens_entrada=entrada, tokens_salida=salida))
        db.commit()
    finally:
        db.close()


# ─── El costo se mide, no se supone ──────────────────────────────────────


def test_el_costo_sale_de_los_tokens_y_la_tarifa():
    """Un millón de tokens de entrada de gpt-4o-mini son 0,15 USD."""
    assert planes.costo_usd("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
    assert planes.costo_usd("gpt-4o-mini", 0, 1_000_000) == pytest.approx(0.60)


def test_un_modelo_gratuito_no_suma_costo():
    """No es que operarlo sea gratis: es que no lo facturamos por token, y
    cobrarlo sería inventar."""
    assert planes.costo_gs("openai/gpt-oss-120b", 100_000, 50_000) == 0


def test_un_turno_real_cuesta_lo_que_dice_la_cuenta():
    """1.200 de entrada + 200 de salida con gpt-4o-mini. Es el orden de
    magnitud sobre el que se fijaron los topes de los planes."""
    gs = planes.costo_gs("gpt-4o-mini", 1200, 200)
    # 1200/1M*0,15 + 200/1M*0,60 = 0,0003 USD ≈ ₲ 2
    assert 1 <= gs <= 5, gs


def test_el_consumo_se_abre_por_modelo():
    """Un total de tokens sin decir de qué modelo no se puede convertir a
    plata: cada uno tiene otra tarifa."""
    cid = _empresa("Consumo Por Modelo")
    _gastar(cid, 3, modelo="gpt-4o-mini")
    _gastar(cid, 5, modelo="openai/gpt-oss-120b")
    db = SessionLocal()
    try:
        uso = consumo.tokens_del_mes(db, cid)
    finally:
        db.close()
    modelos = {m["modelo"]: m for m in uso["por_modelo"]}
    assert modelos["gpt-4o-mini"]["turnos"] == 3
    assert modelos["gpt-4o-mini"]["costo_gs"] > 0
    assert modelos["openai/gpt-oss-120b"]["gratuito"] is True


def test_el_consumo_de_una_empresa_no_se_mezcla_con_otra():
    a = _empresa("Consumo Cruce A")
    b = _empresa("Consumo Cruce B")
    _gastar(a, 10)
    db = SessionLocal()
    try:
        assert consumo.mensajes_del_mes(db, b) == 0
    finally:
        db.close()


def test_el_mes_pasado_no_cuenta():
    """El mes es el calendario: el cliente entiende "se me reinicia el 1°"."""
    cid = _empresa("Consumo Mes Pasado")
    _gastar(cid, 5)
    db = SessionLocal()
    try:
        for r in db.query(AgentRun).filter(AgentRun.company_id == cid).all():
            r.created_at = datetime.utcnow() - timedelta(days=45)
        db.commit()
        assert consumo.mensajes_del_mes(db, cid) == 0
    finally:
        db.close()


# ─── El tope ─────────────────────────────────────────────────────────────


def test_al_agotar_el_plan_deja_de_alcanzar():
    cid = _empresa("Tope Plan", plan="prueba")
    db = SessionLocal()
    try:
        company = db.get(Company, cid)
        assert consumo.alcanza_mensajes(db, company) is True
    finally:
        db.close()

    _gastar(cid, planes.PRUEBA.mensajes_por_mes)
    db = SessionLocal()
    try:
        assert consumo.alcanza_mensajes(db, db.get(Company, cid)) is False
    finally:
        db.close()


def test_el_aviso_le_habla_al_cliente_final_y_no_de_planes():
    """Del otro lado hay alguien que no tiene idea de que existe un plan y no
    tiene la culpa. "Cuota excedida" es vocabulario nuestro y hace quedar mal
    al negocio que nos contrató."""
    db = SessionLocal()
    try:
        aviso = consumo.aviso_de_tope(db.get(Company, _empresa("Aviso")), "mensajes")
    finally:
        db.close()
    for palabra in ("plan", "cuota", "tope", "límite", "excedid"):
        assert palabra not in aviso.lower(), aviso


def test_un_plan_desconocido_cae_al_mas_chico():
    """Si algo sale mal con el dato, que salga mal para el lado de consumir de
    menos."""
    db = SessionLocal()
    try:
        company = db.get(Company, _empresa("Plan Raro", plan="platino-infinito"))
        assert planes.plan_de(company).clave == "prueba"
    finally:
        db.close()


def test_no_se_emite_un_informe_pasado_el_tope():
    cid = _create_company(name="Tope Informes", packs=["finance"])["id"]
    db = SessionLocal()
    try:
        db.get(Company, cid).plan = "prueba"
        db.commit()
    finally:
        db.close()
    client.post(f"/api/companies/{cid}/cfo/metricas/ventas_netas/aprobar",
                json={"version": 1})

    cuerpo = {"metricas": ["ventas_netas"], "desde": "2026-08-01",
              "hasta": "2026-08-15"}
    for _ in range(planes.PRUEBA.informes_por_mes):
        assert client.post(f"/api/companies/{cid}/cfo/informes",
                           json=cuerpo).status_code == 201
    r = client.post(f"/api/companies/{cid}/cfo/informes", json=cuerpo)
    assert r.status_code == 402
    assert r.json()["detail"]["codigo"] == "tope_del_plan"


# ─── Quién puede qué ─────────────────────────────────────────────────────


def test_el_cliente_ve_su_consumo():
    """Ocultarle a un cliente lo que consume es cómo se llega a una discusión
    por la factura."""
    cid = _empresa("Consumo Visible")
    _gastar(cid, 4)
    r = client.get(f"/api/companies/{cid}/consumo").json()
    assert r["mensajes"]["usados"] == 4
    assert r["mensajes"]["tope"] == planes.BASICO.mensajes_por_mes
    assert r["consumo_de_ia"]["costo_gs"] > 0
    assert r["clave_en_uso"] == "plataforma"


def test_hasta_un_operador_ve_el_consumo():
    """No es un dato de administración: es la cuenta de luz del negocio."""
    cid = _empresa("Consumo Operador")
    _make_user("operador-consumo@test.py", cid, role="operator")
    op = _login("operador-consumo@test.py")
    assert op.get(f"/api/companies/{cid}/consumo").status_code == 200


def test_un_cliente_no_se_cambia_solo_de_plan():
    """Un cliente que se pasa solo al plan más grande no es un cliente, es un
    regalo."""
    cid = _empresa("Plan Propio")
    _make_user("duenio-plan@test.py", cid, role="owner")
    duenio = _login("duenio-plan@test.py")
    r = duenio.put(f"/api/companies/{cid}/plan", json={"plan": "empresa"})
    assert r.status_code == 403
    assert r.json()["detail"]["codigo"] == "solo_plataforma"


def test_la_plataforma_si_cambia_el_plan():
    cid = _empresa("Plan Cambiado", plan="prueba")
    r = client.put(f"/api/companies/{cid}/plan", json={"plan": "profesional"})
    assert r.status_code == 200
    assert r.json()["plan"]["clave"] == "profesional"


def test_no_se_puede_poner_un_plan_que_no_existe():
    cid = _empresa("Plan Inventado")
    r = client.put(f"/api/companies/{cid}/plan", json={"plan": "infinito"})
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "plan_desconocido"


def test_el_catalogo_de_planes_no_depende_de_la_empresa():
    filas = client.get("/api/planes").json()
    claves = {p["clave"] for p in filas}
    assert claves == set(planes.PLANES)
    assert all(p["precio_gs"] >= 0 for p in filas)


# ─── La clave de cada cliente ────────────────────────────────────────────


def test_el_cliente_pide_su_clave_pero_no_la_carga():
    """Que la escriba en un formulario nuestro sería enseñarle a pegar su
    credencial de OpenAI en cualquier lado."""
    cid = _empresa("Clave Solicitada")
    _make_user("duenio-clave@test.py", cid, role="owner")
    duenio = _login("duenio-clave@test.py")

    r = duenio.post(f"/api/companies/{cid}/clave-openai/solicitar")
    assert r.status_code == 200
    assert r.json()["ya_tiene"] is False
    assert "no la escribas" in r.json()["aviso"].lower()

    # Pedir no es cargar: sigue atendiendo con la de la plataforma.
    assert duenio.get(f"/api/companies/{cid}/consumo").json()["clave_en_uso"] == "plataforma"
    # Y no puede cargarla él.
    assert duenio.put(f"/api/companies/{cid}/clave-openai",
                      json={"clave": "sk-" + "x" * 40}).status_code == 403


def test_la_plataforma_ve_las_solicitudes_pendientes():
    cid = _empresa("Clave Pendiente")
    client.post(f"/api/companies/{cid}/clave-openai/solicitar")
    filas = client.get("/api/clave-openai/solicitudes").json()
    mia = [f for f in filas if f["company_id"] == cid]
    assert len(mia) == 1
    # Con el consumo al lado: es el dato con el que se decide si le conviene.
    assert "consumo" in mia[0]


def test_la_clave_cargada_se_guarda_cifrada_y_no_sale():
    if not cfo_secretos.hay_llave():
        pytest.skip("sin CFO_SECRETS_KEY en el entorno de prueba")
    cid = _empresa("Clave Cargada")
    secreta = "sk-proj-" + "z" * 40
    assert client.put(f"/api/companies/{cid}/clave-openai",
                      json={"clave": secreta}).status_code == 200

    db = SessionLocal()
    try:
        guardada = db.get(Company, cid).openai_key_cifrada
        assert guardada and secreta not in guardada
        assert cfo_secretos.descifrar(guardada) == secreta
    finally:
        db.close()

    # No sale por ninguna ruta que devuelva la empresa.
    assert secreta not in client.get(f"/api/companies/{cid}/consumo").text
    assert secreta not in client.get("/api/companies").text
    assert client.get(f"/api/companies/{cid}/consumo").json()["clave_en_uso"] == "propia"


def test_una_clave_que_no_parece_de_openai_se_rechaza():
    cid = _empresa("Clave Rara")
    r = client.put(f"/api/companies/{cid}/clave-openai",
                   json={"clave": "esto-no-es-una-clave-de-openai-pero-es-larga"})
    assert r.status_code == 422
    assert r.json()["detail"]["codigo"] == "clave_invalida"


def test_al_cargar_la_clave_la_solicitud_se_cierra():
    if not cfo_secretos.hay_llave():
        pytest.skip("sin CFO_SECRETS_KEY en el entorno de prueba")
    cid = _empresa("Clave Solicitud Cerrada")
    client.post(f"/api/companies/{cid}/clave-openai/solicitar")
    client.put(f"/api/companies/{cid}/clave-openai",
               json={"clave": "sk-" + "y" * 40})
    pendientes = {f["company_id"] for f in
                  client.get("/api/clave-openai/solicitudes").json()}
    assert cid not in pendientes


def test_el_plan_empresa_exige_clave_propia():
    """A ese volumen, que el consumo lo pague la plataforma es regalar el
    margen. El plan lo declara y el panel lo muestra."""
    assert planes.EMPRESA.clave_propia is True
    assert planes.BASICO.clave_propia is False


def test_los_topes_crecen_con_el_precio():
    """Un plan más caro que no da más es una estafa, y uno más barato que da
    lo mismo hace que nadie compre el caro."""
    ordenados = sorted(planes.PLANES.values(), key=lambda p: p.precio_gs)
    for anterior, siguiente in zip(ordenados, ordenados[1:]):
        assert siguiente.mensajes_por_mes > anterior.mensajes_por_mes
        assert siguiente.informes_por_mes > anterior.informes_por_mes


def test_el_costo_de_ia_de_un_plan_agotado_no_se_come_el_precio():
    """El tope está puesto para que, si un cliente lo agota, el mes siga
    siendo rentable. Si esta prueba falla, el plan pierde plata cuando se
    usa."""
    for plan in planes.PLANES.values():
        if plan.precio_gs == 0 or plan.clave_propia:
            continue
        # Un turno medido: ~1.200 de entrada y ~200 de salida.
        costo = planes.costo_gs(
            "gpt-4o-mini",
            1200 * plan.mensajes_por_mes,
            200 * plan.mensajes_por_mes,
        )
        assert costo < plan.precio_gs * 0.35, (
            f"{plan.clave}: la IA se lleva {costo} de {plan.precio_gs}"
        )
