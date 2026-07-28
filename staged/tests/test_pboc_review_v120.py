import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "defecation"))
from pboc_review import ReviewState


def fixture(tmp_path, count=11, unusable=()):
    fps = 10.0
    events = [{"peak_frame": 20 + i * 40, "peak_time_s": 2 + i * 4,
               "peak_z": 3 + i / 10, "recovery_frame": 25 + i * 40,
               "recovery_time_s": 2.5 + i * 4}
              for i in range(count)]
    summary = {"recording": "fixture", "fps": fps,
               "settings": {"contraction_z": 2.5}, "events": events}
    n = 20 + count * 60 + 20
    usable = np.ones(n, int); usable[list(unusable)] = 0
    scan = pd.DataFrame({"frame": np.arange(n), "time_s": np.arange(n)/fps,
                         "usable": usable,
                         "score_z": np.sin(np.arange(n)/5)})
    paths = []
    return ReviewState(summary, scan, tmp_path, paths,
                       tmp_path / "fixture_pboc_review.json")


def test_review_roundtrip_edits_and_null_json(tmp_path):
    state = fixture(tmp_path)
    assert all(event["decision"] == "pending" for event in state.events)
    first = state.events[0]
    state.update(first, decision="accepted", peak=22, recovery=28, note="ok")
    assert first["auto_peak_frame"] == 20
    state.update(first, recovery=None)
    manual = state.add(17)
    assert manual["provenance"] == "manual" and manual["decision"] == "pending"
    state.update(manual, decision="rejected")
    reopened = fixture(tmp_path)
    saved = {event["event_id"]: event for event in reopened.events}
    assert saved[first["event_id"]]["decision"] == "accepted"
    assert saved[first["event_id"]]["auto_peak_frame"] == 20
    assert saved[first["event_id"]]["reviewed_peak_frame"] == 22
    assert saved[first["event_id"]]["reviewed_recovery_frame"] is None
    assert saved[manual["event_id"]]["provenance"] == "manual"
    text = state.review_path.read_text()
    assert "NaN" not in text and json.loads(text)


def test_finalization_uses_only_accepted_reviewed_frames(tmp_path):
    state = fixture(tmp_path)
    for i, event in enumerate(list(state.events)):
        state.update(event, decision="accepted", peak=20 + i * 50,
                     recovery=25 + i * 50)
    rejected = state.add(30); state.update(rejected, decision="rejected")
    result = state.finalize(minimum_accepted=10)
    assert result["eligible"] is True
    assert result["statistics"]["period_mean_s"] == 5.0
    assert rejected["event_id"] not in result["events_used"]


def test_pending_insufficient_and_unusable_refuse_statistics(tmp_path):
    state = fixture(tmp_path, count=9, unusable=(100,))
    for event in state.events[:8]: state.update(event, decision="accepted")
    result = state.finalize(minimum_accepted=10)
    assert result["eligible"] is False and result["statistics"] is None
    assert any("pending" in reason for reason in result["ineligibility_reasons"])
    assert any("at least 10" in reason for reason in result["ineligibility_reasons"])


def test_reanalysis_does_not_attach_old_decisions_to_new_candidates(tmp_path):
    state = fixture(tmp_path, count=3)
    state.update(state.events[0], decision="accepted")
    summary = dict(state.summary)
    summary["events"] = [dict(event) for event in summary["events"]]
    summary["events"][0]["peak_frame"] += 7
    changed = ReviewState(summary, state.scan, tmp_path, [], state.review_path)
    assert all(event["decision"] == "pending" for event in changed.events)
    assert state.review_path.with_name(
        state.review_path.stem + ".pre_reanalysis.json").is_file()
