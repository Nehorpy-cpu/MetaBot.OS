# Planes y precios

Propuesta derivada del costo **medido**, no estimado. Los números de consumo
salen de `agent_runs` en producción; las tarifas, de la lista publicada de
OpenAI al 15-ago-2026.

> **Los precios son una propuesta, no una tarifa vigente.** Salen del costo más
> margen. Antes de publicarlos hay que contrastarlos con lo que un comercio
> paraguayo paga hoy por un CRM o un sistema de turnos, que es el bolsillo del
> que sale la plata — no con lo que nos cuesta a nosotros.

## Los dos ejes, que no son el mismo

| | Qué decide | Dónde vive |
|---|---|---|
| **Bloques** (`packs.py`) | QUÉ compró: agenda, salud, portal, CFO | ya existía |
| **Plan** (`planes.py`) | CUÁNTO puede usar: mensajes, informes | nuevo |

Un sanatorio grande y una veterinaria chica pueden tener los mismos bloques y
consumos que se diferencian en un orden de magnitud. Meter el volumen adentro
del bloque obligaría a vender "agenda chica" y "agenda grande", que son el
mismo software.

## Lo que cuesta de verdad un turno

Medido el 15-ago-2026, 4 turnos reales del CFO con `gpt-4o-mini`:

```
entrada   4.890 tokens de promedio
salida       97 tokens de promedio
costo     0,00079 USD  ≈  ₲ 6 por mensaje
```

**La entrada es 50 veces la salida**, y ahí está casi todo el gasto. No es un
error: cada turno manda el prompt del sistema con las reglas de todos los
bloques contratados, el esquema de las herramientas, la memoria de la empresa
y el historial de la conversación.

Esto importa para el negocio: la palanca más grande para bajar el costo no es
cambiar de modelo, es **achicar el prompt**. Queda anotado como trabajo
aparte.

> El primer cálculo de estos planes se hizo con 1.200 tokens de entrada —una
> suposición— y daba cuatro veces menos. La prueba de rentabilidad pasaba
> contra un número inventado, que es peor que no tenerla.

## Los planes

| | Prueba | Básico | Profesional | Empresa |
|---|---|---|---|---|
| Mensajes/mes | 200 | 2.000 | 8.000 | 40.000 |
| Informes/mes | 5 | 30 | 150 | 1.000 |
| Números del CFO | 1 | 2 | 6 | 25 |
| Conectores | 1 | 2 | 6 | 20 |
| **Precio/mes** | ₲ 0 | **₲ 350.000** | **₲ 990.000** | **₲ 2.400.000** |
| Clave de OpenAI | nuestra | nuestra | nuestra | **propia** |
| Costo de IA si lo agota | ₲ 1.200 | ₲ 11.600 | ₲ 46.200 | la paga el cliente |
| **La IA se lleva** | — | **3,3%** | **4,7%** | 0% |

Hay una prueba que **falla si el costo de IA de un plan agotado supera el 35%
del precio**. Si mañana OpenAI sube la tarifa o el prompt engorda, la suite
avisa antes que la factura.

### Por qué el plan Empresa exige clave propia

A 40.000 mensajes por mes, que el consumo lo pague la plataforma es regalar el
margen. Con clave propia el cliente le paga directo a OpenAI —sin margen
nuestro encima— y le queda la factura a su nombre, que para una empresa que
declara gastos es una ventaja, no una molestia.

## Qué modelo se eligió, y por qué

El pedido era el de **menor costo pero mejor calidad**. `gpt-4o-mini`, por una
razón medida y no por marca:

- Los modelos gratuitos de Groq **no llaman a la herramienta de forma
  confiable**. El 15-ago-2026, ante "cuánto vendí este mes", `gpt-oss-120b` no
  la llamó en ninguna de las pruebas. Sin esa llamada tampoco corre la
  verificación de permiso: ahí no se pierde un número, **se pierde el control
  de acceso**.
- `gpt-4o-mini` la llamó en el 100% de los turnos.
- Es el más barato de los modelos de OpenAI con esa fiabilidad. Los `-pro`, y
  `gpt-5.6-sol` / `-luna`, cuestan un múltiplo y no aportan nada acá: el CFO
  **narra** un número que ya calculó el servidor.

Están autorizados **tres modelos y nada más** —texto, voz a texto, texto a
voz— con la lista blanca en código.

**La conversación común sigue siendo gratis.** Solo la tarea `finanzas`
arranca con el modelo pago; el resto usa los gratuitos, con una prueba que
falla si alguien mete un modelo pago en la cadena general. Un cliente que
compró solo agenda no paga tokens de OpenAI.

## Cómo se cuenta

Sobre `agent_runs` y `finance_reports`, no sobre contadores propios. Un
contador es una segunda verdad sobre lo mismo, y cuando las dos no coinciden
la que está mal es siempre la del contador: se desincroniza con un reinicio,
con una transacción que revierte, con un borrado manual. Contar filas es más
lento y es correcto.

El mes es el **calendario**, no treinta días móviles: el cliente entiende "se
me reinicia el 1°", y una ventana móvil obliga a explicar por qué ayer podía y
hoy no.

## Qué pasa cuando se agota

Al cliente final —que no sabe que existe un plan y no tiene la culpa— se le
dice: *"Por hoy no puedo seguir contestando por acá. Escribinos de nuevo más
tarde o llamanos y te atendemos."*

Nada de "cuota excedida": eso es vocabulario nuestro y hace quedar mal al
negocio que nos contrató. Hay una prueba que falla si aparece la palabra
"plan", "cuota", "tope" o "límite" en ese mensaje.

Hay además un tope de **40 mensajes por hora por número**, independiente del
plan. Ese no es comercial: es para que un integrador mal escrito o un reenvío
en bucle no se coma el plan de un cliente en una tarde.

## La clave de cada cliente

| Estado | Quién paga | Cómo se llega |
|---|---|---|
| Sin clave propia | la plataforma | por defecto |
| Solicitada | la plataforma | el cliente la pide desde el panel |
| Cargada | el cliente, directo a OpenAI | la carga el admin de la plataforma |

El cliente **pide**, no carga. Hacer que escriba su credencial de OpenAI en un
formulario nuestro sería enseñarle a pegarla en cualquier lado; y una
credencial de un tercero no se carga sola. Se guarda cifrada con el mismo
Fernet de los conectores y no sale por ninguna ruta de la API.

## Lo que falta para poder cobrar

Esto mide y limita; **no cobra**. Para facturar de verdad faltan:

1. Pasarela de pago o registro manual de pagos.
2. Qué pasa al vencer: ¿se corta, se degrada al plan de prueba, hay período de
   gracia? Es una decisión comercial, no técnica.
3. Facturación legal paraguaya (timbrado, RUC, IVA). No está tocado.
