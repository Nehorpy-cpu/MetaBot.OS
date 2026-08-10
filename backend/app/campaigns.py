"""Generador de campañas Meta en modo borrador — cada agente con lo suyo:

1. CEO: define título, ángulo estratégico y público.
2. Director Creativo: escribe los copys (por tarjeta si es carrusel, o el
   guion escena por escena si es video).
3. Estudio Visual: genera la imagen de cada tarjeta.
4. Auditor: revisa el conjunto contra las políticas de anuncios de Meta
   ANTES de que nada se publique.

Los números y estructuras los valida el servidor; el LLM redacta.
"""
import json
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from .imagegen import ImageGenError, generate_image
from .llm import complete
from .models import Agent, Campaign, Company, Product, Report

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
FORMATS = {"carousel", "single", "video_script"}


def _agent(db: Session, company: Company, slug: str) -> Agent | None:
    return (
        db.query(Agent)
        .filter(Agent.company_id == company.id, Agent.slug == slug, Agent.active)
        .first()
    )


_OFFER_RE = re.compile(r"(?:₲|Gs\.?)\s?[\d.,]+|\b\d{1,3}\s?%", re.IGNORECASE)


def _invented_offers(brief: str, cards: list[dict]) -> list[str]:
    """Montos/porcentajes en las tarjetas cuyos dígitos no aparecen en el brief."""
    brief_digits = set(re.findall(r"\d+", brief))
    invented = []
    for card in cards:
        text = f"{card.get('headline', '')} {card.get('copy', '')}"
        for offer in _OFFER_RE.findall(text):
            digits = re.findall(r"\d+", offer)
            if digits and not all(d in brief_digits for d in digits):
                invented.append(offer.strip())
    return list(dict.fromkeys(invented))


def _json_of(raw: str) -> dict | list | None:
    match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


async def _ask(
    db: Session, company: Company, slug: str, prompt: str, max_tokens: int = 1200,
    json_mode: bool = False,
) -> str:
    agent = _agent(db, company, slug)
    system = agent.system_prompt if agent else ""
    return await complete(
        [{"role": "user", "content": f"{system}\n\n{prompt}"}],
        model=agent.model if agent else None,
        temperature=agent.temperature if agent else 0.4,
        max_tokens=max_tokens,
        json_mode=json_mode,
    )


async def _ask_json(
    db: Session, company: Company, slug: str, prompt: str, max_tokens: int = 1200
) -> dict | list | None:
    """Pide JSON en modo estructurado, con reintento correctivo si aún falla."""
    raw = await _ask(db, company, slug, prompt, max_tokens, json_mode=True)
    parsed = _json_of(raw)
    if parsed is not None:
        return parsed
    raw = await _ask(
        db, company, slug,
        prompt + "\n\nTU RESPUESTA ANTERIOR NO FUE JSON VÁLIDO. Respondé ÚNICAMENTE el JSON pedido, sin ningún texto adicional.",
        max_tokens,
        json_mode=True,
    )
    return _json_of(raw)


async def build_campaign(
    db: Session, company: Company, brief: str, format: str, n_cards: int = 4
) -> Campaign:
    if format not in FORMATS:
        raise ValueError(f"Formato inválido: {format}")
    n_cards = max(2, min(n_cards, 8)) if format == "carousel" else (1 if format == "single" else max(3, min(n_cards, 8)))
    profile = company.profile or "{}"

    # Si existe investigación de segmentos (scraping real), el CEO la usa
    segments_report = (
        db.query(Report)
        .filter(Report.company_id == company.id, Report.kind == "segments")
        .order_by(Report.id.desc())
        .first()
    )
    segments_ctx = (
        f"\nSegmentos investigados con datos reales del mercado:\n{segments_report.content[:2500]}\n"
        if segments_report
        else ""
    )

    # 1) CEO: estrategia
    strategy_parsed = await _ask_json(
        db, company, "ceo",
        f"Brief de campaña: {brief}\nPerfil del negocio: {profile}\n{segments_ctx}\n"
        'Definí la estrategia (si hay segmentos investigados, elegí el más apto para este brief). '
        'Respondé SOLO JSON: {"title": "nombre corto de la campaña", '
        '"angle": "ángulo persuasivo elegido", "audience": "público objetivo concreto (segmento elegido)"}',
        max_tokens=400,
    )
    strategy = strategy_parsed if isinstance(strategy_parsed, dict) else {}
    title = str(strategy.get("title", brief[:60]))[:300]
    strategy_text = json.dumps(strategy, ensure_ascii=False)

    # 2) Director Creativo: copys / guion
    if format == "video_script":
        creative_raw = await _ask(
            db, company, "creative",
            f"Campaña: {title}. Ángulo: {strategy.get('angle', '')}. Brief: {brief}\n\n"
            f"Escribí un guion de video/reel de {n_cards} escenas para redes. Respondé SOLO JSON: "
            '[{"headline": "ESCENA n — duración", "copy": "voz en off / texto en pantalla", '
            '"visual": "qué se ve en la escena"}]',
            max_tokens=1600,
            json_mode=True,
        )
    else:
        creative_raw = await _ask(
            db, company, "creative",
            f"Campaña: {title}. Ángulo: {strategy.get('angle', '')}. Brief: {brief}\n\n"
            f"Escribí {n_cards} tarjeta(s) de anuncio. La última cierra con llamado a la acción. "
            'Respondé SOLO JSON: [{"headline": "título corto de la tarjeta", "copy": "texto '
            'persuasivo de máx 30 palabras, voseo"}]',
            max_tokens=1600,
            json_mode=True,
        )
    cards_json = _json_of(creative_raw)
    if not isinstance(cards_json, list) or not cards_json:
        raise ValueError(f"El Creativo no devolvió tarjetas válidas: {creative_raw[:200]}")
    cards = [
        {
            "position": i + 1,
            "headline": str(c.get("headline", ""))[:200],
            "copy": str(c.get("copy", ""))[:1000],
            "visual": str(c.get("visual", ""))[:500],
            "image_path": "",
        }
        for i, c in enumerate(cards_json[:n_cards])
    ]

    # 3) Imágenes. REGLA: si el negocio tiene catálogo con fotos reales,
    # las tarjetas usan SOLO fotos reales (nunca se genera un producto).
    products_with_photo = (
        db.query(Product)
        .filter(Product.company_id == company.id, Product.active, Product.image_path != "")
        .all()
    )
    if format != "video_script" and products_with_photo:
        def _match(card: dict) -> Product | None:
            text = f"{card['headline']} {card['copy']}".lower()
            for p in products_with_photo:
                if p.name.lower() in text or (p.brand and len(p.brand) > 2 and p.brand.lower() in text):
                    return p
            return None

        pool = [p for p in products_with_photo if p.in_stock] or products_with_photo
        rotation = 0
        for card in cards:
            product = _match(card)
            if not product:
                product = pool[rotation % len(pool)]
                rotation += 1
            card["image_path"] = product.image_path
            card["image_prompt"] = f"FOTO REAL del catálogo: {product.name} ({product.brand})"
    elif format != "video_script":
        try:
            products = json.loads(company.profile or "{}").get("products") or []
        except json.JSONDecodeError:
            products = []
        product_rule = (
            f"EL PRODUCTO ES EL PROTAGONISTA OBLIGATORIO de cada imagen: este negocio "
            f"vende {company.industry or company.niche}"
            + (f" ({', '.join(str(p) for p in products[:8])})" if products else "")
            + ". Cada prompt debe describir el producto físico en primer plano (ej. si son "
            "perfumes: elegant perfume bottle as hero of the shot). PROHIBIDO: imágenes "
            "genéricas de personas, flores o ambientes SIN el producto visible."
        )
        prompts_raw = await _ask(
            db, company, "visual",
            f"Campaña: {title}. Brief: {brief}\n"
            f"Tarjetas: {json.dumps([{'headline': c['headline'], 'copy': c['copy']} for c in cards], ensure_ascii=False)}\n\n"
            f"{product_rule}\n\n"
            "Escribí el prompt de imagen EN INGLÉS para cada tarjeta (fotografía publicitaria "
            "profesional, sin texto en la imagen, coherencia visual entre tarjetas, alineado "
            "al tema de la campaña). "
            'Respondé SOLO JSON: ["prompt tarjeta 1", "prompt tarjeta 2", ...]',
            max_tokens=800,
            json_mode=True,
        )
        prompts = _json_of(prompts_raw)
        if isinstance(prompts, list):
            folder = MEDIA_DIR / str(company.id)
            folder.mkdir(parents=True, exist_ok=True)
            for card, img_prompt in zip(cards, prompts):
                try:
                    image_bytes, _provider = await generate_image(str(img_prompt), 1024, 1024)
                    filename = f"{uuid.uuid4().hex}.png"
                    (folder / filename).write_bytes(image_bytes)
                    card["image_path"] = f"/media/{company.id}/{filename}"
                    card["image_prompt"] = str(img_prompt)[:500]
                except ImageGenError:
                    card["image_path"] = ""  # la campaña sigue; imagen regenerable

    # 4) Auditor: políticas de Meta antes de publicar nada
    audit_parsed = await _ask_json(
        db, company, "guard",
        "Auditá esta campaña contra las políticas de anuncios de Meta (afirmaciones "
        "engañosas, promesas de resultados, atributos personales, contenido sanitario "
        "prohibido, texto discriminatorio). Respondé SOLO JSON: "
        '{"severity": "ok|info|warning|critical", "note": "explicación breve"}\n\n'
        f"CAMPAÑA:\n{json.dumps(cards, ensure_ascii=False)}",
        max_tokens=400,
    )
    audit = audit_parsed if isinstance(audit_parsed, dict) else {}
    severity = str(audit.get("severity", "")).lower()
    if severity not in {"ok", "info", "warning", "critical"}:
        # Nunca dar por aprobado lo que el auditor no evaluó de forma legible
        severity = "warning"
        audit["note"] = "El auditor no devolvió un veredicto legible; revisar manualmente antes de publicar."

    # Guardia determinística: montos/porcentajes en las tarjetas que NO están
    # en el brief son promesas inventadas por el modelo → revisión obligatoria.
    invented = _invented_offers(brief, cards)
    if invented and severity in {"ok", "info"}:
        severity = "warning"
        audit["note"] = (
            f"Ofertas no presentes en el brief (posible invención del modelo): {', '.join(invented)}. "
            + str(audit.get("note", ""))
        )

    campaign = Campaign(
        company_id=company.id,
        brief=brief,
        format=format,
        title=title,
        strategy=strategy_text,
        cards=json.dumps(cards, ensure_ascii=False),
        audit_severity=severity,
        audit_note=str(audit.get("note", ""))[:2000],
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign
