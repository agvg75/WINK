"""T2: plate-level time-to-paralysis analysis."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

import numpy as np

APP = Path(__file__).resolve().parents[2] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS
from failure_library import FailureLibrary


TOOL_NAME = "neuromuscular_paralysis_pharmacology"
TOOL_VERSION = "0.1.0"
DRUGS = {"aldicarb", "levamisole", "vehicle"}


@dataclass(frozen=True)
class ProdObservation:
    plate_id: str
    worm_id: str
    time_s: float
    result: str
    drug: str
    concentration: float | None
    excluded_reason: str | None = None

    def validate(self):
        if self.result not in {"moving", "paralyzed", "excluded"}:
            raise ValueError("result must be moving, paralyzed, or excluded.")
        if self.drug not in DRUGS:
            raise ValueError(f"drug must be one of {sorted(DRUGS)}")
        if self.time_s < 0:
            raise ValueError("time_s must be non-negative.")
        if self.result == "excluded" and not self.excluded_reason:
            raise ValueError("Excluded observations require a reason.")
        return self


def _worm_outcomes(observations: list[ProdObservation]) -> list[dict]:
    grouped = defaultdict(list)
    for observation in observations:
        observation.validate()
        if observation.result != "excluded":
            grouped[(observation.plate_id, observation.worm_id)].append(
                observation)
    outcomes = []
    for (plate, worm), values in grouped.items():
        values.sort(key=lambda value: value.time_s)
        event = next(
            (value for value in values if value.result == "paralyzed"), None)
        final_time = values[-1].time_s
        outcomes.append({
            "plate_id": plate,
            "worm_id": worm,
            "duration_s": float(event.time_s if event else final_time),
            "event_observed": event is not None,
            "drug": values[0].drug,
            "concentration": values[0].concentration,
        })
    return outcomes


def _plate_curves(observations: list[ProdObservation]) -> list[dict]:
    grouped = defaultdict(list)
    for observation in observations:
        observation.validate()
        grouped[(observation.plate_id, observation.time_s)].append(observation)
    rows = []
    for (plate, time_s), values in sorted(grouped.items()):
        eligible = [value for value in values if value.result != "excluded"]
        moving = sum(value.result == "moving" for value in eligible)
        rows.append({
            "plate_id": plate, "time_s": float(time_s),
            "eligible_denominator": len(eligible),
            "excluded_denominator": len(values) - len(eligible),
            "fraction_still_moving": (
                None if not eligible else moving / len(eligible)),
            "drug": values[0].drug,
            "concentration": values[0].concentration,
        })
    return rows


def analyze_paralysis(
    observations: list[ProdObservation],
    acquisition: AcquisitionMetadata,
    gate_decision: GateDecision,
    *,
    failure_library: FailureLibrary,
) -> dict:
    acquisition.validate(require_complete=True)
    if gate_decision.status != PASS and not gate_decision.forced:
        return {
            **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
            "status": "refused",
            "reason": "capability gate did not pass and was not force-acknowledged",
            "capability_gate": gate_decision.as_dict(),
        }
    if not observations:
        return {
            **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
            "status": "refused", "reason": "no prod observations supplied",
            "capability_gate": gate_decision.as_dict(),
        }
    outcomes = _worm_outcomes(observations)
    plates = sorted({observation.plate_id for observation in observations})
    return {
        **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
        "status": "review_required",
        "inferential_unit": "plate",
        "plate_count": len(plates),
        "worm_level_p_value_emitted": False,
        "capability_gate": gate_decision.as_dict(),
        "plate_fraction_moving_curves": _plate_curves(observations),
        "censored_worm_outcomes_for_plate_curves": outcomes,
        "interpretation": {
            "aldicarb": "combined presynaptic and postsynaptic state",
            "levamisole": "postsynaptic muscle-side state",
            "required_dissociation": "compare drug-specific plate curves; do not "
                                    "interpret aldicarb alone as presynaptic",
        },
        "review_contract": {
            "required_before_export": True,
            "editable": ["moving", "paralyzed", "excluded", "exclusion reason"],
        },
        "failure_library_path": str(failure_library.root),
    }
