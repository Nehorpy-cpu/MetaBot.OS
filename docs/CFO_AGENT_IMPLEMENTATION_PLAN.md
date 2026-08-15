# CFO Agent — Plan de implementación

Once fases. Una fase termina cuando **corre en producción con pruebas verdes**,
no cuando el código está escrito.

Estado al 15-ago-2026: **fases 1 a 5 terminadas**, 584 pruebas verdes.

## Terminadas

### Fase 1 — Identidad y permisos
Quién puede preguntar, hasta dónde ve, y el PIN para lo sensible.
`finance_identities`, `cfo.py`, migración `f2a4d6b19c53`.
Cierra con: un número desconocido no recibe nada; el mismo número ve distinto
en cada empresa; el PIN nunca sale de la API.

### Fase 2 — Catálogo de métricas
Diez métricas versionadas, con fórmula en castellano, fuentes, exclusiones y
advertencias contables. `cfo_metricas.py`.
Cierra con: las claves del mapa de riesgo y las del catálogo coinciden en los
dos sentidos (una prueba lo exige; estaban desalineadas).

### Fase 3 — Aprobación y vigencia
Deny by default: lo que nadie aprobó no se calcula. Queda quién, qué versión y
desde cuándo. `finance_metric_states`, migración `a7c3e91d24f8`.

### Fase 4 — El motor
El único lugar donde nace un monto. Verifica que la métrica exista, esté
aprobada y vigente, y que sus fuentes estén conectadas; si no, devuelve **el
motivo**, nunca un cero. `cfo_motor.py`.
Cierra con: cero-sin-registros y cero-con-registros se distinguen.

### Fase 5 — El informe privado
Snapshot congelado + llave opaca que vence, se revoca y opcionalmente sirve una
sola vez. `cfo_reportes.py`, `routers/reportes.py`, migración `c8d3f5b21e94`.
Cierra con: 20 pruebas escritas desde el lado del atacante; ensayo de migración
sobre copia de producción, con downgrade y re-upgrade; PostgreSQL rechaza una
llave que apunte al informe de otra empresa.

## Pendientes

### Fase 6 — Conectores y frescura de datos
REST, PostgreSQL y CSV. Cada número dice **de cuándo** son los datos: un
informe con datos de hace nueve días y sin decirlo es peor que no tenerlo.
Es la fase que vuelve útil al módulo: hoy la única fuente es interna.

### Fase 7 — Audio
Nota de voz entra, resumen hablado sale. **Bloqueada**: requiere una clave de
OpenAI válida para transcripción y TTS.

### Fase 8 — Memoria por empresa
Qué pregunta siempre este dueño, qué le importa, qué ya le explicamos.
Con olvido y borrado a pedido: memoria financiera que no se puede borrar es un
pasivo.

### Fase 9 — Mejora gobernada
El agente propone mejoras a su propio prompt y catálogo; **nadie las aplica
solo**. `CFO_ALLOW_AUTOMATIC_INSTALL/MERGE/DEPLOY = False`, en código.

### Fase 10 — Panel del CFO
Alta de identidades, aprobación de métricas, informes emitidos y sus aperturas,
y la bandeja "Por mejorar / Sugerencias".

### Fase 11 — Endurecimiento
Límite de consultas por número, pruebas de carga sobre `/r/{token}`, rotación
de llaves, y el repaso final completo.

## Lo que no se va a hacer

- **Que el modelo calcule.** Ni con verificación posterior.
- **Definir métricas desde el panel.** Una fórmula financiera se cambia con un
  commit revisable, no con un formulario.
- **Consejo de inversión.** El módulo informa; no recomienda dónde poner plata.
- **Que el agente se despliegue solo.** Propone; aplica una persona.
