from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT / "app"), str(ROOT / "tools" / "orientation_assays")]

from acquisition import AcquisitionMetadata
from capability_gate import GateDecision, PASS
from chemotaxis import endpoint_index
from failure_library import FailureLibrary
from thermotaxis import analyze_thermotaxis
from stimulus_fields import ThermalRadialProvider


def acquisition():
    return AcquisitionMetadata(
        30, "declared", 4, "declared", 2, "declared",
        bit_depth=12, compression="lossless", recording_duration_s=120,
        channel_identity="brightfield", anatomical_orientation="head_left",
        declared_worm_length_um=1000)


def test_endpoint_index_has_chance_and_empty_null():
    assert endpoint_index(5, 5)["index"] == 0
    assert endpoint_index(0, 0)["index"] is None


def test_thermotaxis_endpoint_declares_isothermal_blindness(tmp_path):
    provider = ThermalRadialProvider((0, 0), 1)
    tracks = [
        {"plate_id": "p1", "worm_id": "w", "time_s": 0,
         "x_mm": 1, "y_mm": 0, "heading_deg": 180}]
    result = analyze_thermotaxis(
        tracks=tracks, provider=provider, acquisition=acquisition(),
        gate_decision=GateDecision("orientation", PASS, {}, (), (), 0, True),
        failure_library=FailureLibrary(tmp_path), cultivation_temperature_c=20,
        feeding_state="fed", spatial_temperature_calibration={"slope": 1},
        geometry="radial", source_xy_mm=(0, 0), endpoint_only=True)
    assert not result["isothermal_tracking_available"]
    assert "endpoint_limitation" in result
