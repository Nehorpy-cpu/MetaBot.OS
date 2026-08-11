# Conectar el canal oficial de Meta (WhatsApp Cloud API)

El lado del servidor ya está listo y verificado. Lo que falta son pasos en la
consola de Meta, que requieren la cuenta del cliente.

## Estado del servidor

| Pieza | Estado |
|---|---|
| Webhook `GET` (handshake) | ✅ verificado en vivo contra botscomercio.com |
| Webhook `POST` (firma HMAC) | ✅ falla cerrado sin `WHATSAPP_APP_SECRET` |
| Ruteo multi-empresa por `phone_number_id` | ✅ con índice único: un número, una empresa |
| Deduplicación de reentregas | ✅ por el id del mensaje de Meta |
| Respuesta rápida (encola y contesta 200) | ✅ el motor corre en el worker |
| `WHATSAPP_VERIFY_TOKEN` | ✅ generado en el servidor |
| `WHATSAPP_APP_SECRET` | ⬜ falta: sale de la consola |
| `WHATSAPP_TOKEN` (permanente) | ⬜ falta: sale de la consola |

**URL del webhook:** `https://botscomercio.com/api/webhooks/whatsapp`

Para leer el verify token (no sale de acá):

```bash
ssh -i ~/.ssh/metabot_vps root@86.48.29.234 "grep '^WHATSAPP_VERIFY_TOKEN=' /opt/MetaBot.OS/.env"
```

## Requisitos antes de empezar

- Cuenta de Meta Business con **portafolio comercial** creado.
- Un **número real** que NO esté activo en la app de WhatsApp ni en WhatsApp
  Business. Si lo está, hay que darlo de baja primero y esperar. Los números
  virtuales o VoIP suelen fallar la verificación o terminar baneados.
- Una **URL de política de privacidad**: es obligatoria para publicar la app.
  Hoy botscomercio.com no tiene una — hay que publicarla antes de este paso.

## Pasos en la consola de Meta

1. **Crear la app** en developers.facebook.com → tipo Negocio → agregar el
   producto **WhatsApp** → vincularla al portafolio comercial.

2. **Registrar el número** en WhatsApp Manager, con verificación por SMS o
   llamada. Anotar el `PHONE_NUMBER_ID` que aparece **después** de registrarlo:
   el que Meta muestra por defecto es el de su número de prueba y no sirve.

3. **App Secret**: Configuración → Básica → Mostrar.

4. **Webhook**: Configuración de WhatsApp → Webhooks →
   - URL de devolución: `https://botscomercio.com/api/webhooks/whatsapp`
   - Token de verificación: el `WHATSAPP_VERIFY_TOKEN` del servidor
   - **Suscribirse al campo `messages`.** Sin esto Meta verifica el webhook
     pero no manda nada nunca, y parece que el bot está roto.

5. **Publicar la app** (requiere la política de privacidad). Sin publicar, el
   bot solo responde a los destinatarios de prueba autorizados.

6. **Token permanente**: Business Settings → Usuarios del sistema → crear uno
   con rol admin → **Asignar activos**: la app *y* la cuenta de WhatsApp (WABA)
   → Generar token con permisos `whatsapp_business_messaging` y
   `whatsapp_business_management` → marcar **sin caducidad**.

   El token temporal de la pantalla de API Setup dura 24 horas. Si se usa ese,
   el bot funciona un día y deja de andar sin aviso.

## Cargar los secretos (no pasan por el chat)

```bash
ssh -i ~/.ssh/metabot_vps root@86.48.29.234
cd /opt/MetaBot.OS
nano .env       # completar WHATSAPP_APP_SECRET y WHATSAPP_TOKEN
docker compose up -d backend
```

## Conectar una empresa a su número

Desde el panel, en Conexiones: modo **meta** y el `PHONE_NUMBER_ID`. Cada
número pertenece a UNA sola empresa —lo garantiza un índice único— porque el
webhook resuelve el tenant solo por ese valor: dos empresas con el mismo
número harían que una reciba los mensajes de los pacientes de la otra.

## Verificar que quedó andando

```bash
# El handshake, como lo hace Meta
TOK=$(ssh -i ~/.ssh/metabot_vps root@86.48.29.234 "grep '^WHATSAPP_VERIFY_TOKEN=' /opt/MetaBot.OS/.env | cut -d= -f2-")
curl "https://botscomercio.com/api/webhooks/whatsapp?hub.mode=subscribe&hub.verify_token=$TOK&hub.challenge=OK123"
# Tiene que devolver exactamente: OK123
```

Después, mandarle un WhatsApp real al número. La respuesta tarda ~40-60
segundos: el webhook contesta 200 al instante y el bot responde cuando el
worker termina.

## Reglas anti-baneo

- **Calentar el número**: arrancar con poco volumen y subir de a poco. Un
  número nuevo que dispara cientos de mensajes se marca.
- **Ventana de 24 horas**: fuera de ella solo salen **plantillas aprobadas**,
  no texto libre. Esto afecta directo a los recordatorios de medicación y de
  citas: si el paciente no escribió en las últimas 24 horas, hace falta una
  plantilla aprobada. Todavía no las tenemos.
- Opt-in obligatorio. El sistema ya lo respeta: los recordatorios exigen
  consentimiento registrado y el paciente corta con **STOP**.
- Vigilar el *quality rating* en WhatsApp Manager: si baja, Meta recorta el
  límite diario de mensajes.

## Síntomas y su causa real

| Síntoma | Causa |
|---|---|
| El webhook verifica pero no llega nada | Falta suscribirse al campo `messages` |
| Solo responde a los números de prueba | La app no está publicada |
| Funcionó un día y dejó de andar | Se usó el token temporal de 24 h |
| `(#100) Invalid parameter` al enviar | `PHONE_NUMBER_ID` viejo tras re-registrar |
| El webhook devuelve 403 en todo | Falta `WHATSAPP_APP_SECRET`: falla cerrado a propósito |
| El handshake devuelve 422 | Los parámetros llegan como `hub.mode`, con punto |

## Lo que queda pendiente después de conectar

- **Plantillas aprobadas** para poder escribirle a un paciente fuera de la
  ventana de 24 horas. Sin ellas, los recordatorios solo llegan si el paciente
  escribió hace poco.
- **Política de privacidad** publicada, que es requisito para publicar la app.
