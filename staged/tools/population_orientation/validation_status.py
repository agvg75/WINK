"""Config 2 validation evidence and tested acquisition envelope."""
import json
from pathlib import Path

ENVELOPE_PATH = Path(__file__).with_name("config2_validated_envelope.json")
CONFIG2_VALIDATION_REASON = (
    "Config 2 is runnable at computational-regression level. It has not yet "
    "earned technical validation on representative crowded plates.")
CONFIG2_REQUIRED_GATES = (
    "synthetic_identity_regression",
    "manual_crowded_plate_technical_validation",
)


def config2_status():
    envelope = (
        json.loads(ENVELOPE_PATH.read_text(encoding="utf-8"))
        if ENVELOPE_PATH.is_file() else None)
    return {
        "validated": envelope is not None,
        "reason": CONFIG2_VALIDATION_REASON,
        "required_gates": list(CONFIG2_REQUIRED_GATES),
        "validated_envelope": envelope,
        "validation_level": (
            "technical_validation" if envelope
            else "computational_regression"),
    }
