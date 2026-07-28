from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "population_orientation"))
from config2_validation_harness import synthetic_fixed_angle_check


def test_injected_angle_recovers_in_field_not_lab_frame():
    stimulus = np.arange(0, 360, 30)
    heading = (stimulus + 120) % 360
    result = synthetic_fixed_angle_check(stimulus, heading, 120)
    assert result["passed"]
    assert result["error_deg"] < 1e-8
    assert result["correct_frame_concentration"] > .99
    assert result["wrong_lab_frame_concentration"] < .01
