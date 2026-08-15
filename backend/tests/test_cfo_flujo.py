"""CFO — Fase 4: el flujo por WhatsApp, sin salir de WhatsApp.

Lo que se prueba: cuando el bot pide el PIN y el dueño lo escribe, ese PIN
NO queda en la base, NO viaja al modelo, y la consulta que quedó pendiente se
resuelve sola. Sin esto, el PIN termina escrito en el historial de un
teléfono que se puede perder y la persona tiene que repetir la pregunta.
"""
import asyncio
from datetime import datetime

import pytest

from tests.test_api import _create_company, client  # noqa: I001

from app import cfo
from app.chat import handle_incoming
from app.db import SessionLocal
from app.models import (
    Appointment, Company, Conversation, FinanceSession, Message, Service,
)

FINANZAS = ["finance", "booking"]
TELEFONO = "595981700001"


def _armar(nombre: str, pin="4721", sensibilidad="alta", precio=250_000):
    """Empresa con datos, métricas aprobadas y un dueño autorizado con PIN."""
    c = _create_company(name=nombre, packs=FINANZAS)
    cid = c["id"]
    db = SessionLocal()
    try:
        s = Service(company_id=cid, name="Consulta", price_gs=precio, active=True)
        db.add(s)
        db.commit()
        svc = s.id
    finally:
        db.close()
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. X"}).json()["id"]
    db = SessionLocal()
    try:
        db.add(Appointment(
            company_id=cid, doctor_id=doc, patient_name="Paciente",
            patient_phone="595981000000", scheduled_at=datetime(2026, 7, 10, 10, 0),
            service_id=svc, status="attended",
        ))
        db.commit()
    finally:
        db.close()
    for clave in ("ventas_netas", "margen_bruto"):
        client.post(f"/api/companies/{cid}/cfo/metricas/{clave}/aprobar",
                    json={"version": 1})
    ident = client.post(f"/api/companies/{cid}/cfo/identidades",
                        json={"phone": TELEFONO, "nombre": "Dueño",
                              "sensibilidad_max": sensibilidad}).json()
    client.put(f"/api/companies/{cid}/cfo/identidades/{ident['id']}/pin",
               json={"pin": pin})
    return cid


def _escribir(cid: int, texto: str, telefono=TELEFONO):
    db = SessionLocal()
    try:
        # `asyncio.run` y no `get_event_loop()`: el segundo devuelve el bucle
        # que haya quedado dando vueltas, y si otro archivo de pruebas corrio
        # antes una prueba async, ese bucle ya esta cerrado. Falla por el orden
        # alfabetico de los archivos, que es la peor forma de fallar.
        return asyncio.run(
            handle_incoming(db, db.get(Company, cid), telefono, texto,
                            channel="whatsapp")
        )
    finally:
        db.close()


def _mensajes(cid: int, telefono=TELEFONO):
    db = SessionLocal()
    try:
        conv = (
            db.query(Conversation)
            .filter(Conversation.company_id == cid,
                    Conversation.contact_phone == telefono)
            .first()
        )
        if not conv:
            return []
        return [
            (m.direction, m.body)
            for m in db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.id)
            .all()
        ]
    finally:
        db.close()


@pytest.fixture(autouse=True)
def _sin_modelo(monkeypatch):
    """Nada de este archivo depende de lo que conteste un modelo.

    Todas las pruebas de acá mandan cuatro cifras y verifican el camino
    DETERMINISTICO del PIN, que el servidor resuelve sin pasar por ninguna IA.
    El modelo solo aparece cuando el PIN no corresponde y el mensaje sigue de
    largo como conversacion comun — y ahi su respuesta da igual.

    Sin este parche, dos pruebas fallaban por la cuota diaria agotada de un
    proveedor gratuito. Una prueba que se cae porque a un tercero se le acabo
    el cupo no esta probando nuestro codigo.
    """
    async def _sin_llamar(*args, **kwargs):
        return {"role": "assistant", "content": "Listo.",
                "_modelo_usado": "prueba", "_proveedor_usado": "prueba"}

    monkeypatch.setattr("app.chat.chat_raw", _sin_llamar)


def _dejar_pendiente(cid: int, metrica="margen_bruto", telefono=TELEFONO):
    """Simula que el bot ya pidió el PIN para esa consulta."""
    db = SessionLocal()
    try:
        cfo.pedir_pin(db, cid, telefono, metrica,
                      datetime(2026, 7, 1).date(), datetime(2026, 7, 31).date())
    finally:
        db.close()


# ─── El PIN no queda escrito ─────────────────────────────────────────────


def test_el_pin_se_guarda_tachado_y_no_en_claro():
    """LA razón de existir de esta fase. El PIN escrito en el chat queda en
    `messages` y viaja al modelo: es una credencial en un teléfono que se
    puede perder."""
    cid = _armar("CFO PIN Tachado")
    _dejar_pendiente(cid)
    _escribir(cid, "4721")

    guardados = _mensajes(cid)
    entrantes = [b for d, b in guardados if d == "in"]
    assert cfo.PIN_TACHADO in entrantes
    assert "4721" not in " ".join(entrantes), "el PIN quedó escrito en la base"
    # Y tampoco en la respuesta.
    assert "4721" not in " ".join(b for d, b in guardados if d == "out")


def test_con_el_pin_correcto_se_resuelve_la_consulta_pendiente(monkeypatch):
    """El camino feliz completo: PIN correcto y el número sale.

    Hoy no hay ninguna métrica que sea sensible Y calculable a la vez —las
    dos que se calculan salen de atenciones y son de riesgo bajo—, así que
    para ejercitar el flujo entero se sube el riesgo de `ventas_netas`. El
    día que haya una fuente de caja conectada, este caso pasa a ser real.
    """
    monkeypatch.setitem(cfo.RIESGO_POR_METRICA, "ventas_netas", cfo.Riesgo.MEDIA)
    cid = _armar("CFO Retoma Consulta")
    _dejar_pendiente(cid, "ventas_netas")
    r = _escribir(cid, "4721")
    assert "Ventas netas" in r["reply"]
    assert "₲ 250.000" in r["reply"]
    # Y avisa de dónde salió y hasta cuándo está actualizado.
    assert "⚠" in r["reply"] and "Datos al" in r["reply"]
    # El PIN no aparece por ningún lado.
    assert "4721" not in r["reply"]


def test_el_pin_equivocado_no_borra_la_consulta():
    """Para que la persona pueda reintentar sin volver a escribir todo."""
    cid = _armar("CFO PIN Equivocado")
    # `margen_bruto` es de riesgo medio: ahí el PIN SÍ se valida.
    _dejar_pendiente(cid, "margen_bruto")
    r = _escribir(cid, "0000")
    assert "no es correcto" in r["reply"].lower()

    db = SessionLocal()
    try:
        assert cfo.consulta_pendiente(db, cid, TELEFONO) is not None
    finally:
        db.close()

    r2 = _escribir(cid, "4721")
    # Con el PIN correcto retoma la consulta. `margen_bruto` no se puede
    # calcular todavía —falta la fuente de compras— y lo dice.
    assert "margen bruto" in r2["reply"].lower()


def test_un_numero_suelto_sin_consulta_pendiente_no_se_tacha():
    """Si no se estaba esperando un PIN, "4721" es un mensaje cualquiera y
    tacharlo dejaría la conversación con un hueco inexplicable."""
    cid = _armar("CFO Número Suelto")
    _escribir(cid, "4721")
    entrantes = [b for d, b in _mensajes(cid) if d == "in"]
    assert "4721" in entrantes
    assert cfo.PIN_TACHADO not in entrantes


def test_la_espera_del_pin_vence():
    """Una espera que no vence convierte cualquier número de cuatro cifras
    que la persona escriba mañana en un intento de PIN."""
    cid = _armar("CFO Espera Vence")
    _dejar_pendiente(cid)
    db = SessionLocal()
    try:
        fila = (
            db.query(FinanceSession)
            .filter(FinanceSession.company_id == cid)
            .first()
        )
        fila.pin_pedido_hasta = datetime.utcnow().replace(microsecond=0)
        fila.pin_pedido_hasta = fila.pin_pedido_hasta.replace(
            year=fila.pin_pedido_hasta.year - 1)
        db.commit()
    finally:
        db.close()

    _escribir(cid, "4721")
    entrantes = [b for d, b in _mensajes(cid) if d == "in"]
    assert "4721" in entrantes, "trató como PIN un pedido que ya venció"


def test_no_se_abre_un_pedido_de_pin_para_algo_que_no_lo_necesita():
    """Un pedido abierto para una consulta de riesgo bajo se traga cualquier
    número de cuatro cifras que la persona escriba después, y encima nunca lo
    valida: la respuesta salía igual con el PIN equivocado."""
    cid = _armar("CFO Pendiente Innecesaria")
    db = SessionLocal()
    try:
        assert cfo.pedir_pin(db, cid, TELEFONO, "ventas_netas") is False
        assert cfo.consulta_pendiente(db, cid, TELEFONO) is None
        assert cfo.pedir_pin(db, cid, TELEFONO, "margen_bruto") is True
        assert cfo.consulta_pendiente(db, cid, TELEFONO) is not None
    finally:
        db.close()


def test_el_pin_dentro_de_una_frase_no_se_tacha_a_medias():
    """"el pin es 4721" no se tacha: tacharlo a medias da una falsa sensación
    de que se cuidó. Se prefiere no reconocerlo como PIN."""
    assert cfo.es_pin("4721")
    assert not cfo.es_pin("el pin es 4721")
    assert not cfo.es_pin("123")
    assert not cfo.es_pin("")


# ─── El aislamiento sigue en pie ─────────────────────────────────────────


def test_el_pin_de_una_empresa_no_sirve_en_la_otra():
    a = _armar("CFO Aislamiento A", pin="1111")
    b = _armar("CFO Aislamiento B", pin="2222")
    _dejar_pendiente(b, "margen_bruto")
    r = _escribir(b, "1111")
    assert "no es correcto" in r["reply"].lower()


def test_un_numero_no_autorizado_no_abre_una_consulta_pendiente():
    cid = _armar("CFO Pendiente Ajena")
    db = SessionLocal()
    try:
        # Nadie pidió PIN para este número.
        assert cfo.consulta_pendiente(db, cid, "595999000111") is None
    finally:
        db.close()
    _escribir(cid, "4721", telefono="595999000111")
    entrantes = [b for d, b in _mensajes(cid, "595999000111") if d == "in"]
    assert "4721" in entrantes


def test_una_empresa_sin_el_bloque_no_intercepta_nada():
    """El atajo del PIN es del bloque financiero. Una clínica que escribe
    "4721" no tiene por qué ver su mensaje tachado."""
    c = _create_company(name="Clínica Sin CFO Flujo")
    _escribir(c["id"], "4721", telefono="595981700099")
    entrantes = [b for d, b in _mensajes(c["id"], "595981700099") if d == "in"]
    assert "4721" in entrantes
