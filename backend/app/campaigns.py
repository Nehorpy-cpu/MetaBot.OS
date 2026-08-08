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
from .models import Agent, Campaign, Company

MEDIA_DIR = Path(__file__).resolve().parents[1] / "media"
FORMATS = {"carousel", "single", "video_script"}


def _agent(db: Session, company: Company, slug: str) -> Agent | None:
    return (
        db.query(Agent)
        .filter(Agent.company_id == company.id, Agent.slug == slug, Agent.active)
        .first()
    )


def _json_of(raw: str) -> dict | list | None:
    match = re.search(r"[\[{].*[\]}]", raw, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group())
    except json.JSONDecodeError:
        return None


async def _ask(db: Session, company: Company, slug: str, prompt: str, max_tokens: int = 1200) -> str:
    agent = _agent(db, company, slug)
    system = agent.system_prompt if agent else ""
    return await complete(
        [{"role": "user", "content": f"{system}\n\n{prompt}"}],
        model=agent.model if agent else None,
        temperature=agent.temperature if agent else 0.4,
        max_tokens=max_tokens,
    )


async def _ask_json(
    db: Session, company: Company, slug: str, prompt: str, max_tokens: int = 1200
) -> dict | list | None:
    """Pide JSON con un reintento correctivo si el modelo no lo respeta."""
    raw = await _ask(db, company, slug, prompt, max_tokens)
    parsed = _json_of(raw)
    if parsed is not None:
        return parsed
    raw = await _ask(
        db, company, slug,
        prompt + "\n\nTU RESPUESTA ANTERIOR NO FUE JSON VÁLIDO. Respondé ÚNICAMENTE el JSON pedido, sin ningún texto adicional.",
        max_tokens,
    )
    return _json_of(raw)


async def build_campaign(
    db: Session, company: Company, brief: str, format: str, n_cards: int = 4
) -> Campaign:
    if format not in FORMATS:
        raise ValueError(f"Formato inválido: {format}")
    n_cards = max(2, min(n_cards, 8)) if format == "carousel" else (1 if format == "single" else max(3, min(n_cards, 8)))
    profile = company.profile or "{}"

    # 1) CEO: estrategia
    strategy_parsed = await _ask_json(
        db, company, "ceo",
        f"Brief de campaña: {brief}\nPerfil del negocio: {profile}\n\n"
        'Definí la estrategia. Respondé SOLO JSON: {"title": "nombre corto de la campaña", '
        '"angle": "ángulo persuasivo elegido", "audience": "público objetivo concreto"}',
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
        )
    else:
        creative_raw = await _ask(
            db, company, "creative",
            f"Campaña: {title}. Ángulo: {strategy.get('angle', '')}. Brief: {brief}\n\n"
            f"Escribí {n_cards} tarjeta(s) de anuncio. La última cierra con llamado a la acción. "
            'Respondé SOLO JSON: [{"headline": "título corto de la tarjeta", "copy": "texto '
            'persuasivo de máx 30 palabras, voseo"}]',
            max_tokens=1600,
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

    # 3) Estudio Visual: una imagen por tarjeta (no aplica a guion de video)
    if format != "video_script":
        prompts_raw = await _ask(
            db, company, "visual",
            f"Campaña: {title}. Tarjetas: {json.dumps([{'headline': c['headline'], 'copy': c['copy']} for c in cards], ensure_ascii=False)}\n\n"
            "Escribí el prompt de imagen EN INGLÉS para cada tarjeta (fotografía publicitaria "
            "profesional, sin texto en la imagen, coherencia visual entre tarjetas). "
            'Respondé SOLO JSON: ["prompt tarjeta 1", "prompt tarjeta 2", ...]',
            max_tokens=800,
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
