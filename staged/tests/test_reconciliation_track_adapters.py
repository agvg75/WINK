from pathlib import Path
import sys
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from track_input_adapters import adapt_existing_track_csv


def test_kinematics_adapts_without_new_tracker():
    source = ROOT / "tests" / "parity" / "golden_input_kinematics" / "WT_day1_L4440_a01.csv"
    table = pd.read_csv(source)
    states = adapt_existing_track_csv(table, "roaming_dwelling", source)
    assert {"plate_id", "worm_id", "time_s", "speed_um_s",
            "angular_velocity_deg_s"} <= set(states)
    search = adapt_existing_track_csv(table, "search", source)
    assert {"event_type", "observable_duration_s", "event_derivation"} <= set(search)
    assert set(search.event_type) <= {"none", "reversal", "omega"}


def test_flat_motion_is_preserved_as_valid_null():
    table = pd.DataFrame({
        "frame": [0, 1, 2], "fps": [1, 1, 1],
        "worm_id": ["w"] * 3, "axial_vel_px_s": [2, 2, 2],
        "angular_vel_deg_s": [0, 0, 0], "um_per_px": [1, 1, 1]})
    adapted = adapt_existing_track_csv(table, "search", "flat.csv")
    assert (adapted.event_type == "none").all()
