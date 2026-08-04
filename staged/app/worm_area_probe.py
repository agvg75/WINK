"""Measure one animal from a recording and derive detector gates from it.

WHY THIS EXISTS
---------------
Area gates are entered in SOURCE pixels, so a default that suits one camera
floods another with noise. Population tracking solved this with its "Measure a
worm" button - click an animal, read the area the DETECTOR gives it, and set the
gates from that - but the logic lived inside that tool's window class, so every
other module kept its own hard-coded numbers. Basal slowing still defaulted to
40/2500, the values that flood a 4K recording, and had no way to do better.

This module is that computation with no Tk in it: the tools keep their own
clicking and dialogs, and share the arithmetic.

THE MEASUREMENT PRINCIPLE, worth preserving verbatim from the original:
clicking says only *which* object is an animal. The number comes from the
detector's own mask, never from a hand-drawn outline - a traced outline is
systematically more generous than the thresholded mask, and it is the mask the
gates are compared against.

MIGRATION NOTE: tools/population_swimming/population_swimming_tool.py still
carries its own inline copy of this logic. It is the reference implementation
these functions were lifted from, and the factors below are its factors. Moving
that tool onto this module is the remaining half of the job; it was left alone
in the same change that introduced this file so a validated tool was not
refactored and re-pointed at once.
"""
from __future__ import annotations

import numpy as np

# Lifted from population_swimming_tool.py so both agree by construction.
MIN_FACTOR = 0.40        # curled, foreshortened, or younger animals
MAX_FACTOR = 5.0         # two animals briefly touching
BACKGROUND_SAMPLES = 15
THIN_PX_WARNING = 3.5    # below this the standard skeleton fragments


def proxy_scale(width, height):
    """Detection resolution. Large frames are sampled down; the caller must
    divide any measured pixel count by scale**2 to get source pixels."""
    return 0.25 if max(int(width), int(height)) >= 1800 else 1.0


def sample_indices(n_frames, n_samples=BACKGROUND_SAMPLES):
    total = max(2, int(n_frames))
    return np.unique(np.linspace(0, total - 1,
                                 min(int(n_samples), total)).astype(int))


def background_and_frame(samples):
    """Median background plus a representative frame, from decoded samples."""
    if len(samples) < 2:
        raise ValueError(
            "Could not decode enough frames to build a background. A single "
            "frame cannot separate a moving animal from the plate.")
    stack = np.stack([np.asarray(s) for s in samples])
    return np.median(stack, axis=0).astype(np.uint8), np.asarray(
        samples[len(samples) // 2])


def detect_objects(frame, background):
    """(labels, stats) for everything that differs from the background."""
    import cv2
    diff = cv2.GaussianBlur(cv2.absdiff(np.asarray(frame), background), (3, 3), 0)
    _, mask = cv2.threshold(diff, 0, 255,
                            cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        raise ValueError(
            "No moving objects were found in the sampled frame. Measuring an "
            "animal needs a recording where the animals move.")
    return labels, stats


def object_at(labels, stats, x, y):
    """Label under (x, y); falls back to the nearest object if background was
    clicked, so a slightly-off click still measures an animal."""
    import cv2
    yy = int(np.clip(y, 0, labels.shape[0] - 1))
    xx = int(np.clip(x, 0, labels.shape[1] - 1))
    label = int(labels[yy, xx])
    if label > 0:
        return label
    centroids = np.stack([
        stats[1:, cv2.CC_STAT_LEFT] + stats[1:, cv2.CC_STAT_WIDTH] / 2.0,
        stats[1:, cv2.CC_STAT_TOP] + stats[1:, cv2.CC_STAT_HEIGHT] / 2.0], 1)
    return int(np.argmin(np.hypot(centroids[:, 0] - x,
                                  centroids[:, 1] - y))) + 1


def describe(stats, label, scale):
    """What the detector thinks the clicked object is, in source pixels."""
    import cv2
    proxy_area = float(stats[label, cv2.CC_STAT_AREA])
    w = float(stats[label, cv2.CC_STAT_WIDTH])
    h = float(stats[label, cv2.CC_STAT_HEIGHT])
    span = float(np.hypot(w, h))
    all_areas = np.sort(stats[1:, cv2.CC_STAT_AREA].astype(float))
    percentile = 100.0 * float((all_areas <= proxy_area).sum()) / max(1, len(all_areas))
    thickness = proxy_area / max(1.0, span)
    return {
        "proxy_area_px": proxy_area,
        "source_area_px": proxy_area / (scale * scale),
        "span_source_px": span / scale,
        "thickness_proxy_px": thickness,
        "percentile_of_objects": percentile,
        "n_objects": int(len(all_areas)),
        "all_areas_proxy": all_areas,
        "scale": float(scale),
        "too_thin_for_skeleton": bool(thickness < THIN_PX_WARNING),
    }


def suggest_gates(described, min_factor=MIN_FACTOR, max_factor=MAX_FACTOR):
    """Area gates in SOURCE pixels, plus how many objects they would keep."""
    source_area = described["source_area_px"]
    scale = described["scale"]
    all_areas = described["all_areas_proxy"]
    low = max(1.0, round(source_area * float(min_factor)))
    high = round(source_area * float(max_factor))
    kept = int(((all_areas >= low * scale * scale)
                & (all_areas <= high * scale * scale)).sum())
    return {"min_area": int(low), "max_area": int(high),
            "kept_objects": kept, "n_objects": described["n_objects"],
            "min_factor": float(min_factor), "max_factor": float(max_factor)}


def gates_look_wrong_for(described, min_area, max_area):
    """Why the CURRENT gates would misbehave on this recording, or None.

    Exists so a tool can say what is about to go wrong before an analysis runs,
    rather than leaving someone to infer it from a tracker that found four
    thousand animals.
    """
    area = described["source_area_px"]
    reasons = []
    if area > max_area:
        reasons.append(
            f"the measured animal is {area:,.0f} source px, above the current "
            f"maximum of {max_area:,.0f}, so real animals are being discarded")
    if area < min_area:
        reasons.append(
            f"the measured animal is {area:,.0f} source px, below the current "
            f"minimum of {min_area:,.0f}, so it is being discarded as noise")
    if min_area <= area <= max_area and min_area < 0.1 * area:
        reasons.append(
            f"the minimum of {min_area:,.0f} px is far below the measured "
            f"animal ({area:,.0f} px), so debris and noise blobs will be "
            f"tracked as animals")
    return "; ".join(reasons) if reasons else None


def estimate_link_px(frames, background, proxy_area, scale):
    """Observed per-frame travel of worm-sized objects -> a link gate.

    Returns None when too few frames resolve. An over-large link gate is what
    lets a tracker weld two animals into one track with a long straight jump,
    so this is measured rather than guessed.
    """
    import cv2
    steps, previous = [], None
    for frame in frames:
        diff = cv2.GaussianBlur(cv2.absdiff(np.asarray(frame), background), (3, 3), 0)
        _, mask = cv2.threshold(diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
        pts = np.array([centroids[k] for k in range(1, count)
                        if stats[k, cv2.CC_STAT_AREA] >= 0.3 * proxy_area], float)
        if previous is not None and len(pts) and len(previous):
            for q in pts:
                steps.append(float(np.min(np.hypot(previous[:, 0] - q[0],
                                                   previous[:, 1] - q[1]))))
        previous = pts
    if len(steps) < 20:
        return None
    # p95 of observed motion, with headroom for frames where a worm was missed.
    return max(8.0, round(float(np.percentile(steps, 95)) / scale * 3.0))
