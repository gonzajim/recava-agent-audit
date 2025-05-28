import os
from flask import Flask, request, jsonify
from openai import OpenAI
from agents import Orchestrator, AgentConfig
from dotenv import load_dotenv

# Carga .env para desarrollo local; ignóralo en producción
load_dotenv()

app = Flask(__name__)

# Leer variables de entorno
api_key     = os.getenv("OPENAI_API_KEY")
assistant_id= os.getenv("ASISTENTE_ID")
auditor_id  = os.getenv("AUDITOR_ID")

# Validar existencia
if not all([api_key, assistant_id, auditor_id]):
    raise RuntimeError("Faltan variables de entorno: OPENAI_API_KEY, ASISTENTE_ID, AUDITOR_ID")  # :contentReference[oaicite:7]{index=7}

client = OpenAI(api_key=api_key)


# Configurar orquestador
orch = Orchestrator(
    name="auditoria_orquestador",
    subagents=[
        AgentConfig(name="auditor", assistant_id=auditor_id),
        AgentConfig(name="asistente", assistant_id=assistant_id)
    ]
)

@app.route("/orchestrate", methods=["POST"])
def orchestrate():
    user_input = request.json.get("input")
    result     = client.agents.run(orchestrator=orch, input=user_input)
    # Opcional: persistir en Cloud Storage o Firestore aquí
    return jsonify({"output": result.output})

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
