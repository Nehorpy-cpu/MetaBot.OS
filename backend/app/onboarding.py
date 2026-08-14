"""Arquitecto de Negocio: perfila cualquier empresa y arma su enjambre a medida.

Con nombre + descripción (y opcionalmente la web del negocio), el LLM detecta
rubro, productos, audiencia y tono, y redacta los system prompts de los 7
agentes adaptados a ese negocio. El consultorio médico es solo un caso más:
si detecta rubro de salud, activa además el módulo de agenda.
"""
import json
import re

from sqlalchemy.orm import Session

from . import packs
from .llm import complete
from .models import Agent, Company
from .templates import TEMPLATES

AGENT_SLUGS = ["ceo", "quant", "guard", "creative", "visual", "cx", "optimizer"]

AGENT_ROLES = {
    "ceo": ("CEO (Orquestador)", "Estrategia general y coordinación del enjambre"),
    "quant": ("Analista Quant", "Métricas, reportes y rendimiento del negocio"),
    "guard": ("Auditor de Calidad", "Cumplimiento normativo y control de calidad"),
    "creative": ("Director Creativo", "Copywriting y campañas"),
    "visual": ("Estudio Visual", "Imágenes y creativos de marca"),
    "cx": ("CX Bot", "Atención al cliente 24/7 por WhatsApp"),
    "optimizer": ("Optimizador de Prompts", "Audita y mejora los prompts del resto de agentes"),
}

PROFILE_PROMPT = """Sos el Arquitecto de Negocio de MetaBot.OS, un sistema de agentes IA
para empresas de Paraguay. Con los datos de abajo, perfilá el negocio y diseñá
los system prompts de sus 7 agentes.

Respondé ÚNICAMENTE un JSON con esta forma exacta:
{{
  "industry": "rubro específico en español",
  "vertical": "medical" si es salud (clínica, consultorio, odontología, veterinaria con turnos) — si no, una palabra corta en inglés para el rubro (ecommerce, gastronomy, services, education, retail, beauty, construction, other),
  "niche": "descripción corta del nicho",
  "products": ["producto o servicio 1", "..."],
  "audience": "público objetivo",
  "tone_notes": "notas de tono para este rubro",
  "agents": {{
    "ceo": "system prompt...", "quant": "...", "guard": "...", "creative": "...",
    "visual": "...", "cx": "...", "optimizer": "..."
  }}
}}

Reglas para TODOS los prompts de agentes (en español):
- FORMATO OBLIGATORIO: cada prompt es un SYSTEM PROMPT de identidad permanente,
  NUNCA una tarea puntual. Empieza con "Sos ..." (identidad y rol), luego describe
  su comportamiento continuo, sus reglas y su tono. Entre 300 y 700 caracteres.
  Incluye el nombre del negocio. MAL: "Generá un plan de expansión..." (tarea).
  BIEN: "Sos el CEO autónomo de X. Coordinás..., priorizás..., siempre...".
- Voseo paraguayo y jopara sutil donde aplique al trato con clientes.
- Montos siempre en Guaraníes (₲) con puntos de miles.
- Específicos del rubro detectado: mencionar productos/servicios reales del negocio.
- El "cx" atiende WhatsApp: mensajes cortos, una pregunta por vez, nunca inventa
  datos, escala a humano cuando no sabe. Si el rubro es salud: JAMÁS diagnósticos,
  siempre derivar a consulta.
- El "guard" define qué está prohibido en este rubro específico.
- El "optimizer" audita las salidas de los demás agentes y propone mejoras de prompts.

NEGOCIO:
Nombre: {name}
Descripción: {description}
{website_context}"""


def _parse_profile(raw: str) -> tuple[dict | None, str]:
    """Devuelve (perfil, motivo de rechazo)."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return None, "no hay JSON en la respuesta"
    try:
        data = json.loads(match.group())
    except json.JSONDecodeError as exc:
        return None, f"JSON inválido: {exc}"
    agents = data.get("agents") or {}
    for slug in AGENT_SLUGS:
        prompt = agents.get(slug)
        if not isinstance(prompt, str) or len(prompt) < 150:
            return None, f"el prompt de '{slug}' es muy corto o falta (mínimo 150 caracteres)"
        if "sos" not in prompt[:80].lower():
            return None, (
                f"el prompt de '{slug}' no define identidad permanente: debe empezar "
                "con 'Sos ...' describiendo rol y comportamiento continuo, no una tarea puntual"
            )
    return data, ""


async def profile_and_create(
    db: Session, name: str, description: str, website_text: str = "", website: str = ""
) -> Company:
    website_context = f"Contenido de su web:\n{website_text[:3000]}" if website_text else ""
    base_prompt = PROFILE_PROMPT.format(
        name=name, description=description, website_context=website_context
    )
    profile = None
    reason = ""
    for attempt in range(2):
        content = base_prompt
        if attempt and reason:
            content += (
                f"\n\nTU INTENTO ANTERIOR FUE RECHAZADO: {reason}. "
                "Corregilo y respondé de nuevo el JSON completo."
            )
        raw = await complete(
            [{"role": "user", "content": content}],
            model="nvidia/llama-3.3-nemotron-super-49b-v1.5",
            temperature=0.3,
            max_tokens=3500,
        )
        profile, reason = _parse_profile(raw)
        if profile:
            break
    if not profile:
        raise ValueError(f"El Arquitecto no devolvió un perfil válido: {reason}")

    vertical = str(profile.get("vertical", "other"))[:20] or "other"
    company = Company(
        name=name,
        vertical=vertical,
        # Business DNA → Business Packs: qué capacidades se activan
        packs=packs.packs_iniciales(vertical),
        niche=str(profile.get("niche", ""))[:200],
        industry=str(profile.get("industry", ""))[:200],
        profile=json.dumps(
            {
                "description": description,
                "website": website,
                "products": profile.get("products", []),
                "audience": profile.get("audience", ""),
                "tone_notes": profile.get("tone_notes", ""),
            },
            ensure_ascii=False,
        ),
    )
    db.add(company)
    db.flush()

    # Modelos por defecto: los mismos verificados de las plantillas estáticas
    base_models = {a["slug"]: a["model"] for a in TEMPLATES["medical"]["agents"]}
    base_models.setdefault("optimizer", "nvidia/llama-3.3-nemotron-super-49b-v1.5")
    temps = {"ceo": 0.3, "quant": 0.3, "guard": 0.1, "creative": 0.6, "visual": 0.4, "cx": 0.3, "optimizer": 0.2}

    for slug in AGENT_SLUGS:
        agent_name, role = AGENT_ROLES[slug]
        db.add(
            Agent(
                company_id=company.id,
                slug=slug,
                name=agent_name,
                role=role,
                model=base_models.get(slug, "nvidia/llama-3.3-nemotron-super-49b-v1.5"),
                system_prompt=profile["agents"][slug].strip(),
                temperature=temps[slug],
            )
        )
    db.commit()
    db.refresh(company)
    return company
