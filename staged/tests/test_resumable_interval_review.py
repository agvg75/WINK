import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "afd_neuron"))
sys.path.insert(0, str(ROOT / "tools" / "worm_kinematics" / "dic_tracker"))

from tracker_review_session import load_tracker_session, save_tracker_session
from worm_dic_tracker import DICWormTracker


def _state(y, *, good=True, area=1000.0):
    points = np.column_stack([np.linspace(0, 100, 25), np.full(25, y)])
    return {
        "pts": points, "path": points.copy(), "curv": np.zeros(24),
        "seg_widths": np.ones(24), "length": 100.0, "area": area,
        "head": tuple(points[0]), "tail": tuple(points[-1]),
        "centroid": tuple(np.mean(points, axis=0)),
        "head_bend": 0.0, "head_angle": 0.0,
        "provenance": "measured" if good else "help",
        "needs_help": 0 if good else 1, "clip_start": 0,
        "shape_shift": 0.0,
    }


def _tracker(count=8):
    tracker = DICWormTracker(
        np.zeros((count, 48, 128), np.float32), fps=10, um_per_px=1,
        fps_source="declared", um_per_px_source="declared")
    tracker.len_ref = 100.0; tracker.area_ref = 1000.0
    tracker.state = [_state(float(frame)) for frame in range(count)]
    return tracker


def test_user_selected_interval_is_reconstructed_without_touching_outside_frames():
    tracker = _tracker()
    outside_before = [tracker.state[i]["pts"].copy() for i in (0, 1, 6, 7)]
    left_anchor = tracker.state[2]["pts"].copy()
    right_anchor = tracker.state[5]["pts"].copy()

    filled = tracker.reanalyze_interval(2, 5)

    assert filled == [3, 4]
    assert all(np.array_equal(tracker.state[i]["pts"], before)
               for i, before in zip((0, 1, 6, 7), outside_before))
    assert np.array_equal(tracker.state[2]["pts"], left_anchor)
    assert np.array_equal(tracker.state[5]["pts"], right_anchor)
    assert all(tracker.state[i]["provenance"] == "inferred_between_neighbors"
               for i in range(3, 5))


def test_review_session_round_trip_restores_manual_and_inferred_geometry(tmp_path):
    tracker = _tracker()
    tracker.reanalyze_interval(2, 5)
    tracker.state[3]["provenance"] = "manual"
    source = {"recording_key": "recording", "first_frame": "recording-0000.jpg",
              "last_frame": "recording-0007.jpg", "frame_count": 8}
    path = tmp_path / "review.json"
    save_tracker_session(path, tracker, tool="single_worm_tracker", source=source)

    restored = _tracker()
    load_tracker_session(path, restored, tool="single_worm_tracker", source=source)

    assert restored.state[3]["provenance"] == "manual"
    assert isinstance(restored.state[4]["pts"], np.ndarray)
    assert np.allclose(restored.state[4]["pts"], tracker.state[4]["pts"])


def test_new_internal_anchor_rebuilds_prior_interpolation_without_losing_anchors():
    tracker = _tracker()
    tracker.reanalyze_interval(1, 6)
    outside = tracker.state[0]["pts"].copy(), tracker.state[7]["pts"].copy()
    manual = _state(20.0)
    manual["provenance"] = "manual"; manual["needs_help"] = 0
    tracker.state[3] = manual

    tracker._prepare_bounded_reconstruction(1, 6)
    filled = tracker._temporal_reconstruct(bounds=(1, 6))

    assert filled == [2, 4, 5]
    assert tracker.state[3]["provenance"] == "manual"
    assert np.allclose(tracker.state[2]["pts"][:, 1], 10.5)
    assert np.allclose(tracker.state[4]["pts"][:, 1], 15.333333333333334)
    assert np.array_equal(tracker.state[0]["pts"], outside[0])
    assert np.array_equal(tracker.state[7]["pts"], outside[1])


def test_calibrated_identity_bounds_flag_a_short_larval_geometry():
    tracker = _tracker(count=1)
    tracker.strict_target_identity = True
    tracker.identity_length_bounds = (88.0, 112.0)
    tracker.identity_area_bounds = (750.0, 1250.0)
    tracker.state[0] = _state(0, area=320.0)
    tracker.state[0]["length"] = 55.0

    tracker._qc()

    assert tracker.state[0]["needs_help"] == 1
    assert tracker.state[0]["provenance"] == "help"
