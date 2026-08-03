from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "orientation_assays"),
    str(ROOT / "tools" / "population_orientation")]

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS
from failure_library import FailureLibrary
from magnetotaxis import analyze_magnetotaxis
from orientation_plate_stats import analyse_plates
from stimulus_fields import MagnetProvider


def acquisition():
    return AcquisitionMetadata(
        3, "declared", 20, "declared", 5, "declared",
        bit_depth=12, compression="lossless", recording_duration_s=60,
        channel_identity="brightfield", anatomical_orientation="head_left",
        declared_worm_length_um=1000)


def provider():
    return MagnetProvider(
        shape="disc", dimensions_mm=(50.8, 6.35), remanence_t=1.32,
        magnetization_direction_xyz=(0, 0, 1),
        position_xyz_mm=(0, 0, 6.35),
        distance_uncertainty_mm=.25)


def test_closed_form_field_within_one_percent():
    p = provider()
    face_z = 6.35 + 6.35 / 2
    result = p.validate_on_axis((0, 0, face_z), 6.35 / 2)
    assert result["passes"]
    assert result["relative_error"] < .01


def test_per_worm_tier_runs_stamped_without_config2(tmp_path):
    result = analyze_magnetotaxis(
        tracks=[{"plate_id": "p", "worm_id": "w", "time_s": 0,
                 "x_mm": 1, "y_mm": 0, "heading_deg": 0}],
        provider=provider(), acquisition=acquisition(),
        gate_decision=GateDecision("orientation", PASS, {}, (), (), 0, True),
        failure_library=FailureLibrary(tmp_path),
        departure_results=[], humidity_percent=45, worm_age="adult",
        genotype="N2", time_since_food_removal_s=300,
        magnetic_pulse={"applied": False}, source_xy_mm=(0, 0),
        analysis_tier="per_worm_vectorial")
    assert result["status"] == "review_required"
    assert not result["config2_validation"]["validated"]
    assert result["validation_level"] == "computational_regression"
    assert result["validation_stamp"]["metric"] == (
        "per_worm_vectorial_orientation")
    assert result["config2_envelope_warnings"]


def test_plate_state_tier_completes_while_tier2_is_unvalidated(tmp_path):
    result = analyze_magnetotaxis(
        tracks=[{"plate_id": "p", "worm_id": None, "time_s": 0,
                 "x_mm": 1, "y_mm": 0, "heading_deg": 0}],
        provider=provider(), acquisition=acquisition(),
        gate_decision=GateDecision("orientation", PASS, {}, (), (), 0, True),
        failure_library=FailureLibrary(tmp_path),
        departure_results=[], humidity_percent=45, worm_age="adult",
        genotype="N2", time_since_food_removal_s=300,
        magnetic_pulse={"applied": False}, source_xy_mm=(0, 0),
        analysis_tier="plate_state")
    assert result["status"] == "review_required"
    assert result["analysis_tier"] == "plate_state"
    assert result["departure_survival_rows"] == []
    assert not result["config2_validation"]["validated"]


def test_rotation_identifiability_field_and_room_locked():
    field = [
        {"plate_id": f"p{i}", "plate_mean_angle_deg": angle,
         "plate_axis_orientation_deg": angle, "n_worms_on_plate": 10,
         "magnet_orientation_relative_to_room_deg": angle}
        for i, angle in enumerate((0, 90, 180))]
    room = [
        {**row, "plate_mean_angle_deg": 30,
         "plate_axis_orientation_deg": 30} for row in field]
    assert abs(analyse_plates(field)["magnet_rotation_slope"] - 1) < .05
    assert abs(analyse_plates(room)["magnet_rotation_slope"]) < .05
    assert analyse_plates(field[:1])[
        "stimulus_driven_certification"] == "REFUSED"
    assert "at least three distinct magnet orientations" in analyse_plates(
        field[:1])["identifiability_reason"].lower()


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'reconciliation - magnetotaxis'))
