"""Supervisión del CEO: corre DESPUÉS del CX, y solo cuando el turno salió mal.

Lo que estos tests protegen, en orden de importancia:
1. Con `supervision="off"` (el default) el comportamiento no cambia en nada.
2. El supervisor nunca puede inventar datos ni entrar en bucle.
3. En modo shadow no toca jamás la respuesta que recibe el cliente.
"""
import json

import pytest
from tests.test_api import _create_company, client, db_module

from app import chat as chat_engine
from app import job_handlers, jobs
from app import packs as packs_module
from app import supervisor
from app.models import Agent, Company, Conversation, Job, Supervision


def _mock_llm(responses):
    calls = []

    async def fake_chat_raw(messages, **kwargs):
        calls.append({"messages": list(messages), "kwargs": kwargs})
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return fake_chat_raw, calls


def _empresa(**kwargs) -> Company:
    """Una empresa desprendida de la base, para probar `detect` sin I/O."""
    return Company(id=1, name="X", vertical="medical", packs="commerce,booking", **kwargs)


# --------------------------------------------------------------------------
# 1. El default no cambia nada
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_supervision_off_no_llama_al_modelo(monkeypatch):
    """Con supervisión apagada, `review` sale sin tocar la base ni el modelo."""
    llamadas = []

    async def explota(*args, **kwargs):
        llamadas.append(1)
        raise AssertionError("no debe llamarse al modelo con supervision=off")

    monkeypatch.setattr(supervisor, "chat_raw", explota)
    resultado = await supervisor.review(
        None, _empresa(supervision="off"), None,
        cliente="hola", respuesta="", actions=[],
        turnos_cliente=99, rondas_agotadas=True,
    )
    assert resultado == {"reply": None, "escalate": False, "trigger": "", "action": "keep"}
    assert not llamadas


def test_empresa_nueva_nace_apagada():
    company = _create_company(name="Empresa Default")
    db = db_module.SessionLocal()
    try:
        assert db.get(Company, company["id"]).supervision == "off"
    finally:
        db.close()


def test_flujo_completo_con_supervision_off_es_identico(monkeypatch):
    """El turno entero con el default produce exactamente una llamada al
    modelo: la del CX. Si el supervisor se colara, habría dos."""
    company = _create_company(name="Clínica Sin Supervisión")
    fake, calls = _mock_llm([{"content": "Perdoná, ¿me repetís eso último?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    monkeypatch.setattr(supervisor, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{company['id']}/chat",
        json={"contact_phone": "+595971000001", "text": "hola"},
    )
    assert resp.status_code == 200
    assert resp.json()["supervision"] is None
    assert len(calls) == 1, "el default no debe agregar ninguna llamada al modelo"


# --------------------------------------------------------------------------
# 2. Disparadores: determinísticos, gratis y sobre herramientas, no rubros
# --------------------------------------------------------------------------

def test_no_dispara_cuando_el_turno_salio_bien():
    t = supervisor.detect(
        _empresa(),
        actions=[{"tool": "search_catalog", "result": {"products": [{"name": "X"}], "exact_match": True}}],
        reply_text="Tenemos el Good Girl a ₲ 130.000. ¿Te lo reservo?",
        turnos_cliente=2,
        rondas_agotadas=False,
    )
    assert t is None


def test_catalogo_sin_resultados_dispara():
    t = supervisor.detect(
        _empresa(),
        actions=[{"tool": "search_catalog", "result": {"products": [], "note": "Sin coincidencias."}}],
        reply_text="No encontré nada.",
        turnos_cliente=1,
        rondas_agotadas=False,
    )
    assert t and t.key == "catalog_miss"


def test_choque_de_agenda_dispara():
    t = supervisor.detect(
        _empresa(),
        actions=[{"tool": "book_appointment", "result": {"error": "Ese horario se solapa con otra cita (10:00)."}}],
        reply_text="Ese horario no está libre.",
        turnos_cliente=3,
        rondas_agotadas=False,
    )
    assert t and t.key == "booking_clash"


def test_respuesta_vacia_o_de_relleno_dispara():
    t = supervisor.detect(
        _empresa(), actions=[], reply_text="Perdoná, ¿me repetís eso último?",
        turnos_cliente=1, rondas_agotadas=False,
    )
    assert t and t.key == "dead_end"


def test_rondas_agotadas_dispara():
    t = supervisor.detect(
        _empresa(), actions=[], reply_text="Dejame ver eso.",
        turnos_cliente=1, rondas_agotadas=True,
    )
    assert t and t.key == "dead_end"


def test_venta_estancada_dispara_una_sola_vez():
    """En el turno del umbral, sí; en los siguientes, no.

    Si se disparara en cada turno a partir del sexto, el disparador menos
    grave se comería el presupuesto de la conversación y dejaría sin cupo a
    un riesgo clínico posterior.
    """
    umbral = supervisor.STALL_TURNOS
    justo = supervisor.detect(_empresa(), actions=[], reply_text="Claro, contame.",
                              turnos_cliente=umbral, rondas_agotadas=False)
    assert justo and justo.key == "stalled_sale"

    for despues in range(umbral + 1, umbral + 6):
        assert supervisor.detect(_empresa(), actions=[], reply_text="Claro, contame.",
                                 turnos_cliente=despues, rondas_agotadas=False) is None


def test_no_dispara_si_la_conversacion_ya_cerro():
    cerrada = supervisor.detect(
        _empresa(),
        actions=[{"tool": "book_appointment", "result": {"ok": True}}],
        reply_text="Listo, te agendé.",
        turnos_cliente=supervisor.STALL_TURNOS,
        rondas_agotadas=False,
    )
    assert cerrada is None


def test_venta_estancada_exige_herramientas_de_venta():
    """El disparador se expresa sobre HERRAMIENTAS, no sobre el rubro.

    Una empresa sin packs que vendan (soporte puro) no tiene venta que
    estancar. Ojo: `packs=""` NO es ese caso — `active_packs` cae al vertical
    y toda empresa termina con commerce; hay que anular las herramientas.
    """
    soporte = Company(id=2, name="Mesa de ayuda", vertical="other", packs="ninguno")
    assert not packs_module.tools_for(soporte)
    assert supervisor.detect(soporte, actions=[], reply_text="Claro, contame.",
                             turnos_cliente=supervisor.STALL_TURNOS,
                             rondas_agotadas=False) is None


def test_riesgo_clinico_solo_con_pack_healthcare():
    receta = "Tomá 500 mg de paracetamol cada 8 horas."
    clinica = supervisor.detect(
        Company(id=3, name="Sanatorio", vertical="medical", packs="booking,healthcare"),
        actions=[], reply_text=receta, turnos_cliente=1, rondas_agotadas=False,
    )
    assert clinica and clinica.key == "compliance_risk"

    perfumeria = supervisor.detect(
        Company(id=4, name="Perfumería", vertical="retail", packs="commerce"),
        actions=[], reply_text=receta, turnos_cliente=1, rondas_agotadas=False,
    )
    # La misma frase en una perfumería no es riesgo clínico: el disparador
    # mira el PACK, no el rubro escrito a mano.
    assert perfumeria is None or perfumeria.key != "compliance_risk"


def test_solo_dispara_uno_y_gana_el_mas_grave():
    """Un turno puede salir mal de varias formas; supervisar dos veces gasta
    el doble sin valer el doble."""
    t = supervisor.detect(
        Company(id=5, name="Sanatorio", vertical="medical", packs="booking,healthcare"),
        actions=[
            {"tool": "search_catalog", "result": {"products": []}},
            {"tool": "escalate_to_human", "result": {"ok": True}},
        ],
        reply_text="Tomá 500 mg cada 8 horas.",
        turnos_cliente=9,
        rondas_agotadas=True,
    )
    assert t.key == "compliance_risk"  # prioridad 100


def test_detectar_es_instantaneo():
    """Corre en el camino del cliente: no puede costar nada."""
    import time

    company = _empresa()
    acciones = [{"tool": "search_catalog", "result": {"products": [], "note": "x"}}]
    t0 = time.perf_counter()
    for _ in range(1000):
        supervisor.detect(company, actions=acciones, reply_text="No encontré nada.",
                          turnos_cliente=2, rondas_agotadas=False)
    assert time.perf_counter() - t0 < 0.5


# --------------------------------------------------------------------------
# 3. Puertas antes de gastar una llamada
# --------------------------------------------------------------------------

def test_conversacion_ya_escalada_no_se_supervisa():
    db = db_module.SessionLocal()
    try:
        company = Company(name="Z", vertical="medical", packs="booking", supervision="inline")
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+1", status="needs_human")
        db.add(conv)
        db.commit()
        ok, _, motivo = supervisor.should_supervise(
            db, company, conv, supervisor._POR_KEY["dead_end"]
        )
        assert not ok and "escalada" in motivo
    finally:
        db.close()


def test_pausar_el_agente_en_el_panel_apaga_la_supervision():
    db = db_module.SessionLocal()
    try:
        company = Company(name="Kill Switch", vertical="medical", packs="booking", supervision="inline")
        db.add(company)
        db.flush()
        db.add(Agent(company_id=company.id, slug="ceo", name="CEO", role="r",
                     model="m", system_prompt="p", active=False))
        conv = Conversation(company_id=company.id, contact_phone="+2")
        db.add(conv)
        db.commit()
        ok, _, motivo = supervisor.should_supervise(
            db, company, conv, supervisor._POR_KEY["dead_end"]
        )
        assert not ok and "pausado" in motivo
    finally:
        db.close()


def test_presupuesto_por_conversacion():
    db = db_module.SessionLocal()
    try:
        company = Company(name="Presupuesto", vertical="medical", packs="booking", supervision="shadow")
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+3")
        db.add(conv)
        db.flush()
        for _ in range(supervisor.MAX_POR_CONVERSACION):
            db.add(Supervision(company_id=company.id, conversation_id=conv.id,
                               trigger_key="dead_end", agent_slug="ceo", mode="shadow"))
        db.commit()
        ok, _, motivo = supervisor.should_supervise(
            db, company, conv, supervisor._POR_KEY["dead_end"]
        )
        assert not ok and "conversación" in motivo
    finally:
        db.close()


def test_empresa_en_shadow_degrada_un_disparador_inline():
    db = db_module.SessionLocal()
    try:
        company = Company(name="Degrada", vertical="medical", packs="booking", supervision="shadow")
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+4")
        db.add(conv)
        db.commit()
        ok, modo, motivo = supervisor.should_supervise(
            db, company, conv, supervisor._POR_KEY["compliance_risk"]  # pide inline
        )
        assert ok and modo == "shadow" and motivo
    finally:
        db.close()


def test_el_brazo_es_estable_y_reproducible():
    """Una conversación no puede ver un turno supervisado y el siguiente no."""
    assert all(supervisor.arm_for(7, 100) == "supervised" for _ in range(5))
    assert supervisor.arm_for(7, 0) == "control"
    primera = supervisor.arm_for(12345, 50)
    assert all(supervisor.arm_for(12345, 50) == primera for _ in range(20))
    # Con 50% ambos brazos existen sobre una población de conversaciones
    brazos = {supervisor.arm_for(i, 50) for i in range(1, 200)}
    assert brazos == {"supervised", "control"}


# --------------------------------------------------------------------------
# 4. El veredicto: todo lo que no se puede validar termina en "keep"
# --------------------------------------------------------------------------

def test_veredicto_sin_json_no_toca_nada():
    v = supervisor._parse_veredicto("me parece que está bien", "respuesta cx", "{}")
    assert v["action"] == "keep"
    # El motivo guarda lo que el modelo sí dijo: si no, el fallo es invisible.
    assert "me parece que está bien" in v["reason"]


def test_ignora_el_razonamiento_en_voz_alta():
    """Regresión de producción: el CEO corría con un modelo de razonamiento y
    su bloque <think> tapaba el veredicto."""
    crudo = (
        "<think>El cliente pidió algo fuera de presupuesto. Podría {sugerir} otra "
        "cosa. Veamos {opciones}.</think>\n"
        '{"action": "directive", "directive": "Ofrecé una alternativa concreta.", "reason": "x"}'
    )
    v = supervisor._parse_veredicto(crudo, "cx", "{}")
    assert v["action"] == "directive"
    assert v["directive"] == "Ofrecé una alternativa concreta."


def test_razonamiento_sin_cerrar_no_rompe():
    v = supervisor._parse_veredicto("<think>pensando {algo} y me quedé sin tokens", "cx", "{}")
    assert v["action"] == "keep"


def test_el_supervisor_no_usa_el_modelo_del_agente_que_supervisa():
    """El auditor con el mismo modelo que el productor se auto-aprueba."""
    cx = Agent(slug="cx", name="CX", role="r", model="modelo-a", system_prompt="p")
    mismo = Agent(slug="ceo", name="CEO", role="r", model="modelo-a", system_prompt="p")
    distinto = Agent(slug="ceo", name="CEO", role="r", model="modelo-b", system_prompt="p")
    empresa = _empresa()

    assert supervisor.modelo_para(empresa, mismo, cx) != "modelo-a"
    assert supervisor.modelo_para(empresa, distinto, cx) == "modelo-b"
    # Sin agente configurado también hay que elegir alguno.
    assert supervisor.modelo_para(empresa, None, cx)


def test_accion_desconocida_no_toca_nada():
    v = supervisor._parse_veredicto('{"action": "borrar_todo", "reply": "x"}', "cx", "{}")
    assert v["action"] == "keep"


def test_rewrite_sin_texto_no_toca_nada():
    v = supervisor._parse_veredicto('{"action": "rewrite", "reply": ""}', "cx", "{}")
    assert v["action"] == "keep"
    assert "reply" not in v


def test_no_puede_inventar_precios():
    """El supervisor redacta mejor, pero no trae un precio de la nada."""
    v = supervisor._parse_veredicto(
        '{"action": "rewrite", "reply": "Te lo dejo a ₲ 95.000 con envío gratis"}',
        respuesta_cx="El Good Girl está ₲ 130.000.",
        fuentes='[{"products": [{"price": "₲ 130.000"}]}]',
    )
    assert v["action"] == "keep"
    assert "inventadas" in v["reason"]


def test_rewrite_con_cifras_del_material_pasa():
    v = supervisor._parse_veredicto(
        '{"action": "rewrite", "reply": "El Good Girl está ₲ 130.000 y tengo stock. ¿Te lo reservo?"}',
        respuesta_cx="Good Girl: 130.000.",
        fuentes='[{"products": [{"price_gs": 130000}]}]',
    )
    assert v["action"] == "rewrite"
    assert "130.000" in v["reply"]


def test_cifras_chicas_no_cuentan_como_dato_duro():
    v = supervisor._parse_veredicto(
        '{"action": "rewrite", "reply": "Te paso 2 opciones y elegís 1."}',
        respuesta_cx="Hay varias opciones.", fuentes="{}",
    )
    assert v["action"] == "rewrite"


def test_el_veredicto_no_puede_traer_sintaxis_de_herramienta():
    v = supervisor._parse_veredicto(
        '{"action": "rewrite", "reply": "Te derivo <escalate_to_human> {\\"motivo\\": \\"x\\"}"}',
        respuesta_cx="cx", fuentes="{}",
    )
    assert "escalate_to_human" not in v.get("reply", "")


def test_respuesta_larguisima_se_recorta():
    largo = "palabra " * 500
    v = supervisor._parse_veredicto(
        json.dumps({"action": "rewrite", "reply": largo}), "cx", "{}"
    )
    assert len(v["reply"]) <= supervisor.MAX_REPLY_CHARS + 1


# --------------------------------------------------------------------------
# 5. Shadow nunca toca al cliente; inline sí
# --------------------------------------------------------------------------

@pytest.mark.anyio
async def test_shadow_no_hace_esperar_al_cliente(monkeypatch):
    """El modo shadow ENCOLA: no llama al modelo dentro del turno.

    Regresión de producción: revisando en línea, shadow le agregaba ~36 s a
    una respuesta que —por definición— la revisión no puede cambiar, porque
    ya se envió.
    """
    db = db_module.SessionLocal()
    try:
        company = Company(name="Shadow SA", vertical="retail", packs="commerce",
                          supervision="shadow", supervision_pct=100)
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+595971000009")
        db.add(conv)
        db.commit()

        async def explota(*args, **kwargs):
            raise AssertionError("shadow no puede llamar al modelo dentro del turno")

        monkeypatch.setattr(supervisor, "chat_raw", explota)
        r = await supervisor.review(
            db, company, conv,
            cliente="busco un perfume", respuesta="No encontré nada.",
            actions=[{"tool": "search_catalog", "result": {"products": []}}],
            turnos_cliente=1, rondas_agotadas=False,
        )
        assert r["reply"] is None and r["escalate"] is False
        assert r["action"] == "encolada"

        encolado = db.query(Job).filter(Job.kind == job_handlers.SUPERVISION_KIND).one()
        assert encolado.status == "pending"
        assert json.loads(encolado.payload)["conversation_id"] == conv.id
    finally:
        db.close()


@pytest.mark.anyio
async def test_el_trabajo_encolado_deja_la_directiva(monkeypatch):
    """Y cuando el trabajo corre —ya fuera del turno— sí produce el análisis."""
    db = db_module.SessionLocal()
    try:
        company = Company(name="Shadow Cola SA", vertical="retail", packs="commerce",
                          supervision="shadow", supervision_pct=100)
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+595971000019")
        db.add(conv)
        db.commit()

        async def nada(*args, **kwargs):
            return {"content": "{}"}

        monkeypatch.setattr(supervisor, "chat_raw", nada)
        await supervisor.review(
            db, company, conv,
            cliente="busco un perfume", respuesta="No encontré nada.",
            actions=[{"tool": "search_catalog", "result": {"products": []}}],
            turnos_cliente=1, rondas_agotadas=False,
        )

        fake, _ = _mock_llm([{"content": json.dumps({
            "action": "rewrite",
            "reply": "TEXTO NUEVO DEL SUPERVISOR",
            "directive": "Preguntá el presupuesto antes de recomendar.",
            "reason": "faltó calificar al cliente",
        })}])
        monkeypatch.setattr(supervisor, "chat_raw", fake)

        trabajo = (
            db.query(Job)
            .filter(Job.kind == job_handlers.SUPERVISION_KIND, Job.company_id == company.id)
            .one()
        )
        await jobs.run_job(db, trabajo)
        assert trabajo.status == "done"

        db.refresh(conv)
        assert conv.pending_directive.startswith("Preguntá el presupuesto")
        registro = db.query(Supervision).filter(Supervision.conversation_id == conv.id).one()
        assert registro.arm == "supervised"
        # Propuso reescribir, pero en shadow la respuesta ya se envió.
        assert registro.action == "keep"
        assert "shadow" in registro.downgraded
    finally:
        db.close()


def test_en_shadow_no_se_le_pide_una_reescritura_que_se_va_a_tirar():
    """Observado en producción: en shadow proponía `rewrite` —que shadow
    descarta— y no dejaba directiva, que era lo único aprovechable."""
    trigger = supervisor._POR_KEY["catalog_miss"]
    empresa = _empresa(industry="perfumería")

    shadow = supervisor._prompt(empresa, trigger, "hola", "no hay", [], "shadow")[0]["content"]
    assert "rewrite" not in shadow
    assert "YA SE ENVIÓ" in shadow

    inline = supervisor._prompt(empresa, trigger, "hola", "no hay", [], "inline")[0]["content"]
    assert "rewrite" in inline


def test_el_modo_del_disparador_es_un_techo():
    """Una empresa en `inline` no vuelve inline a todos los disparadores.

    Cada disparador declara hasta dónde puede llegar. `catalog_miss` se
    analiza en shadow aunque la empresa esté en inline: perder una venta no
    justifica el riesgo de reescribirle el mensaje al cliente.
    """
    db = db_module.SessionLocal()
    try:
        company = Company(name="Techo SA", vertical="retail", packs="commerce",
                          supervision="inline")
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+5")
        db.add(conv)
        db.commit()
        ok, modo, _ = supervisor.should_supervise(
            db, company, conv, supervisor._POR_KEY["catalog_miss"]
        )
        assert ok and modo == "shadow"
        ok2, modo2, _ = supervisor.should_supervise(
            db, company, conv, supervisor._POR_KEY["compliance_risk"]
        )
        assert ok2 and modo2 == "inline"
    finally:
        db.close()


@pytest.mark.anyio
async def test_inline_si_reescribe_el_mensaje_de_traspaso(monkeypatch):
    """Cuando el bot escala, lo último que lee el cliente importa mucho.

    Cubre además la excepción de la puerta `needs_human`: el CX marca la
    conversación como escalada DURANTE este turno, así que sin la excepción
    este disparador nunca podría correr.
    """
    db = db_module.SessionLocal()
    try:
        company = Company(name="Inline SA", vertical="retail", packs="commerce",
                          supervision="inline", supervision_pct=100)
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+595971000010",
                            status="needs_human")  # como lo deja escalate_to_human
        db.add(conv)
        db.commit()

        fake, calls = _mock_llm([{"content": json.dumps({
            "action": "rewrite",
            "reply": "Ya le paso tu caso a una compañera del equipo; te escribe en un rato.",
            "reason": "el traspaso quedaba frío",
        })}])
        monkeypatch.setattr(supervisor, "chat_raw", fake)

        r = await supervisor.review(
            db, company, conv,
            cliente="quiero hablar con alguien", respuesta="Derivado.",
            actions=[{"tool": "escalate_to_human", "result": {"ok": True}}],
            turnos_cliente=2, rondas_agotadas=False,
        )
        assert r["trigger"] == "escalation_requested"
        assert r["reply"].startswith("Ya le paso tu caso")
        # El supervisor es un asesor SIN herramientas: no puede reentrar.
        assert calls[0]["kwargs"].get("tools") is None
    finally:
        db.close()


@pytest.mark.anyio
async def test_si_el_supervisor_falla_el_cliente_igual_recibe_respuesta(monkeypatch):
    db = db_module.SessionLocal()
    try:
        company = Company(name="Falla SA", vertical="retail", packs="commerce",
                          supervision="inline", supervision_pct=100)
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+595971000011")
        db.add(conv)
        db.commit()

        async def revienta(*args, **kwargs):
            raise RuntimeError("proveedor caído")

        monkeypatch.setattr(supervisor, "chat_raw", revienta)
        # Disparador inline (se ejecuta dentro del turno): es el caso donde un
        # fallo del supervisor podría dejar al cliente sin respuesta.
        r = await supervisor.review(
            db, company, conv,
            cliente="quiero hablar con alguien", respuesta="Respuesta del CX.",
            actions=[{"tool": "escalate_to_human", "result": {"ok": True}}],
            turnos_cliente=1, rondas_agotadas=False,
        )
        assert r["reply"] is None and r["escalate"] is False
    finally:
        db.close()


@pytest.mark.anyio
async def test_brazo_de_control_registra_pero_no_gasta(monkeypatch):
    db = db_module.SessionLocal()
    try:
        company = Company(name="Control SA", vertical="retail", packs="commerce",
                          supervision="inline", supervision_pct=0)
        db.add(company)
        db.flush()
        conv = Conversation(company_id=company.id, contact_phone="+595971000012")
        db.add(conv)
        db.commit()

        async def explota(*args, **kwargs):
            raise AssertionError("el brazo de control no llama al modelo")

        monkeypatch.setattr(supervisor, "chat_raw", explota)
        r = await supervisor.review(
            db, company, conv,
            cliente="hola", respuesta="Respuesta del CX.",
            actions=[{"tool": "search_catalog", "result": {"products": []}}],
            turnos_cliente=1, rondas_agotadas=False,
        )
        assert r["reply"] is None
        registro = db.query(Supervision).filter(Supervision.conversation_id == conv.id).one()
        assert registro.arm == "control"
    finally:
        db.close()


# --------------------------------------------------------------------------
# 6. Integración con el motor
# --------------------------------------------------------------------------

def test_la_directiva_llega_al_prompt_del_proximo_turno(monkeypatch):
    company = _create_company(name="Clínica Directiva")
    cid = company["id"]
    fake, calls = _mock_llm([{"content": "Buenas, ¿en qué te ayudo?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": "+595971000013", "text": "hola"})

    db = db_module.SessionLocal()
    try:
        conv = db.query(Conversation).filter(
            Conversation.company_id == cid, Conversation.contact_phone == "+595971000013"
        ).one()
        conv.pending_directive = "Preguntá el presupuesto antes de recomendar."
        db.commit()
    finally:
        db.close()

    fake2, calls2 = _mock_llm([{"content": "¿Qué presupuesto manejás?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake2)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": "+595971000013", "text": "busco algo"})
    assert "Preguntá el presupuesto" in calls2[0]["messages"][0]["content"]

    # Se consume: en el turno siguiente ya no está.
    fake3, calls3 = _mock_llm([{"content": "Dale."}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake3)
    client.post(f"/api/companies/{cid}/chat",
                json={"contact_phone": "+595971000013", "text": "unos 200 mil"})
    assert "Preguntá el presupuesto" not in calls3[0]["messages"][0]["content"]
