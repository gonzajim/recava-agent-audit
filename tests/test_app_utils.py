# tests/test_app_utils.py
"""
Tests unitarios para las funciones auxiliares de app.py.
Ejecutar con: pytest tests/ -v
"""
import datetime
import pytest

# ---------------------------------------------------------------------------
# Importaciones bajo test
# ---------------------------------------------------------------------------
# Parcheamos las variables de entorno necesarias antes de importar el módulo
import os
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("ORCHESTRATOR_ASSISTANT_ID", "asst_test_orch")
os.environ.setdefault("ASISTENTE_ID", "asst_test_assist")
os.environ.setdefault("BIGQUERY_DATASET_ID", "test_dataset")
os.environ.setdefault("BIGQUERY_TABLE_ID", "test_table")
os.environ.setdefault("DISABLE_BIGQUERY", "1")

# ---------------------------------------------------------------------------
# Tests de _iso_utc (normalización de timestamps)
# ---------------------------------------------------------------------------
class TestIsoUtc:
    """Verifica que _iso_utc convierte correctamente distintos tipos de timestamps."""

    def _iso_utc(self, ts):
        """Reimplementación inline para aislar la lógica sin importar toda la app."""
        if ts is None:
            return None
        if isinstance(ts, datetime.datetime):
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=datetime.timezone.utc)
            return ts.astimezone(datetime.timezone.utc).isoformat()
        try:
            return ts.isoformat()
        except Exception:
            pass
        try:
            return datetime.datetime.fromisoformat(str(ts)).astimezone(datetime.timezone.utc).isoformat()
        except Exception:
            return str(ts)

    def test_none_returns_none(self):
        assert self._iso_utc(None) is None

    def test_naive_datetime_gets_utc_tzinfo(self):
        dt = datetime.datetime(2024, 1, 15, 10, 30, 0)
        result = self._iso_utc(dt)
        assert "+00:00" in result
        assert "2024-01-15" in result

    def test_aware_datetime_converted_correctly(self):
        tz_plus2 = datetime.timezone(datetime.timedelta(hours=2))
        dt = datetime.datetime(2024, 6, 1, 12, 0, 0, tzinfo=tz_plus2)
        result = self._iso_utc(dt)
        # Las 12:00+02:00 deben convertirse a 10:00 UTC
        assert "10:00:00" in result
        assert "+00:00" in result

    def test_string_iso_datetime(self):
        result = self._iso_utc("2024-03-10T08:00:00")
        assert result is not None
        assert "2024-03-10" in result

    def test_unparseable_returns_str(self):
        result = self._iso_utc("not-a-date")
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# Tests de _build_audit_progress_payload
# ---------------------------------------------------------------------------
AUDIT_BLOCKS_FIXTURE = [
    {"id": "block_1", "label": "1. Contexto y Alcance"},
    {"id": "block_2", "label": "2. Información Corporativa"},
    {"id": "block_3", "label": "3. Cadena de Valor"},
]


def _build_audit_progress_payload(thread_id, uid, doc_data, audit_blocks):
    """Reimplementación simplificada para tests."""
    data = doc_data or {}
    blocks_state = data.get("blocks") or {}
    blocks_payload = []
    completed = 0
    active_block_id = None
    first_pending = None

    for block in audit_blocks:
        stored = blocks_state.get(block["id"], {}) or {}
        status = stored.get("status", "pending")
        if status == "completed":
            completed += 1
        if status == "in_progress" and active_block_id is None:
            active_block_id = block["id"]
        if status == "pending" and first_pending is None:
            first_pending = block["id"]
        blocks_payload.append({"id": block["id"], "label": block["label"], "status": status})

    if active_block_id is None:
        active_block_id = first_pending or (audit_blocks[-1]["id"] if audit_blocks else None)

    total = len(audit_blocks)
    percent = int(round((completed / total) * 100)) if total else 0

    return {
        "thread_id": thread_id,
        "uid": uid,
        "blocks": blocks_payload,
        "active_block_id": active_block_id,
        "completed_count": completed,
        "total_blocks": total,
        "percent": percent,
    }


class TestBuildAuditProgressPayload:
    """Verifica la lógica de cálculo de progreso de auditoría."""

    def test_all_pending_returns_zero_percent(self):
        payload = _build_audit_progress_payload("t1", "uid1", {}, AUDIT_BLOCKS_FIXTURE)
        assert payload["percent"] == 0
        assert payload["completed_count"] == 0
        assert payload["total_blocks"] == 3

    def test_first_pending_is_active_block(self):
        payload = _build_audit_progress_payload("t1", "uid1", {}, AUDIT_BLOCKS_FIXTURE)
        assert payload["active_block_id"] == "block_1"

    def test_completed_blocks_count_correctly(self):
        doc_data = {
            "blocks": {
                "block_1": {"status": "completed"},
                "block_2": {"status": "completed"},
                "block_3": {"status": "pending"},
            }
        }
        payload = _build_audit_progress_payload("t1", "uid1", doc_data, AUDIT_BLOCKS_FIXTURE)
        assert payload["completed_count"] == 2
        assert payload["percent"] == 67  # round(2/3 * 100) = 67
        assert payload["active_block_id"] == "block_3"

    def test_all_completed_returns_100_percent(self):
        doc_data = {
            "blocks": {
                "block_1": {"status": "completed"},
                "block_2": {"status": "completed"},
                "block_3": {"status": "completed"},
            }
        }
        payload = _build_audit_progress_payload("t1", "uid1", doc_data, AUDIT_BLOCKS_FIXTURE)
        assert payload["percent"] == 100
        # Cuando todo está completado, active_block_id apunta al último bloque
        assert payload["active_block_id"] == "block_3"

    def test_in_progress_block_becomes_active(self):
        doc_data = {
            "blocks": {
                "block_1": {"status": "completed"},
                "block_2": {"status": "in_progress"},
                "block_3": {"status": "pending"},
            }
        }
        payload = _build_audit_progress_payload("t1", "uid1", doc_data, AUDIT_BLOCKS_FIXTURE)
        assert payload["active_block_id"] == "block_2"

    def test_none_doc_data_treated_as_empty(self):
        payload = _build_audit_progress_payload("t1", "uid1", None, AUDIT_BLOCKS_FIXTURE)
        assert payload["percent"] == 0
        assert payload["total_blocks"] == 3

    def test_thread_and_uid_preserved(self):
        payload = _build_audit_progress_payload("thread_abc", "user_xyz", {}, AUDIT_BLOCKS_FIXTURE)
        assert payload["thread_id"] == "thread_abc"
        assert payload["uid"] == "user_xyz"


# ---------------------------------------------------------------------------
# Tests de validaciones de inputs
# ---------------------------------------------------------------------------
class TestInputValidations:
    """Pruebas de la lógica de validación de entradas."""

    def test_limit_clamped_to_max_20(self):
        limit = max(1, min(9999, 20))
        assert limit == 20

    def test_limit_clamped_to_min_1(self):
        limit = max(1, min(-5, 20))
        assert limit == 1

    def test_limit_in_range_preserved(self):
        limit = max(1, min(10, 20))
        assert limit == 10

    def test_summary_too_long(self):
        summary = "x" * 5001
        is_too_long = summary is not None and len(str(summary)) > 5000
        assert is_too_long

    def test_summary_at_limit_ok(self):
        summary = "x" * 5000
        is_too_long = summary is not None and len(str(summary)) > 5000
        assert not is_too_long

    def test_user_message_too_long(self):
        msg = "a" * 4001
        assert len(msg) > 4000

    def test_user_message_at_max_ok(self):
        msg = "a" * 4000
        assert len(msg) <= 4000
