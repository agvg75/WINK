"""T1: mechanosensation and habituation as a C1 consumer."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
import sys

import numpy as np
from scipy.optimize import curve_fit

APP = Path(__file__).resolve().parents[2] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS
from failure_library import FailureLibrary
from reversal_core import ReversalEvent, response_summary


TOOL_NAME = "evoked_mechanosensation_habituation"
TOOL_VERSION = "0.1.0"
FRONT_ENDS = {"population_tap", "nose_touch", "gentle_body_touch",
              "harsh_body_touch"}


@dataclass(frozen=True)
class TrialRecord:
    plate_id: str
    trial_number: int
    interstimulus_interval_s: float | None
    event: ReversalEvent
    stimulus_front_end: str
    artifact_amplitude: float | None = None
    phase: str = "habituation"

    def validate(self):
        if self.stimulus_front_end not in FRONT_ENDS:
            raise ValueError(f"Unknown front end: {self.stimulus_front_end}")
        if self.trial_number < 1:
            raise ValueError("trial_number must be >= 1.")
        if self.phase not in {
                "habituation", "recovery", "dishabituation"}:
            raise ValueError("phase is not recognized.")
        if self.event.plate_id != self.plate_id:
            raise ValueError("Event and trial plate IDs disagree.")
        return self


def _decay(trial, asymptote, initial_minus_asymptote, rate):
    return asymptote + initial_minus_asymptote * np.exp(-rate * (trial - 1))


def _plate_trial_rows(records: list[TrialRecord]) -> list[dict]:
    grouped = defaultdict(list)
    for record in records:
        record.validate()
        grouped[(record.plate_id, record.phase,
                 record.trial_number)].append(record)
    rows = []
    for (plate, phase, trial), values in sorted(grouped.items()):
        eligible = [
            value.event for value in values
            if value.event.response != "excluded"]
        responders = [event for event in eligible if event.response == "yes"]
        reversals = [
            event for event in responders if event.event_type == "reversal"]
        accelerations = [
            event for event in responders
            if event.event_type == "forward_acceleration"]
        rows.append({
            "plate_id": plate,
            "phase": phase,
            "trial_number": trial,
            "interstimulus_interval_s": next(
                (value.interstimulus_interval_s for value in values
                 if value.interstimulus_interval_s is not None), None),
            "eligible_denominator": len(eligible),
            "excluded_denominator": len(values) - len(eligible),
            "response_probability": (
                None if not eligible else len(responders) / len(eligible)),
            "reversal_probability": (
                None if not eligible else len(reversals) / len(eligible)),
            "forward_acceleration_probability": (
                None if not eligible else len(accelerations) / len(eligible)),
            "mean_reversal_length_body_lengths": (
                None if not reversals else float(np.mean([
                    event.reversal_length_body_lengths
                    for event in reversals
                    if event.reversal_length_body_lengths is not None]))),
            "mean_peak_reversal_velocity_body_lengths_s": (
                None if not reversals else float(np.mean([
                    event.peak_reversal_velocity_body_lengths_s
                    for event in reversals
                    if event.peak_reversal_velocity_body_lengths_s is not None]))),
            "mean_artifact_amplitude": (
                None if not any(value.artifact_amplitude is not None
                                for value in values)
                else float(np.mean([
                    value.artifact_amplitude for value in values
                    if value.artifact_amplitude is not None]))),
        })
    return rows


def _fit_plate_habituation(rows: list[dict], plate_id: str) -> dict:
    selected = [
        row for row in rows
        if row["plate_id"] == plate_id and row["phase"] == "habituation"
        and row["response_probability"] is not None]
    if len(selected) < 3:
        return {
            "plate_id": plate_id, "initial_level": None, "asymptote": None,
            "decrement_rate_per_trial": None,
            "fit_status": "not estimable: fewer than three eligible trials"}
    x = np.asarray([row["trial_number"] for row in selected], dtype=float)
    y = np.asarray([row["response_probability"] for row in selected])
    try:
        parameters, _ = curve_fit(
            _decay, x, y, p0=[float(y[-1]), float(y[0] - y[-1]), 0.2],
            bounds=([0, -1, 0], [1, 1, 10]), maxfev=10000)
        asymptote, delta, rate = parameters
        return {
            "plate_id": plate_id,
            "initial_level": float(asymptote + delta),
            "asymptote": float(asymptote),
            "decrement_rate_per_trial": float(rate),
            "fit_status": "fit"}
    except Exception as exc:
        return {
            "plate_id": plate_id, "initial_level": None, "asymptote": None,
            "decrement_rate_per_trial": None,
            "fit_status": f"not estimable: {exc}"}


def analyze_habituation(
    records: list[TrialRecord],
    spontaneous_events: list[ReversalEvent],
    acquisition: AcquisitionMetadata,
    gate_decision: GateDecision,
    *,
    failure_library: FailureLibrary,
) -> dict:
    """Return plate-first results; never pool worms for inferential statistics."""
    acquisition.validate(require_complete=True)
    if gate_decision.status != PASS and not gate_decision.forced:
        return {
            **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
            "status": "refused",
            "reason": "capability gate did not pass and was not force-acknowledged",
            "capability_gate": gate_decision.as_dict(),
        }
    if not records:
        return {
            **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
            "status": "refused", "reason": "no trials were supplied",
            "capability_gate": gate_decision.as_dict(),
        }
    rows = _plate_trial_rows(records)
    plates = sorted({record.plate_id for record in records})
    fits = [_fit_plate_habituation(rows, plate) for plate in plates]
    evoked_events = [record.event for record in records]
    baseline = response_summary(
        evoked_events, spontaneous_events, mode="population")
    recovery = [
        row for row in rows if row["phase"] in {"recovery", "dishabituation"}]
    return {
        **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
        "status": "review_required",
        "inferential_unit": "plate",
        "plate_count": len(plates),
        "worm_level_p_value_emitted": False,
        "capability_gate": gate_decision.as_dict(),
        "trial_series": rows,
        "plate_habituation_fits": fits,
        "recovery_and_dishabituation": recovery,
        "evoked_vs_spontaneous": baseline,
        "review_contract": {
            "required_before_export": True,
            "editable": ["stimulus onset", "prior state", "event type",
                         "response", "exclusion", "artifact frames"],
        },
        "failure_library_path": str(failure_library.root),
    }
