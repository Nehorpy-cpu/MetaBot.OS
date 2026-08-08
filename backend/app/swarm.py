"""Tareas autónomas del enjambre: Quant (informes), Guard (auditoría),
Inteligencia Web (competencia).

Principio del proyecto: los datos los calcula el servidor; el LLM redacta e
interpreta. Toda salida del LLM que dispare acciones se parsea con tolerancia
a fallos y valores por defecto seguros.
"""
import json
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy.orm import Session

from .analytics import compute_stats
from .config import TIMEZONE
from .llm import complete
from .models import (
    Agent,
    AuditFinding,
    Company,
    CompetitorSource,
    Conversation,
    Creative,
    Message,
    PromptSuggestion,
    Report,
)

VALID_SEVERITIES = {"info", "warning", "critical"}


def _agent(db: Session, company: Company, slug: str) -> Agent | None:
    return (
        db.query(Agent)
        .filter(Agent.company_id == company.id, Agent.slug == slug, Agent.active)
        .first()
    )


async def run_weekly_report(db: Session, company: Company, days: int = 7) -> Report:
    """El Analista Quant redacta el informe semanal sobre stats reales."""
    quant = _agent(db, company, "quant")
    stats = compute_stats(db, company, days)
    now = datetime.now(ZoneInfo(TIMEZONE))
    prompt = (
        f"{quant.system_prompt if quant else 'Sos analista de negocio.'}\n\n"
        "Redactá el informe semanal para el dueño del negocio en español "
        "(voseo paraguayo), claro y accionable, con secciones breves: "
        "resumen, citas, atención al cliente, y 2-3 recomendaciones concretas. "
        "Usá SOLO estos datos reales (no inventes cifras):\n"
        f"{json.dumps(stats, ensure_ascii=False)}"
    )
    content = await complete(
        [{"role": "user", "content": prompt}],
        model=quant.model if quant else None,
        temperature=quant.temperature if quant else 0.3,
        max_tokens=1500,
    )
    report = Report(
        company_id=company.id,
        kind="weekly",
        title=f"Informe semanal — {now.strftime('%d/%m/%Y')}",
        content=content,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def _parse_verdict(raw: str) -> dict:
    """Extrae el JSON del veredicto del Guard con tolerancia a texto extra."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {"severity": "info", "note": f"Veredicto no parseable: {raw[:200]}"}
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return {"severity": "info", "note": f"JSON inválido del auditor: {raw[:200]}"}
    if "severity" not in data:
        # Formato inesperado (ej. modelo clasificador mal configurado como
        # auditor): visibilizarlo, nunca tratarlo como "ok" silencioso.
        return {
            "severity": "info",
            "note": f"El auditor respondió en formato inesperado; revisar su modelo. Salida: {raw[:200]}",
        }
    severity = str(data.get("severity", "ok")).lower()
    note = str(data.get("note", ""))[:1000]
    return {"severity": severity, "note": note}


async def run_guard_audit(
    db: Session, company: Company, days: int = 7, max_conversations: int = 20
) -> list[AuditFinding]:
    """El Auditor revisa las conversaciones recientes del CX Bot.

    Solo audita conversaciones sin hallazgo previo (no duplica trabajo).
    """
    guard = _agent(db, company, "guard")
    since = datetime.now() - timedelta(days=days)
    audited_ids = {
        f.conversation_id
        for f in db.query(AuditFinding).filter(AuditFinding.company_id == company.id).all()
    }
    convs = (
        db.query(Conversation)
        .filter(Conversation.company_id == company.id, Conversation.created_at >= since)
        .order_by(Conversation.id.desc())
        .limit(max_conversations)
        .all()
    )
    rules = (
        "Reglas para clínicas: NUNCA diagnósticos ni medicación por chat; "
        "urgencias derivadas de inmediato; tono respetuoso."
        if company.vertical == "medical"
        else "Reglas de venta: sin promesas falsas, sin datos de pago por chat, tono respetuoso."
    )
    findings: list[AuditFinding] = []
    for conv in convs:
        if conv.id in audited_ids:
            continue
        msgs = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id)
            .order_by(Message.id)
            .limit(60)
            .all()
        )
        if not any(m.direction == "out" for m in msgs):
            continue
        transcript = "\n".join(
            f"{'CLIENTE' if m.direction == 'in' else 'BOT'}: {m.body}" for m in msgs
        )
        prompt = (
            f"{guard.system_prompt if guard else 'Sos auditor de calidad.'}\n\n{rules}\n\n"
            "Auditá SOLO las respuestas del BOT en esta conversación. Respondé "
            'ÚNICAMENTE un JSON: {"severity": "ok|info|warning|critical", '
            '"note": "explicación breve en español"}. Usá "ok" si no hay problema.\n\n'
            f"CONVERSACIÓN:\n{transcript}"
        )
        raw = await complete(
            [{"role": "user", "content": prompt}],
            model=guard.model if guard else None,
            temperature=guard.temperature if guard else 0.1,
            max_tokens=400,
        )
        verdict = _parse_verdict(raw)
        if verdict["severity"] not in VALID_SEVERITIES:
            continue  # "ok" u otro valor: sin hallazgo
        finding = AuditFinding(
            company_id=company.id,
            conversation_id=conv.id,
            severity=verdict["severity"],
            note=verdict["note"],
        )
        db.add(finding)
        findings.append(finding)
    db.commit()
    return findings


# --- Optimizador de Prompts: el agente que mejora al resto ---

def _gather_evidence(db: Session, company: Company, agent: Agent) -> str:
    """Junta salidas reales recientes del agente para que el Optimizador
    las evalúe. Sin evidencia no hay optimización (no se opina en el vacío)."""
    if agent.slug == "cx":
        msgs = (
            db.query(Message)
            .join(Conversation, Message.conversation_id == Conversation.id)
            .filter(Conversation.company_id == company.id, Message.direction == "out")
            .order_by(Message.id.desc())
            .limit(15)
            .all()
        )
        findings = (
            db.query(AuditFinding)
            .filter(AuditFinding.company_id == company.id)
            .order_by(AuditFinding.id.desc())
            .limit(10)
            .all()
        )
        parts = [f"RESPUESTA DEL BOT: {m.body}" for m in reversed(msgs)]
        parts += [f"HALLAZGO DEL AUDITOR [{f.severity}]: {f.note}" for f in findings]
        return "\n".join(parts)
    if agent.slug == "creative":
        creatives = (
            db.query(Creative)
            .filter(Creative.company_id == company.id)
            .order_by(Creative.id.desc())
            .limit(8)
            .all()
        )
        return "\n".join(f"BRIEF: {c.brief}\nCOPY PRODUCIDO: {c.copy_text}" for c in creatives)
    if agent.slug == "visual":
        creatives = (
            db.query(Creative)
            .filter(Creative.company_id == company.id)
            .order_by(Creative.id.desc())
            .limit(8)
            .all()
        )
        return "\n".join(f"BRIEF: {c.brief}\nPROMPT DE IMAGEN: {c.image_prompt}" for c in creatives)
    if agent.slug == "quant":
        reports = (
            db.query(Report)
            .filter(Report.company_id == company.id, Report.kind == "weekly")
            .order_by(Report.id.desc())
            .limit(2)
            .all()
        )
        return "\n".join(f"INFORME PRODUCIDO:\n{r.content[:1500]}" for r in reports)
    return ""


def _parse_suggestion(raw: str) -> dict | None:
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        return None
    improved = str(data.get("improved_prompt", "")).strip()
    if len(improved) < 40:
        return None
    return {"improved_prompt": improved, "rationale": str(data.get("rationale", ""))[:1000]}


async def run_prompt_optimization(db: Session, company: Company) -> list[PromptSuggestion]:
    """El Optimizador propone mejoras de prompts basadas en salidas reales.

    Nunca aplica cambios: crea sugerencias 'pending' que un humano aprueba.
    No duplica: si un agente ya tiene una sugerencia pendiente, lo saltea.
    """
    optimizer = _agent(db, company, "optimizer")
    if not optimizer:
        return []
    pending_agent_ids = {
        s.agent_id
        for s in db.query(PromptSuggestion)
        .filter(PromptSuggestion.company_id == company.id, PromptSuggestion.status == "pending")
        .all()
    }
    suggestions: list[PromptSuggestion] = []
    agents = (
        db.query(Agent)
        .filter(Agent.company_id == company.id, Agent.active, Agent.slug != "optimizer")
        .all()
    )
    for agent in agents:
        if agent.id in pending_agent_ids:
            continue
        evidence = _gather_evidence(db, company, agent)
        if len(evidence) < 100:
            continue
        prompt = (
            f"{optimizer.system_prompt}\n\n"
            f"Negocio: {company.name} ({company.industry or company.niche}).\n"
            f"Agente auditado: {agent.name} ({agent.role}).\n\n"
            f"SYSTEM PROMPT ACTUAL:\n{agent.system_prompt}\n\n"
            f"SALIDAS REALES RECIENTES:\n{evidence[:6000]}\n\n"
            "Si el prompt actual ya es óptimo, respondé {\"improved_prompt\": \"\"}. "
            "Si podés mejorarlo, respondé ÚNICAMENTE un JSON: "
            '{"improved_prompt": "prompt completo mejorado en español", '
            '"rationale": "qué mejora y por qué, citando las salidas"}. '
            "OBLIGATORIO: conservar todas las reglas de seguridad del prompt actual."
        )
        raw = await complete(
            [{"role": "user", "content": prompt}],
            model=optimizer.model,
            temperature=optimizer.temperature,
            max_tokens=1200,
        )
        parsed = _parse_suggestion(raw)
        if not parsed or parsed["improved_prompt"] == agent.system_prompt:
            continue
        suggestion = PromptSuggestion(
            company_id=company.id,
            agent_id=agent.id,
            old_prompt=agent.system_prompt,
            suggested_prompt=parsed["improved_prompt"],
            rationale=parsed["rationale"],
        )
        db.add(suggestion)
        suggestions.append(suggestion)
    db.commit()
    return suggestions


async def _fetch_page_text(url: str) -> str:
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (MetaBot.OS scanner)"})
        resp.raise_for_status()
        html = resp.text
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text[:8000]


async def _fetch_site(url: str, max_internal: int = 3) -> str:
    """Portada + algunas páginas internas del mismo dominio (catálogo, etc.)."""
    from urllib.parse import urljoin, urlparse

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0 (MetaBot.OS scanner)"})
        resp.raise_for_status()
        html = resp.text
    base = urlparse(str(url))
    links: list[str] = []
    for href in re.findall(r'href=["\']([^"\'#]+)["\']', html):
        full = urljoin(url, href)
        parsed = urlparse(full)
        if parsed.netloc == base.netloc and parsed.path not in ("", "/") and full not in links:
            if not re.search(r"\.(css|js|png|jpe?g|svg|ico|webp|pdf)$", parsed.path, re.I):
                links.append(full)
    def _to_text(h: str) -> str:
        t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", h, flags=re.DOTALL | re.IGNORECASE)
        t = re.sub(r"<[^>]+>", " ", t)
        return re.sub(r"\s+", " ", t)
    parts = [_to_text(html)[:5000]]
    for link in links[:max_internal]:
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
                sub = await client.get(link, headers={"User-Agent": "Mozilla/5.0 (MetaBot.OS scanner)"})
                if sub.status_code == 200:
                    parts.append(f"[{link}] " + _to_text(sub.text)[:2500])
        except httpx.HTTPError:
            continue
    return "\n\n".join(parts)


def _render_segments_report(data: dict) -> str:
    lines = ["## Productos detectados", ""]
    lines += [f"- {p}" for p in data.get("products", [])[:20]] or ["- (sin datos)"]
    lines += ["", "## Segmentos de clientes", ""]
    for s in data.get("segments", []):
        lines += [
            f"### {s.get('name', 'Segmento')}",
            f"- Perfil: {s.get('perfil', '')}",
            f"- Edad: {s.get('edad', '')}",
            f"- Intereses: {s.get('intereses', '')}",
            f"- Ángulo de venta: {s.get('angulo', '')}",
            f"- Formato sugerido: {s.get('formato_sugerido', '')}",
            "",
        ]
    if data.get("insights"):
        lines += ["## Insights", "", str(data["insights"])]
    return "\n".join(lines)


async def run_segment_research(db: Session, company: Company, website: str = "") -> Report:
    """Inteligencia de mercado con datos scrapeados reales: productos,
    segmentos de clientes y ángulo de venta por segmento."""
    if not website:
        try:
            website = json.loads(company.profile or "{}").get("website", "")
        except json.JSONDecodeError:
            website = ""
    site_text = ""
    if website:
        try:
            site_text = await _fetch_site(website)
        except httpx.HTTPError as exc:
            site_text = f"(sitio no accesible: {exc})"
    comp_chunks = []
    for s in db.query(CompetitorSource).filter(CompetitorSource.company_id == company.id).limit(3):
        try:
            comp_chunks.append(f"[{s.label or s.url}] " + await _fetch_page_text(s.url))
        except httpx.HTTPError:
            continue
    if not site_text and not comp_chunks:
        raise ValueError("No hay fuentes para investigar: pasá la web del negocio o cargá competidores.")

    prompt = (
        f"Sos investigador de mercado para {company.name} ({company.industry or company.niche}) "
        "en Paraguay. Con el CONTENIDO REAL scrapeado de abajo (no inventes productos que no "
        "aparezcan), definí los segmentos de clientes para campañas de Meta Ads.\n"
        'Respondé SOLO JSON: {"products": ["producto/marca real detectada", ...], '
        '"segments": [{"name": "nombre corto", "perfil": "quiénes son", "edad": "rango", '
        '"intereses": "para segmentación de Meta", "angulo": "ángulo de venta para este segmento", '
        '"formato_sugerido": "carousel|single|video"}], "insights": "2-3 hallazgos accionables"}. '
        "Entre 3 y 5 segmentos.\n\n"
        f"=== SITIO DEL NEGOCIO ===\n{site_text[:9000]}\n\n"
        + (f"=== COMPETENCIA ===\n{chr(10).join(comp_chunks)[:4000]}" if comp_chunks else "")
    )
    raw = await complete([{"role": "user", "content": prompt}],
                         model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
                         temperature=0.3, max_tokens=2000)
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    data = {}
    if match:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            data = {}
    if not data.get("segments"):
        raise ValueError(f"La investigación no devolvió segmentos válidos: {raw[:200]}")
    now = datetime.now(ZoneInfo(TIMEZONE))
    report = Report(
        company_id=company.id,
        kind="segments",
        title=f"Segmentos y mercado — {now.strftime('%d/%m/%Y')}",
        content=_render_segments_report(data),
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


async def run_competitive_scan(db: Session, company: Company) -> Report | None:
    """Inteligencia Web: lee las páginas de competidores y resume hallazgos."""
    sources = (
        db.query(CompetitorSource).filter(CompetitorSource.company_id == company.id).all()
    )
    if not sources:
        return None
    chunks = []
    for s in sources[:5]:
        try:
            text = await _fetch_page_text(s.url)
            chunks.append(f"--- {s.label or s.url} ---\n{text[:4000]}")
        except httpx.HTTPError as exc:
            chunks.append(f"--- {s.label or s.url} ---\n(no accesible: {exc})")
    prompt = (
        f"Sos analista de mercado para {company.name} ({company.niche}) en Paraguay. "
        "Con el contenido real de estas páginas de competidores, resumí en español: "
        "qué ofrecen, precios visibles (en ₲ si aparecen), promociones, y 2-3 "
        "oportunidades concretas para diferenciarse. No inventes datos.\n\n"
        + "\n\n".join(chunks)
    )
    content = await complete([{"role": "user", "content": prompt}], max_tokens=1200)
    now = datetime.now(ZoneInfo(TIMEZONE))
    report = Report(
        company_id=company.id,
        kind="competitive",
        title=f"Escaneo de competencia — {now.strftime('%d/%m/%Y')}",
        content=content,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report
