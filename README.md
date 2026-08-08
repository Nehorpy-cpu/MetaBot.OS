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
bridge/          Puente WhatsApp Web por QR (Node + Baileys) para PyMEs sin Meta API
docs/            PDFs de arquitectura
```

## Canales de WhatsApp (por empresa)

| Modo | Para quién | Cómo |
|---|---|---|
| `qr` | PyMEs sin verificación de Meta | Escanean QR con su WhatsApp Business (bridge Baileys). Solo responde a quien escribe. ⚠️ Canal no oficial: riesgo de restricción del número. |
| `meta` | Empresas con Meta Business verificado | WhatsApp Cloud API oficial (webhook + token) |
| `none` | Pruebas | Solo simulador del panel |

Bridge QR:

```bash
cd bridge
npm install
BRIDGE_SECRET=<mismo-del-.env> npm start   # escucha en :3001
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
| 2b | Webhook WhatsApp Cloud API multi-tenant (falta conectar credenciales) | ✅ |
| 2c | Canal QR (Baileys) por empresa + Centro de Conexiones | ✅ |
| 3 | Módulo médico: recordatorios + export iCalendar | ✅ |
| 4 | Enjambre autónomo: informes Quant, auditoría Guard, competencia, planificador | ✅ |
| 5 | Meta Marketing API (campañas) | ⬜ |
| 6 | Voz/jopara ASR + Estudio Visual + Bancar vPOS | ⬜ |

## Tareas autónomas (planificador, hora de Asunción)

| Cuándo | Qué |
|---|---|
| Lunes 07:00 | Informe semanal del Analista Quant (datos reales, el LLM solo redacta) |
| Diario 20:00 | Auditoría del Guard sobre conversaciones nuevas del CX Bot |
| Diario 18:00 | Recordatorios de citas de mañana por WhatsApp |
| Domingo 06:00 | Escaneo de competencia (URLs cargadas por empresa) |

Desactivable con `SCHEDULER_ENABLED=0`.

## Reglas del proyecto

- Secretos solo en `.env` (nunca en git, nunca hardcodeados).
- System prompts viven en el servidor, jamás se envían al navegador.
- Montos en Guaraníes como enteros; formato `₲ 1.500.000` en el frontend.
- Zona horaria: America/Asuncion.
- El bot médico nunca da diagnósticos: deriva a consulta presencial.
