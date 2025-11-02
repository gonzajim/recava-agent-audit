// functions/index.js

const functions = require("firebase-functions");
const { onRequest } = require("firebase-functions/v2/https");
const admin = require("firebase-admin");
const { initializeApp } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { BigQuery } = require("@google-cloud/bigquery");

// Global initialization
initializeApp();

const region = "europe-west1";
const ALLOWED_ORIGINS = new Set([
  "https://divulgador-uclm.web.app",
  "https://divulgador-uclm.firebaseapp.com",
  "https://divulgador-uclm-admin.web.app",
  "https://divulgador-uclm-admin.firebaseapp.com",
]);

function withCors(handler) {
  return async (req, res) => {
    const origin = req.get("Origin");
    if (origin && ALLOWED_ORIGINS.has(origin)) {
      res.set("Access-Control-Allow-Origin", origin);
      res.set("Vary", "Origin");
      res.set("Access-Control-Allow-Credentials", "true");
    }
    res.set("Access-Control-Allow-Headers", "Authorization, Content-Type, Idempotency-Key, Accept");
    res.set("Access-Control-Allow-Methods", "GET,POST,OPTIONS");
    if (req.method === "OPTIONS") {
      return res.status(204).send("");
    }
    return handler(req, res);
  };
}

async function requireVerifiedUser(req, res) {
  const hdr = req.headers.authorization || "";
  if (!hdr.startsWith("Bearer ")) {
    return res.status(401).send({ error: "Missing or invalid Authorization header" });
  }
  const idToken = hdr.split("Bearer ")[1];

  let decoded;
  try {
    decoded = await getAuth().verifyIdToken(idToken);
  } catch (err) {
    console.error("Auth: invalid token:", err?.message || err);
    return res.status(401).send({ error: "Unauthorized" });
  }

  if (!decoded.email_verified) {
    return res.status(403).send({ error: "Email no verificado" });
  }

  console.log(`Auth OK uid=${decoded.uid} email=${decoded.email} verified=${decoded.email_verified}`);
  return decoded;
}

/**
 * Obtiene el historial de chat, con un filtro de busqueda opcional.
 */
exports.getChatHistory = onRequest(
  { region, memory: "256MiB" },
  withCors(async (req, res) => {
    const decoded = await requireVerifiedUser(req, res);
    if (!decoded || res.headersSent) return;

    if (req.method !== "POST") {
      return res.status(405).send({ error: "Method Not Allowed" });
    }

    const bigquery = new BigQuery();

    const { searchTerm } = req.body?.data || {};
    let query;
    const options = { params: {} };
    const baseQuery = `
      SELECT
        id, timestamp, thread_id, user_message, assistant_response, expert_response, endpoint_source
      FROM \`divulgador-uclm-5b8b9.divulgador_uclm_audit.chat_history\`
    `;

    if (searchTerm && String(searchTerm).trim() !== "") {
      query = `${baseQuery}
        WHERE LOWER(user_message) LIKE @searchTerm
           OR LOWER(assistant_response) LIKE @searchTerm
           OR LOWER(expert_response) LIKE @searchTerm
        ORDER BY timestamp DESC
        LIMIT 200;`;
      options.params.searchTerm = `%${String(searchTerm).toLowerCase()}%`;
    } else {
      query = `${baseQuery}
        ORDER BY timestamp DESC
        LIMIT 200;`;
    }
    options.query = query;

    try {
      const [rows] = await bigquery.query(options);
      return res.status(200).json({ history: rows });
    } catch (error) {
      console.error("ERROR AL CONSULTAR BIGQUERY:", error);
      return res.status(500).send({ error: "No se pudo obtener el historial de chat." });
    }
  })
);

/**
 * Actualiza el campo expert_response para un registro especifico.
 */
exports.updateExpertResponse = onRequest(
  { region, memory: "256MiB" },
  withCors(async (req, res) => {
    const decoded = await requireVerifiedUser(req, res);
    if (!decoded || res.headersSent) return;

    if (req.method !== "POST") {
      return res.status(405).send({ error: "Method Not Allowed" });
    }

    const bigquery = new BigQuery();

    const { id, expertResponse } = req.body?.data || {};
    if (!id || typeof expertResponse !== "string") {
      return res.status(400).send({ error: "Se requiere un 'id' y una 'expertResponse' valida." });
    }

    const query = `
      UPDATE \`divulgador-uclm-5b8b9.divulgador_uclm_audit.chat_history\`
      SET expert_response = @expertResponse
      WHERE id = @id;
    `;
    const options = { query, params: { expertResponse, id } };

    try {
      await bigquery.query(options);
      return res.status(200).json({
        success: true,
        message: "Registro " + id + " actualizado correctamente.",
      });
    } catch (error) {
      console.error("ERROR AL ACTUALIZAR EN BIGQUERY:", error);
      return res.status(500).send({ error: "No se pudo actualizar la respuesta del experto." });
    }
  })
);
