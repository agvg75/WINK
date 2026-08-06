"""T9: endpoint chemotaxis/avoidance and vectorial positive control.

The population layer - time off OP50, movement state at plate opening,
per-segment covariates, toward/away split - comes from plate_assay and used to
exist only inside magnetotaxis. Chemotaxis had none of it, which meant plates
run at different delays after food removal were being compared as if that did
not matter.
"""
from __future__ import annotations

from common import analyze_tracks
from plate_assay import PointSource, population_layer

TOOL_NAME = "chemotaxis_avoidance"
TOOL_VERSION = "0.1.0"


def endpoint_index(toward: int, away: int, neutral: int = 0) -> dict:
    values = [toward, away, neutral]
    if any(int(value) < 0 for value in values):
        raise ValueError("Region counts cannot be negative.")
    total = sum(values)
    return {
        "index": None if total == 0 else (toward - away) / total,
        "chance_level": 0.0,
        "total_count": total,
        "status": "no worms counted" if total == 0 else "measured",
        "validation_level": "computational_regression",
        "validation_stamp": {
            "level": "computational_regression",
            "tool_name": TOOL_NAME, "tool_version": TOOL_VERSION,
            "metric": "endpoint_index"},
    }


def analyze_chemotaxis_tracks(
    *, tracks, provider, acquisition, gate_decision, failure_library,
    source_xy_mm, stimulus_orientations_deg=None,
    time_since_food_removal_s=None, food_removal_clock=None,
    assay_start_clock=None, per_worm_food_offsets_s=None,
    departure_rows=(), initial_state_window_s=30.0, pick_state=None,
    min_worms_per_regime=3, include_population_layer=True,
):
    result = analyze_tracks(
        tool_name=TOOL_NAME, tool_version=TOOL_VERSION, tracks=tracks,
        provider=provider, acquisition=acquisition, gate_decision=gate_decision,
        failure_library=failure_library, source_xy_mm=source_xy_mm,
        geometry="radial",
        stimulus_orientations_deg=stimulus_orientations_deg,
        endpoint_only=False,
        extra={"known_answer_calibrator": True})
    if result.get("status") != "refused":
        values = [
            row["along_gradient"] for row in result["segments"]
            if row["along_gradient"] is not None]
        result["along_gradient_positive_control"] = {
            "mean": None if not values else sum(values) / len(values),
            "passes_directional_sanity_check":
                bool(values) and sum(values) / len(values) > 0,
        }
        if include_population_layer:
            # An odour spot IS a point source, so chemotaxis gets the regime
            # split that was written inside magnetotaxis under the name
            # "field-flip analog" while taking source_xy_mm as its parameter.
            result["population"] = population_layer(
                tracks=tracks, segments=result["segments"],
                geometry=PointSource(source_xy_mm),
                departure_rows=departure_rows,
                time_since_food_removal_s=time_since_food_removal_s,
                food_removal_clock=food_removal_clock,
                assay_start_clock=assay_start_clock,
                per_worm_food_offsets_s=per_worm_food_offsets_s,
                initial_state_window_s=initial_state_window_s,
                pick_state=pick_state,
                min_worms_per_regime=min_worms_per_regime)
    return result
