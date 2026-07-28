from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT), str(ROOT / "app"),
    str(ROOT / "tools" / "mechanosensation"),
    str(ROOT / "tools" / "paralysis_pharmacology"),
]

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS, RED
from failure_library import FailureLibrary
from mechanosensation import TrialRecord, analyze_habituation
from paralysis import ProdObservation, analyze_paralysis
from reversal_core import ReversalEvent


def acquisition():
    return AcquisitionMetadata(
        30, "declared", 4, "declared", 2, "declared",
        bit_depth=12, compression="lossless", recording_duration_s=120,
        channel_identity="brightfield", anatomical_orientation="head_left",
        declared_worm_length_um=1000)


def gate(status=PASS):
    return GateDecision(
        "response_probability", status, {}, (), (), 0, True)


def event(plate, worm, trial, response="yes", length=0.5):
    return ReversalEvent(
        worm, plate, f"s{trial}", response, None, "forward",
        "reversal" if response == "yes" else None,
        0.2 if response == "yes" else None,
        length if response == "yes" else 0,
        0.8 if response == "yes" else 0,
        1.0 if response == "yes" else 0)


def test_t1_keeps_trial_series_and_plate_unit(tmp_path):
    records = []
    for trial, response in enumerate(["yes", "yes", "no", "no"], 1):
        records.append(TrialRecord(
            "p1", trial, 10, event("p1", f"w{trial}", trial, response),
            "population_tap", artifact_amplitude=5))
    result = analyze_habituation(
        records, [event("p1", "base", 0, "no")], acquisition(), gate(),
        failure_library=FailureLibrary(tmp_path))
    assert result["inferential_unit"] == "plate"
    assert len(result["trial_series"]) == 4
    assert not result["worm_level_p_value_emitted"]


def test_t1_refuses_red_gate(tmp_path):
    result = analyze_habituation(
        [TrialRecord("p", 1, 10, event("p", "w", 1),
                     "population_tap")],
        [], acquisition(), gate(RED), failure_library=FailureLibrary(tmp_path))
    assert result["status"] == "refused"


def test_t2_nondeparture_is_censored_and_plate_curve_is_primary(tmp_path):
    observations = [
        ProdObservation("p1", "w1", 0, "moving", "aldicarb", 1),
        ProdObservation("p1", "w1", 60, "paralyzed", "aldicarb", 1),
        ProdObservation("p1", "w2", 0, "moving", "aldicarb", 1),
        ProdObservation("p1", "w2", 60, "moving", "aldicarb", 1),
    ]
    result = analyze_paralysis(
        observations, acquisition(), gate(),
        failure_library=FailureLibrary(tmp_path))
    outcomes = result["censored_worm_outcomes_for_plate_curves"]
    assert sum(row["event_observed"] for row in outcomes) == 1
    assert result["inferential_unit"] == "plate"
    assert not result["worm_level_p_value_emitted"]
