# CFO Agent — Progreso

Se actualiza al cerrar cada fase, con lo que quedó hecho, lo que se decidió y
lo que quedó bloqueado. La auditoría previa está en
[`CFO_AGENT_AUDITORIA.md`](CFO_AGENT_AUDITORIA.md).

---

## Fase 0 — Auditoría y línea base ✅

**Línea base:** 493 tests verdes, typecheck limpio, build OK, migraciones en
`e9b3c07f4a15`.

**Hallazgo principal:** el prompt describe otro stack (Express/TypeScript,
Firebase, PM2, Redis). Ninguna de sus referencias de archivo existe. Se
implementa el mismo producto contra el stack real (FastAPI, PostgreSQL,
Docker Compose, cola durable propia). Detalle y tabla de equivalencias en la
auditoría.

**Segundo hallazgo:** el modo "Finance Only" **ya estaba construido**. Los
Business Packs con gate por path en el servidor hacen exactamente eso, así
que `finance` es el quinto bloque y no un mecanismo nuevo.

---

## Fase 1 — Fundamentos: quién puede preguntar ✅

**516 tests verdes** (23 nuevos), typecheck limpio, build OK, migración
`f2a4d6b19c53` ensayada contra copia de producción.

### Qué quedó

**El bloque `finance`** (`app/packs.py`). Una empresa puede contratar SOLO el
CFO: no depende de agenda ni de salud. El gate del servidor le cierra todo lo
demás sin una línea nueva — hay test de que una empresa con `finance` recibe
402 en `/doctors` y en `/prescriptions`, y 200 en `/services` (que es núcleo).

Sus reglas de conducta van en el pack, así que el bot las recibe solo:
analista financiero de ESA empresa, nunca asistente general; los números
salen de las herramientas; nunca llamar "utilidad" a un margen o a una
cobranza; siempre el período y la frescura.

**`finance_identities`**: quién puede preguntarle plata al bot.

- El número **no es la identidad**: es la primera llave. Se guarda solo en
  dígitos, porque `+595 981 123-456` y `595981123456` son la misma persona y
  guardarlos distinto deja dos filas con permisos distintos.
- Es **por empresa**. Un dueño de tres negocios tiene un permiso en cada una;
  subirle el techo en la chica no se lo sube en la grande. Hay test.
- **PIN con scrypt**, igual que las contraseñas. Ni el PIN ni su hash salen
  de la API: se informa si TIENE, no cuál es.
- **Bloqueo por fuerza bruta**: 5 intentos y 15 minutos. Se bloquea el PIN y
  **no la identidad**, así que un atacante que prueba números no puede dejar
  al dueño afuera de las consultas básicas.

**Clasificación de riesgo** (`app/cfo.py`), en código y no en la base:

| Riesgo | Ejemplos | Qué exige |
|---|---|---|
| baja | ventas del día, metas, productos más vendidos | número autorizado |
| media | margen, gastos, cuentas por cobrar, inventario valorizado | + PIN |
| alta | saldos bancarios, nómina, impuestos, proyección de caja, utilidad neta | + PIN |

Dos decisiones que sostienen esto:

1. **Lo que no está clasificado es de riesgo ALTO.** Una métrica nueva no
   puede nacer siendo pública porque nadie se acordó de clasificarla.
2. **El riesgo de una consulta es el de su peor métrica.** "Ventas y saldo
   bancario" en un mismo mensaje no se cuela como consulta de riesgo bajo.

Y el orden de las verificaciones importa: primero se descarta al desconocido,
después el techo, y **recién al final se pide el PIN**. Pedirle el PIN a
alguien que igual no tiene permiso le confirma que el número está dado de
alta en algún lado.

**`/api/companies/{id}/cfo/identidades`** (alta, baja, edición, PIN) y
`/cfo/riesgos` (solo lectura). Todo exige `MANAGE_MEMBERS`: dar de alta un
número que consulta saldos es exactamente la operación que un atacante
querría hacer. Cada cambio de permisos va a `audit_log` — sin el PIN, ni
truncado.

### Decisiones

- **No se agrega Redis.** La cola durable en PostgreSQL (`app/jobs.py`) ya da
  idempotencia, backoff, reintentos que sobreviven reinicios y trazabilidad.
- **No se agrega Firebase.** La autenticación propia ya existe y está probada.
- `cfo_conectores` y `cfo_metricas` **no se declararon todavía**: un módulo
  que no gatea ninguna ruta es una casilla vendible de una función que no
  existe. Llegan con sus fases. El test que lo frena ya estaba escrito y
  atajó el intento.

### Bloqueado

- **`OPENAI_API_KEY` no está configurada.** Afecta solo transcripción y TTS
  (Fase 7). El análisis financiero no depende de OpenAI: el router
  multi-proveedor actual sirve.

---

## Fase 2 — Capa semántica y motor de métricas ⏳

Definiciones versionadas (`ventas_netas`, `cobrado`, `margen_bruto`…) con
fórmula, fuentes, vigencia y aprobación; motor de cálculo determinístico en
guaraníes enteros reutilizando `app/aranceles.py`. Recién cuando una métrica
esté definida y probada se habilita su herramienta.
