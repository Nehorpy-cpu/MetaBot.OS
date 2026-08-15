/**
 * MetaBot.OS — Puente WhatsApp Web (Baileys, conexión por QR).
 *
 * Para PyMEs sin verificación de Meta: escanean un QR con el WhatsApp
 * Business existente y el bot responde a los clientes que escriben.
 *
 * Reglas de seguridad y de uso:
 * - SOLO responde: nunca inicia conversaciones ni hace envíos masivos
 *   (reduce el riesgo de baneo, aunque no lo elimina — canal no oficial).
 * - Ignora grupos, estados y mensajes propios.
 * - Toda comunicación con el backend lleva el secreto compartido
 *   BRIDGE_SECRET en el header X-Bridge-Secret, en ambos sentidos.
 *
 * Una sesión por empresa (companyId); credenciales en sessions/<id>/.
 */
import express from "express";
import fs from "fs";
import path from "path";
import pino from "pino";
import QRCode from "qrcode";
import makeWASocket, {
  DisconnectReason,
  downloadMediaMessage,
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "baileys";

const PORT = Number(process.env.BRIDGE_PORT || 3001);
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const BRIDGE_SECRET = process.env.BRIDGE_SECRET || "";
const SESSIONS_DIR = path.resolve("sessions");

const logger = pino({ level: process.env.LOG_LEVEL || "info" });

// Topes de la nota de voz. Transcribir se cobra por minuto: sin esto, alguien
// manda un audio de dos horas y la cuenta la paga el dueño del negocio.
const MAX_AUDIO_SEGUNDOS = 300;
const MAX_AUDIO_BYTES = 8 * 1024 * 1024;
const AUDIO_MUY_LARGO =
  "Ese audio es muy largo para que lo pueda escuchar. ¿Me lo resumís en uno " +
  "más corto o me lo escribís?";
// Identidad de este proceso: la usa el lease para impedir que dos workers
// abran la MISMA sesión de WhatsApp (eso corrompe las credenciales).
const WORKER_ID = `${process.pid}-${Date.now().toString(36)}`;

async function backend(path, body) {
  const resp = await fetch(`${BACKEND_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Bridge-Secret": BRIDGE_SECRET },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`backend ${path}: ${resp.status}`);
  return resp.json();
}
const sessions = new Map(); // companyId -> { sock, status, qrDataUrl, phone }

if (!BRIDGE_SECRET) {
  logger.warn("BRIDGE_SECRET vacío: configuralo en producción");
}

function sessionInfo(companyId) {
  const s = sessions.get(companyId);
  if (!s) return { status: "disconnected" };
  return { status: s.status, qr: s.qrDataUrl || null, phone: s.phone || null };
}

async function startSession(companyId) {
  const existing = sessions.get(companyId);
  if (existing && ["connected", "connecting", "qr"].includes(existing.status)) {
    return sessionInfo(companyId);
  }
  // Lease: si otro worker vivo tiene esta sesión, no se abre.
  try {
    const { granted } = await backend("/api/webhooks/bridge/lease", {
      company_id: Number(companyId), worker_id: WORKER_ID,
    });
    if (!granted) {
      logger.warn({ companyId }, "otro worker tiene el lease de esta sesión; no se abre");
      return { status: "locked_by_other_worker" };
    }
  } catch (err) {
    logger.error({ err: String(err) }, "no se pudo obtener el lease");
    return { status: "lease_error" };
  }

  const dir = path.join(SESSIONS_DIR, String(companyId));
  fs.mkdirSync(dir, { recursive: true });
  const { state, saveCreds } = await useMultiFileAuthState(dir);
  const { version } = await fetchLatestBaileysVersion();

  const sock = makeWASocket({
    version,
    auth: state,
    logger: logger.child({ companyId }),
    printQRInTerminal: false,
    markOnlineOnConnect: false,
    browser: ["MetaBot.OS", "Chrome", "1.0"],
  });
  const session = { sock, status: "connecting", qrDataUrl: null, phone: null };
  sessions.set(companyId, session);

  sock.ev.on("creds.update", saveCreds);

  // Latido: renueva el lease y reporta estado. Si se pierde el lease (otro
  // worker lo tomó), esta sesión se cierra para no corromper credenciales.
  session.heartbeat = setInterval(async () => {
    try {
      const { held } = await backend("/api/webhooks/bridge/heartbeat", {
        company_id: Number(companyId), worker_id: WORKER_ID,
        status: session.status, phone: session.phone || "",
      });
      if (!held) {
        logger.warn({ companyId }, "lease perdido: cerrando sesión local");
        clearInterval(session.heartbeat);
        try { session.sock.end(); } catch { /* ya cerrado */ }
        sessions.delete(companyId);
      }
    } catch (err) {
      logger.error({ err: String(err) }, "heartbeat falló");
    }
  }, 45000);

  sock.ev.on("connection.update", async (update) => {
    const { connection, lastDisconnect, qr } = update;
    if (qr) {
      session.status = "qr";
      session.qrDataUrl = await QRCode.toDataURL(qr, { margin: 1, width: 300 });
    }
    if (connection === "open") {
      session.status = "connected";
      session.qrDataUrl = null;
      session.phone = sock.user?.id?.split(":")[0] || null;
      logger.info({ companyId, phone: session.phone }, "sesión conectada");
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (session.heartbeat) clearInterval(session.heartbeat);
      if (code === DisconnectReason.loggedOut) {
        logger.warn({ companyId }, "sesión cerrada desde el teléfono; limpiando credenciales");
        sessions.delete(companyId);
        fs.rmSync(dir, { recursive: true, force: true });
      } else {
        logger.info({ companyId, code }, "conexión caída; reintentando");
        sessions.delete(companyId);
        setTimeout(() => startSession(companyId).catch((e) => logger.error(e)), 3000);
      }
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;
    for (const msg of messages) {
      try {
        await handleIncoming(companyId, session, msg);
      } catch (err) {
        logger.error({ err: String(err), companyId }, "error procesando mensaje");
      }
    }
  });

  return sessionInfo(companyId);
}

async function handleIncoming(companyId, session, msg) {
  const jid = msg.key?.remoteJid || "";
  // Solo chats directos de personas: ni grupos, ni estados, ni propios
  if (msg.key?.fromMe || !jid.endsWith("@s.whatsapp.net")) return;
  const text =
    msg.message?.conversation ||
    msg.message?.extendedTextMessage?.text ||
    "";

  // Nota de voz. Mucha gente acá manda audios y no escribe: un bot que solo
  // entiende texto deja afuera a una parte de sus clientes. Se baja, se manda
  // al backend y allá se transcribe; acá NO se decide nada sobre el
  // contenido.
  const nota = msg.message?.audioMessage;
  let audioBase64 = "";
  let audioMime = "";
  if (!text.trim() && nota) {
    // El tope va antes de bajar el archivo: sin esto, un audio de dos horas
    // se descarga entero para que el backend después lo rechace.
    if ((nota.seconds || 0) > MAX_AUDIO_SEGUNDOS) {
      logger.info({ companyId, seconds: nota.seconds }, "nota de voz demasiado larga");
      await session.sock.sendMessage(jid, { text: AUDIO_MUY_LARGO });
      return;
    }
    try {
      const buf = await downloadMediaMessage(msg, "buffer", {});
      if (buf.length > MAX_AUDIO_BYTES) {
        logger.info({ companyId, bytes: buf.length }, "nota de voz demasiado pesada");
        await session.sock.sendMessage(jid, { text: AUDIO_MUY_LARGO });
        return;
      }
      audioBase64 = buf.toString("base64");
      audioMime = nota.mimetype || "audio/ogg";
    } catch (err) {
      logger.error({ err: String(err) }, "no se pudo bajar la nota de voz");
      return;
    }
  }
  if (!text.trim() && !audioBase64) return;

  const from = "+" + jid.split("@")[0];
  const name = msg.pushName || "";
  logger.info({ companyId, from }, "mensaje entrante");

  const resp = await fetch(`${BACKEND_URL}/api/webhooks/bridge`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Bridge-Secret": BRIDGE_SECRET,
    },
    body: JSON.stringify({
      company_id: Number(companyId), from, name, text,
      audio_base64: audioBase64, audio_mime: audioMime,
      // id del mensaje en WhatsApp: el backend deduplica reentregas
      external_id: msg.key?.id || "",
    }),
  });
  if (!resp.ok) {
    logger.error({ status: resp.status }, "backend rechazó el mensaje");
    return;
  }
  const data = await resp.json();
  if (data.duplicate) {
    logger.info({ companyId, from }, "mensaje ya procesado (reentrega): no se responde de nuevo");
    return;
  }
  if (!data.reply && !(data.media || []).length) return;

  // Toque humano: presencia "escribiendo" proporcional al largo del texto
  await session.sock.presenceSubscribe(jid);
  await session.sock.sendPresenceUpdate("composing", jid);
  const typingMs = Math.min(1200 + (data.reply || "").length * 25, 6000);
  await new Promise((r) => setTimeout(r, typingMs));
  await session.sock.sendPresenceUpdate("paused", jid);

  // Fotos reales del catálogo (con precio en el caption), luego el texto
  for (const item of (data.media || []).slice(0, 5)) {
    try {
      await session.sock.sendMessage(jid, {
        image: { url: `${BACKEND_URL}${item.path}` },
        caption: item.caption || "",
      });
      await new Promise((r) => setTimeout(r, 800));
    } catch (err) {
      logger.error({ err: String(err) }, "no se pudo enviar imagen de catálogo");
    }
  }
  if (data.reply) await session.sock.sendMessage(jid, { text: data.reply });

  // Si preguntaron por audio, se contesta también por audio. Va DESPUÉS del
  // texto y no en lugar de él: un monto que se escucha una vez no se puede
  // volver a mirar, y el enlace del informe no se puede dictar.
  if (data.audio_base64) {
    try {
      await session.sock.sendMessage(jid, {
        audio: Buffer.from(data.audio_base64, "base64"),
        mimetype: "audio/ogg; codecs=opus",
        ptt: true,
      });
    } catch (err) {
      logger.error({ err: String(err) }, "no se pudo enviar la respuesta hablada");
    }
  }
}

// ---- API HTTP del bridge (la consume el backend) ----
const app = express();
app.use(express.json());
app.use((req, res, next) => {
  if (BRIDGE_SECRET && req.headers["x-bridge-secret"] !== BRIDGE_SECRET) {
    return res.status(403).json({ error: "secreto inválido" });
  }
  next();
});

app.get("/sessions/:id/status", (req, res) => {
  res.json(sessionInfo(req.params.id));
});

app.post("/sessions/:id/start", async (req, res) => {
  try {
    res.json(await startSession(req.params.id));
  } catch (err) {
    res.status(500).json({ error: String(err) });
  }
});

// Salida proactiva: el backend inicia un envío (recordatorio de toma, aviso
// de cita). Hasta ahora el bridge SOLO podía contestar dentro del manejador
// de mensajes entrantes, así que no existía forma de que el servidor mandara
// nada por su cuenta — ni siquiera manualmente.
//
// Advertencia que no hay que perder de vista: este es un cliente NO oficial.
// Mandar mensajes no solicitados por acá es lo que hace que le quemen el
// número al cliente. Por eso el backend solo llega hasta acá con mensajes
// que el paciente pidió o consintió, y con horario silencioso.
app.post("/sessions/:id/send", async (req, res) => {
  const session = sessions.get(String(req.params.id));
  if (!session || session.status !== "connected") {
    return res.status(409).json({ error: "sesión no conectada", status: session?.status || "disconnected" });
  }
  const { to, text } = req.body || {};
  if (!to || !text) {
    return res.status(422).json({ error: "faltan 'to' o 'text'" });
  }
  const jid = String(to).replace(/[^0-9]/g, "") + "@s.whatsapp.net";
  try {
    const enviado = await session.sock.sendMessage(jid, { text: String(text).slice(0, 4096) });
    logger.info({ companyId: req.params.id, to: jid }, "envío proactivo");
    res.json({ sent: true, id: enviado?.key?.id || "" });
  } catch (err) {
    logger.error({ err, to: jid }, "falló el envío proactivo");
    res.status(502).json({ error: String(err) });
  }
});

app.post("/sessions/:id/logout", async (req, res) => {
  const s = sessions.get(req.params.id);
  if (s) {
    try {
      await s.sock.logout();
    } catch {
      /* ya desconectado */
    }
    sessions.delete(req.params.id);
  }
  fs.rmSync(path.join(SESSIONS_DIR, String(req.params.id)), { recursive: true, force: true });
  res.json({ status: "disconnected" });
});

app.listen(PORT, () => logger.info(`bridge escuchando en :${PORT}`));

// Al arrancar, reanudar sesiones que ya tenían credenciales guardadas
if (fs.existsSync(SESSIONS_DIR)) {
  for (const id of fs.readdirSync(SESSIONS_DIR)) {
    if (fs.existsSync(path.join(SESSIONS_DIR, id, "creds.json"))) {
      startSession(id).catch((e) => logger.error(e));
    }
  }
}
