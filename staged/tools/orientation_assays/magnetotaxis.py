"""T8: magnetotaxis with departure, state, pulse, and identifiability contracts."""
from __future__ import annotations

from datetime import datetime
import numpy as np

from common import analyze_tracks
# These four are not magnetic - they are what every plate-migration assay
# shares, and they moved to plate_assay so chemotaxis and thermotaxis can
# use them too. Imported back here so existing callers are unaffected.
from plate_assay import (
    build_segment_covariates, regime_comparison,
    resolve_time_off_op50_offset, _initial_states)
from orientation_core import mean_resultant, wrap_degrees
from validation_status import config2_status
from validation import envelope_warnings, stamp

TOOL_NAME = "magnetotaxis"
TOOL_VERSION = "0.2.0"

PREDICTOR_ROLES = {
    "assay_elapsed_s": "primary", "time_off_op50_s": "primary",
    "forward_velocity_mm_s": "exploratory",
    "absolute_angular_velocity_deg_s": "exploratory",
    "turning_frequency_hz": "exploratory",
    "reversal_rate_hz": "exploratory", "run_length_mm": "exploratory",
    "dwell": "exploratory",
    "time_since_committed_departure_s": "exploratory",
    "initial_state": "exploratory", "pick_state": "exploratory",
}


def analyze_magnetotaxis(
    *, tracks, provider, acquisition, gate_decision, failure_library,
    departure_results, humidity_percent, worm_age, genotype,
    time_since_food_removal_s=None, magnetic_pulse=None, source_xy_mm=None,
    stimulus_orientations_deg=None, endpoint_only=False,
    analysis_tier="plate_state", config2_validation_override=False,
    config2_recording_conditions=None,
    food_removal_clock=None, assay_start_clock=None,
    per_worm_food_removal_offsets_s=None, initial_state_window_s=30.0,
    pick_state=None, min_worms_per_regime=3,
):
    food_offset_s = resolve_time_off_op50_offset(
        elapsed_s=time_since_food_removal_s,
        food_removal_clock=food_removal_clock,
        assay_start_clock=assay_start_clock)
    required = {
        "humidity_percent": humidity_percent, "worm_age": worm_age,
        "genotype": genotype,
        "time_off_op50_at_assay_start": food_offset_s,
    }
    missing = [name for name, value in required.items()
               if value is None or value == ""]
    if missing:
        raise ValueError(
            "Magnetotaxis state variables are required: " + ", ".join(missing))
    if not getattr(provider, "has_true_direction", False):
        raise ValueError("Magnetotaxis requires a true-direction field provider.")
    if analysis_tier not in {"plate_state", "per_worm_vectorial"}:
        raise ValueError("analysis_tier is not recognized.")
    status = config2_status()
    level = status["validation_level"] if (
        analysis_tier == "per_worm_vectorial") else "computational_regression"
    tier_stamp = stamp(
        TOOL_NAME, TOOL_VERSION,
        "per_worm_vectorial_orientation" if
        analysis_tier == "per_worm_vectorial" else "plate_state_orientation",
        level=level, validated_envelope=status.get("validated_envelope"),
        evidence=("synthetic_identity_regression",))
    departure_rows = (
        [result.as_dict() for result in departure_results]
        if analysis_tier == "per_worm_vectorial" else [])
    start_fields = {}
    for row in sorted(tracks, key=lambda item: float(item["time_s"])):
        worm = str(row.get("worm_id"))
        if worm in start_fields:
            continue
        sample = provider.sample(
            float(row["x_mm"]), float(row["y_mm"]), float(row["time_s"]))
        start_fields[worm] = {
            "start_field_magnitude": float(sample.magnitude),
            "start_gradient_magnitude": float(np.linalg.norm(
                np.asarray(sample.gradient_xy, dtype=float)))}
    for row in departure_rows:
        row.update(start_fields.get(str(row.get("worm_id")), {}))

    def field_regression(outcome):
        usable = [row for row in departure_rows
                  if row.get(outcome) is not None and
                  row.get("start_field_magnitude") is not None and
                  row.get("start_gradient_magnitude") is not None]
        if len(usable) < 3:
            return {"status": "insufficient", "n": len(usable),
                    "reason": "At least three uncensored worms are required."}
        y = np.asarray([row[outcome] for row in usable], dtype=float)
        x = np.column_stack([
            np.ones(len(usable)),
            [row["start_field_magnitude"] for row in usable],
            [row["start_gradient_magnitude"] for row in usable]])
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        return {
            "status": "computed", "n": len(usable),
            "intercept": float(beta[0]),
            "field_magnitude_slope": float(beta[1]),
            "field_gradient_slope": float(beta[2]),
            "censoring_note": (
                "Descriptive uncensored regression; survival regression is "
                "required for publication certification.")}
    field_trapping = {
        "central_dwell": field_regression("central_dwell_s"),
        "departure_latency": field_regression("committed_departure_s"),
        "validation_level": "computational_regression"}
    result = analyze_tracks(
        tool_name=TOOL_NAME, tool_version=TOOL_VERSION, tracks=tracks,
        provider=provider, acquisition=acquisition, gate_decision=gate_decision,
        failure_library=failure_library, source_xy_mm=source_xy_mm,
        geometry="radial",
        stimulus_orientations_deg=stimulus_orientations_deg,
        endpoint_only=endpoint_only,
        extra={
            "state_variables": {
                "humidity_percent": float(humidity_percent),
                "worm_age": str(worm_age), "genotype": str(genotype),
                "time_since_food_removal_s": float(food_offset_s),
                "food_removal_clock": food_removal_clock,
                "assay_start_clock": assay_start_clock},
            "magnetic_pulse": dict(magnetic_pulse or {}),
            "analysis_tier": analysis_tier,
            "config2_validation": status,
            "config2_envelope_warnings": envelope_warnings(
                config2_recording_conditions or {},
                status.get("validated_envelope"))
                if analysis_tier == "per_worm_vectorial" else [],
            "departure_survival_rows": departure_rows,
            "primary_departure_outputs": [
                "committed_departure_s", "reentry_count", "central_dwell_s"],
            "field_trapping_test_required":
                analysis_tier == "per_worm_vectorial",
            "field_trapping_regressions": field_trapping,
            "field_overlay_review_required": True,
            "validation_level": level,
            "validation_stamp": tier_stamp,
        })
    if analysis_tier == "per_worm_vectorial":
        covariates, turning_events = build_segment_covariates(
            tracks, result["segments"], departure_rows, food_offset_s,
            per_worm_food_offsets_s=per_worm_food_removal_offsets_s,
            initial_state_window_s=initial_state_window_s,
            pick_state=pick_state)
        result["segments"] = covariates
        result["per_segment_covariate_schema"] = {
            name: {"predictor_role": role}
            for name, role in PREDICTOR_ROLES.items()}
        result["turning_mode_events"] = turning_events
        result["turning_mode_gate"] = {
            "requirement":
                "reviewed spine_quality >= 0.7 on reorientation frames",
            "null": "unclassified"}
        result["within_plate_regime_comparison"] = regime_comparison(
            covariates, source_xy_mm,
            min_worms_per_regime=min_worms_per_regime)
        departure_by_worm = {
            str(row.get("worm_id")): row for row in departure_rows}
        states = {}
        for row in covariates:
            states.setdefault(str(row["worm_id"]), row["initial_state"])
        nondeparters = [
            worm for worm, row in departure_by_worm.items()
            if row.get("departure_censored")]
        result["non_departer_state_composition"] = {
            "n_all_reviewed_worms": len(departure_by_worm),
            "n_never_committed": len(nondeparters),
            "fraction_never_committed": (
                len(nondeparters) / len(departure_by_worm)
                if departure_by_worm else None),
            "initial_state_counts": {
                state: sum(states.get(worm) == state for worm in nondeparters)
                for state in ("roaming", "dwelling", "unclassified")}}
        result["analysis_discipline"] = {
            "observational_covariates_are_not_causal": True,
            "exploratory_relationships_require_held_out_plates": True,
            "pick_state_manipulation_required_to_disentangle_correlated_predictors":
                True}
    return result


def comparable_angle_runs(left: dict, right: dict) -> tuple[bool, str]:
    keys = ("humidity_percent", "worm_age", "genotype",
            "time_since_food_removal_s")
    for key in keys:
        if key not in left or key not in right:
            return False, f"cannot compare angles: {key} was not declared"
    return True, "required state variables were declared in both runs"
