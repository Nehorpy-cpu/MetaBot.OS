# CFO Agent — Seguridad

Del otro lado de este módulo se contestan saldos bancarios por WhatsApp. Este
documento dice qué se defiende, cómo, y qué prueba lo demuestra.

Cada control tiene un test que lo ejerce **desde el lado del atacante**. Un
control sin ese test es una intención.

## 1. Quién pregunta

**El número de WhatsApp no es la identidad: es la primera llave.** Un WhatsApp
se clona, se hereda con un chip reciclado y se pierde en un taxi.

| Control | Dónde | Test |
|---|---|---|
| El número sale de la conversación, nunca de un argumento del modelo | `chat.py`, `conversation.contact_phone` | `test_el_modelo_no_puede_elegir_de_quien_es_la_consulta` |
| Se guarda normalizado a dígitos | `cfo.solo_digitos` | `test_el_numero_se_guarda_normalizado` |
| El permiso es **por empresa**, no por número | `finance_identities` UNIQUE(company_id, phone) | `test_el_mismo_numero_ve_distinto_en_cada_empresa` |
| Un número desconocido no recibe nada | `cfo.autorizar` | `test_un_numero_desconocido_no_consulta_nada` |

## 2. Cuánto pesa la pregunta

Tres niveles en código —no en la base—, porque un cambio en "qué es sensible"
tiene que verse en el diff de un commit. Editarlo desde un panel es cómo se
llega a que el saldo bancario amanezca en riesgo bajo sin que nadie sepa quién
lo movió.

- **Lo que no está clasificado es ALTO.** Una métrica nueva no nace pública.
- **El riesgo de una consulta es el de su PEOR métrica.** "Ventas y saldo
  bancario" no se cuela como consulta baja.
- **El riesgo lo decide el catálogo, no el modelo.** Hay un test que le hace
  declarar `sensitivity: "low"` sobre una métrica media y le pide el PIN igual.

Un test exige que las claves del mapa de riesgo y las del catálogo de métricas
sean **idénticas en los dos sentidos**. Estaban desalineadas y la métrica más
común caía en "sin clasificar → ALTA".

## 3. El PIN

- scrypt, como las contraseñas. **Ni el PIN ni su hash salen de la API**: se
  informa si TIENE, no cuál es.
- **No se guarda escrito.** Cuando el dueño lo manda por chat, el servidor lo
  reconoce, lo guarda tachado, resuelve la consulta pendiente **sin pasar por
  ninguna IA** y responde con plantilla.
- 5 intentos, 15 minutos de bloqueo. Se bloquea **el PIN, no la identidad**:
  un atacante que prueba números no puede dejar al dueño afuera de lo básico.
- El pedido de PIN **vence a los 5 minutos**. Uno que no vence convierte
  cualquier número de cuatro cifras de mañana en un intento.
- **No se abre un pedido de PIN para una métrica de riesgo bajo.** Uno abierto
  ahí se traga cualquier número y encima nunca lo valida.
- **El orden importa**: primero el desconocido, después el techo de
  sensibilidad, y recién al final el PIN. Pedírselo a quien igual no tiene
  permiso le confirma que el número está dado de alta en algún lado.

## 4. El enlace del informe

| Control | Por qué |
|---|---|
| 32 bytes de entropía, `secrets.token_urlsafe` | adivinarlo no es una estrategia |
| Se guarda el **SHA-256**, nunca el token | con acceso de lectura a un respaldo, alguien abriría los informes de todos los clientes |
| **Opaco**: no lleva empresa, teléfono ni fecha | un enlace interceptado no tiene por qué contar de quién es |
| Vence (24 h por defecto) | un enlace eterno es una filtración esperando su momento |
| Revocable | para cuando llegó a quien no debía |
| Un solo uso, opcional | reenviarlo por un grupo deja de ser una filtración |
| **Todos los rechazos son idénticos** | decir "venció" le confirma a quien prueba tokens que acertó uno |
| Snapshot congelado | el dueño lo reenvía a su contador tres días después y los dos ven el mismo número |

El HTML se arma en el servidor con **todo escapado**, sin JavaScript y **sin
una sola petición a otro dominio** — cada una de esas peticiones le contaría a
un tercero que alguien abrió un reporte. Encabezados: `no-store`, `noindex`,
`no-referrer`, `nosniff`, `DENY`, y CSP con `default-src 'none'` y **sin
`script-src`**.

## 5. Aislamiento entre empresas

- `company_id` sale del **path validado contra la membresía**, nunca del body,
  del query ni de un argumento del modelo.
- Claves foráneas **compuestas** `(company_id, id)`: PostgreSQL rechaza el
  cruce, no un `if`.
- El bloque `finance` se gatea **por path** en el middleware: quien sepa la URL
  recibe 402.
- Tests: no se revoca el informe de otra empresa, el listado no muestra
  informes ajenos, el PIN de una empresa no sirve en la otra, los datos de otra
  empresa no entran en el cálculo.

## 6. Lo que la IA no puede hacer

| No puede | Cómo se impide |
|---|---|
| Calcular un número | los montos salen de `cfo_motor.py`; la herramienta devuelve el resultado ya calculado |
| Ejecutar SQL | ninguna herramienta acepta SQL; todo es consulta parametrizada |
| Definir o cambiar una métrica | las fórmulas viven en código; aprobar es un acto administrativo con nombre y fecha |
| Habilitar una métrica | `finance_metric_states`, deny by default |
| Elegir la empresa | sale del contexto autenticado |
| Elegir de quién es la consulta | sale del teléfono de la conversación |
| Declarar el riesgo | sale del catálogo |
| Ver un PIN | nunca entra al historial ni a la llamada |

## 7. Lo que todavía NO está resuelto

Se dice acá y no en una nota al pie:

1. **El número de WhatsApp del sanatorio demo es personal.** El bot contesta a
   cualquiera que le escriba al privado. Para un CFO eso es inaceptable: hay
   que usar una línea dedicada antes de habilitar el bloque en un cliente real.
2. **No hay verificación de segundo canal.** El PIN viaja por el mismo WhatsApp
   que se quiere proteger. Un teléfono comprometido con la sesión abierta pasa
   los dos controles. Mitigado por el vencimiento y el bloqueo, no resuelto.
3. **El informe no pide PIN al abrirse.** Hoy la llave es el único control. Para
   informes de riesgo alto habría que intercambiar el token por una sesión
   corta previo PIN — está diseñado, no construido.
4. **Sin conectores, casi todo es teórico.** Los controles están; los datos que
   protegen todavía no llegaron.
