import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "defecation"))
sys.path.insert(0, str(ROOT / "tools" / "afd_neuron"))
sys.path.insert(0, str(ROOT / "tools" / "worm_kinematics" / "dic_tracker"))

from temporal_worm_geometry import (fill_adaptive_spine_gaps,
                                    fill_short_spine_gaps,
                                    suggest_manual_anchor_frames)
from pboc_engine import (axial_participating_fraction, build_pboc_calibration,
                         calibrated_pboc_score)
from worm_dic_tracker import DICWormTracker
from segmentation_review import FrameRangeRecipe, SegmentationConfig


def line_state(y, length=100.0, good=True):
    pts = np.column_stack([np.linspace(0, length, 25), np.full(25, y)])
    return {"pts": pts, "path": pts.copy(), "length": length,
            "head": tuple(pts[0]), "tail": tuple(pts[-1]),
            "needs_help": 0 if good else 1,
            "provenance": "measured" if good else "help"}


def test_short_gap_is_filled_from_both_sides_with_provenance():
    states = [line_state(0), line_state(0, good=False),
              line_state(0, good=False), line_state(3)]
    states[1]["pts"] = states[1]["path"] = None
    states[2]["pts"] = states[2]["path"] = None
    filled = fill_short_spine_gaps(states, max_gap=2, target_length=100.0)
    assert filled == [1, 2]
    assert np.allclose(states[1]["pts"][:, 1], 1.0)
    assert np.allclose(states[2]["pts"][:, 1], 2.0)
    assert states[1]["provenance"] == "inferred_between_neighbors"
    assert states[1]["temporal_left_frame"] == 0
    assert states[1]["temporal_right_frame"] == 3


def test_gap_length_in_frames_does_not_block_safe_reconstruction():
    states = [line_state(0)]
    for _ in range(19):
        bad = line_state(0, good=False); bad["pts"] = bad["path"] = None
        states.append(bad)
    states.append(line_state(3))
    filled = fill_adaptive_spine_gaps(states, target_length=100.0)
    assert filled == list(range(1, 20))


def test_one_sided_or_high_translation_gaps_request_midpoint_anchor():
    states = [line_state(0, good=False), line_state(0),
              line_state(0, good=False), line_state(0, good=False),
              line_state(0, good=False), line_state(80)]
    states[0]["pts"] = states[0]["path"] = None
    for frame in (2, 3, 4):
        states[frame]["pts"] = states[frame]["path"] = None
    assert fill_adaptive_spine_gaps(states, target_length=100.0) == []
    assert states[0]["suggested_manual_anchor"] == 1
    assert states[3]["suggested_manual_anchor"] == 1
    assert suggest_manual_anchor_frames(states) == [0, 3]


def ellipse(cx, cy, rx, ry, count=80):
    angle = np.linspace(0, 2*np.pi, count, endpoint=False)
    return np.column_stack([cx+rx*np.cos(angle), cy+ry*np.sin(angle)]).tolist()


def test_three_anchor_pboc_calibration_and_geometry_score():
    document = {"pboc_anchors": [
        {"state": "baseline", "frame": 10, "outline_xy": ellipse(80, 50, 45, 8)},
        {"state": "peak", "frame": 14, "outline_xy": ellipse(80, 50, 42, 8.5)},
        {"state": "recovered", "frame": 20, "outline_xy": ellipse(80, 50, 45, 8)},
    ]}
    calibration = build_pboc_calibration(document, (120, 180), 1.0, 10.0)
    assert calibration["baseline_length_px"] > calibration["peak_length_px"]
    assert calibration["contraction_duration_s"] == 0.4
    lengths = np.array([calibration["baseline_length_px"],
                        calibration["peak_length_px"]])
    area = np.full(2, np.mean([a["area_px"] for a in calibration["anchors"]]))
    _, fraction, error = calibrated_pboc_score(np.array([0.0, 1.0]), lengths, area, calibration)
    assert np.allclose(fraction, [0.0, 1.0])
    assert np.all(error < 0.1)


def test_camera_translation_is_estimated_before_background_comparison():
    from scipy.ndimage import shift
    rng = np.random.default_rng(7)
    texture = rng.normal(100, 12, (96, 96)).astype(np.float32)
    frames = np.asarray([texture, shift(texture, (2, -3), order=1, mode="nearest")])
    tracker = DICWormTracker(
        frames, fps=10, um_per_px=1.0, fps_source="declared",
        um_per_px_source="declared")
    assert tracker.clip_starts == [0]
    # Alignment shift for frame 2 should be approximately (-2, +3).
    assert np.allclose(tracker.camera_shift[1], [-2, 3], atol=1.0)


def test_unalignable_scene_change_starts_a_new_clip():
    rng = np.random.default_rng(11)
    first = rng.normal(90, 15, (96, 96)).astype(np.float32)
    second = rng.normal(150, 20, (96, 96)).astype(np.float32)
    frames = np.asarray([first, first.copy(), first.copy(), second])
    tracker = DICWormTracker(
        frames, fps=10, um_per_px=1.0,
        fps_source="declared", um_per_px_source="declared")
    assert tracker.clip_starts == [0, 3]
    assert np.allclose(tracker.camera_shift[3], [0, 0])


def test_opt_in_camera_registration_moves_identity_hint_to_current_frame():
    tracker = DICWormTracker.__new__(DICWormTracker)
    tracker.camera_shift = np.asarray([[0.0, 0.0], [-2.0, 3.0]])
    tracker.clip_start_set = {0}
    tracker.segmentation_config = SegmentationConfig(
        ranges=[FrameRangeRecipe(
            0, 9, camera_registration=True)]).validate()
    # Current-to-reference registration is (-2 y, +3 x), so the same point
    # appears in the current raw frame at (+2 y, -3 x).
    assert tracker._camera_compensated_hint(1, (40.0, 20.0)) == (37.0, 22.0)

    tracker.segmentation_config.ranges[0].camera_registration = False
    assert tracker._camera_compensated_hint(1, (40.0, 20.0)) == (40.0, 20.0)


def test_temporal_prior_tracks_mask_through_camera_translation():
    tracker = DICWormTracker.__new__(DICWormTracker)
    tracker.camera_shift = np.asarray([[0.0, 0.0], [-2.0, 3.0]])
    tracker.clip_start_set = {0}
    tracker.len_ref = 100.0
    tracker.segmentation_config = SegmentationConfig(
        ranges=[FrameRangeRecipe(
            0, 9, temporal_overlap=True,
            camera_registration=True)]).validate()
    previous = np.zeros((80, 80), bool)
    previous[20, 40] = True
    prior = tracker._temporal_identity_prior(1, previous)
    # Same specimen point is predicted at x=37, y=22 in the current image.
    assert prior[22, 37]
    assert not prior[60, 60]

    tracker.segmentation_config.ranges[0].temporal_overlap = False
    assert tracker._temporal_identity_prior(1, previous) is None


def test_temporal_overlap_rejects_a_spatially_separate_new_worm():
    import cv2
    from scipy.ndimage import center_of_mass
    frames = np.full((2, 128, 128), 200, np.float32)
    cv2.ellipse(frames[0], (35, 60), (10, 25), 0, 0, 360, 50, -1)
    cv2.ellipse(frames[1], (39, 60), (10, 25), 0, 0, 360, 50, -1)
    cv2.ellipse(frames[1], (100, 95), (13, 30), 0, 0, 360, 50, -1)
    config = SegmentationConfig(
        accepted=True, locked=True, target_tools=["track_one_worm"],
        ranges=[FrameRangeRecipe(
            0, 1, mode="global", feature="gray", polarity="dark",
            threshold=144, temporal_overlap=True,
            camera_registration=True)])
    tracker = DICWormTracker(
        frames, fps=10, um_per_px=1.0, fps_source="declared",
        um_per_px_source="declared", segmentation_config=config,
        thickness_iter=1)
    first = tracker._mask(0)
    # Even a deliberately misleading point hint on the newcomer cannot win.
    second = tracker._mask(1, hint=(100, 95), previous_mask=first)
    _, x = center_of_mass(second)
    assert x < 60


def test_axially_participating_pixel_fraction_distinguishes_flow_direction():
    points = np.column_stack([np.linspace(10, 85, 25), np.full(25, 48.0)])
    yy, xx = np.ogrid[:96, :96]
    mask = ((xx-48)/42)**2+((yy-48)/8)**2 <= 1
    image = ((xx+yy) % 9).astype(np.uint8)
    axial_flow = np.zeros((96, 96, 2), np.float32)
    axial_flow[..., 0] = 1.0
    normal_flow = np.zeros_like(axial_flow)
    normal_flow[..., 1] = 1.0
    axial_fraction, _ = axial_participating_fraction(
        axial_flow, image, points, mask, (0, 24))
    normal_fraction, _ = axial_participating_fraction(
        normal_flow, image, points, mask, (0, 24))
    assert axial_fraction > 0.9
    assert normal_fraction < 0.1
