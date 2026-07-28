"""T7: linear and radial thermotaxis."""
from __future__ import annotations

from common import analyze_tracks

TOOL_NAME = "thermotaxis"
TOOL_VERSION = "0.1.0"


def analyze_thermotaxis(
    *, tracks, provider, acquisition, gate_decision, failure_library,
    cultivation_temperature_c, feeding_state, spatial_temperature_calibration,
    geometry, source_xy_mm=None, stimulus_orientations_deg=None,
    endpoint_only=False, absolute_temperature_calibrated=False,
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
    return result
