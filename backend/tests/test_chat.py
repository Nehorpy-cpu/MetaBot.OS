"""Tests del motor conversacional con LLM mockeado (sin red)."""
import json

from tests.test_api import _create_company, client  # reutiliza la app/DB de test

from app import chat as chat_engine


def _mock_llm(responses):
    """Crea un chat_raw falso que devuelve respuestas en orden y captura los
    mensajes que recibió."""
    calls = []

    async def fake_chat_raw(messages, **kwargs):
        calls.append({"messages": list(messages), "kwargs": kwargs})
        return responses[min(len(calls) - 1, len(responses) - 1)]

    return fake_chat_raw, calls


def test_simple_reply_and_memory(monkeypatch):
    company = _create_company(name="Clínica Chat")
    cid = company["id"]

    fake, calls = _mock_llm([{"content": "¡Hola! ¿Todo bien? ¿En qué te ayudo?"}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595971111111", "contact_name": "Ana", "text": "Hola"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["reply"].startswith("¡Hola!")

    # Segundo mensaje: el historial debe incluir el intercambio anterior
    fake2, calls2 = _mock_llm([{"content": "Claro, contame."}])
    monkeypatch.setattr(chat_engine, "chat_raw", fake2)
    client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595971111111", "text": "Quiero información"},
    )
    sent = calls2[0]["messages"]
    bodies = [m["content"] for m in sent if m["role"] in ("user", "assistant")]
    assert "Hola" in bodies
    assert "¡Hola! ¿Todo bien? ¿En qué te ayudo?" in bodies
    # El system prompt incluye contexto del negocio y reglas de estilo
    assert "Clínica Chat" in sent[0]["content"]
    assert "voseo" in sent[0]["content"].lower()

    # La conversación quedó persistida
    convs = client.get(f"/api/companies/{cid}/conversations").json()
    assert len(convs) == 1
    msgs = client.get(f"/api/companies/{cid}/conversations/{convs[0]['id']}/messages").json()
    assert len(msgs) == 4  # 2 entrantes + 2 salientes


def test_tool_call_books_real_appointment(monkeypatch):
    company = _create_company(name="Clínica Turnos")
    cid = company["id"]
    doc = client.post(
        f"/api/companies/{cid}/doctors", json={"name": "Dra. López", "specialty": "Clínica"}
    ).json()

    fake, calls = _mock_llm(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "function": {
                            "name": "book_appointment",
                            "arguments": json.dumps(
                                {
                                    "doctor_id": doc["id"],
                                    "patient_name": "Carlos Ruiz",
                                    "datetime_iso": "2026-08-12T10:00",
                                    "notes": "Consulta general",
                                }
                            ),
                        },
                    }
                ],
            },
            {"content": "¡Listo Carlos! Te agendé para el 12/08 a las 10:00 con la Dra. López."},
        ]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595972222222", "text": "Confirmo el turno del miércoles a las 10"},
    )
    data = resp.json()
    assert "agendé" in data["reply"]
    assert data["actions"][0]["tool"] == "book_appointment"
    assert data["actions"][0]["result"]["ok"] is True

    # La cita existe de verdad en la base
    appts = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(appts) == 1
    assert appts[0]["patient_name"] == "Carlos Ruiz"
    # El teléfono se completó desde la conversación
    assert appts[0]["patient_phone"] == "+595972222222"

    # El resultado de la herramienta volvió al modelo en la segunda llamada
    roles = [m["role"] for m in calls[1]["messages"]]
    assert "tool" in roles


def test_double_booking_rejected_by_tool(monkeypatch):
    company = _create_company(name="Clínica Choques")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. X"}).json()
    client.post(
        f"/api/companies/{cid}/appointments",
        json={
            "doctor_id": doc["id"],
            "patient_name": "Primero",
            "scheduled_at": "2026-08-12T10:00:00",
        },
    )

    fake, calls = _mock_llm(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "book_appointment",
                            "arguments": json.dumps(
                                {
                                    "doctor_id": doc["id"],
                                    "patient_name": "Segundo",
                                    "datetime_iso": "2026-08-12T10:00",
                                }
                            ),
                        },
                    }
                ],
            },
            {"content": "Ese horario ya está tomado, ¿te sirve a las 11:00?"},
        ]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595973333333", "text": "A las 10"}
    )
    assert "error" in resp.json()["actions"][0]["result"]
    appts = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(appts) == 1  # no se duplicó


def test_busy_slot_blocks_rebooking_same_turn(monkeypatch):
    """Regresión: si el horario pedido está ocupado, el bot NO puede agendar
    otro horario en el mismo turno; debe ofrecer alternativas."""
    company = _create_company(name="Clínica Guardia")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Guard"}).json()
    client.post(
        f"/api/companies/{cid}/appointments",
        json={"doctor_id": doc["id"], "patient_name": "Primero", "scheduled_at": "2030-01-15T09:00:00"},
    )

    def call(dt):
        return {
            "content": None,
            "tool_calls": [
                {
                    "id": f"c-{dt}",
                    "function": {
                        "name": "book_appointment",
                        "arguments": json.dumps(
                            {"doctor_id": doc["id"], "patient_name": "Insistente", "datetime_iso": dt}
                        ),
                    },
                }
            ],
        }

    fake, calls = _mock_llm(
        [
            call("2030-01-15T09:00"),   # ocupado
            call("2030-01-15T10:00"),   # el modelo intenta reagendar solo → bloqueado
            {"content": "Ese horario está tomado. ¿Te sirve a las 10:00 o a las 11:00?"},
        ]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595978888888", "text": "El 15 a las 9"}
    )
    data = resp.json()
    # El mensaje lo redacta ahora agenda.verificar_turno, que además del
    # solape valida día, franja y licencias.
    assert "superpone" in data["actions"][0]["result"]["error"]
    assert "NO agendes" in data["actions"][1]["result"]["error"]
    # Solo existe la cita original: nada se agendó sin confirmación
    appts = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(appts) == 1
    assert appts[0]["patient_name"] == "Primero"


def test_escalate_to_human(monkeypatch):
    company = _create_company(name="Clínica Escala")
    cid = company["id"]

    fake, _ = _mock_llm(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "escalate_to_human",
                            "arguments": json.dumps({"reason": "urgencia"}),
                        },
                    }
                ],
            },
            {"content": "Ya le aviso al equipo, en un ratito te contactan."},
        ]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595974444444", "text": "Necesito hablar con una persona"},
    )
    assert resp.json()["status"] == "needs_human"
    convs = client.get(f"/api/companies/{cid}/conversations").json()
    assert convs[0]["status"] == "needs_human"


def test_booking_in_the_past_rejected(monkeypatch):
    """Regresión: el modelo intentó agendar en 2024; el motor debe rechazar
    fechas pasadas y pedir el año correcto."""
    company = _create_company(name="Clínica Fechas")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Pasado"}).json()

    fake, _ = _mock_llm(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "book_appointment",
                            "arguments": json.dumps(
                                {
                                    "doctor_id": doc["id"],
                                    "patient_name": "Viajera del Tiempo",
                                    "datetime_iso": "2024-08-10T09:00",
                                }
                            ),
                        },
                    }
                ],
            },
            {"content": "Perdoná, me confundí de fecha. ¿Para el 10/08/2026 entonces?"},
        ]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    resp = client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595976666666", "text": "El 10 a las 9"}
    )
    result = resp.json()["actions"][0]["result"]
    assert "ya pasó" in result["error"]
    appts = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert len(appts) == 0  # nada se agendó en el pasado


def test_booking_phone_string_null_sanitized(monkeypatch):
    """Regresión: el modelo mandó patient_phone='null'; debe usarse el
    teléfono real de la conversación."""
    company = _create_company(name="Clínica Null")
    cid = company["id"]
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dra. Sane"}).json()

    fake, _ = _mock_llm(
        [
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "book_appointment",
                            "arguments": json.dumps(
                                {
                                    "doctor_id": doc["id"],
                                    "patient_name": "Sin Teléfono",
                                    "patient_phone": "your phone number",
                                    "datetime_iso": "2030-01-15T10:00",
                                }
                            ),
                        },
                    }
                ],
            },
            {"content": "¡Listo!"},
        ]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)

    client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595977777777", "text": "Agendame"}
    )
    appts = client.get(f"/api/companies/{cid}/appointments", params={"doctor_id": doc["id"]}).json()
    assert appts[0]["patient_phone"] == "+595977777777"


def test_tool_syntax_in_text_is_sanitized(monkeypatch):
    """Regresión de producción: el modelo escribió '<escalate_to_human> {...}'
    como texto; eso no debe llegar jamás al cliente."""
    company = _create_company(name="Clínica Sanitizada")
    cid = company["id"]

    fake, _ = _mock_llm(
        [{"content": "Te agendo el lunes, ¿sí?\n\n<escalate_to_human>\n{\"reason\": \"pedido\"}"}]
    )
    monkeypatch.setattr(chat_engine, "chat_raw", fake)
    resp = client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595979999999", "text": "Turno"}
    )
    reply = resp.json()["reply"]
    assert reply == "Te agendo el lunes, ¿sí?"
    assert "escalate" not in reply


def test_paused_cx_agent_returns_error(monkeypatch):
    company = _create_company(name="Clínica Pausada")
    cid = company["id"]
    agents = client.get(f"/api/companies/{cid}/agents").json()
    cx = next(a for a in agents if a["slug"] == "cx")
    client.patch(f"/api/agents/{cx['id']}", json={"active": False})

    resp = client.post(
        f"/api/companies/{cid}/chat", json={"contact_phone": "+595975555555", "text": "Hola"}
    )
    assert resp.json()["reply"] is None
    assert "pausado" in resp.json()["error"]
