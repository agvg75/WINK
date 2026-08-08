"""Supervised segmentation review: the preview/accept/lock gate and its recipes.

Converted from pytest to the plain runner the rest of this directory uses, so
it runs in the venv Setup_Lab_Tools.bat builds. Installing pytest would put a
test framework into a student runtime to serve one file.
"""
from pathlib import Path
import shutil
import sys
import tempfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from segmentation_review import (                        # noqa: E402
    FrameRangeRecipe, SegmentationConfig, SpaceTimePatch, continuity_acceptance,
    effective_threshold_map, find_accepted_config, segment_frame)

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def refuses(name, call, expect):
    """Assert a call is refused AND that it says why."""
    try:
        call()
    except ValueError as error:
        if expect in str(error):
            check(name, True)
        else:
            check(name, False, f"raised, but said {str(error)!r}")
    except Exception as error:                      # noqa: BLE001
        check(name, False, f"{type(error).__name__}: {error}")
    else:
        check(name, False, "was accepted")


print("segmentation review - regression\n")
tmp = Path(tempfile.mkdtemp())
try:
    # ------------------------------------------------------------------
    # 1. Nothing segments until a person has previewed, accepted and locked
    # ------------------------------------------------------------------
    frame = np.zeros((40, 50), np.uint8)
    frame[10:30, 15:35] = 200
    config = SegmentationConfig(
        mode="global", threshold=120, target_tools=["track_one_worm"])
    refuses("an unaccepted, unlocked config cannot segment anything - the "
            "human gate is not advisory",
            lambda: segment_frame(frame, 0, config), "preview, accept, and lock")

    config.accepted = config.locked = config.blinding_acknowledged = True
    config.save(tmp / "nike_segmentation_review.json")
    loaded = find_accepted_config(tmp, "track_one_worm")
    check("an accepted config is found again by the tool it was locked for",
          loaded is not None)
    check("and reproduces the same mask, so a locked review is replayable",
          segment_frame(frame, 0, loaded).sum() == 400,
          segment_frame(frame, 0, loaded).sum())
    check("segmentation never edits the pixels it measures",
          np.array_equal(frame[10:30, 15:35], np.full((20, 20), 200)))

    # ------------------------------------------------------------------
    # 2. The photometry firewall
    # ------------------------------------------------------------------
    refuses("a fluorescence tool cannot be given a segmentation mask - "
            "thresholding upstream of photometry would change the numbers",
            lambda: SegmentationConfig(target_tools=["rgbcamp"]).validate(),
            "Photometry firewall")

    # ------------------------------------------------------------------
    # 3. Space-time patches blend in, and seams are caught
    # ------------------------------------------------------------------
    config = SegmentationConfig(
        mode="space_time", threshold=100, accepted=True, locked=True,
        target_tools=["defecation_cycle"],
        patches=[SpaceTimePatch(
            [[10, 10], [30, 10], [30, 30], [10, 30]],
            10, 20, 180, temporal_blend_frames=5)])
    before = effective_threshold_map((50, 50), 4, config)
    ramp = effective_threshold_map((50, 50), 8, config)
    active = effective_threshold_map((50, 50), 12, config)
    check("before its window a patch has no effect",
          abs(before[20, 20] - 100) < 1e-6, before[20, 20])
    check("the patch ramps in rather than switching on between two frames, "
          "which would read as a step change in the measurement",
          100 < ramp[20, 20] < active[20, 20],
          (ramp[20, 20], active[20, 20]))
    check("and applies only inside its own polygon",
          active[20, 20] > active[0, 0], (active[20, 20], active[0, 0]))

    result = continuity_acceptance([100, 101, 100, 140, 141], [3],
                                   tolerance_fraction=.15)
    check("a discontinuity across a seam fails the continuity gate",
          result["passed"] is False)
    check("and names which seam, so it can be looked at",
          result["failed_seams"] == [3], result["failed_seams"])

    # ------------------------------------------------------------------
    # 4. Per-range thresholds and morphology
    # ------------------------------------------------------------------
    frame = np.full((30, 40), 180, np.uint8)
    frame[8:22, 10:28] = 100
    frame[13:16, 18:21] = 180        # a hole, closed only in the second range
    config = SegmentationConfig(
        mode="global", threshold=50, polarity="dark",
        accepted=True, locked=True, target_tools=["track_one_worm"],
        ranges=[
            FrameRangeRecipe(0, 4, threshold=90, polarity="dark"),
            FrameRangeRecipe(5, 9, threshold=120, polarity="dark",
                             close_iterations=1, fill_holes=True,
                             min_object_area=50),
        ])
    check("a frame in the first range keeps its hole",
          segment_frame(frame, 2, config).sum() == 14 * 18 - 9,
          segment_frame(frame, 2, config).sum())
    check("a frame in the second range has it filled, because the recipe "
          "changes with the frame, not just the threshold",
          segment_frame(frame, 7, config).sum() == 14 * 18,
          segment_frame(frame, 7, config).sum())

    config.save(tmp / "nike_segmentation_review.json")
    loaded = SegmentationConfig.load(tmp / "nike_segmentation_review.json")
    check("morphology settings survive a save/load round trip",
          loaded.recipe_for_frame(7).fill_holes is True)
    check("and so does the per-range threshold",
          loaded.recipe_for_frame(4).threshold == 90,
          loaded.recipe_for_frame(4).threshold)

    refuses("overlapping frame ranges are rejected - two recipes claiming one "
            "frame has no defensible answer",
            lambda: SegmentationConfig(ranges=[
                FrameRangeRecipe(0, 10), FrameRangeRecipe(10, 20)]).validate(),
            "overlap")

    # ------------------------------------------------------------------
    # 5. Adding ranges must not have changed the no-range behaviour
    # ------------------------------------------------------------------
    frame = np.arange(100, dtype=np.uint8).reshape(10, 10)
    legacy = SegmentationConfig(
        mode="global", threshold=50, polarity="bright",
        accepted=True, locked=True, target_tools=["track_one_worm"])
    normalized = cv2.normalize(frame, None, 0, 255, cv2.NORM_MINMAX)
    check("with no ranges the result is bit-for-bit the legacy segmentation, "
          "so old measurements stay reproducible",
          np.array_equal(segment_frame(frame, 3, legacy), normalized >= 50))
    check("and no recipe is invented for a frame",
          legacy.recipe_for_frame(3) is None)

    # ---------------------------------------------------- band polarity
    # REPORTED FROM THE LIVE WORKBENCH, 8 Aug 2026: "tried band rather than
    # bright or dark and broke it". Two defects, and the second is worse.
    #
    #   1. The dropdown offered "band" and SegmentationConfig.validate()
    #      rejected it. Band had been added to FrameRangeRecipe and to the
    #      mask function; this validator was never updated. Loud failure.
    #
    #   2. segment_frame read `recipe and polarity == "band"`, so a band set
    #      on the CONFIG - with no per-range recipe - fell through to the
    #      plain-threshold branch and was segmented AS IF BRIGHT. Silent, and
    #      a wrong mask that looks like a working one.
    banded = np.zeros((40, 40), np.uint8)
    banded[10:20, 10:20] = 100          # inside the band
    banded[25:35, 25:35] = 220          # brighter than the band
    common = dict(target_tools=["track_one_worm"], accepted=True, locked=True,
                  blinding_acknowledged=True, source="x")
    band = SegmentationConfig(mode="global", polarity="band",
                              threshold_low=80, threshold_high=150, **common)
    band.validate()
    check("a config polarity of 'band' validates - the workbench offers it, "
          "so the config must accept it", band.polarity == "band")

    mask = segment_frame(banded, 0, band)
    check("band selects what is INSIDE the band", bool(mask[15, 15]))
    check("and excludes what is brighter than it", not bool(mask[30, 30]))
    check("and excludes the background below it", not bool(mask[0, 0]))

    bright = SegmentationConfig(mode="global", polarity="bright",
                                threshold=80, **common)
    bright.validate()
    bright_mask = segment_frame(banded, 0, bright)
    check("a band mask DIFFERS from the bright mask it used to silently "
          "become - proof the fallthrough was producing a wrong answer "
          "rather than an equivalent one",
          not np.array_equal(mask, bright_mask))
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("SEGMENTATION_REVIEW_REGRESSION_PASS")
