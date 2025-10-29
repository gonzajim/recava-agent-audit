"""FastAPI entrypoint for RecavAI advisor mode."""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .adapters import to_legacy_contract
from .agents_registry import get_agents
from .schemas import AdvisorRequest, AdvisorResponse
from .workflow import WorkflowInput, run_workflow

app = FastAPI(title="RecavAI Advisor API")

# Adjust CORS origins to your Firebase Hosting domains in production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/advisor/answer", response_model=AdvisorResponse)
async def advisor_answer(payload: AdvisorRequest):
    try:
        agents = get_agents()
        wf_in = WorkflowInput(input_as_text=payload.question)
        wf_out = await run_workflow(wf_in, *agents)
        return AdvisorResponse(
            status="ok",
            answer=wf_out.get("respuesta_final", ""),
            citations=wf_out.get("citas", []),
            meta={
                "evaluations": wf_out.get("evaluaciones", []),
                "draft": wf_out.get("asistente_inicial", {}).get("output_text", ""),
            },
        )
    except Exception as exc:  # log appropriately in real deployment
        raise HTTPException(status_code=500, detail=f"advisor_error: {exc}") from exc


@app.post("/chat_assistant")
async def legacy_contract(payload: AdvisorRequest):
    agents = get_agents()
    wf_in = WorkflowInput(input_as_text=payload.question)
    wf_out = await run_workflow(wf_in, *agents)
    return to_legacy_contract(wf_out)

