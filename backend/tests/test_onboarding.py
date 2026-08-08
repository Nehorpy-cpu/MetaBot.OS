"""Tests del onboarding inteligente y del Optimizador de Prompts (LLM mockeado)."""
import json

from tests.test_api import SWARM_SLUGS, _create_company, client

from app import onboarding, swarm

FAKE_PROFILE = {
    "industry": "Ferretería y materiales de construcción",
    "vertical": "retail",
    "niche": "Ferretería de barrio con delivery",
    "products": ["herramientas", "pinturas", "materiales eléctricos"],
    "audience": "constructores y hogares de Asunción",
    "tone_notes": "práctico y directo",
    "agents": {
        slug: (
            f"Sos el agente {slug} de la Ferretería El Tornillo en Asunción. Atendés en voseo "
            "paraguayo con precios en Guaraníes (₲) y puntos de miles. Conocés el catálogo de "
            "herramientas, pinturas y materiales eléctricos, coordinás delivery y nunca inventás "
            "datos: cuando no sabés algo, escalás a un humano del equipo."
        )
        for slug in SWARM_SLUGS
    },
}


def test_smart_onboarding_creates_custom_swarm(monkeypatch):
    async def fake_complete(messages, **kwargs):
        assert "Ferretería El Tornillo" in messages[-1]["content"]
        return json.dumps(FAKE_PROFILE, ensure_ascii=False)

    monkeypatch.setattr(onboarding, "complete", fake_complete)
    resp = client.post(
        "/api/companies/smart",
        json={"name": "Ferretería El Tornillo", "description": "Venta de herramientas, pinturas y materiales, con delivery en Asunción"},
    )
    assert resp.status_code == 201
    company = resp.json()
    assert company["vertical"] == "retail"
    assert company["industry"].startswith("Ferretería")

    agents = client.get(f"/api/companies/{company['id']}/agents").json()
    assert {a["slug"] for a in agents} == SWARM_SLUGS
    # Los prompts son a medida, no de plantilla
    detail = client.get(f"/api/agents/{agents[0]['id']}").json()
    assert "El Tornillo" in detail["system_prompt"]


def test_smart_onboarding_invalid_profile_rejected(monkeypatch):
    async def fake_complete(messages, **kwargs):
        return "esto no es un perfil"

    monkeypatch.setattr(onboarding, "complete", fake_complete)
    resp = client.post(
        "/api/companies/smart",
        json={"name": "Negocio X", "description": "descripción suficientemente larga"},
    )
    assert resp.status_code == 502


def test_optimizer_suggests_and_apply_flow(monkeypatch):
    company = _create_company(name="Clínica Optim")
    cid = company["id"]

    # Sembrar evidencia: conversación con respuestas del bot
    async def fake_chat(messages, **kwargs):
        return {"content": "Respuesta robótica sin voseo. Consulte nuestros servicios."}

    monkeypatch.setattr("app.chat.chat_raw", fake_chat)
    for i in range(4):
        client.post(
            f"/api/companies/{cid}/chat",
            json={"contact_phone": f"+59597100000{i}", "text": f"Consulta {i} sobre turnos"},
        )

    async def fake_complete(messages, **kwargs):
        assert "SALIDAS REALES RECIENTES" in messages[-1]["content"]
        return json.dumps(
            {
                "improved_prompt": "Atendés pacientes por WhatsApp en voseo paraguayo, cálido y breve. Nunca des diagnósticos: ofrecé agendar turno. Precios en Guaraníes (₲).",
                "rationale": "Las respuestas reales usan usted y suenan robóticas; el prompt debe reforzar el voseo.",
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{cid}/prompt-suggestions/run")
    assert resp.json()["new_suggestions"] >= 1

    suggestions = client.get(f"/api/companies/{cid}/prompt-suggestions").json()
    cx_sugg = next(s for s in suggestions if "CX" in s["agent_name"])
    assert cx_sugg["status"] == "pending"
    assert "voseo" in cx_sugg["rationale"]

    # Segunda corrida: no duplica sugerencias pendientes del mismo agente
    resp2 = client.post(f"/api/companies/{cid}/prompt-suggestions/run")
    assert resp2.json()["new_suggestions"] == 0

    # Aplicar cambia el prompt real del agente
    apply = client.post(f"/api/companies/{cid}/prompt-suggestions/{cx_sugg['id']}/apply")
    assert apply.status_code == 200
    detail = client.get(f"/api/agents/{cx_sugg['agent_id']}").json()
    assert detail["system_prompt"].startswith("Atendés pacientes por WhatsApp en voseo")

    # No se puede aplicar dos veces
    again = client.post(f"/api/companies/{cid}/prompt-suggestions/{cx_sugg['id']}/apply")
    assert again.status_code == 409


def test_optimizer_no_evidence_no_suggestions(monkeypatch):
    company = _create_company(name="Clínica Vacía")

    async def fake_complete(messages, **kwargs):
        raise AssertionError("no debería llamarse al LLM sin evidencia")

    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{company['id']}/prompt-suggestions/run")
    assert resp.json()["new_suggestions"] == 0


def test_optimizer_empty_improvement_ignored(monkeypatch):
    company = _create_company(name="Clínica Óptima")
    cid = company["id"]

    async def fake_chat(messages, **kwargs):
        return {"content": "¡Hola! ¿Todo bien? Te agendo un turno, contame tu horario preferido."}

    monkeypatch.setattr("app.chat.chat_raw", fake_chat)
    for i in range(4):
        client.post(
            f"/api/companies/{cid}/chat",
            json={"contact_phone": f"+59597200000{i}", "text": f"Mensaje {i} de prueba"},
        )

    async def fake_complete(messages, **kwargs):
        return '{"improved_prompt": ""}'

    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{cid}/prompt-suggestions/run")
    assert resp.json()["new_suggestions"] == 0
