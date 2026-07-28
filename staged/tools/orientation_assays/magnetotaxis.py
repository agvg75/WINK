"""T8: magnetotaxis with departure, state, pulse, and identifiability contracts."""
from __future__ import annotations

from datetime import datetime
import numpy as np

from common import analyze_tracks
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


def resolve_time_off_op50_offset(
    *, elapsed_s=None, food_removal_clock=None, assay_start_clock=None,
):
    """Return the physiological-clock offset without inventing a zero."""
    if elapsed_s is not None and elapsed_s != "":
        value = float(elapsed_s)
        if value < 0:
            raise ValueError("Time off OP50 cannot be negative.")
        return value
    if food_removal_clock and assay_start_clock:
        parsed = []
        for value in (food_removal_clock, assay_start_clock):
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    parsed.append(datetime.strptime(str(value), fmt))
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("Clock times must be HH:MM or HH:MM:SS.")
        delta = (parsed[1] - parsed[0]).total_seconds()
        return float(delta + 24 * 3600 if delta < 0 else delta)
    return None


def _initial_states(rows, opening_s=30.0, speed_threshold=0.05,
                    angular_velocity_threshold=30.0):
    grouped, output = {}, {}
    for row in rows:
        grouped.setdefault(
            (str(row["plate_id"]), str(row.get("worm_id"))), []).append(row)
    for key, group in grouped.items():
        group = sorted(group, key=lambda item: float(item["time_s"]))
        start = float(group[0]["time_s"])
        opening = [row for row in group
                   if float(row["time_s"]) <= start + float(opening_s)]
        if len(opening) < 3 or float(opening[-1]["time_s"]) - start < opening_s / 2:
            output[key] = "unclassified"
            continue
        speeds, turns = [], []
        for left, right in zip(opening, opening[1:]):
            dt = float(right["time_s"]) - float(left["time_s"])
            if dt <= 0:
                continue
            speeds.append(np.hypot(
                float(right["x_mm"]) - float(left["x_mm"]),
                float(right["y_mm"]) - float(left["y_mm"])) / dt)
            turns.append(abs(float(wrap_degrees(
                float(right["heading_deg"]) -
                float(left["heading_deg"])))) / dt)
        output[key] = (
            "roaming" if speeds and np.median(speeds) >= speed_threshold
            and np.median(turns) <= angular_velocity_threshold
            else "dwelling" if speeds else "unclassified")
    return output


def build_segment_covariates(
    tracks, orientation_segments, departure_rows, plate_food_offset_s,
    *, per_worm_food_offsets_s=None, initial_state_window_s=30.0,
    dwell_speed_threshold_mm_s=0.02, spine_quality_threshold=0.7,
    pick_state=None,
):
    """Keep full-resolution predictors; summaries are downstream."""
    departures = {str(row.get("worm_id")): row for row in departure_rows}
    initial = _initial_states(tracks, opening_s=initial_state_window_s)
    lookup = {
        (str(row["plate_id"]), str(row.get("worm_id")), float(row["time_s"])):
            dict(row) for row in orientation_segments}
    per_worm_food_offsets_s = per_worm_food_offsets_s or {}
    grouped = {}
    for row in tracks:
        grouped.setdefault(
            (str(row["plate_id"]), str(row.get("worm_id"))), []).append(row)
    output, events = [], []
    for key, group in grouped.items():
        group = sorted(group, key=lambda item: float(item["time_s"]))
        run_length = 0.0
        for index, row in enumerate(group):
            time_s = float(row["time_s"])
            enriched = lookup.get((key[0], key[1], time_s))
            if enriched is None:
                continue
            dt = distance = angular_velocity = 0.0
            if index:
                previous = group[index - 1]
                dt = time_s - float(previous["time_s"])
                if dt > 0:
                    distance = float(np.hypot(
                        float(row["x_mm"]) - float(previous["x_mm"]),
                        float(row["y_mm"]) - float(previous["y_mm"])))
                    angular_velocity = float(wrap_degrees(
                        float(row["heading_deg"]) -
                        float(previous["heading_deg"]))) / dt
            velocity = row.get("forward_velocity_mm_s")
            velocity = float(velocity) if velocity is not None else (
                distance / dt if dt > 0 else 0.0)
            reversing = bool(row.get("reversing", velocity < 0))
            run_length = 0.0 if reversing else run_length + distance
            departure = departures.get(key[1], {})
            committed = departure.get("committed_departure_s")
            worm_offset = per_worm_food_offsets_s.get(
                key[1], plate_food_offset_s)
            spine_quality = row.get("spine_quality")
            event_candidate = bool(row.get(
                "reorientation_event", abs(angular_velocity) >= 90))
            mode = None
            if event_candidate:
                if spine_quality is None or float(spine_quality) < spine_quality_threshold:
                    mode = "unclassified"
                elif bool(row.get("omega_turn", False)):
                    mode = "omega_turn"
                elif reversing and bool(row.get(
                        "turning", abs(angular_velocity) >= 30)):
                    mode = "reversal_then_turn_pirouette"
                elif reversing:
                    mode = "reversal"
                else:
                    mode = "shallow_gradual_turn"
                events.append({
                    "plate_id": key[0], "worm_id": key[1], "time_s": time_s,
                    "turning_mode": mode, "spine_quality": spine_quality,
                    "validation_level": "computational_regression"})
            enriched.update({
                "assay_elapsed_s": time_s,
                "time_off_op50_s": (
                    None if worm_offset is None else float(worm_offset) + time_s),
                "forward_velocity_mm_s": velocity,
                "absolute_angular_velocity_deg_s": abs(angular_velocity),
                "signed_track_curvature_deg_s": angular_velocity,
                "turning_frequency_hz": (
                    float(row.get("turning", abs(angular_velocity) >= 30)) / dt
                    if dt > 0 else 0.0),
                "reversal_rate_hz": float(reversing) / dt if dt > 0 else 0.0,
                "run_length_mm": run_length,
                "dwell": velocity >= 0 and
                    abs(velocity) < dwell_speed_threshold_mm_s,
                "time_since_committed_departure_s": (
                    None if committed is None or time_s < float(committed)
                    else time_s - float(committed)),
                "initial_state": initial.get(key, "unclassified"),
                "pick_state": (
                    pick_state.get(key[1]) if isinstance(pick_state, dict)
                    else pick_state),
                "turning_mode": mode,
            })
            output.append(enriched)
    return output, events


def regime_comparison(segment_rows, source_xy_mm, min_worms_per_regime=3,
                      rotation_tolerance_deg=30.0,
                      concentration_tolerance=0.2):
    """Plate-first internal field-flip analog with explicit thin-cell refusal."""
    source, worms = np.asarray(source_xy_mm, dtype=float), {}
    for row in segment_rows:
        worms.setdefault(
            (str(row["plate_id"]), str(row["worm_id"])), []).append(row)
    by_plate = {}
    for (plate, worm), rows in worms.items():
        rows = sorted(rows, key=lambda item: float(item["time_s"]))
        start = np.asarray([rows[0]["x_mm"], rows[0]["y_mm"]], dtype=float)
        end = np.asarray([rows[-1]["x_mm"], rows[-1]["y_mm"]], dtype=float)
        regime = ("toward" if np.linalg.norm(start - source) >
                  np.linalg.norm(end - source) else "away")
        by_plate.setdefault(plate, {"toward": [], "away": []})[regime].append(
            {"worm_id": worm, "rows": rows})
    results = {}
    for plate, regimes in by_plate.items():
        summary = {}
        for name, members in regimes.items():
            angles = [row["angle_to_vector_deg"] for member in members
                      for row in member["rows"]
                      if row.get("angle_to_vector_deg") is not None]
            curvature = [row["signed_track_curvature_deg_s"]
                         for member in members for row in member["rows"]]
            summary[name] = {
                "n_worms": len(members), "held_angle": mean_resultant(angles),
                "mean_signed_track_curvature_deg_s": (
                    float(np.mean(curvature)) if curvature else None)}
        if min(summary["toward"]["n_worms"],
               summary["away"]["n_worms"]) < min_worms_per_regime:
            results[plate] = {
                "status": "withheld",
                "reason": "Too few worms in one regime for comparison.",
                "regimes": summary}
            continue
        toward, away = summary["toward"]["held_angle"], summary["away"]["held_angle"]
        separation = abs(float(wrap_degrees(
            away["mean_angle_deg"] - toward["mean_angle_deg"])))
        rotation_error = abs(180.0 - separation)
        c1 = summary["toward"]["mean_signed_track_curvature_deg_s"]
        c2 = summary["away"]["mean_signed_track_curvature_deg_s"]
        chirality = c1 is not None and c2 is not None and (
            c1 == 0 or c2 == 0 or np.sign(c1) == np.sign(c2))
        concentration_difference = abs(
            toward["resultant_length"] - away["resultant_length"])
        results[plate] = {
            "status": "computed", "regimes": summary,
            "concentration_difference": concentration_difference,
            "concentrations_comparable":
                concentration_difference <= concentration_tolerance,
            "preferred_angle_separation_deg": separation,
            "rotation_error_from_180_deg": rotation_error,
            "rotation_not_reflection_supported":
                rotation_error <= rotation_tolerance_deg,
            "chirality_conserved": bool(chirality),
            "decisive_internal_field_flip_analog": bool(
                concentration_difference <= concentration_tolerance and
                rotation_error <= rotation_tolerance_deg and chirality)}
    computed = [row for row in results.values()
                if row["status"] == "computed"]
    return {
        "inferential_unit": "plate", "per_plate": results,
        "plates_computed": len(computed),
        "plates_withheld": len(results) - len(computed),
        "across_plate": {
            "status": "computed" if len(computed) >= 2 else "withheld",
            "reason": None if len(computed) >= 2 else
                "At least two qualifying plates are required.",
            "mean_rotation_error_deg": (
                float(np.mean([row["rotation_error_from_180_deg"]
                               for row in computed]))
                if len(computed) >= 2 else None),
            "fraction_conserved_chirality": (
                float(np.mean([row["chirality_conserved"]
                               for row in computed]))
                if len(computed) >= 2 else None)}}


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
