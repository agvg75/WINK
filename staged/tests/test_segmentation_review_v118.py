from pathlib import Path
import sys

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from segmentation_review import (
    FrameRangeRecipe, SegmentationConfig, SpaceTimePatch, continuity_acceptance,
    effective_threshold_map, find_accepted_config, segment_frame)


def test_preview_accept_lock_is_required_and_reconstructible(tmp_path):
    frame = np.zeros((40, 50), np.uint8)
    frame[10:30, 15:35] = 200
    config = SegmentationConfig(
        mode="global", threshold=120, target_tools=["track_one_worm"])
    with pytest.raises(ValueError, match="preview, accept, and lock"):
        segment_frame(frame, 0, config)
    config.accepted = config.locked = config.blinding_acknowledged = True
    config.save(tmp_path / "nike_segmentation_review.json")
    loaded = find_accepted_config(tmp_path, "track_one_worm")
    assert loaded is not None
    assert segment_frame(frame, 0, loaded).sum() == 400
    assert np.array_equal(frame[10:30, 15:35], np.full((20, 20), 200))


def test_photometry_firewall():
    with pytest.raises(ValueError, match="Photometry firewall"):
        SegmentationConfig(target_tools=["rgbcamp"]).validate()


def test_space_time_blending_and_continuity_gate():
    config = SegmentationConfig(
        mode="space_time", threshold=100, accepted=True, locked=True,
        target_tools=["defecation_cycle"],
        patches=[SpaceTimePatch(
            [[10, 10], [30, 10], [30, 30], [10, 30]],
            10, 20, 180, temporal_blend_frames=5)])
    before = effective_threshold_map((50, 50), 4, config)
    ramp = effective_threshold_map((50, 50), 8, config)
    active = effective_threshold_map((50, 50), 12, config)
    assert before[20, 20] == pytest.approx(100)
    assert 100 < ramp[20, 20] < active[20, 20]
    assert active[20, 20] > active[0, 0]
    result = continuity_acceptance(
        [100, 101, 100, 140, 141], [3], tolerance_fraction=.15)
    assert result["passed"] is False
    assert result["failed_seams"] == [3]


def test_frame_ranges_apply_different_thresholds_and_morphology(tmp_path):
    frame = np.full((30, 40), 180, np.uint8)
    frame[8:22, 10:28] = 100
    frame[13:16, 18:21] = 180  # hole closed/filled only in second range
    config = SegmentationConfig(
        mode="global", threshold=50, polarity="dark",
        accepted=True, locked=True, target_tools=["track_one_worm"],
        ranges=[
            FrameRangeRecipe(0, 4, threshold=90, polarity="dark"),
            FrameRangeRecipe(5, 9, threshold=120, polarity="dark",
                             close_iterations=1, fill_holes=True,
                             min_object_area=50),
        ])
    assert segment_frame(frame, 2, config).sum() == 14 * 18 - 9
    assert segment_frame(frame, 7, config).sum() == 14 * 18
    config.save(tmp_path / "nike_segmentation_review.json")
    loaded = SegmentationConfig.load(tmp_path / "nike_segmentation_review.json")
    assert loaded.recipe_for_frame(7).fill_holes is True
    assert loaded.recipe_for_frame(4).threshold == 90


def test_overlapping_ranges_are_rejected():
    with pytest.raises(ValueError, match="overlap"):
        SegmentationConfig(ranges=[
            FrameRangeRecipe(0, 10), FrameRangeRecipe(10, 20)
        ]).validate()


def test_no_range_preserves_legacy_segmentation_exactly():
    frame = np.arange(100, dtype=np.uint8).reshape(10, 10)
    legacy = SegmentationConfig(
        mode="global", threshold=50, polarity="bright",
        accepted=True, locked=True, target_tools=["track_one_worm"])
    # Legacy segmentation thresholds the same normalized 8-bit feature image.
    normalized = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX)
    expected = normalized >= 50
    assert np.array_equal(segment_frame(frame, 3, legacy), expected)
    assert legacy.recipe_for_frame(3) is None
