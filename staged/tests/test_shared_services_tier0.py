import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from acquisition import AcquisitionMetadata
from capability_gate import (
    AMBER, PASS, RED, MetricRequirement, RecordingProxies, do_not_attempt,
    evaluate_metric, force_gated_metric,
)
from failure_library import FailureContext, FailureLibrary
from intake import run_intake, verify_scale


def complete_acquisition(**overrides):
    values = dict(
        fps=30, fps_source="declared",
        um_per_px=4.0, um_per_px_source="declared",
        exposure_ms=2, exposure_source="declared",
        bit_depth=12, compression="lossless", recording_duration_s=60,
        channel_identity="brightfield", anatomical_orientation="head_left",
        declared_worm_length_um=1000,
    )
    values.update(overrides)
    return AcquisitionMetadata(**values)


def test_scale_verification_can_refuse_and_block_discrepancy():
    acq = complete_acquisition()
    assert verify_scale(acq, []).status == "not_verifiable"
    assert verify_scale(acq, [250, 252]).status == "pass"
    assert verify_scale(acq, [50]).status == "discrepancy"


def test_intake_requires_full_constants():
    result = run_intake(complete_acquisition(), [250])
    assert result.validated
    assert result.as_dict()["scale_verification"]["measured_length_px"] == 250


def test_gate_is_per_metric_and_force_is_logged():
    proxies = RecordingProxies(
        worm_length_px=100, worm_width_px=7, fps=20, contrast_ratio=1.4,
        saturation_fraction=0.0, bit_depth=12, focus_score=1.0,
        occluded_fraction=0.0, compression_artifact_score=0.0)
    easy = evaluate_metric(
        proxies, MetricRequirement("centroid", min_length_px=25, min_fps=3))
    hard = evaluate_metric(
        proxies, MetricRequirement("pumping", min_length_px=250, min_fps=30))
    assert easy.status == PASS
    assert hard.status in {AMBER, RED}
    forced = force_gated_metric(hard, "Expert review; analyze as exploratory.")
    assert forced.forced and forced.acknowledgment


def test_gate_can_return_do_not_attempt():
    proxies = RecordingProxies(
        None, None, None, None, None, None, None, None, None)
    decisions = [
        evaluate_metric(proxies, MetricRequirement("a", min_length_px=20)),
        evaluate_metric(proxies, MetricRequirement("b", min_fps=30)),
    ]
    assert all(item.status == RED for item in decisions)
    assert do_not_attempt(decisions)


def test_failure_library_captures_and_checks_saved_state(tmp_path):
    evidence = tmp_path / "frame.txt"
    evidence.write_text("pixels", encoding="utf-8")
    library = FailureLibrary(tmp_path / "failures")
    report = library.capture(
        FailureContext(
            "orientation", "1.0", complete_acquisition(),
            "tracked_wrong_object", [1, 2, 3, 4], 10, {"threshold": 3},
            severity=4, classification="tool_failure"),
        [evidence])
    ok, _ = library.verify_reproducible(report)
    assert ok
    payload = json.loads((report / "report.json").read_text(encoding="utf-8"))
    assert payload["tool_name"] == "orientation"
    assert payload["acquisition_constants"]["bit_depth"] == 12
    assert library.ranked_backlog()[0]["priority"] == 8
