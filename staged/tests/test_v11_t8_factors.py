from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "population_orientation"))
from orientation_plate_stats import analyse_plates


def test_pulse_latency_angle_dissociation():
    rows = [
        {"plate_id": "u1", "plate_mean_angle_deg": 120,
         "plate_axis_orientation_deg": 120, "n_worms_on_plate": 10,
         "magnet_orientation_relative_to_room_deg": 0,
         "magnetic_pulse_applied": False, "median_departure_latency_s": 10},
        {"plate_id": "u2", "plate_mean_angle_deg": 121,
         "plate_axis_orientation_deg": 121, "n_worms_on_plate": 10,
         "magnet_orientation_relative_to_room_deg": 90,
         "magnetic_pulse_applied": False, "median_departure_latency_s": 12},
        {"plate_id": "p1", "plate_mean_angle_deg": 120,
         "plate_axis_orientation_deg": 120, "n_worms_on_plate": 10,
         "magnet_orientation_relative_to_room_deg": 180,
         "magnetic_pulse_applied": True, "median_departure_latency_s": 30},
        {"plate_id": "p2", "plate_mean_angle_deg": 121,
         "plate_axis_orientation_deg": 121, "n_worms_on_plate": 10,
         "magnet_orientation_relative_to_room_deg": 270,
         "magnetic_pulse_applied": True, "median_departure_latency_s": 32}]
    result = analyse_plates(rows)["magnetic_pulse_comparison"]
    assert result["status"] == "computed"
    assert result["departure_latency_shift_s"] == 20
    assert abs(result["angle_shift_deg"]) < 1
