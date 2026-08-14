# Canales de WhatsApp

El bot es **el mismo** en los dos canales. Lo único que cambia es por dónde
entran y salen los mensajes, y qué está permitido hacer en cada uno.

En el panel: **Conexiones → Estado de la conexión** dice, paso por paso, qué
falta y dónde se arregla. Antes de tocar nada, mirá eso.

---

## Hoy: WhatsApp Web (QR, Baileys)

Es lo que se usa ahora. El cliente escanea un QR con el WhatsApp del negocio y
listo: sin trámites con Meta, sin verificación de empresa, funcionando en
minutos.

**Cómo se conecta**

1. Panel → Conexiones → elegir *QR — WhatsApp Web*.
2. Botón **Conectar / Generar QR**. El QR aparece en pantalla (tarda ~3s).
3. En el celular del negocio: WhatsApp → **Dispositivos vinculados** →
   *Vincular un dispositivo* → escanear.
4. El estado pasa a `connected` y el bot ya responde.

La sesión queda guardada en el volumen `bridge/sessions/`, así que sobrevive a
reinicios: no hay que reescanear cada vez.

**Lo que este canal NO hace, y por qué**

No es una integración oficial de WhatsApp: es un conector de comunidad que usa
WhatsApp Web. Sirve para **responder a quien escribe primero**.

No manda campañas ni mensajes masivos. No es una limitación técnica —el puente
tiene endpoint de envío— sino una decisión: mandar mensajes no solicitados por
este canal es exactamente lo que hace que **restrinjan el número del cliente**,
y el número es del cliente, no nuestro.

Sí salen avisos que el paciente pidió: el recordatorio de **su propia** cita y
de **su propia** medicación, con horario silencioso (22:00–07:00) y baja
inmediata escribiendo `STOP`.

**Si algo falla**

| Síntoma | Causa probable |
|---|---|
| El QR no aparece | El contenedor `bridge` está caído: `docker compose up -d bridge` |
| Estado `disconnected` y no reconecta | Cerraron la sesión desde el celular. Volver a escanear. |
| Responde a unos sí y a otros no | Otro worker tomó el lease de la sesión. Ver `channel_sessions`. |

---

## Cuando haga falta: Meta Cloud API (oficial)

Es la integración autorizada. Vale la pena cuando el cliente necesita mandar
plantillas aprobadas, volumen alto, o cuando maneja datos sensibles y quiere el
canal formal.

**Ya está todo implementado.** Lo único que falta es conseguir las credenciales
en la consola de Meta.

### Lo que va en el `.env` del servidor (una vez, para toda la plataforma)

```
WHATSAPP_TOKEN=          # token permanente de la app
WHATSAPP_VERIFY_TOKEN=   # lo inventás vos; Meta lo usa al dar de alta el webhook
WHATSAPP_APP_SECRET=     # firma cada mensaje entrante
```

`WHATSAPP_APP_SECRET` **no es opcional**: sin él el webhook rechaza todo. Es a
propósito. Sin firma no hay forma de saber que el mensaje lo mandó Meta y no
cualquiera que conozca la URL, y esa URL termina en los logs de todos lados.

### Lo que va por empresa (en el panel)

**Conexiones → phone_number_id**. Es lo que enruta cada mensaje entrante a la
empresa correcta: una sola app de Meta puede servir a muchos clientes, y el
`phone_number_id` es lo que los distingue. Tiene índice único: dos empresas no
pueden compartirlo.

### Webhook a configurar en Meta

```
https://botscomercio.com/api/webhooks/whatsapp
```

Campo a suscribir: `messages`.

### Antes de publicar la app

Meta pide una **política de privacidad pública**. Todavía no está: es lo que
falta para poder salir de modo desarrollo.

Y para escribirle a alguien fuera de las 24 horas desde su último mensaje hacen
falta **plantillas aprobadas**. Eso bloquea los recordatorios de cita y de
medicación por este canal hasta tenerlas.

---

## Cómo se decide el canal en el código

`Company.wa_mode` es `"none"` | `"qr"` | `"meta"`, y `app/channels.py` define
qué puede hacer cada uno. El motor conversacional no sabe qué canal hay
detrás: recibe un mensaje normalizado y devuelve una respuesta.

Migrar un cliente de QR a Meta no toca agentes, memoria, catálogo ni agenda:
se cambia el modo, se carga el `phone_number_id` y listo.

`channels.can_send_proactive(wa_mode)` es el que decide si un recordatorio
sale o no. Los recordatorios lo consultan antes de enviar, así que activar un
canal que no puede escribir primero no genera envíos fallidos: genera
no-envíos, que es distinto y está registrado.
