"""Part VIII validation stamps that travel with every result."""
from __future__ import annotations

from dataclasses import asdict, dataclass

LEVELS = (
    "computational_regression", "technical_validation",
    "biological_validation", "publication_use")


@dataclass(frozen=True)
class ValidationStamp:
    level: str
    tool_name: str
    tool_version: str
    metric: str
    evidence: tuple[str, ...] = ()
    validated_envelope: dict | None = None

    def as_dict(self):
        if self.level not in LEVELS:
            raise ValueError(f"Unknown Part VIII validation level: {self.level}")
        return asdict(self)


def stamp(tool_name, tool_version, metric, *,
          level="computational_regression", evidence=(),
          validated_envelope=None):
    return ValidationStamp(
        level, tool_name, tool_version, metric, tuple(evidence),
        validated_envelope).as_dict()


def publication_certification(validation_stamp: dict) -> dict:
    level = validation_stamp.get("level")
    passed = level in {
        "technical_validation", "biological_validation", "publication_use"}
    return {
        "publication_certified": passed,
        "status": "eligible" if passed else "refused",
        "reason": "" if passed else (
            "Publication certification requires technical validation for "
            "this metric. The computational result remains available with "
            "its current validation stamp."),
        "input_validation_stamp": validation_stamp,
    }


def envelope_warnings(recording: dict, envelope: dict | None) -> list[str]:
    if not envelope:
        return ["No Config 2 technical-validation envelope exists yet."]
    warnings = []
    for key, limits in envelope.items():
        if key not in recording or recording[key] is None:
            warnings.append(f"{key} was not declared; envelope match unknown")
            continue
        value = recording[key]
        if isinstance(limits, dict):
            if limits.get("min") is not None and value < limits["min"]:
                warnings.append(f"{key} is below validated minimum")
            if limits.get("max") is not None and value > limits["max"]:
                warnings.append(f"{key} is above validated maximum")
        elif isinstance(limits, list) and value not in limits:
            warnings.append(f"{key} is outside validated values")
    return warnings
