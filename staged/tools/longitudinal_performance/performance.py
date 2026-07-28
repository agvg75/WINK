"""T3 swimming fatigue and T6 longitudinal decline."""
from __future__ import annotations

from collections import defaultdict
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

TOOL_NAME = "longitudinal_performance"
TOOL_VERSION = "0.1.0"


def _decay(time_s, asymptote, delta, rate):
    return asymptote + delta * np.exp(-rate * time_s)


def fit_fatigue_curve(times_s, values) -> dict:
    x = np.asarray(times_s, dtype=float)
    y = np.asarray(values, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    x, y = x[valid], y[valid]
    if len(x) < 3:
        return {"initial": None, "asymptote": None, "decay_constant_s": None,
                "decay_rate_s_inverse": None,
                "status": "not estimable: fewer than three observations"}
    try:
        parameters, _ = curve_fit(
            _decay, x - x.min(), y,
            p0=[float(y[-1]), float(y[0] - y[-1]), 0.01],
            bounds=([-np.inf, -np.inf, 0], [np.inf, np.inf, np.inf]),
            maxfev=10000)
        asymptote, delta, rate = parameters
        return {
            "initial": float(asymptote + delta),
            "asymptote": float(asymptote),
            "decay_constant_s": None if rate == 0 else float(1 / rate),
            "decay_rate_s_inverse": float(rate),
            "status": "no fatigue" if rate < 1e-6 else "decay fit"}
    except Exception as exc:
        return {"initial": None, "asymptote": None, "decay_constant_s": None,
                "decay_rate_s_inverse": None,
                "status": f"not estimable: {exc}"}


def analyze_swimming_fatigue(
    rows, acquisition: AcquisitionMetadata, gate_decision: GateDecision, *,
    failure_library: FailureLibrary,
) -> dict:
    acquisition.validate(require_complete=True)
    stamp = acquisition.stamped("swimming_fatigue", TOOL_VERSION)
    if gate_decision.status != PASS and not gate_decision.forced:
        return {**stamp, "status": "refused",
                "reason": "capability gate did not pass",
                "capability_gate": gate_decision.as_dict()}
    grouped = defaultdict(list)
    for row in rows:
        grouped[(str(row["plate_id"]), str(row["worm_id"]))].append(row)
    worm_results = []
    for (plate, worm), values in grouped.items():
        values.sort(key=lambda row: float(row["time_s"]))
        times = [float(row["time_s"]) for row in values]
        frequency = fit_fatigue_curve(
            times, [float(row["thrash_frequency_hz"]) for row in values])
        amplitude = fit_fatigue_curve(
            times, [float(row["amplitude_body_lengths"]) for row in values])
        recovery_rows = [row for row in values if row.get("phase") == "recovery"]
        worm_results.append({
            "plate_id": plate, "worm_id": worm,
            "frequency_fatigue": frequency, "amplitude_fatigue": amplitude,
            "amplitude_collapse": bool(
                amplitude["initial"] is not None and
                amplitude["asymptote"] is not None and
                amplitude["asymptote"] < 0.25 * amplitude["initial"]),
            "recovery_after_rest": (
                None if not recovery_rows else float(np.mean([
                    row["thrash_frequency_hz"] for row in recovery_rows]))),
        })
    plate_results = []
    for plate in sorted({row["plate_id"] for row in worm_results}):
        values = [row for row in worm_results if row["plate_id"] == plate]
        rates = [
            row["frequency_fatigue"]["decay_rate_s_inverse"] for row in values
            if row["frequency_fatigue"]["decay_rate_s_inverse"] is not None]
        plate_results.append({
            "plate_id": plate, "within_plate_worm_count": len(values),
            "mean_frequency_decay_rate_s_inverse":
                None if not rates else float(np.mean(rates))})
    return {
        **stamp, "status": "review_required", "inferential_unit": "plate",
        "capability_gate": gate_decision.as_dict(),
        "worm_observations": worm_results, "plate_summaries": plate_results,
        "flat_nondecaying_is_valid": True,
        "failure_library_path": str(failure_library.root)}


def analyze_longitudinal_decline(session_rows) -> dict:
    """Aggregate maintained cohort identities across adult-age sessions."""
    grouped = defaultdict(list)
    for row in session_rows:
        grouped[(str(row["cohort_id"]), str(row["plate_id"]))].append(row)
    curves = []
    for (cohort, plate), values in grouped.items():
        values.sort(key=lambda row: float(row["adult_age_days"]))
        ages = np.asarray([row["adult_age_days"] for row in values], dtype=float)
        measurements = np.asarray(
            [row["measurement"] for row in values], dtype=float)
        slope = (
            None if len(values) < 2 else
            float(np.polyfit(ages, measurements, 1)[0]))
        curves.append({
            "cohort_id": cohort, "plate_id": plate,
            "sessions": values, "slope_per_day": slope,
            "trajectory": (
                "not estimable" if slope is None else
                "flat/no decline" if abs(slope) < 1e-9 else
                "decline" if slope < 0 else "increase")})
    return {"inferential_unit": "cohort", "cohort_plate_curves": curves,
            "flat_trajectory_is_valid": True,
            "validation_level": "computational_regression",
            "validation_stamp": {
                "level": "computational_regression",
                "tool_name": "longitudinal_healthspan",
                "tool_version": TOOL_VERSION,
                "metric": "cohort_decline_curve"}}
