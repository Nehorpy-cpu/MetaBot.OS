"""Tests de analítica, informes del Quant y auditoría del Guard (sin red)."""
import os

os.environ["SCHEDULER_ENABLED"] = "0"

from tests.test_api import _create_company, client  # noqa: E402

from app import swarm  # noqa: E402


def _seed_activity(cid: int) -> int:
    doc = client.post(f"/api/companies/{cid}/doctors", json={"name": "Dr. Datos"}).json()
    for i, status in enumerate(["attended", "no_show", "attended", "cancelled"]):
        appt = client.post(
            f"/api/companies/{cid}/appointments",
            json={
                "doctor_id": doc["id"],
                "patient_name": f"Paciente {i}",
                "scheduled_at": f"2030-06-0{i+1}T09:00:00",
            },
        ).json()
        client.patch(f"/api/companies/{cid}/appointments/{appt['id']}", json={"status": status})
    return doc["id"]


def test_stats_no_show_rate():
    company = _create_company(name="Clínica Stats")
    cid = company["id"]
    _seed_activity(cid)
    stats = client.get(f"/api/companies/{cid}/stats").json()
    a = stats["appointments"]
    assert a["total"] == 4
    assert a["by_status"]["attended"] == 2
    assert a["by_status"]["no_show"] == 1
    # 1 no-show sobre 3 finalizadas (2 attended + 1 no_show) = 33.3%
    assert a["no_show_rate_pct"] == 33.3
    assert a["by_doctor"]["Dr. Datos"] == 4


def test_weekly_report_uses_real_stats(monkeypatch):
    company = _create_company(name="Clínica Informe")
    cid = company["id"]
    _seed_activity(cid)

    captured = {}

    async def fake_complete(messages, **kwargs):
        captured["prompt"] = messages[-1]["content"]
        return "Informe: esta semana hubo 4 citas."

    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{cid}/reports/weekly")
    assert resp.status_code == 200
    # El prompt lleva los números reales calculados por el servidor
    assert '"total": 4' in captured["prompt"]
    assert "no inventes" in captured["prompt"].lower()

    reports = client.get(f"/api/companies/{cid}/reports").json()
    assert len(reports) == 1
    assert reports[0]["kind"] == "weekly"
    assert "4 citas" in reports[0]["content"]


def test_guard_audit_flags_and_skips_audited(monkeypatch):
    company = _create_company(name="Clínica Audit")
    cid = company["id"]

    # Conversación con respuesta del bot (mock del motor para sembrar mensajes)
    async def fake_chat(messages, **kwargs):
        return {"content": "Eso es apendicitis segura, tomá ibuprofeno."}

    monkeypatch.setattr("app.chat.chat_raw", fake_chat)
    client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595971010101", "text": "Me duele la panza"},
    )

    async def fake_complete(messages, **kwargs):
        return '{"severity": "critical", "note": "El bot dio diagnóstico y medicación."}'

    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{cid}/audits/run")
    assert resp.json()["new_findings"] == 1

    findings = client.get(f"/api/companies/{cid}/audits").json()
    assert findings[0]["severity"] == "critical"
    assert "diagnóstico" in findings[0]["note"]

    # Segunda corrida: la conversación ya auditada no se repite
    resp2 = client.post(f"/api/companies/{cid}/audits/run")
    assert resp2.json()["new_findings"] == 0


def test_guard_audit_ok_verdict_creates_nothing(monkeypatch):
    company = _create_company(name="Clínica Audit OK")
    cid = company["id"]

    async def fake_chat(messages, **kwargs):
        return {"content": "¡Hola! Te agendo un turno así te revisa el doctor."}

    monkeypatch.setattr("app.chat.chat_raw", fake_chat)
    client.post(
        f"/api/companies/{cid}/chat",
        json={"contact_phone": "+595971020202", "text": "Me duele la cabeza"},
    )

    async def fake_complete(messages, **kwargs):
        return 'El análisis dice: {"severity": "ok", "note": "Conducta correcta"}'

    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{cid}/audits/run")
    assert resp.json()["new_findings"] == 0


def test_parse_verdict_tolerates_garbage():
    assert swarm._parse_verdict("no json aquí")["severity"] == "info"
    assert swarm._parse_verdict('{"severity": "warning", "note": "x"}')["severity"] == "warning"
    assert swarm._parse_verdict('bla {"severity": "critical", "note": "y"} bla')["severity"] == "critical"


def test_parse_verdict_flags_classifier_format():
    """Regresión: el Safety Guard clasificador responde con su propio formato;
    eso debe generar un hallazgo visible, no un 'ok' silencioso."""
    raw = '{"User Safety": "unsafe", "Response Safety": "unsafe"}'
    verdict = swarm._parse_verdict(raw)
    assert verdict["severity"] == "info"
    assert "formato inesperado" in verdict["note"]


def test_competitors_crud_and_scan_requires_sources():
    company = _create_company(name="Tienda Comp", vertical="ecommerce")
    cid = company["id"]

    resp = client.post(f"/api/companies/{cid}/reports/competitive")
    assert resp.status_code == 422  # sin URLs cargadas

    ok = client.post(
        f"/api/companies/{cid}/competitors",
        json={"url": "https://ejemplo.com.py", "label": "Rival 1"},
    )
    assert ok.status_code == 201
    dup = client.post(f"/api/companies/{cid}/competitors", json={"url": "https://ejemplo.com.py"})
    assert dup.status_code == 409
    bad = client.post(f"/api/companies/{cid}/competitors", json={"url": "no-es-url"})
    assert bad.status_code == 422

    listed = client.get(f"/api/companies/{cid}/competitors").json()
    assert len(listed) == 1


def test_competitive_scan_with_mocked_fetch(monkeypatch):
    company = _create_company(name="Tienda Scan", vertical="ecommerce")
    cid = company["id"]
    client.post(f"/api/companies/{cid}/competitors", json={"url": "https://rival.com.py", "label": "Rival"})

    async def fake_fetch(url):
        return "Ofertas de zapatillas a Gs. 350.000 envío gratis"

    async def fake_complete(messages, **kwargs):
        assert "zapatillas" in messages[-1]["content"]
        return "Resumen: el rival vende zapatillas a ₲ 350.000."

    monkeypatch.setattr(swarm, "_fetch_page_text", fake_fetch)
    monkeypatch.setattr(swarm, "complete", fake_complete)
    resp = client.post(f"/api/companies/{cid}/reports/competitive")
    assert resp.status_code == 200
    assert "₲ 350.000" in resp.json()["content"]
