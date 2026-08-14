"""Planillas de honorarios: separar por aseguradora para poder cobrar.

Acá se mueve plata de verdad. Un error no se ve como una excepción: se ve
como un profesional que cobra de menos y firma conforme, o como una atención
facturada dos veces que termina en una nota de crédito.

El archivo NO se llama `test_honorarios.py` a propósito: `tests/` no tiene
`__init__.py`, así que un módulo de test con el mismo nombre que uno de `app/`
lo tapa y la suite completa falla de una forma que no se entiende. Ya pasó con
`test_agenda.py`.
"""
from datetime import date, datetime, timedelta

from tests.test_api import _create_company, client  # noqa: I001
from tests.test_portal import _acceso, _doctor
from tests.test_tenancy import _login, _make_user

from app.db import SessionLocal
from app.models import Appointment, Doctor, Insurer, Service

PORTAL = ["booking", "healthcare", "practitioner"]

# Un período cerrado en el pasado: no se mueve con el reloj y no choca con la
# validación de agenda, que es de turnos futuros.
DESDE = date(2026, 7, 1)
HASTA = date(2026, 7, 31)


def _clinica(nombre: str):
    return _create_company(name=nombre, packs=PORTAL)


def _convenio(cid: int, nombre: str, plan: str = "", pct: int = 80, copago: int = 0):
    db = SessionLocal()
    try:
        i = Insurer(company_id=cid, name=nombre, plan=plan, coverage_pct=pct,
                    copay_gs=copago, active=True)
        db.add(i)
        db.commit()
        return i.id
    finally:
        db.close()


def _servicio(cid: int, nombre: str, precio: int):
    db = SessionLocal()
    try:
        s = Service(company_id=cid, name=nombre, price_gs=precio, active=True)
        db.add(s)
        db.commit()
        return s.id
    finally:
        db.close()


def _atencion(cid: int, doctor_id: int, paciente: str, dia: int,
              service_id=None, insurer_id=None, estado="attended"):
    """Una atención ya ocurrida. Se inserta directo: el endpoint de alta
    valida contra la agenda futura, y acá el período es pasado a propósito."""
    db = SessionLocal()
    try:
        a = Appointment(
            company_id=cid, doctor_id=doctor_id, patient_name=paciente,
            patient_phone="595981000000", scheduled_at=datetime(2026, 7, dia, 10, 0),
            service_id=service_id, insurer_id=insurer_id, status=estado,
        )
        db.add(a)
        db.commit()
        return a.id
    finally:
        db.close()


def _pct(cid: int, doctor_id: int, pct: int):
    db = SessionLocal()
    try:
        db.get(Doctor, doctor_id).honorario_pct = pct
        db.commit()
    finally:
        db.close()


def _preview(portal, cid, **extra):
    r = portal.get(f"/api/companies/{cid}/portal/honorarios/preview",
                   params={"desde": DESDE.isoformat(), "hasta": HASTA.isoformat(), **extra})
    assert r.status_code == 200, r.text
    return r.json()


def _armar(portal, cid):
    return portal.post(f"/api/companies/{cid}/portal/honorarios",
                       params={"desde": DESDE.isoformat(), "hasta": HASTA.isoformat()})


# ─── Lo que el profesional necesita para cobrar ──────────────────────────


def test_las_atenciones_se_separan_por_aseguradora():
    """LA función: cada aseguradora tiene su formato y su circuito. Una
    planilla mezclada no la recibe nadie."""
    c = _clinica("Sanatorio Separar")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Separadora")
    consulta = _servicio(cid, "Consulta clínica", 150_000)
    nanduti = _convenio(cid, "Seguro Ñandutí", "Plan Oro", pct=80)
    asismed = _convenio(cid, "Asismed", "", pct=60)

    _atencion(cid, doc["id"], "Paciente Ñandutí", 3, consulta, nanduti)
    _atencion(cid, doc["id"], "Paciente Asismed", 4, consulta, asismed)
    _atencion(cid, doc["id"], "Paciente Particular", 5, consulta, None)

    portal = _acceso(cid, doc["id"], "separar@test.py")
    datos = _preview(portal, cid)

    grupos = {g["aseguradora"]: g for g in datos["grupos"]}
    assert set(grupos) == {"Seguro Ñandutí Plan Oro", "Asismed", "Particulares"}
    # 80% de 150.000 = 120.000 lo pone la aseguradora.
    assert grupos["Seguro Ñandutí Plan Oro"]["total_facturado_gs"] == 120_000
    assert grupos["Asismed"]["total_facturado_gs"] == 90_000
    # El particular paga el precio de lista entero.
    assert grupos["Particulares"]["total_facturado_gs"] == 150_000
    # Los particulares van últimos: primero lo que hay que ir a cobrar afuera.
    assert datos["grupos"][-1]["aseguradora"] == "Particulares"


def test_el_honorario_es_el_porcentaje_arreglado_del_profesional():
    """En un sanatorio el profesional cobra una parte y la institución retiene
    el resto. El arreglo es por profesional: no todos firman lo mismo."""
    c = _clinica("Sanatorio Porcentajes")
    cid = c["id"]
    doc = _doctor(cid, "Dr. Sesenta")
    _pct(cid, doc["id"], 60)
    consulta = _servicio(cid, "Consulta", 200_000)
    seguro = _convenio(cid, "Prepaga Test", pct=100)
    _atencion(cid, doc["id"], "Un Paciente", 7, consulta, seguro)

    portal = _acceso(cid, doc["id"], "sesenta@test.py")
    datos = _preview(portal, cid)
    assert datos["honorario_pct"] == 60
    assert datos["total_facturado_gs"] == 200_000
    assert datos["total_honorario_gs"] == 120_000


def test_solo_se_liquida_lo_atendido_y_lo_demas_se_avisa():
    """Un turno confirmado al que el paciente no vino no es plata.

    Pero omitirlo en silencio es peor: el profesional cobra de menos y firma
    conforme sin enterarse. Por eso el preview dice cuántos quedaron sin
    marcar.
    """
    c = _clinica("Sanatorio Sin Marcar")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Sin Marcar")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc["id"], "Vino", 2, consulta, estado="attended")
    _atencion(cid, doc["id"], "No Vino", 3, consulta, estado="no_show")
    _atencion(cid, doc["id"], "Canceló", 4, consulta, estado="cancelled")
    _atencion(cid, doc["id"], "Sin Marcar", 5, consulta, estado="confirmed")
    _atencion(cid, doc["id"], "Tampoco Marcado", 6, consulta, estado="pending")

    portal = _acceso(cid, doc["id"], "sinmarcar@test.py")
    datos = _preview(portal, cid)
    assert datos["atenciones"] == 1
    assert datos["total_facturado_gs"] == 100_000
    assert datos["sin_marcar_como_atendido"] == 2, "no avisó de los turnos sin cerrar"


def test_una_atencion_no_se_puede_cobrar_dos_veces():
    """El invariante que hace confiable a todo lo demás.

    Rearmar la planilla o superponer dos períodos tiene que fallar. Si
    facturara dos veces la misma consulta, no lo arregla un deploy: lo
    arregla una nota de crédito y una discusión con la aseguradora.
    """
    c = _clinica("Sanatorio Doble Cobro")
    cid = c["id"]
    doc = _doctor(cid, "Dr. Doble Cobro")
    consulta = _servicio(cid, "Consulta", 100_000)
    seguro = _convenio(cid, "Prepaga Doble", pct=100)
    _atencion(cid, doc["id"], "Paciente Único", 10, consulta, seguro)

    portal = _acceso(cid, doc["id"], "doblecobro@test.py")
    primera = _armar(portal, cid)
    assert primera.status_code == 201, primera.text

    segunda = _armar(portal, cid)
    assert segunda.status_code == 409, segunda.text
    # La segunda vez ya no queda nada nuevo para liquidar.
    assert segunda.json()["detail"]["codigo"] == "sin_atenciones"
    # Y el preview lo dice en vez de mostrar un cero misterioso.
    datos = _preview(portal, cid)
    assert datos["atenciones"] == 0
    assert datos["ya_liquidadas"] == 1


def test_borrar_un_borrador_libera_las_atenciones():
    """Rearmar una planilla mal armada tiene que ser posible, o el profesional
    queda trabado con un documento equivocado."""
    c = _clinica("Sanatorio Rearmar")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Rearmar")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc["id"], "Paciente Rearmado", 12, consulta)

    portal = _acceso(cid, doc["id"], "rearmar@test.py")
    planilla = _armar(portal, cid).json()[0]
    assert portal.delete(
        f"/api/companies/{cid}/portal/honorarios/{planilla['id']}"
    ).status_code == 204
    # Liberada: se puede volver a armar.
    assert _armar(portal, cid).status_code == 201


def test_lo_firmado_no_se_borra():
    """Una planilla firmada es un documento, no un borrador."""
    c = _clinica("Sanatorio Firmado")
    cid = c["id"]
    doc = _doctor(cid, "Dr. Firmante")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc["id"], "Paciente Firmado", 14, consulta)

    portal = _acceso(cid, doc["id"], "firmante@test.py")
    planilla = _armar(portal, cid).json()[0]
    assert portal.post(
        f"/api/companies/{cid}/portal/honorarios/{planilla['id']}/firmar"
    ).status_code == 200

    r = portal.delete(f"/api/companies/{cid}/portal/honorarios/{planilla['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "planilla_cerrada"


def test_no_se_entrega_lo_que_no_esta_firmado():
    """La planilla que llega a la aseguradora tiene que estar firmada. El
    circuito es una escalera de un solo sentido."""
    c = _clinica("Sanatorio Escalera")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Escalera")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc["id"], "Paciente Escalera", 16, consulta)

    portal = _acceso(cid, doc["id"], "escalera@test.py")
    planilla = _armar(portal, cid).json()[0]
    base = f"/api/companies/{cid}/portal/honorarios/{planilla['id']}"

    r = portal.post(f"{base}/entregar")
    assert r.status_code == 409
    assert r.json()["detail"]["codigo"] == "estado_invalido"

    assert portal.post(f"{base}/firmar").status_code == 200
    assert portal.post(f"{base}/entregar").json()["estado"] == "entregada"
    # Firmar dos veces tampoco: ya está firmada.
    assert portal.post(f"{base}/firmar").status_code == 409


def test_el_profesional_no_se_marca_a_si_mismo_que_le_pagaron():
    """Sería firmar que se pagó a sí mismo. Lo registra la administración."""
    c = _clinica("Sanatorio Cobro")
    cid = c["id"]
    doc = _doctor(cid, "Dr. Cobrador")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc["id"], "Paciente Cobro", 18, consulta)

    portal = _acceso(cid, doc["id"], "cobrador@test.py")
    planilla = _armar(portal, cid).json()[0]
    base = f"/api/companies/{cid}/portal/honorarios/{planilla['id']}"
    portal.post(f"{base}/firmar")
    portal.post(f"{base}/entregar")

    assert portal.post(f"{base}/pagar").status_code == 403

    # La administración sí. Aparece en lo que la clínica debe.
    _make_user("admin-honorarios@test.py", cid, role="owner")
    admin = _login("admin-honorarios@test.py")
    pendientes = admin.get(f"/api/companies/{cid}/portal/honorarios-a-pagar").json()
    assert [p["id"] for p in pendientes] == [planilla["id"]]
    assert pendientes[0]["doctor"] == "Dr. Cobrador"
    assert admin.post(f"{base}/pagar").json()["estado"] == "cobrada"
    # Y deja de figurar como pendiente de pago.
    assert admin.get(f"/api/companies/{cid}/portal/honorarios-a-pagar").json() == []


def test_un_profesional_no_ve_la_planilla_del_colega():
    """Cuánto cobra otro médico no es asunto suyo."""
    c = _clinica("Sanatorio Planillas Ajenas")
    cid = c["id"]
    ana = _doctor(cid, "Dra. Ana Planilla")
    beto = _doctor(cid, "Dr. Beto Planilla")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, ana["id"], "Paciente De Ana", 20, consulta)

    portal_ana = _acceso(cid, ana["id"], "ana.planilla@test.py")
    portal_beto = _acceso(cid, beto["id"], "beto.planilla@test.py")
    planilla = _armar(portal_ana, cid).json()[0]

    assert portal_beto.get(
        f"/api/companies/{cid}/portal/honorarios/{planilla['id']}"
    ).status_code == 404
    assert portal_beto.get(f"/api/companies/{cid}/portal/honorarios").json() == []


def test_los_montos_quedan_congelados_al_armar():
    """La planilla es un documento. Si mañana sube el precio del estudio o el
    convenio baja del 80% al 70%, lo que ya se armó no se mueve."""
    c = _clinica("Sanatorio Congelado")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Congelada")
    consulta = _servicio(cid, "Consulta", 100_000)
    seguro = _convenio(cid, "Prepaga Cambiante", pct=100)
    _atencion(cid, doc["id"], "Paciente Congelado", 22, consulta, seguro)

    portal = _acceso(cid, doc["id"], "congelada@test.py")
    planilla = _armar(portal, cid).json()[0]
    assert planilla["total_honorario_gs"] == 100_000

    db = SessionLocal()
    try:
        db.get(Service, consulta).price_gs = 500_000
        db.get(Insurer, seguro).coverage_pct = 10
        db.commit()
    finally:
        db.close()

    de_nuevo = portal.get(
        f"/api/companies/{cid}/portal/honorarios/{planilla['id']}"
    ).json()
    assert de_nuevo["total_honorario_gs"] == 100_000, "la planilla se movió sola"
    assert de_nuevo["items"][0]["facturado_gs"] == 100_000


def test_la_planilla_impresa_dice_lo_que_hay_que_firmar():
    c = _clinica("Sanatorio Impresión")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Imprimir")
    consulta = _servicio(cid, "Consulta clínica", 150_000)
    seguro = _convenio(cid, "Seguro Ñandutí", "Plan Oro", pct=80)
    _atencion(cid, doc["id"], "Marco Garcete", 24, consulta, seguro)

    portal = _acceso(cid, doc["id"], "imprimir@test.py")
    planilla = _armar(portal, cid).json()[0]
    texto = portal.get(
        f"/api/companies/{cid}/portal/honorarios/{planilla['id']}"
    ).json()["texto"]

    assert "PLANILLA DE HONORARIOS PROFESIONALES" in texto
    assert "Dra. Imprimir" in texto
    assert "Seguro Ñandutí Plan Oro" in texto
    assert "Marco Garcete" in texto
    assert "Firma y aclaración" in texto


def test_una_atencion_sin_servicio_no_desaparece():
    """Sin servicio cargado no hay precio, y sin precio no hay honorario. Se
    muestra en cero y se avisa: si desapareciera del listado, el profesional
    no se enteraría de que hay algo que arreglar."""
    c = _clinica("Sanatorio Sin Arancel")
    cid = c["id"]
    doc = _doctor(cid, "Dr. Sin Arancel")
    _atencion(cid, doc["id"], "Paciente Sin Estudio", 26, service_id=None)

    portal = _acceso(cid, doc["id"], "sinarancel@test.py")
    datos = _preview(portal, cid)
    assert datos["atenciones"] == 1
    assert datos["sin_arancel"] == 1
    assert datos["total_honorario_gs"] == 0


def test_el_periodo_tiene_que_tener_sentido():
    c = _clinica("Sanatorio Fechas")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Fechas")
    portal = _acceso(cid, doc["id"], "fechas@test.py")
    base = f"/api/companies/{cid}/portal/honorarios/preview"

    assert portal.get(base, params={"desde": "2026-07-31", "hasta": "2026-07-01"}).status_code == 422
    assert portal.get(base, params={"desde": "ayer", "hasta": "hoy"}).status_code == 422
    assert portal.get(base, params={"desde": "2020-01-01", "hasta": "2026-07-01"}).status_code == 422


def test_el_ultimo_dia_del_periodo_entra_entero():
    """Comparando contra las 00:00 del último día, la jornada entera del 31 se
    perdía de cada planilla."""
    c = _clinica("Sanatorio Último Día")
    cid = c["id"]
    doc = _doctor(cid, "Dr. Último Día")
    consulta = _servicio(cid, "Consulta", 100_000)
    _atencion(cid, doc["id"], "Paciente Del 31", 31, consulta)

    portal = _acceso(cid, doc["id"], "ultimodia@test.py")
    assert _preview(portal, cid)["atenciones"] == 1


def test_los_honorarios_son_del_bloque_4():
    c = _create_company(name="Clínica Sin Honorarios")
    r = client.get(f"/api/companies/{c['id']}/portal/honorarios",
                   params={"desde": DESDE.isoformat(), "hasta": HASTA.isoformat()})
    assert r.status_code == 402
    assert r.json()["detail"]["bloque"] == "practitioner"


def test_el_copago_no_se_le_factura_a_la_aseguradora():
    """El copago lo paga el paciente en caja. Facturárselo a la aseguradora
    además de su parte es pedirle de más y que rechace la planilla."""
    c = _clinica("Sanatorio Copago")
    cid = c["id"]
    doc = _doctor(cid, "Dra. Copago")
    consulta = _servicio(cid, "Consulta", 100_000)
    seguro = _convenio(cid, "Prepaga Copago", pct=70, copago=15_000)
    _atencion(cid, doc["id"], "Paciente Copago", 28, consulta, seguro)

    portal = _acceso(cid, doc["id"], "copago@test.py")
    grupo = _preview(portal, cid)["grupos"][0]
    assert grupo["total_facturado_gs"] == 70_000
    item = grupo["items"][0]
    assert item["paga_el_paciente_gs"] == 30_000 + 15_000
