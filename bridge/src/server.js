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
  fetchLatestBaileysVersion,
  useMultiFileAuthState,
} from "baileys";

const PORT = Number(process.env.BRIDGE_PORT || 3001);
const BACKEND_URL = process.env.BACKEND_URL || "http://localhost:8000";
const BRIDGE_SECRET = process.env.BRIDGE_SECRET || "";
const SESSIONS_DIR = path.resolve("sessions");

const logger = pino({ level: process.env.LOG_LEVEL || "info" });
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
  if (!text.trim()) return;

  const from = "+" + jid.split("@")[0];
  const name = msg.pushName || "";
  logger.info({ companyId, from }, "mensaje entrante");

  const resp = await fetch(`${BACKEND_URL}/api/webhooks/bridge`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Bridge-Secret": BRIDGE_SECRET,
    },
    body: JSON.stringify({ company_id: companyId, from, name, text }),
  });
  if (!resp.ok) {
    logger.error({ status: resp.status }, "backend rechazó el mensaje");
    return;
  }
  const data = await resp.json();
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
