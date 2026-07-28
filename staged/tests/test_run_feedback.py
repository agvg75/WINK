import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from acquisition import AcquisitionMetadata
from run_feedback import RunFeedbackStore, ToolBriefing


def acquisition():
    return AcquisitionMetadata(
        30, "declared", 4, "declared", 2, "declared",
        bit_depth=12, compression="lossless", recording_duration_s=120,
        channel_identity="brightfield", anatomical_orientation="head_left",
        declared_worm_length_um=1000)


def test_briefing_is_once_per_version(tmp_path):
    store = RunFeedbackStore(tmp_path)
    briefing = ToolBriefing(
        "tool", "1", "plate", ("check fps",), "sham control")
    assert store.needs_briefing(briefing)
    store.acknowledge(briefing)
    assert not store.needs_briefing(briefing)
    assert store.needs_briefing(ToolBriefing(
        "tool", "2", "plate", ("check fps",), "sham control"))


def test_clean_and_issue_runs_share_denominator(tmp_path):
    store = RunFeedbackStore(tmp_path)
    store.record_clean_run(
        tool_name="tool", tool_version="1", run_id="clean",
        acquisition=acquisition())
    report = store.record_issue(
        tool_name="tool", tool_version="1", run_id="issue",
        acquisition=acquisition(), category="missed_event",
        parameters={"threshold": 2}, user_note="one event missing")
    assert (report / "report.json").is_file()
    tally = store.tally()
    assert tally["total_runs_reported"] == 2
    assert tally["issue_rate"] == 0.5
    assert tally["categories"]["missed_event"] == 1


def test_support_bundle_falls_back_to_metadata_when_over_limit(tmp_path):
    store = RunFeedbackStore(tmp_path)
    evidence = tmp_path / "large.bin"
    evidence.write_bytes(b"x" * 2048)
    report = store.record_issue(
        tool_name="tool", tool_version="1", run_id="issue",
        acquisition=acquisition(), category="missed_event",
        parameters={}, user_note="missing", evidence_paths=[evidence])
    bundle = store.prepare_support_bundle(report, maximum_bytes=100)
    assert not bundle["evidence_included"]
    assert bundle["omitted_evidence"] == ["large.bin"]
    assert Path(bundle["bundle_path"]).is_file()
