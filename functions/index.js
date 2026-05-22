// functions/index.js

const { onRequest } = require("firebase-functions/v2/https");
const { defineString } = require("firebase-functions/params");
const { initializeApp } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { BigQuery } = require("@google-cloud/bigquery");
const cors = require("cors");

// Inicialización ligera en ámbito global
initializeApp();

const region = "europe-west1";

// ---------- Configuración CORS restringida ----------
const allowedOrigins = [
  "https://recava-buscador.web.app",
  "https://recava-buscador-panel.web.app",
];

const corsMiddleware = cors({
  origin: (origin, callback) => {
    // Permite peticiones sin origen (ej. Postman, curl en server-to-server)
    // En producción puedes eliminar el !origin si quieres ser más estricto
    if (!origin || allowedOrigins.includes(origin)) {
      callback(null, true);
    } else {
      callback(new Error(`Origin '${origin}' not allowed by CORS policy`));
    }
  },
  methods: ["POST", "OPTIONS"],
  allowedHeaders: ["Content-Type", "Authorization"],
});

// ---------- Parámetros configurables ----------
// Define estos parámetros en Firebase con:
//   firebase functions:params:set BQ_CHAT_HISTORY_TABLE="project.dataset.table"
const BQ_CHAT_HISTORY_TABLE = defineString("BQ_CHAT_HISTORY_TABLE", {
  default: "recava-buscador.recava_agent_audit_qa.chat_history",
  description: "Tabla BigQuery de historial de chat (formato: project.dataset.table)",
});

// Cliente BigQuery inicializado a nivel de módulo (cold start eficiente)
const bigquery = new BigQuery();

// ------------------------------
// Helper de autenticación
// ------------------------------
async function requireVerifiedUser(req, res) {
  // Preflight CORS lo gestiona el middleware corsMiddleware
  const hdr = req.headers.authorization || "";
  if (!hdr.startsWith("Bearer ")) {
    res.status(401).json({ error: "Missing or invalid Authorization header" });
    return null;
  }
  const idToken = hdr.split("Bearer ")[1];

  let decoded;
  try {
    decoded = await getAuth().verifyIdToken(idToken);
  } catch (err) {
    console.error("Auth: invalid token:", err?.message || err);
    res.status(401).json({ error: "Unauthorized" });
    return null;
  }

  if (!decoded.email_verified) {
    res.status(403).json({ error: "Email no verificado" });
    return null;
  }

  // Log mínimo (no PII excesiva en producción)
  console.log(`Auth OK uid=${decoded.uid} verified=${decoded.email_verified}`);
  return decoded;
}

/**
 * Obtiene el historial de chat, con un filtro de búsqueda opcional.
 */
exports.getChatHistory = onRequest({ region, memory: "256MiB" }, async (req, res) => {
  return corsMiddleware(req, res, async () => {
    // 1) Autenticación + verificación de email
    const decoded = await requireVerifiedUser(req, res);
    if (!decoded || res.headersSent) return;

    // 2) Solo POST
    if (req.method !== "POST") {
      return res.status(405).json({ error: "Method Not Allowed" });
    }

    // 3) Query
    const { searchTerm } = req.body?.data || {};
    const tableFqn = `\`${BQ_CHAT_HISTORY_TABLE.value()}\``;
    let query;
    const options = { params: {} };
    const baseQuery = `
      SELECT
        id, timestamp, thread_id, user_message, assistant_response, expert_response, endpoint_source
      FROM ${tableFqn}
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
      return res.status(500).json({ error: "No se pudo obtener el historial de chat." });
    }
  });
});

/**
 * Actualiza el campo expert_response para un registro específico.
 */
exports.updateExpertResponse = onRequest({ region, memory: "256MiB" }, async (req, res) => {
  return corsMiddleware(req, res, async () => {
    // 1) Autenticación + verificación de email
    const decoded = await requireVerifiedUser(req, res);
    if (!decoded || res.headersSent) return;

    // 2) Solo POST
    if (req.method !== "POST") {
      return res.status(405).json({ error: "Method Not Allowed" });
    }

    // 3) Validación de payload
    const { id, expertResponse } = req.body?.data || {};
    if (!id || typeof expertResponse !== "string") {
      return res.status(400).json({ error: "Se requiere un 'id' y una 'expertResponse' válida." });
    }
    if (expertResponse.length > 10000) {
      return res.status(400).json({ error: "expertResponse demasiado larga (máx 10.000 caracteres)." });
    }

    // 4) Update
    const tableFqn = `\`${BQ_CHAT_HISTORY_TABLE.value()}\``;
    const query = `
      UPDATE ${tableFqn}
      SET expert_response = @expertResponse
      WHERE id = @id;
    `;
    const options = { query, params: { expertResponse, id } };

    try {
      await bigquery.query(options);
      return res.status(200).json({ success: true, message: `Registro ${id} actualizado correctamente.` });
    } catch (error) {
      console.error("ERROR AL ACTUALIZAR EN BIGQUERY:", error);
      return res.status(500).json({ error: "No se pudo actualizar la respuesta del experto." });
    }
  });
});

