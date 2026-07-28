"""Shared contracts for T7/T8/T9."""
from __future__ import annotations

from pathlib import Path
import sys

APP = Path(__file__).resolve().parents[2] / "app"
if str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS
from failure_library import FailureLibrary
from orientation_core import decompose_segment, population_plate_statistics


def analyze_tracks(
    *, tool_name, tool_version, tracks, provider, acquisition,
    gate_decision, failure_library, source_xy_mm, geometry,
    stimulus_orientations_deg=None, endpoint_only=False, extra=None,
):
    acquisition.validate(require_complete=True)
    stamp = acquisition.stamped(tool_name, tool_version)
    if gate_decision.status != PASS and not gate_decision.forced:
        return {
            **stamp, "status": "refused",
            "reason": "capability gate did not pass and was not force-acknowledged",
            "capability_gate": gate_decision.as_dict()}
    if not tracks:
        return {**stamp, "status": "refused", "reason": "no tracks supplied",
                "capability_gate": gate_decision.as_dict()}
    segments = [
        decompose_segment(
            provider, plate_id=str(row["plate_id"]),
            worm_id=(None if row.get("worm_id") is None
                     else str(row["worm_id"])),
            time_s=float(row["time_s"]), x_mm=float(row["x_mm"]),
            y_mm=float(row["y_mm"]), heading_deg=float(row["heading_deg"]),
            source_xy_mm=source_xy_mm)
        for row in tracks]
    plate_angles = {}
    for segment in segments:
        angle = (segment.angle_to_vector_deg
                 if segment.angle_to_vector_deg is not None
                 else segment.radial_heading_deg)
        if angle is not None:
            plate_angles.setdefault(segment.plate_id, []).append(angle)
    statistics = population_plate_statistics(
        plate_angles, stimulus_orientations_deg=stimulus_orientations_deg,
        geometry=geometry, endpoint_only=endpoint_only)
    return {
        **stamp, "status": "review_required", "inferential_unit": "plate",
        "capability_gate": gate_decision.as_dict(),
        "segments": [segment.as_dict() for segment in segments],
        "plate_statistics": statistics,
        "review_contract": {
            "required_before_export": True,
            "editable": ["segmentation", "track identity", "heading",
                         "stimulus geometry", "accept/reject"]},
        "failure_library_path": str(failure_library.root),
        **(extra or {}),
    }
