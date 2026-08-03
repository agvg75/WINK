from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "orientation_assays"),
    str(ROOT / "tools" / "population_orientation")]

from magnetotaxis import (
    build_segment_covariates, regime_comparison,
    resolve_time_off_op50_offset)


def test_op50_offset_accepts_elapsed_or_clock_and_can_return_no():
    assert resolve_time_off_op50_offset(elapsed_s=300) == 300
    assert resolve_time_off_op50_offset(
        food_removal_clock="09:55", assay_start_clock="10:00") == 300
    assert resolve_time_off_op50_offset() is None


def test_raw_segment_covariates_keep_two_clocks():
    tracks = [
        {"plate_id": "p", "worm_id": "w", "time_s": t,
         "x_mm": t * .1, "y_mm": 0, "heading_deg": 0,
         "spine_quality": .9}
        for t in (0, 15, 30)]
    segments = [{**row, "angle_to_vector_deg": 0,
                 "radial_heading_deg": 0} for row in tracks]
    rows, _ = build_segment_covariates(
        tracks, segments, [{"worm_id": "w", "committed_departure_s": 15}],
        300, initial_state_window_s=30)
    assert [row["assay_elapsed_s"] for row in rows] == [0, 15, 30]
    assert [row["time_off_op50_s"] for row in rows] == [300, 315, 330]
    assert rows[-1]["time_since_committed_departure_s"] == 15
    assert rows[-1]["initial_state"] == "roaming"


def test_regime_split_withholds_thin_plate():
    rows = [
        {"plate_id": "p", "worm_id": regime, "time_s": time_s,
         "x_mm": x, "y_mm": 0, "angle_to_vector_deg": angle,
         "signed_track_curvature_deg_s": 1}
        for regime, angle, pair in (
            ("toward", 0, (5, 4)), ("away", 180, (5, 6)))
        for time_s, x in enumerate(pair)]
    result = regime_comparison(rows, (0, 0), min_worms_per_regime=2)
    assert result["per_plate"]["p"]["status"] == "withheld"


def test_regime_split_supports_rotation_with_conserved_chirality():
    rows = []
    for regime, angles, step in (
        ("t", (0, 2, -2), -1), ("a", (180, 178, -178), 1)):
        for index, angle in enumerate(angles):
            for time_s, x in ((0, 5 + index), (1, 5 + index + step)):
                rows.append({
                    "plate_id": "p", "worm_id": f"{regime}{index}",
                    "time_s": time_s, "x_mm": x, "y_mm": 0,
                    "angle_to_vector_deg": angle,
                    "signed_track_curvature_deg_s": 2})
    plate = regime_comparison(
        rows, (0, 0), min_worms_per_regime=3)["per_plate"]["p"]
    assert plate["rotation_not_reflection_supported"]
    assert plate["chirality_conserved"]
    assert plate["decisive_internal_field_flip_analog"]


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'magnetotaxis covariate extension'))
