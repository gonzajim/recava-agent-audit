// functions/index.js

const functions = require("firebase-functions");
const { onRequest } = require("firebase-functions/v2/https");
const admin = require("firebase-admin");
const { initializeApp } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { BigQuery } = require("@google-cloud/bigquery");
const cors = require("cors")({ origin: true });

// Inicialización ligera en ámbito global
initializeApp();

const region = "europe-west1"; // Región para todas las funciones

// ------------------------------
// Helper de autenticación
// ------------------------------
async function requireVerifiedUser(req, res) {
  // Soporte preflight CORS
  if (req.method === "OPTIONS") {
    res.set("Access-Control-Allow-Origin", "*");
    res.set("Access-Control-Allow-Methods", "POST, OPTIONS");
    res.set("Access-Control-Allow-Headers", "Content-Type, Authorization");
    return res.status(204).send("");
  }

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

  // Log mínimo (no PII excesiva)
  console.log(`Auth OK uid=${decoded.uid} email=${decoded.email} verified=${decoded.email_verified}`);
  return decoded;
}

/**
 * Obtiene el historial de chat, con un filtro de búsqueda opcional.
 */
exports.getChatHistory = onRequest({ region, memory: "256MiB" }, async (req, res) => {
  return cors(req, res, async () => {
    // 1) Autenticación + verificación de email
    const decoded = await requireVerifiedUser(req, res);
    if (!decoded || res.headersSent) return; // ya respondió con 401/403

    // 2) Solo POST (OPTIONS lo gestiona requireVerifiedUser)
    if (req.method !== "POST") {
      return res.status(405).send({ error: "Method Not Allowed" });
    }

    // 3) BigQuery client
    const bigquery = new BigQuery();

    // 4) Query
    const { searchTerm } = req.body?.data || {};
    let query;
    const options = { params: {} };
    const baseQuery = `
      SELECT
        id, timestamp, thread_id, user_message, assistant_response, expert_response, endpoint_source
      FROM \`recava-auditor-dev.recava_agent_audit_qa.chat_history\`
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
  });
});

/**
 * Actualiza el campo expert_response para un registro específico.
 */
exports.updateExpertResponse = onRequest({ region, memory: "256MiB" }, async (req, res) => {
  return cors(req, res, async () => {
    // 1) Autenticación + verificación de email
    const decoded = await requireVerifiedUser(req, res);
    if (!decoded || res.headersSent) return;

    // 2) Solo POST
    if (req.method !== "POST") {
      return res.status(405).send({ error: "Method Not Allowed" });
    }

    // 3) BigQuery client
    const bigquery = new BigQuery();

    // 4) Validación de payload
    const { id, expertResponse } = req.body?.data || {};
    if (!id || typeof expertResponse !== "string") {
      return res.status(400).send({ error: "Se requiere un 'id' y una 'expertResponse' válida." });
    }

    // 5) Update
    const query = `
      UPDATE \`recava-auditor-dev.recava_agent_audit_qa.chat_history\`
      SET expert_response = @expertResponse
      WHERE id = @id;
    `;
    const options = { query, params: { expertResponse, id } };

    try {
      await bigquery.query(options);
      return res.status(200).json({ success: true, message: `Registro ${id} actualizado correctamente.` });
    } catch (error) {
      console.error("ERROR AL ACTUALIZAR EN BIGQUERY:", error);
      return res.status(500).send({ error: "No se pudo actualizar la respuesta del experto." });
    }
  });
});

//
// --- AÑADE ESTA NUEVA FUNCIÓN AL FINAL DE TU ARCHIVO ---
//
exports.setMyAdminClaim = functions
    .region("europe-west1") // Asegúrate que la región coincide con tus otras funciones
    .https.onRequest(async (req, res) => {
        
        // --- ¡IMPORTANTE! Reemplaza este UID por tu UID real ---
        const YOUR_UID = "AMaDy7n2iRQLproofi8UDDPuK472";

        // --- (Opcional) Seguridad simple para que solo tú la llames ---
        // const secretKey = req.query.key;
        // if (secretKey !== "mi-clave-secreta-123") {
        //     res.status(401).send("No autorizado");
        //     return;
        // }

        try {
            // Asignamos el claim 'admin: true' a tu UID
            await admin.auth().setCustomUserClaims(YOUR_UID, { admin: true });
            
            // Forzamos el refresco del token
            await admin.auth().revokeRefreshTokens(YOUR_UID);

            const msg = `¡Éxito! Claim 'admin:true' asignado a ${YOUR_UID}. Cierra sesión y vuelve a entrar.`;
            console.log(msg);
            res.status(200).send(msg);

        } catch (error) {
            console.error("Error asignando el claim:", error);
            res.status(500).send("Error: " + error.message);
        }
    });
