# MetaBot.OS — Arquitectura v1

MetaBot.OS **no** es un sistema para clínicas al que se le agregan rubros.
Es un **Business Agent OS multiempresa**: un núcleo genérico sobre el que
perfumería, clínica, inmobiliaria, agencia de viajes, concesionaria,
restaurante o estudio jurídico son **configuraciones distintas** (Business
Packs), no forks del código.

```
 WhatsApp QR ─┐
 WhatsApp API ─┤
 Instagram ────┤
 Webchat ──────┤──> OMNICHANNEL GATEWAY
 Messenger ────┤
 Voz ──────────┤
 Email ────────┘
                        │
                        ▼
              Identity + Tenant Router
                        │
              ┌─────────┴─────────┐
              │ Conversation Core │
              │ Memory + Context  │
              └─────────┬─────────┘
                        ▼
                  CEO ORCHESTRATOR
                        │
       ┌────────────────┼─────────────────┐
      CX             Creative          Quant
       ├────── Visual/Multimedia ─────────┤
       ├──────── Quality/Guard ───────────┤
       └──────── Evaluator/Trainer ───────┘
                        ▼
                 MCP / TOOL GATEWAY
       (Catalog · Calendar · Payments · CRM · Meta · Scraping)
                        ▼
                TEMPORAL WORKFLOWS
                        ▼
                 TENANT DATA VAULT
```

## Principios innegociables

1. **El aislamiento entre tenants vive en la capa de datos**, no en la
   disciplina del programador. Nadie debe poder olvidarse un `WHERE
   company_id`. El `tenant_id` sale de la identidad autenticada y **jamás**
   de un dato enviado por el frontend.
2. **El LLM recomienda; el catálogo confirma.** Un modelo nunca inventa
   precio, stock, producto, promoción ni característica comercial.
3. **Nada de lock-in.** Todo proveedor externo (modelo, imagen, pago,
   catálogo, canal, inteligencia) entra detrás de un contrato propio.
   Se elige por resultados en evals, no por marca.
4. **Lo que no se puede perder va a workflows durables** (citas,
   recordatorios, cobros, webhooks pendientes). n8n queda para
   integraciones laterales, nunca para estado crítico.
5. **Honestidad comercial**: el conector QR (Baileys) no es una integración
   oficial de WhatsApp y se presenta como tal al cliente.

## Contratos del núcleo

| Contrato | Implementaciones | Estado |
|---|---|---|
| `ChannelConnector` | WhatsApp QR (Baileys), WhatsApp Cloud API | ✅ v1 |
| `ModelRouter` | NVIDIA NIM, Groq, OpenRouter, Gemini | ✅ v1 |
| `ImageProvider` | NVIDIA Flux, Pollinations, (Gemini Image) | ✅ parcial |
| `CatalogSource` | WebsiteCrawler, CustomAPI, (Woo/Shopify/CSV/ERP) | ✅ parcial |
| `PaymentProvider` | (Bancard Tpago, vPOS, Transfer, CashOnDelivery) | ⬜ |
| `IntelligenceSource` | Web público, (Meta Ad Library) | ✅ parcial |
| `AgentRuntime` | propio (in-house), (ADK como implementación) | ⬜ |

## Capabilities por canal

Cada conector declara qué puede hacer, técnica y legítimamente:

```
can_reply · can_send_media · can_send_catalog · can_send_template
can_send_proactive · can_receive_voice · can_receive_images · can_receive_location
```

El cerebro no sabe qué WhatsApp hay detrás: recibe un `InboundMessage`
normalizado y responde con un `OutboundMessage`. Migrar un cliente de QR a
Cloud API no toca agentes, memoria, catálogo ni automatizaciones.

## Dos memorias, nunca mezcladas

- **TenantMemory** — clientes, conversaciones, ventas, catálogo privado,
  doctores, precios, prompts y documentos de **esa** empresa.
- **IndustryKnowledge** — solo información pública, plantillas y patrones
  reutilizables entre empresas del mismo rubro. Cuando entra otra
  perfumería, el sistema **sugiere** campos y servicios típicos; el dueño
  acepta, modifica o descarta.

## Business DNA

Al dar de alta una empresa no se pregunta solo nombre y rubro: se analiza
su web y fuentes públicas para inferir modelo de negocio, catálogo,
moneda, mercado, estilo de venta y **necesidades detectadas**, y con eso se
propone el **Business Pack** correspondiente (Commerce, Booking,
Healthcare, Travel…).

## Cumplimiento

- **Ley 7593/2025 (Paraguay)**: datos de salud, genéticos y biométricos son
  sensibles. Privacidad desde el diseño, seguridad, evaluación de impacto.
- **Bot médico**: no diagnostica, no modifica indicaciones, no reemplaza al
  profesional. Triaje administrativo, agenda, preparación de estudios y
  derivación. Ante lo que excede su autoridad → escalamiento a humano.

## Supervisión del CEO (`app/supervisor.py`)

El CEO **nunca corre antes del CX**. Corre después, y solo si el propio
resultado del CX muestra que el turno salió mal. La ruta rápida —la del
cliente esperando en WhatsApp— no paga nada.

Esto contradice el diseño intuitivo (clasificar la intención y rutear), y
la razón es medible: la línea base de una respuesta con herramientas es de
**~61 segundos**. Cualquier llamada al modelo *antes* de responder la
duplica. Detectar que un turno salió mal, en cambio, es determinístico y
gratis: se lee de variables que el motor ya tiene resueltas.

**Tres modos por empresa** (`Company.supervision`):

| Modo | Qué hace |
|---|---|
| `off` | Default de toda empresa. Comportamiento byte a byte el de hoy: los disparadores ni se evalúan. |
| `shadow` | Analiza fuera del camino del cliente. Nunca toca la respuesta de este turno ni escala. Deja una directiva para el turno siguiente. |
| `inline` | Además puede reescribir la respuesta antes de enviarla y escalar. |

**Disparadores** — expresados sobre HERRAMIENTAS y PACKS, nunca sobre
`company.vertical`. Se dispara como mucho uno por turno (el de mayor
prioridad), porque supervisar dos cosas gasta el doble sin valer el doble.
El modo de cada disparador es un **techo**: `catalog_miss` se analiza en
shadow aunque la empresa esté en inline. Perder una venta no justifica el
riesgo de reescribirle el mensaje al cliente; una indicación clínica sí.

**Anti-bucle, por construcción y no por promesa**: el supervisor es un
asesor sin herramientas (`tools=None`), así que estructuralmente no puede
reentrar al motor; corre una vez por turno; hay presupuesto por
conversación (3/24h) y por empresa (200/día); pausar el agente en el panel
lo apaga; y `off` lo apaga entero.

**El veredicto pasa por guardias determinísticas** antes de tocar nada:
acción dentro del enum, largo acotado, sintaxis de herramienta saneada y
—lo más importante— ninguna cifra que no esté en la respuesta del CX o en
el resultado de las herramientas. Todo lo que no se puede validar termina
en `keep`: ante la duda se envía lo que el CX ya había producido, que es
exactamente lo que pasaría sin supervisión.

**Brazo de control**: `supervision_pct` deja a propósito un porcentaje de
conversaciones sin supervisar, con el disparo igual registrado. Sin eso no
hay forma de responder la única pregunta que importa antes de activar
`inline`: ¿supervisar mejora las respuestas o solo agrega costo?

> Nota: `app/intents.py` (taxonomía de intención) **no** participa de este
> camino. Se construyó pensando en rutear por intención y el análisis
> mostró que rutear así es justamente lo que duplica la latencia. Queda
> disponible para analítica e informes, no para decidir.

## Métricas que definen el éxito

No "cantidad de agentes" ni "cantidad de modelos": conversaciones
resueltas, ventas generadas, citas correctamente agendadas, tasa de error,
alucinaciones, conversión, costo por conversación, latencia, cumplimiento
e intervenciones humanas necesarias. Una tecnología entra si gana en los
evals; no por ser nueva.

## Suite de pruebas obligatoria por release

Aislamiento tenant A/B · roles · prompt injection · permisos de
herramientas · replay de webhooks · duplicación de mensajes de WhatsApp ·
desconexión/reconexión QR · dos workers sobre la misma sesión · stock
concurrente · reserva simultánea del mismo horario · recordatorios tras
reinicio · pago repetido · callback falso · RAG poisoning · URLs
maliciosas · fuga de secretos · regresión de prompts · fallback de modelos.

## Orden de construcción

1. **MetaBot Core** — PostgreSQL multi-tenant, migraciones, aislamiento en
   capa de datos, Agent Runtime, MCP Gateway, Model Router, audit log,
   permisos, Super-Configurator.
2. **WhatsApp Connectors** (Cloud + QR) para poder conversar desde el día 1.
3. **ARFAGI Commerce Pilot** — catálogo autoimportado, búsqueda semántica,
   imágenes, stock, vendedor CX, pedidos y recomendaciones.
4. **Booking Engine + Healthcare Pack**.
5. **Industry Intelligence + Evaluator/Trainer** (shadow → canary → prod).
6. **Meta / Social Studio**.
7. **Voz avanzada, pagos y multimodalidad**.
