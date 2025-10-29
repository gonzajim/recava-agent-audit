"""Guardrails helpers to keep workflow module slim."""

from guardrails.runtime import instantiate_guardrails, load_config_bundle, run_guardrails  # type: ignore

# TODO: replace placeholders with your real context/config bundle.
ctx = object()
guardrails_config = "path/to/guardrails_bundle"


def guardrails_has_tripwire(result) -> bool:
    try:
        return bool(getattr(result, "has_tripwire", False))
    except Exception:
        return False


def get_guardrail_checked_text(result, original: str) -> str:
    # If your guardrails apply transformations (e.g., anonymization), expose them here.
    return original

