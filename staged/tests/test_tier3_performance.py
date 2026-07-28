from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "longitudinal_performance")]

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS
from failure_library import FailureLibrary
from performance import analyze_longitudinal_decline, analyze_swimming_fatigue


def test_fatigue_accepts_flat_no_fatigue(tmp_path):
    acquisition = AcquisitionMetadata(
        30, "declared", 4, "declared", 2, "declared",
        bit_depth=12, compression="lossless", recording_duration_s=120,
        channel_identity="brightfield", anatomical_orientation="head_left",
        declared_worm_length_um=1000)
    rows = [
        {"plate_id": "p", "worm_id": "w", "time_s": t,
         "thrash_frequency_hz": 2, "amplitude_body_lengths": .4}
        for t in (0, 30, 60, 90)]
    result = analyze_swimming_fatigue(
        rows, acquisition,
        GateDecision("fatigue", PASS, {}, (), (), 0, True),
        failure_library=FailureLibrary(tmp_path))
    assert result["flat_nondecaying_is_valid"]
    assert result["inferential_unit"] == "plate"


def test_longitudinal_flat_is_valid():
    rows = [
        {"cohort_id": "c", "plate_id": "p", "adult_age_days": day,
         "measurement": 1.0} for day in (1, 3, 5)]
    result = analyze_longitudinal_decline(rows)
    assert result["cohort_plate_curves"][0]["trajectory"] == "flat/no decline"
