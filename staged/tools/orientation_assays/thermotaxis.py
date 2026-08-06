"""T7: linear and radial thermotaxis.

Andres's description of the assay: two temperatures, one at each end, worms in
the middle, and they crawl toward cultivation temperature. That last part is
why the shared layer takes a GEOMETRY rather than a source position - the
preferred end is a fact about how the animals were reared, so two plates with
identical geometry and differently reared worms have opposite "toward"
directions, and the preferred temperature may not lie on the plate at all.

The population layer (time off OP50, state at plate opening, covariates,
toward/away) comes from plate_assay and previously existed only inside
magnetotaxis.
"""
from __future__ import annotations

from common import analyze_tracks
from plate_assay import LinearGradient, population_layer

TOOL_NAME = "thermotaxis"
TOOL_VERSION = "0.1.0"


def analyze_thermotaxis(
    *, tracks, provider, acquisition, gate_decision, failure_library,
    cultivation_temperature_c, feeding_state, spatial_temperature_calibration,
    geometry, source_xy_mm=None, stimulus_orientations_deg=None,
    endpoint_only=False, absolute_temperature_calibrated=False,
    gradient_ends=None, time_since_food_removal_s=None,
    food_removal_clock=None, assay_start_clock=None,
    per_worm_food_offsets_s=None, departure_rows=(),
    initial_state_window_s=30.0, pick_state=None, min_worms_per_regime=3,
    include_population_layer=True, enhanced_slowing_s=None,
):
    if feeding_state not in {"fed", "starved"}:
        raise ValueError("feeding_state must be fed or starved.")
    if cultivation_temperature_c is None:
        raise ValueError("cultivation temperature is required.")
    if not spatial_temperature_calibration:
        raise ValueError("spatial-to-temperature calibration is required.")
    result = analyze_tracks(
        tool_name=TOOL_NAME, tool_version=TOOL_VERSION, tracks=tracks,
        provider=provider, acquisition=acquisition, gate_decision=gate_decision,
        failure_library=failure_library, source_xy_mm=source_xy_mm,
        geometry=geometry,
        stimulus_orientations_deg=stimulus_orientations_deg,
        endpoint_only=endpoint_only,
        extra={
            "cultivation_temperature_c": float(cultivation_temperature_c),
            "feeding_state": feeding_state,
            "spatial_temperature_calibration":
                spatial_temperature_calibration,
            "absolute_temperature_calibrated":
                bool(absolute_temperature_calibrated),
            "isothermal_tracking_available": not endpoint_only,
        })
    if endpoint_only and result.get("status") != "refused":
        result["endpoint_limitation"] = (
            "isothermal contour-following cannot be measured in endpoint mode")
    if include_population_layer and result.get("status") != "refused":
        # `gradient_ends` names where the two temperatures sit and what they
        # are: {"cold_xy_mm", "hot_xy_mm", "cold_c", "hot_c"}. It is separate
        # from the spatial calibration because the calibration says what the
        # temperature is at a place, while the gradient says which end the
        # animal is trying to reach - and only cultivation temperature answers
        # that.
        grad = None
        if gradient_ends:
            grad = LinearGradient(
                cold_xy_mm=gradient_ends["cold_xy_mm"],
                hot_xy_mm=gradient_ends["hot_xy_mm"],
                cold_c=gradient_ends["cold_c"], hot_c=gradient_ends["hot_c"],
                cultivation_c=cultivation_temperature_c)
        result["population"] = population_layer(
            tracks=tracks, segments=result["segments"], geometry=grad,
            departure_rows=departure_rows,
            time_since_food_removal_s=time_since_food_removal_s,
            food_removal_clock=food_removal_clock,
            assay_start_clock=assay_start_clock,
            per_worm_food_offsets_s=per_worm_food_offsets_s,
            initial_state_window_s=initial_state_window_s,
            pick_state=pick_state, min_worms_per_regime=min_worms_per_regime,
            **({} if enhanced_slowing_s is None
               else {"enhanced_slowing_s": enhanced_slowing_s}))
        if grad is None:
            result["population"]["warnings"].append(
                "gradient_ends was not supplied, so the two plate ends and "
                "their temperatures are unknown and worms could not be split "
                "toward and away from cultivation temperature. The endpoint "
                "index is unaffected.")
    return result
