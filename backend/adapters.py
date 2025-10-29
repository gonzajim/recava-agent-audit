"""Legacy contract adapters."""

from typing import Any, Dict, List


def to_legacy_contract(wf_result: Dict[str, Any]) -> Dict[str, Any]:
    final = wf_result.get("respuesta_final") or wf_result.get("asistente_inicial", {}).get("output_text", "")
    citations: List[Dict[str, Any]] = wf_result.get("citas", []) or []
    return {
        "message": final,
        "citations": citations,
        "meta": {
            "evaluations": wf_result.get("evaluaciones", []),
            "draft": wf_result.get("asistente_inicial", {}).get("output_text", ""),
        },
    }

