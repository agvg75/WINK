"""T9: endpoint chemotaxis/avoidance and vectorial positive control."""
from __future__ import annotations

from common import analyze_tracks

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
    return result
