# CFO Agent — Arquitectura

## El recorrido de una pregunta

El dueño escribe `¿cómo vengo este mes?` al WhatsApp de su empresa. De ahí
hasta la respuesta hay seis pasos, y ninguno los hace el modelo salvo el
penúltimo.

```
WhatsApp ──> chat.py ──> cfo.autorizar() ──> cfo_motor.calcular() ──> LLM ──> respuesta
             (canal)     (quién y cuánto)     (el número)          (redacta)  (+ enlace)
```

1. **Canal.** El teléfono sale de la conversación, no de un argumento del
   modelo. Un modelo que puede elegir de quién es la consulta puede ser
   convencido de elegir mal.
2. **Identidad y permiso.** `cfo.autorizar()` responde tres cosas en este
   orden: ¿este número existe en esta empresa? ¿la métrica está por debajo de
   su techo? ¿hace falta PIN? El orden no es estético — está en
   `CFO_AGENT_SECURITY.md`.
3. **Cálculo.** `cfo_motor.calcular()` es el **único** lugar del sistema donde
   nace un monto financiero. Devuelve el número o el motivo por el que no hay
   número. Nunca un cero de relleno.
4. **Redacción.** El LLM recibe el resultado ya calculado y lo cuenta en
   castellano paraguayo. No suma, no divide, no completa.
5. **Entrega.** El resumen va por WhatsApp; el detalle, en un enlace privado
   que vence.

## Los módulos y qué responde cada uno

| Archivo | La única pregunta que contesta |
|---|---|
| `cfo_metricas.py` | ¿Qué significa esta métrica y de dónde sale? |
| `cfo.py` | ¿Quién pregunta y hasta dónde puede ver? |
| `cfo_motor.py` | ¿Cuánto da, o por qué no da? |
| `cfo_reportes.py` | ¿Cómo se entrega sin que lo lea un tercero? |
| `routers/cfo.py` | ¿Cómo lo administra el dueño desde el panel? |
| `routers/reportes.py` | ¿Cómo se abre un enlace sin sesión? |
| `packs.py` | ¿Esta empresa contrató finanzas? |

Un archivo que contesta dos preguntas termina contestando mal las dos. La
regla se nota en `cfo_motor.py`: no sabe de permisos, y `cfo.py` no sabe
sumar.

## Las tres decisiones que sostienen todo

### 1. El catálogo manda, el modelo interpreta

Una métrica es una entrada versionada en `CATALOGO`: fórmula en castellano,
fuentes que necesita, qué excluye, qué advertir. El modelo no puede crear una,
cambiarla ni declararla menos sensible.

Esto es lo que separa un asistente de un CFO. Un asistente contesta
`₲ 12.400.000`. Un CFO contesta `₲ 12.400.000, que son atenciones cobradas
entre el 1 y el 31, sin las canceladas, y no es facturación contable`. La
segunda respuesta se puede discutir; la primera solo se puede creer.

### 2. Aprobar es un acto administrativo

`finance_metric_states` guarda quién aprobó qué versión de qué métrica, desde
cuándo. Deny by default: una métrica que nadie aprobó **no se calcula**, ni
siquiera si el modelo la pide y hay datos para hacerlo.

Sirve para lo que va a pasar de verdad: alguien discute un número de hace tres
meses. Con la vigencia se sabe qué definición estaba activa ese día, y si
cambió, se ve el cambio y quién lo hizo.

### 3. No calculable ≠ cero

`₲ 0` significa "no vendiste nada". "No se pudo calcular" significa "no sé".
Confundirlos es cómo un sistema financiero pierde la confianza de golpe: el
dueño ve un cero, se asusta o se confía, y después descubre que faltaba
conectar una fuente. El motor distingue los dos casos y el informe también.

## Dónde se apoya en lo que ya existía

El CFO **no** trajo infraestructura nueva. Reutiliza:

- la **autenticación** y la membresía por empresa (`auth.py`, middleware);
- el **gate por bloques** — `finance` es un pack como `booking`;
- la **cola durable** en PostgreSQL para lo que corre solo;
- la **auditoría** (`audit()`), donde queda cada alta, cada aprobación y cada
  informe emitido;
- el **canal de WhatsApp** ya construido, con su dedup y su lease.

Lo único propio es el router `/r/{token}`, que va **fuera de `/api`** porque no
hay sesión: la llave es la autorización.

## Modelo de datos

```
companies
   ├── finance_identities        quién puede preguntar (teléfono, techo, PIN)
   ├── finance_metric_states     qué métricas están aprobadas y desde cuándo
   ├── finance_sessions          consulta pendiente de PIN (vence a los 5')
   └── finance_reports           el SNAPSHOT congelado
         └── finance_report_tokens   hash de la llave, vencimiento, aperturas
```

Todas cuelgan de `company_id` y usan claves foráneas **compuestas**: el cruce
entre empresas lo rechaza PostgreSQL, no un `if` que alguien puede borrar.

## Lo que falta para que esto valga

Hoy la única fuente es interna (atenciones). El módulo está completo de la
mitad para arriba —permisos, catálogo, motor, entrega— y vacío de la mitad
para abajo. La Fase 6 (conectores) es la que lo vuelve útil: sin ventas
reales, gastos y bancos, el CFO puede contestar bien tres preguntas de diez.
