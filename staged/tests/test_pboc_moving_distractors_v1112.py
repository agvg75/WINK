import json
import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "defecation"))

from distractor_preflight import save_annotations
from pboc_engine import apply_distractor_identity_gate


def test_distractor_annotation_document_is_versioned_and_atomic(tmp_path):
    path = tmp_path / "moving_distractors.json"
    episode = {
        "episode_id": "distractor-001", "label": "worm entering from left",
        "seed_frame": 4, "start_frame": 4, "end_frame": 12,
        "seed_centerline_xy": [[10.0, 20.0], [18.0, 21.0], [27.0, 24.0]],
    }
    save_annotations(path, "fixture", 20, [episode])
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema_version"] == "1.0"
    assert "moving distractor worm" in document["meaning"]
    assert document["episodes"] == [episode]
    assert not list(tmp_path.glob("*.tmp"))


def test_identity_gate_refuses_lost_distractor_and_target_contact():
    states = [{"needs_help": 0, "provenance": "automatic"} for _ in range(5)]
    target = [np.zeros((40, 40), bool) for _ in states]
    distractor = [np.zeros((40, 40), bool) for _ in states]
    for mask in target:
        mask[15:21, 15:21] = True
    distractor[3][23:25, 16:20] = True
    results = [{"episode_id": "distractor-001", "start_frame": 1,
                "end_frame": 4, "usable_frames": [1, 3, 4]}]
    apply_distractor_identity_gate(states, target, distractor, results,
                                   proximity_px=3)
    assert states[0]["needs_help"] == 0
    assert states[2]["identity_warning"] == "distractor_identity_not_observable"
    assert states[3]["identity_warning"] == "target_distractor_contact"
    assert states[4]["needs_help"] == 0


def test_identity_gate_accepts_separated_moving_distractor():
    states = [{"needs_help": 0} for _ in range(3)]
    target = [np.zeros((30, 30), bool) for _ in states]
    distractor = [np.zeros((30, 30), bool) for _ in states]
    for i in range(3):
        target[i][20:24, 20:24] = True
        distractor[i][2+i:5+i, 2+i:5+i] = True
    results = [{"episode_id": "d1", "start_frame": 0, "end_frame": 2,
                "usable_frames": [0, 1, 2]}]
    apply_distractor_identity_gate(states, target, distractor, results,
                                   proximity_px=3)
    assert all(state["needs_help"] == 0 for state in states)
