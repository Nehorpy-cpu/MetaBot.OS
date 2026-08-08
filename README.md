# MetaBot.OS

Sistema operativo multi-empresa de agentes de IA autónomos para gestión de
campañas Meta Ads y automatización de atención al cliente y agendamiento
médico por WhatsApp. Optimizado para Paraguay: voseo, jopara y Guaraníes (₲).

Documentos de arquitectura en [docs/](docs/).

## Estructura

```
backend/         API FastAPI (Python) — multi-tenant, enjambre de agentes, capa LLM
frontend/panel/  Panel Admin (Vite + React + TS + Tailwind), proxy /api → backend
frontend/reference/  Prototipo de UI original (solo referencia de diseño)
docs/            PDFs de arquitectura
```

## Setup frontend (panel)

```bash
cd frontend/panel
npm install
npm run dev     # http://localhost:5173 (requiere backend en :8000)
```

## Setup backend

```bash
cd backend
python -m venv .venv
.venv/Scripts/activate      # Windows
pip install -r requirements.txt
copy ..\.env.example ..\.env  # completar API keys
uvicorn app.main:app --reload
```

API docs en http://localhost:8000/docs

## Tests

```bash
cd backend
python -m pytest tests/ -v
```

## Proveedores LLM

Capa de abstracción con fallback (todos OpenAI-compatibles):

1. **NVIDIA NIM** — `NVIDIA_API_KEY` (build.nvidia.com)
2. **Groq** — `GROQ_API_KEY` (console.groq.com, free tier)
3. **OpenRouter** — `OPENROUTER_API_KEY` (openrouter.ai, modelos :free)

Se usa el primero configurado; si falla, se intenta el siguiente.

## Roadmap

| Fase | Entregable | Estado |
|---|---|---|
| 0 | Fundaciones: repo, esquema multi-tenant, capa LLM | ✅ |
| 1 | Panel Admin / Super-Configurator | ✅ |
| 2 | CX Bot: motor conversacional con herramientas + simulador | ✅ |
| 2b | Conexión WhatsApp Cloud API (webhook) | ⬜ |
| 3 | Módulo médico: citas, resúmenes diarios | ⬜ |
| 4 | Enjambre completo + Inteligencia Web | ⬜ |
| 5 | Meta Marketing API (campañas) | ⬜ |
| 6 | Voz/jopara ASR + Estudio Visual + Bancar vPOS | ⬜ |

## Reglas del proyecto

- Secretos solo en `.env` (nunca en git, nunca hardcodeados).
- System prompts viven en el servidor, jamás se envían al navegador.
- Montos en Guaraníes como enteros; formato `₲ 1.500.000` en el frontend.
- Zona horaria: America/Asuncion.
- El bot médico nunca da diagnósticos: deriva a consulta presencial.
