from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from orientation_core import decompose_segment, population_plate_statistics
from reversal_core import response_summary, score_stimulus
from stimulus_fields import ThermalLinearProvider


def test_reversal_null_and_onset_exclusion():
    excluded = score_stimulus(
        worm_id="w", plate_id="p", stimulus_id="s", times_s=[0, 1, 2],
        signed_velocity_body_lengths_s=[-1, -1, 0], stimulus_time_s=1,
        prior_state="reversing")
    assert excluded.response == "excluded"
    no = score_stimulus(
        worm_id="w2", plate_id="p", stimulus_id="s", times_s=[0, 1, 2],
        signed_velocity_body_lengths_s=[0.01, 0.01, 0.01],
        stimulus_time_s=1, prior_state="forward")
    assert no.response == "no" and no.reversal_length_body_lengths == 0


def test_population_summary_has_no_worm_n_or_p_value():
    event = score_stimulus(
        worm_id="w", plate_id="p", stimulus_id="s", times_s=[0, 1, 2],
        signed_velocity_body_lengths_s=[0.1, -0.5, 0],
        stimulus_time_s=1, prior_state="forward")
    result = response_summary([event], [event], mode="population")
    assert result["inferential_unit"] == "plate"
    assert "worm_count" not in result and "p" not in result


def test_orientation_identifiability_refuses_linear_single_orientation():
    provider = ThermalLinearProvider((1, 0), 1)
    segment = decompose_segment(
        provider, plate_id="p1", worm_id="w", time_s=0, x_mm=0, y_mm=0,
        heading_deg=0)
    assert segment.along_gradient == 1
    stats = population_plate_statistics(
        {"p1": [0, 5]}, geometry="linear", endpoint_only=False)
    assert not stats["certified_stimulus_response"]
    assert len(stats["identifiability_reasons"]) == 2
