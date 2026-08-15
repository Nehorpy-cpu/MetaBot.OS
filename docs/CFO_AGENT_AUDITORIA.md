# CFO Agent — Auditoría previa (Fase 0)

Fecha: 15-ago-2026. Ejecutado antes de escribir una línea del módulo.

## 1. Línea base

| Comprobación | Resultado |
|---|---|
| `pytest tests/` | **493 pasan**, 0 fallan, 5 warnings (91 s) |
| `tsc --noEmit` (panel) | limpio, exit 0 |
| `vite build` | OK, 332 kB / 90 kB gzip (1,25 s) |
| Migraciones | `e9b3c07f4a15 (head)`, aplicada en producción |

Nada roto al empezar. Cualquier fallo posterior es del módulo nuevo.

## 2. La diferencia que hay que resolver primero

El prompt describe un sistema que **no es este**. No son nombres que
evolucionaron: es otro lenguaje, otro framework, otra base y otro despliegue.
Se verificó archivo por archivo.

| El prompt dice | Verificación | Lo que hay de verdad |
|---|---|---|
| Backend Express + TypeScript, `server.ts` | `server.ts` no existe | **FastAPI + Python 3.12**, `backend/app/main.py` |
| Puerto 3000, `dist/server.cjs` | no existe | uvicorn en contenedor, expuesto por Caddy |
| PM2, `ecosystem.config.cjs` | no existe | **Docker Compose**: backend, db, bridge, n8n, caddy |
| Firebase Auth + Firestore | `firebase.json`, `firestore.rules` no existen | **PostgreSQL 16** + sesión propia en cookie `HttpOnly` (`app/auth.py`, tablas `users`, `auth_sessions`, `memberships`) |
| `tenantId` | — | **`company_id`** (entero), en toda tabla de negocio |
| Roles ADMIN / ASESOR, `advisorId` | — | `owner`, `admin`, `operator`, `viewer`, `professional` (`app/permissions.py`) |
| `WhatsAppSessionManager.ts`, `WhatsAppProcessLock.ts`, `WhatsAppDisconnectClassifier.ts`, `src/lib/whatsapp.ts` | ninguno existe | **`bridge/src/server.js`**: un solo archivo Node con Baileys, lock, heartbeat y TTL |
| `WhatsAppInboxView.tsx`, `WhatsAppConnectionStatus.tsx` | no existen | `views/ChatView.tsx`, `views/ConnectionsView.tsx` |
| Redis + BullMQ | no hay Redis | **cola durable en PostgreSQL** (`app/jobs.py`): lease, dedup_key, backoff exponencial, reintentos que sobreviven reinicios |
| OpenAI Responses API, `gpt-5.6-luna/terra/sol` | no hay `OPENAI_API_KEY` | router propio multi-proveedor OpenAI-compatible (`app/llm.py`): Groq, NVIDIA, OpenRouter, Gemini |

Lo único que coincide: **React 18 + Vite** en el panel, y **Baileys** para
WhatsApp.

### Qué se hace con esto

Se implementa **el mismo producto** contra el stack real. El prompt describe
un QUÉ (agente CFO por WhatsApp, Finance Only, reportes privados, memoria por
tenant, mejora gobernada) que es perfectamente construible acá; lo que no se
puede seguir es el CÓMO, porque describe otra máquina.

Traducción de términos que se usa en todo el módulo:

```
tenantId          → company_id
Firestore         → PostgreSQL (tablas del plano de control)
BullMQ + Redis    → app/jobs.py (cola durable en PostgreSQL)
Express router    → APIRouter de FastAPI
PM2 process       → servicio de docker-compose
Firebase Auth     → app/auth.py (sesión opaca revocable)
```

**No se agrega Redis ni Firebase.** Sería meter dos infraestructuras nuevas
para reemplazar dos que ya funcionan y están probadas. La cola de Postgres se
eligió a conciencia en su momento y tiene las garantías que el prompt pide
(idempotencia, reintentos, backoff, dead-letter, trazabilidad).

## 3. Lo que el prompt pide y YA ESTÁ CONSTRUIDO

Esto es lo más importante del informe: buena parte de la sección 3 del prompt
—el modo "Finance Only"— existe y está desplegado.

**Business Packs** (`app/packs.py`) hace exactamente lo que el prompt describe
como `enabledModules`:

- una empresa contrata bloques (`core`, `booking`, `healthcare`,
  `practitioner`) y `Company.packs` guarda cuáles;
- cada bloque habilita módulos del panel, herramientas del bot y reglas de
  conducta;
- **el corte se aplica en el servidor, por path**, en el middleware de
  `app/main.py`: una empresa que no compró un bloque recibe 402 con
  `codigo: "modulo_no_contratado"`, aunque sepa la URL;
- un test recorre las 64 rutas de empresa del app real y **falla si alguna
  quedó sin clasificar**;
- la cola de trabajos también respeta los bloques: no se encola un envío de un
  bloque que la empresa no tiene;
- el panel esconde lo no contratado y ofrece comprarlo.

Por eso **`finance_cfo` no es un sistema de módulos nuevo: es el quinto
bloque**. Una empresa con `packs = "core,finance"` ya queda en Finance Only
por construcción, con el gate del servidor incluido.

Otras piezas que el prompt pide y existen:

| Pide | Existe |
|---|---|
| Aislamiento multiempresa | claves foráneas **compuestas** `(company_id, id)`: PostgreSQL rechaza un cruce, no un `if` |
| `tenantId` nunca desde el cliente | middleware `enforce_auth_and_tenant`; el id sale del path y se valida contra la membresía |
| Cola con idempotencia, backoff, DLQ | `app/jobs.py` |
| Router de modelos con fallback | `app/llm.py` (`cadena_para`, sin sustitución silenciosa) |
| Auditoría de quién hizo qué | tabla `audit_log` + helper `auth.audit()` |
| Aritmética de dinero exacta | `app/aranceles.py`, guaraníes **enteros**, nunca float |
| Reglas de conducta por bloque inyectadas al prompt | `packs.rules_for()` |
| El modelo no ejecuta SQL libre | ninguna herramienta acepta SQL; todo son consultas parametrizadas |

## 4. Riesgos encontrados

1. **No hay `OPENAI_API_KEY`.** Transcripción (§6) y TTS (§6.3) dependen de
   ella. Se implementa la interfaz, las variables y los mocks; queda
   documentado el bloqueo. El análisis financiero **no** depende de OpenAI:
   el router actual sirve.
2. **Los modelos `gpt-5.6-luna/terra/sol` no se pueden verificar** desde acá.
   Van como variables de entorno configurables, sin hardcodear, y el router
   ya sabe fallar al siguiente candidato sin sustituir en silencio.
3. **El plan gratuito de Groq no aguanta una conversación**: 429 al cuarto
   mensaje, y un turno tardó 110 s cayendo por la cadena de respaldo. Un CFO
   que tarda dos minutos no se usa. Es una decisión comercial pendiente.
4. **`llama-3.3-70b-versatile` falla 3 de 3 con 400** (determinístico). Ya se
   instrumentó el log para ver el motivo del proveedor; falta el diagnóstico.
5. **El número de WhatsApp conectado es personal.** El bot responde a
   cualquiera que le escriba al privado. Para un CFO —que contesta saldos—
   eso es inaceptable: la identidad autorizada (§4.1) es obligatoria antes de
   habilitar el bloque en un cliente real.
6. **No hay almacenamiento de objetos (S3)** ni Redis. El PDF/XLSX de §15.5 se
   resolverá contra el disco del contenedor con volumen, o se pospone.

## 5. Plan por fases (adaptado al stack real)

| Fase | Contenido | Estado |
|---|---|---|
| 0 | Auditoría y línea base | **hecha** (este documento) |
| 1 | Bloque `finance`, identidad autorizada por WhatsApp, clasificación de riesgo, PIN, migración | **en curso** |
| 2 | Capa semántica: definiciones de métricas versionadas + motor de cálculo determinístico | |
| 3 | Herramientas financieras (catálogo §9) sobre datos propios del sistema | |
| 4 | Flujo por WhatsApp: identidad → riesgo → PIN → encolado → respuesta | |
| 5 | Reporte HTML privado: snapshot, token opaco, sesión corta, revocación | |
| 6 | Conectores (REST, PostgreSQL, CSV) + frescura de datos | |
| 7 | Audio: transcripción y TTS (bloqueado por credencial) | |
| 8 | Memoria por capas con scoping por empresa | |
| 9 | Improvement Scout + registro de Skills, sin despliegue automático | |
| 10 | Panel de administración del CFO + "Por mejorar / Sugerencias" | |
| 11 | Endurecimiento, pruebas de seguridad, despliegue | |

Cada fase termina con: pytest verde, typecheck limpio, build OK, y este
documento y `CFO_AGENT_PROGRESS.md` actualizados.

## 6. Lo que NO se va a hacer, y por qué

- **No se migra a Express/TypeScript, Firebase ni PM2.** Reescribir un sistema
  probado y en producción para que coincida con la descripción sería tirar el
  trabajo hecho y todas sus garantías.
- **No se agrega Redis.** La cola durable en PostgreSQL ya da lo que se pide.
- **No se instala nada automáticamente** desde el Improvement Scout, ni se
  despliega, ni se fusiona una rama: las variables `CFO_ALLOW_AUTOMATIC_*`
  nacen en `false` y el código no tiene el camino para ponerlas en `true`.
- **No se borra ninguna función existente** para simplificar el módulo.
