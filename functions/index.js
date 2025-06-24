// functions/index.js

const { onRequest } = require("firebase-functions/v2/https");
const { initializeApp } = require("firebase-admin/app");
const { getAuth } = require("firebase-admin/auth");
const { BigQuery } = require("@google-cloud/bigquery");
const cors = require("cors")({ origin: true });

// La inicialización de Firebase Admin es ligera y está bien en el ámbito global.
initializeApp();

const region = 'europe-west1'; // Región definida para todas las funciones

/**
 * Obtiene el historial de chat, con un filtro de búsqueda opcional.
 */
exports.getChatHistory = onRequest({ region: region, memory: '256MiB' }, async (req, res) => {
  // Envolver la lógica en el middleware de CORS
  cors(req, res, async () => {
    // --- CAMBIO CLAVE: Inicializamos BigQuery aquí dentro ---
    const bigquery = new BigQuery();

    // 1. Verificar que la petición sea POST
    if (req.method !== 'POST') {
      return res.status(405).send({ error: 'Method Not Allowed' });
    }

    // 2. Verificar la autenticación del usuario
    if (!req.headers.authorization || !req.headers.authorization.startsWith('Bearer ')) {
      console.error("Petición no autorizada: No se encontró token.");
      return res.status(403).send({ error: "Unauthorized" });
    }
    const idToken = req.headers.authorization.split('Bearer ')[1];
    try {
      await getAuth().verifyIdToken(idToken);
    } catch (error) {
      console.error("Token inválido:", error);
      return res.status(403).send({ error: "Unauthorized" });
    }

    // 3. Lógica principal de la función
    const { searchTerm } = req.body.data || {};
    let query;
    const options = { params: {} };
    const baseQuery = `SELECT id, timestamp, thread_id, user_message, assistant_response, expert_response, endpoint_source FROM \`recava-auditor-dev.recava_agent_audit_qa.chat_history\``;

    if (searchTerm && searchTerm.trim() !== '') {
      query = `${baseQuery} WHERE LOWER(user_message) LIKE @searchTerm OR LOWER(assistant_response) LIKE @searchTerm OR LOWER(expert_response) LIKE @searchTerm ORDER BY timestamp DESC LIMIT 200;`;
      options.params.searchTerm = `%${searchTerm.toLowerCase()}%`;
    } else {
      query = `${baseQuery} ORDER BY timestamp DESC LIMIT 200;`;
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
exports.updateExpertResponse = onRequest({ region: region, memory: '256MiB' }, async (req, res) => {
  cors(req, res, async () => {
    // --- CAMBIO CLAVE: Inicializamos BigQuery aquí dentro también ---
    const bigquery = new BigQuery();
    
    if (req.method !== 'POST') {
      return res.status(405).send({ error: 'Method Not Allowed' });
    }
    if (!req.headers.authorization || !req.headers.authorization.startsWith('Bearer ')) {
      console.error("Petición no autorizada: No se encontró token.");
      return res.status(403).send({ error: "Unauthorized" });
    }
    const idToken = req.headers.authorization.split('Bearer ')[1];
    try {
      await getAuth().verifyIdToken(idToken);
    } catch (error) {
      console.error("Token inválido:", error);
      return res.status(403).send({ error: "Unauthorized" });
    }

    const { id, expertResponse } = req.body.data;
    if (!id || typeof expertResponse !== "string") {
      return res.status(400).send({ error: "Se requiere un 'id' y una 'expertResponse' válida." });
    }

    const query = `UPDATE \`recava-auditor-dev.recava_agent_audit_qa.chat_history\` SET expert_response = @expertResponse WHERE id = @id;`;
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