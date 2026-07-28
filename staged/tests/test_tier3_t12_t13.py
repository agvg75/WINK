from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "tools" / "pharynx_morphometry"),
    str(ROOT / "tools" / "single_channel_gcamp")]

from gcamp import extract_trace, feasibility_pass
from pharynx import analyze_pharynx


def test_pharynx_has_separate_definition_and_no_unvalidated_score():
    image = np.zeros((80, 160), float)
    image[35:45, 20:140] = 10
    result = analyze_pharynx(
        image, anterior_xy=(20, 40), posterior_xy=(140, 40),
        width_px=12, um_per_px=1)
    assert len(result["compartments"]) == 4
    assert result["composite_damage_score"] is None
    assert "grinder_integrity" in result["damage_definition"]


def test_gcamp_low_signal_predicts_instead_of_brightest_jump():
    frames = np.zeros((3, 50, 50), float)
    frames[0, 25, 10] = 20
    frames[1, 25, 40] = 100
    frames[2, 25, 12] = 20
    result = extract_trace(frames, (10, 25), 2, search_radius_px=8)
    assert result["global_brightest_blob_search_used"] is False
    assert result["rows"][1]["x"] < 20


def test_feasibility_can_say_do_not_attempt():
    frames = np.ones((3, 20, 20))
    result = feasibility_pass(
        frames, [(10, 10)] * 3, neuron_radius_px=2, fps=30)
    assert result["difficulty_tier"] == "do not attempt"
