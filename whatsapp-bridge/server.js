/**
 * WhatsApp Bridge — REST API wrapper around @whiskeysockets/baileys
 *
 * Uses the WhatsApp protocol directly (no browser/Chromium needed).
 *
 * Endpoints:
 *   GET  /status          → { connected, phone, name }
 *   POST /send            → { chatId, message }  → sends text
 *   GET  /qr              → current QR code as scannable HTML page
 *   GET  /qr.json         → current QR code as JSON
 *   GET  /health          → { status: "ok", uptime }
 *
 * Incoming messages are forwarded to WEBHOOK_URL via POST.
 *
 * Environment variables:
 *   PORT          — HTTP port (default 3000)
 *   WEBHOOK_URL   — URL to POST incoming messages to
 *   API_KEY       — optional bearer token for auth
 */

const express = require("express");
const {
  default: makeWASocket,
  useMultiFileAuthState,
  DisconnectReason,
  fetchLatestBaileysVersion,
  makeCacheableSignalKeyStore,
} = require("@whiskeysockets/baileys");
const pino = require("pino");
const QRCode = require("qrcode");
const qrcode = require("qrcode-terminal");
const axios = require("axios");
const fs = require("fs");
const path = require("path");

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3000;
const WEBHOOK_URL =
  process.env.WEBHOOK_URL || "http://api:9000/api/v1/whatsapp/bridge/webhook";
const API_KEY = process.env.API_KEY || "";

const AUTH_DIR = "/data/auth";
const logger = pino({ level: "warn" });

// ── State ───────────────────────────────────────
let currentQR = null;
let isReady = false;
let clientInfo = {};
let sock = null;

// ── Ensure auth directory exists ────────────────
function ensureDir(dir) {
  if (!fs.existsSync(dir)) {
    fs.mkdirSync(dir, { recursive: true });
    console.log(`📁 Created auth directory: ${dir}`);
  }
}

// ── Connect to WhatsApp ─────────────────────────
async function connectToWhatsApp() {
  ensureDir(AUTH_DIR);

  const { state, saveCreds } = await useMultiFileAuthState(AUTH_DIR);
  const { version, isLatest } = await fetchLatestBaileysVersion();
  console.log(`📱 Using WA v${version.join(".")}, isLatest: ${isLatest}`);

  sock = makeWASocket({
    version,
    auth: {
      creds: state.creds,
      keys: makeCacheableSignalKeyStore(state.keys, logger),
    },
    logger,
    generateHighQualityLinkPreview: false,
    syncFullHistory: false,
    markOnlineOnConnect: false,
  });

  // ── Credentials updates ─────────────────────
  sock.ev.on("creds.update", saveCreds);

  // ── Connection updates ──────────────────────
  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      currentQR = qr;
      console.log("\n📱 Scan this QR code with WhatsApp:\n");
      qrcode.generate(qr, { small: true });
      console.log("\nOr visit http://localhost:" + PORT + "/qr to see it\n");
    }

    if (connection === "close") {
      isReady = false;
      const statusCode =
        lastDisconnect?.error?.output?.statusCode;
      const reason = DisconnectReason;

      console.log(`❌ Connection closed. Status code: ${statusCode}`);

      if (statusCode === reason.loggedOut) {
        console.log("🔒 Logged out. Clearing auth and reconnecting...");
        // Clear auth data so we get a fresh QR
        fs.rmSync(AUTH_DIR, { recursive: true, force: true });
        setTimeout(connectToWhatsApp, 3000);
      } else {
        // Reconnect for any other disconnect reason
        console.log("🔄 Reconnecting in 3 seconds...");
        setTimeout(connectToWhatsApp, 3000);
      }
    } else if (connection === "open") {
      isReady = true;
      currentQR = null;
      const me = sock.user;
      clientInfo = {
        phone: me?.id?.split(":")[0] || me?.id?.split("@")[0] || "unknown",
        name: me?.name || "unknown",
        platform: "baileys",
      };
      console.log(
        `✅ WhatsApp connected as ${clientInfo.name} (${clientInfo.phone})`
      );
    }
  });

  // ── Incoming messages ───────────────────────
  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify") return;

    for (const msg of messages) {
      // Skip our own messages
      if (msg.key.fromMe) continue;
      // Skip status broadcasts
      if (msg.key.remoteJid === "status@broadcast") continue;
      // Skip group messages
      if (msg.key.remoteJid?.endsWith("@g.us")) continue;

      const senderJid = msg.key.remoteJid;
      const senderPhone = senderJid?.split("@")[0];

      // Skip invalid/empty phone numbers
      if (!senderPhone || senderPhone === "0" || senderPhone.length < 5) {
        console.log(`⚠️  Skipping message with invalid sender: ${senderJid}`);
        continue;
      }

      // Extract text from various message types (including media captions)
      const text =
        msg.message?.conversation ||
        msg.message?.extendedTextMessage?.text ||
        msg.message?.imageMessage?.caption ||
        msg.message?.videoMessage?.caption ||
        msg.message?.documentMessage?.caption ||
        "";

      // Skip messages with no readable text
      if (!text || text.trim() === "") {
        console.log(`⚠️  Skipping non-text message from ${senderPhone} (type: ${Object.keys(msg.message || {}).join(",")})`);
        continue;
      }

      // Guard against base64/binary content leaking through
      if (text.length > 500 && /^[A-Za-z0-9+/=\s]+$/.test(text.substring(0, 200))) {
        console.log(`⚠️  Skipping likely base64/binary content from ${senderPhone} (${text.length} chars)`);
        continue;
      }

      const pushName = msg.pushName || senderPhone;

      const payload = {
        id: msg.key.id,
        from: senderJid,
        body: text,
        sender_name: pushName,
        timestamp: msg.messageTimestamp,
        type: "chat",
        hasMedia: !!(
          msg.message?.imageMessage ||
          msg.message?.videoMessage ||
          msg.message?.audioMessage ||
          msg.message?.documentMessage
        ),
      };

      console.log(
        `📩 Message from ${payload.sender_name} (${senderJid}): ${text.substring(0, 80)}`
      );

      if (WEBHOOK_URL) {
        try {
          await axios.post(WEBHOOK_URL, payload, {
            headers: { "Content-Type": "application/json" },
            timeout: 10000,
          });
          console.log(`  → Forwarded to ${WEBHOOK_URL}`);
        } catch (err) {
          const detail = err.response?.data || err.message;
          console.error(
            `  ✗ Webhook failed (${err.response?.status}):`,
            JSON.stringify(detail)
          );
        }
      }
    }
  });
}

// ── Auth middleware ──────────────────────────────
function authMiddleware(req, res, next) {
  if (!API_KEY) return next();
  const auth = req.headers.authorization;
  if (auth === `Bearer ${API_KEY}`) return next();
  return res.status(401).json({ error: "Unauthorized" });
}

// ── Routes ──────────────────────────────────────

app.get("/status", (req, res) => {
  res.json({
    connected: isReady,
    phone: clientInfo.phone || null,
    name: clientInfo.name || null,
    platform: clientInfo.platform || null,
    hasQR: !!currentQR,
  });
});

// PNG-only QR endpoint for frontend embedding (scales better than iframe HTML)
app.get("/qr.png", async (req, res) => {
  res.set("Cache-Control", "no-store, no-cache, must-revalidate, proxy-revalidate");
  res.set("Pragma", "no-cache");
  res.set("Expires", "0");

  if (isReady) {
    return res.status(409).json({
      status: "already_connected",
      phone: clientInfo.phone,
      name: clientInfo.name,
    });
  }

  if (!currentQR) {
    return res.status(404).json({
      status: "waiting",
      message: "QR code not yet generated",
    });
  }

  try {
    const qrBuffer = await QRCode.toBuffer(currentQR, {
      type: "png",
      width: 512,
      margin: 2,
    });

    res.set("Content-Type", "image/png");
    return res.send(qrBuffer);
  } catch (err) {
    return res
      .status(500)
      .json({ error: "Failed to generate QR image", details: err.message });
  }
});

app.get("/qr", async (req, res) => {
  if (isReady) {
    return res.send(`
      <html><body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;font-family:sans-serif;background:#0a0a0a;color:#22c55e">
        <div style="text-align:center"><h1>&#9989; WhatsApp Connected</h1><p>Phone: ${clientInfo.phone}</p><p>Name: ${clientInfo.name}</p></div>
      </body></html>`);
  }
  if (!currentQR) {
    return res.send(`
      <html><head><meta http-equiv="refresh" content="3"></head>
      <body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;font-family:sans-serif;background:#0a0a0a;color:#fff">
        <div style="text-align:center"><h1>&#9203; Waiting for QR code...</h1><p>Page will auto-refresh.</p></div>
      </body></html>`);
  }
  try {
    const qrDataUrl = await QRCode.toDataURL(currentQR, {
      width: 400,
      margin: 2,
    });
    res.send(`
      <html><head><meta http-equiv="refresh" content="15"></head>
      <body style="display:flex;justify-content:center;align-items:center;height:100vh;margin:0;font-family:sans-serif;background:#0a0a0a;color:#fff">
        <div style="text-align:center">
          <h1>&#128241; Scan QR Code with WhatsApp</h1>
          <p style="color:#aaa">Open WhatsApp &gt; Settings &gt; Linked Devices &gt; Link a Device</p>
          <img src="${qrDataUrl}" style="border-radius:12px;margin:20px 0" />
          <p style="color:#666;font-size:12px">Page refreshes automatically. QR expires every ~60s.</p>
        </div>
      </body></html>`);
  } catch (err) {
    res
      .status(500)
      .json({ error: "Failed to generate QR image", details: err.message });
  }
});

// JSON-only QR endpoint for programmatic access
app.get("/qr.json", (req, res) => {
  if (isReady)
    return res.json({
      status: "already_connected",
      phone: clientInfo.phone,
    });
  if (!currentQR)
    return res.json({
      status: "waiting",
      message: "QR code not yet generated",
    });
  res.json({ status: "scan_required", qr: currentQR });
});

app.post("/send", authMiddleware, async (req, res) => {
  const { chatId, message } = req.body;

  if (!chatId || !message) {
    return res.status(400).json({ error: "chatId and message are required" });
  }

  if (!isReady || !sock) {
    return res
      .status(503)
      .json({ error: "WhatsApp not connected. Scan QR first." });
  }

  try {
    const result = await sock.sendMessage(chatId, { text: message });
    console.log(`📤 Sent to ${chatId}: ${message.substring(0, 50)}...`);
    res.json({
      success: true,
      id: result.key.id,
      message_id: result.key.id,
      timestamp: Math.floor(Date.now() / 1000),
    });
  } catch (err) {
    console.error(`✗ Send failed to ${chatId}: ${err.message}`);
    res.status(500).json({ success: false, error: err.message });
  }
});

// Health check
app.get("/health", (req, res) => {
  res.json({ status: "ok", uptime: process.uptime() });
});

// ── Start ───────────────────────────────────────
app.listen(PORT, () => {
  console.log(`🚀 WhatsApp Bridge (Baileys) running on port ${PORT}`);
  console.log(`   Webhook URL: ${WEBHOOK_URL}`);
  console.log(`   Auth: ${API_KEY ? "enabled" : "disabled"}`);
  console.log("\n⏳ Connecting to WhatsApp...\n");
  connectToWhatsApp().catch((err) => {
    console.error("💥 Failed to connect:", err.message);
    console.error("   Will retry in 5 seconds...");
    setTimeout(() => {
      connectToWhatsApp().catch((e) =>
        console.error("💥 Retry also failed:", e.message)
      );
    }, 5000);
  });
});
