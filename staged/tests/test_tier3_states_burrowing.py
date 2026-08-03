from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "tools" / "behavioral_states"),
    str(ROOT / "tools" / "burrowing")]

from burrowing import analyze_burrowing
from states import area_restricted_search, quiescence, roaming_dwelling


def test_behavioral_nulls_are_valid():
    tracks = [
        {"plate_id": "p", "worm_id": "w", "time_s": t, "speed_um_s": 5,
         "angular_velocity_deg_s": 0} for t in (0, 1, 2, 3)]
    assert roaming_dwelling(tracks)["worm_observations"][0]["single_state_valid"]
    assert quiescence(
        tracks, speed_threshold_um_s=1,
        minimum_bout_s=2)["worm_observations"][0]["zero_quiescence_valid"]
    events = [
        {"plate_id": "p", "time_s": t, "event_type": "none",
         "observable_duration_s": 60} for t in (0, 60, 120)]
    assert area_restricted_search(
        events, removal_from_food_s=0)["plate_summaries"][0][
            "flat_no_local_search_is_valid"]


def test_no_penetration_is_censored_not_zero_velocity():
    rows = [
        {"plate_id": "p", "worm_id": "w", "resistance": 1,
         "time_s": t, "depth_um": 0} for t in (0, 1, 2)]
    result = analyze_burrowing(
        rows, minimum_progress_um=10, stall_velocity_um_s=1)
    worm = result["worm_observations"][0]
    assert not worm["penetration_event_observed"]
    assert worm["mean_vertical_velocity_um_s"] is None


if __name__ == "__main__":
    # Without this the file defines its tests and runs none of them, then
    # exits 0. See tests/_runner.py.
    import sys
    from pathlib import Path as _Path
    sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _runner import run_module_tests

    raise SystemExit(run_module_tests(globals(), 'tier 3 - states and burrowing'))
