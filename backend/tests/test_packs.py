"""Business Packs y vendedor consultivo.

El núcleo es genérico: una clínica es un tenant con packs booking+healthcare,
no un caso especial del código.
"""
import json

from tests.test_api import _create_company, client

from app import chat as chat_engine
from app import packs
from app.db import SessionLocal
from app.models import Company, Product


def _set_packs(company_id: int, keys: str) -> None:
    db = SessionLocal()
    try:
        company = db.get(Company, company_id)
        company.packs = keys
        db.commit()
    finally:
        db.close()


def _tool_names(company_id: int) -> set[str]:
    db = SessionLocal()
    try:
        company = db.get(Company, company_id)
        return {t["function"]["name"] for t in chat_engine._tools_for(company)}
    finally:
        db.close()


def test_healthcare_requires_booking():
    """Los packs resuelven dependencias: healthcare arrastra booking."""
    company = _create_company(name="Sanatorio Packs")
    _set_packs(company["id"], "healthcare")
    db = SessionLocal()
    try:
        active = [p.key for p in packs.active_packs(db.get(Company, company["id"]))]
    finally:
        db.close()
    # El núcleo va primero SIEMPRE: no es un bloque que se compra, es el
    # bot, el catálogo y los servicios que todos tienen.
    assert active == ["core", "booking", "healthcare"]


def test_tools_come_from_packs_not_from_vertical():
    company = _create_company(name="Negocio Genérico", vertical="ecommerce")
    cid = company["id"]

    # Solo el núcleo: vende, no agenda.
    _set_packs(cid, "")
    solo_nucleo = _tool_names(cid)
    assert "search_catalog" in solo_nucleo
    assert "list_services" in solo_nucleo
    assert "book_appointment" not in solo_nucleo  # una tienda no agenda citas

    # Con la agenda: gana los turnos y CONSERVA el catálogo del núcleo. Antes
    # `list_services` vivía dentro de la agenda, así que quien no compraba ese
    # bloque no podía ni decir cuánto sale un estudio.
    _set_packs(cid, "booking")
    con_agenda = _tool_names(cid)
    assert {"book_appointment", "check_agenda", "my_appointments"} <= con_agenda
    assert {"search_catalog", "list_services"} <= con_agenda

    # escalate_to_human siempre está, compre lo que compre
    assert "escalate_to_human" in solo_nucleo & con_agenda


def test_healthcare_rules_only_when_pack_active(monkeypatch):
    company = _create_company(name="Clínica Reglas")
    cid = company["id"]
    _set_packs(cid, "booking,healthcare")

    captured = {}

    async def fake_chat(messages, **kwargs):
        captured["system"] = messages[0]["content"]
        return {"content": "ok"}

    monkeypatch.setattr(chat_engine, "chat_raw", fake_chat)
    client.post(f"/api/companies/{cid}/chat", json={"contact_phone": "+595971777001", "text": "hola"})
    assert "JAMÁS des diagnósticos" in captured["system"]

    # La misma empresa sin el bloque de salud: sin reglas sanitarias. Se pone
    # un bloque explícito y no vacío, porque `packs=""` todavía cae al vertical
    # y una empresa "medical" volvería a resolver healthcare.
    _set_packs(cid, "booking")
    client.post(f"/api/companies/{cid}/chat", json={"contact_phone": "+595971777002", "text": "hola"})
    assert "JAMÁS des diagnósticos" not in captured["system"]
    # Las reglas del núcleo sí: no inventar lo que el negocio no ofrece.
    assert "Nunca inventes un servicio" in captured["system"]


def _seed_catalog(cid: int) -> None:
    db = SessionLocal()
    try:
        for name, brand, price, gender, notes, stock in [
            ("Yara", "Lattafa", 220000, "femenino", "dulce, floral, vainilla, tropical", True),
            ("Le Beau", "Jean Paul Gaultier", 650000, "masculino", "amaderado, intenso", True),
            ("Good Girl", "Carolina Herrera", 720000, "femenino", "dulce, oriental, muy pesado", True),
            ("Amber Romance", "Victoria Secret", 130000, "femenino", "dulce, suave, ámbar", True),
            ("Sauvage", "Dior", 900000, "masculino", "fresco, especiado", False),
        ]:
            db.add(Product(company_id=cid, name=name, brand=brand, price_gs=price,
                           gender=gender, notes=notes, in_stock=stock, category="Perfume"))
        db.commit()
    finally:
        db.close()


def _search(cid: int, args: dict) -> dict:
    """Ejecuta search_catalog como lo haría el bot."""
    db = SessionLocal()
    try:
        company = db.get(Company, cid)
        from app.models import Conversation

        conv = Conversation(company_id=cid, contact_phone="+595971000000")
        db.add(conv)
        db.flush()
        media: list = []
        return chat_engine._execute_tool("search_catalog", args, db, company, conv, media_out=media), media
    finally:
        db.close()


def test_consultative_search_respects_budget():
    """'dulce para mujer, hasta 350 mil' → solo productos reales que cumplen."""
    company = _create_company("ecommerce", "Perfumería Consultiva")
    cid = company["id"]
    _seed_catalog(cid)

    result, media = _search(cid, {
        "query": "dulce floral", "gender": "femenino", "budget_max": 350000, "max_results": 5,
    })
    names = [p["name"] for p in result["products"]]
    assert "Yara" in names and "Amber Romance" in names
    assert "Good Girl" not in names   # 720.000 supera el presupuesto
    assert "Le Beau" not in names     # masculino
    assert all(p["price_gs"] <= 350000 for p in result["products"])
    assert result["exact_match"] is True
    # Las fotos reales acompañan la recomendación
    assert len(media) == len([p for p in result["products"] if p["photo_attached"]])


def test_consultative_search_honors_avoid():
    company = _create_company("ecommerce", "Perfumería Avoid")
    cid = company["id"]
    _seed_catalog(cid)
    result, _ = _search(cid, {
        "query": "dulce", "gender": "femenino", "budget_max": 800000, "avoid": "muy pesado",
    })
    names = [p["name"] for p in result["products"]]
    assert names, "debe devolver alternativas"
    assert "Good Girl" not in names  # es el 'muy pesado' que pidió evitar


def test_search_excludes_out_of_stock_by_default():
    company = _create_company("ecommerce", "Perfumería Stock")
    cid = company["id"]
    _seed_catalog(cid)
    result, _ = _search(cid, {"query": "Sauvage Dior", "max_results": 5})
    assert "Sauvage" not in [p["name"] for p in result["products"]]  # sin stock


def test_search_is_honest_when_nothing_fits_budget():
    company = _create_company("ecommerce", "Perfumería Honesta")
    cid = company["id"]
    _seed_catalog(cid)
    result, _ = _search(cid, {"query": "perfume", "budget_max": 50000})
    assert result["products"] == []
    assert "No hay nada hasta" in result["note"]
    assert "Amber Romance" in result["note"]  # sugiere lo más accesible real
