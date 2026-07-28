from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from departure_roi import analyze_departure, survival_rows
from stimulus_fields import (
    ChemicalProvider, NullProvider, ThermalLinearProvider,
    ThermalRadialProvider,
)


def test_field_providers_can_return_null_and_uncertainty():
    null = NullProvider().sample(0, 0)
    assert null.magnitude == 0 and null.direction_xyz is None
    linear = ThermalLinearProvider((1, 0), 0.5, 0.05).sample(1, 2)
    assert linear.gradient_xy == (0.5, 0.0)
    radial = ThermalRadialProvider((0, 0), 1).sample(1, 0)
    assert radial.gradient_xy[0] < 0
    chemical = ChemicalProvider(
        (0, 0), lambda x, y, t: x * x + y * y, 0.7).sample(1, 0)
    assert chemical.uncertainty["relative"] == 0.7


def test_departure_wobble_is_not_commitment_and_nondeparture_is_censored():
    wobble = analyze_departure(
        "w1", [0, 1, 2, 3, 4], [1, 0, 1, 1, 1], [0, 1, 0, 0, 0],
        droplet_clear=[0, 1, 1, 1, 1], minimum_commitment_s=2)
    assert wobble.first_excursion_s == 1
    assert wobble.committed_departure_s is None
    assert wobble.departure_censored
    assert survival_rows([wobble])[0]["event_observed"] is False


def test_sustained_progress_is_committed_departure():
    result = analyze_departure(
        "w2", [0, 1, 2, 3, 4], [1, 1, 0, 0, 0], [0, 0, 1, 2, 3],
        droplet_clear=[0, 1, 1, 1, 1], minimum_commitment_s=2,
        minimum_outward_progress=1, time_since_food_at_recording_start_s=60)
    assert result.committed_departure_s == 2
    assert result.time_since_food_at_departure_s == 62
