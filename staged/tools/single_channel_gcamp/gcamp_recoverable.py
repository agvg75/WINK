"""
GCaMP recoverability: flattening, conserved-length calibration, partial exits
==============================================================================

This module handles the harder case surfaced by the high-zoom, no-DIC,
blue-only Pmyo-3::GCaMP movies: the worm fills much of the frame, body
brightness is uneven along its length (real biology, not noise), and the
animal sometimes partially exits the field of view.

It is explicitly NOT a replacement for Track one worm / the supervised
segmentation workbench. It is a pre-flight tool with two jobs:

1. Estimate, per movie, how much of the recording is actually usable, as
   contiguous runs rather than a single pass/fail label. A long movie with
   a few solid, uninterrupted stretches is good data even if large parts of
   it are unusable; a short average hides that the same way an
   average frequency can hide fragmented swimming data (same principle as
   Single-worm swimming analysis's usable-coverage reporting).
2. Flag, frame by frame, when an apparent size/length change is explained
   by the worm crossing the frame edge (expected, inferable) versus an
   unexplained shrinkage (a segmentation problem, not a real animal event).
   This uses the same assumption the tracker already relies on elsewhere:
   worm length does not change. If a fully-visible calibration outline says
   the animal is L pixels long and a later frame's visible length is
   shorter AND the mask touches the frame boundary, the missing length is
   inferred to be off-frame, not gone.

Calibration is meant to come from a human-drawn outline, the same pattern
used in Track one worm and pBoc's three-outline landmark calibration: the
user marks the animal once, on a frame where it is fully visible, and that
defines the conserved length/area used to interpret every other frame.
Two stand-ins are provided here since this module runs headless:
  - calibrate_from_polygon(): use a real traced polygon (x, y) point list.
  - calibrate_from_auto_segmentation(): auto-segment a chosen frame and use
    that as calibration. This is a convenience for batch triage only; it is
    not a substitute for a human confirming the outline before it is
    trusted, and should be labeled as such in any report that uses it.

The interactive UI this feeds into is gcamp_recoverable_tool.py: a person
picks a representative frame, gets an adaptive per-acquisition bg_sigma
default (estimate_body_bg_sigma) with a confidence/abstain decision, and
adjusts it with a multiplier dial while watching the body/signal mask
redraw live. It also includes the "maximize contrast" display-only toggle
(auto_contrast_preview()) for the drawing/marking step - it affects only
what the person sees, never the pixels that get measured - and the
straight/coiled frame marking that licenses validate_coil_branch's coil
classification for a specific recording.
"""

from dataclasses import dataclass, field
from pathlib import Path

import cv2
import networkx as nx
import numpy as np
from PIL import Image
from skimage.morphology import skeletonize


# ---------------------------------------------------------------------------
# Tunable defaults. Record any non-default value used for a real batch run.
# ---------------------------------------------------------------------------
BG_SIGMA = 25          # gaussian sigma for background estimate (px)
SMOOTH_SIGMA = 2       # gaussian sigma for denoising the flattened signal
NOISE_SIGMA_MULT = 3   # threshold = this many std devs above the noise floor
CLOSE_PX = 15          # morphological closing kernel (px); bridges gaps from
                        # uneven brightness along the body. This is very
                        # frame/zoom-dependent, 41px looked right on one test
                        # frame and badly over-bridged another (mask ballooned
                        # 3x, corrupting the width model), so treat 15 as a
                        # starting point, not a trustworthy batch default.
                        # Larger = more forgiving of gaps but more likely to
                        # bridge in nearby background texture. Always check
                        # the width model (mask_width_profile) it produces
                        # against a sanity range before trusting it.
EDGE_MARGIN_PX = 3     # how close to the frame border counts as "touching"
LENGTH_TOL = 0.90      # visible length below this fraction of calibration
                        # is treated as a real change, not noise
AREA_TOL = 0.85


# ---------------------------------------------------------------------------
# Display-only helper for the interactive outline-drawing step
# ---------------------------------------------------------------------------
def auto_contrast_preview(gray_full, low_pct=0.5, high_pct=99.9):
    """Percentile stretch for on-screen display only while a user is
    drawing the calibration outline. Never feed this back into measurement,
    only the raw frame is measured."""
    lo, hi = np.percentile(gray_full, [low_pct, high_pct])
    if hi <= lo:
        return np.zeros_like(gray_full, dtype=np.uint8)
    stretched = np.clip((gray_full.astype(float) - lo) / (hi - lo) * 255,
                         0, 255)
    return stretched.astype(np.uint8)


# ---------------------------------------------------------------------------
# Segmentation for zoomed / no-DIC frames
# ---------------------------------------------------------------------------
def flatten_and_segment(gray_full, bg_sigma=BG_SIGMA,
                         smooth_sigma=SMOOTH_SIGMA,
                         sigma_mult=NOISE_SIGMA_MULT, close_px=CLOSE_PX):
    """Background-subtract, denoise, threshold relative to the local noise
    floor, then morphologically close to bridge gaps from uneven along-body
    brightness. Returns the single largest resulting component as a
    full-resolution boolean mask (or None if nothing survives)."""
    gray = gray_full.astype(np.float32)
    # BORDER_REPLICATE avoids a bright/dark halo artifact right at the true
    # frame edge that the default border mode introduces, which matters a
    # lot here since a worm partially exiting the frame is exactly the
    # region we need this to behave correctly in.
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=bg_sigma,
                           borderType=cv2.BORDER_REPLICATE)
    flat = np.clip(gray - bg, 0, None)
    flat_smooth = cv2.GaussianBlur(flat, (0, 0), sigmaX=smooth_sigma,
                                    borderType=cv2.BORDER_REPLICATE)

    noise_std = flat_smooth.std()
    thresh = sigma_mult * noise_std
    mask = (flat_smooth > thresh).astype(np.uint8) * 255

    if close_px > 0:
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                            (close_px, close_px))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask, connectivity=8)
    if n_labels <= 1:
        return None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == largest


# ---------------------------------------------------------------------------
# Length / area measurement, calibration, edge detection
# ---------------------------------------------------------------------------
BODY_BG_SIGMA = 50     # see segment_body_and_signal for why this is not 25


def segment_body_and_signal(gray_full, bg_sigma=BODY_BG_SIGMA):
    """Separate WHERE THE ANIMAL IS from WHERE IT IS BRIGHT.

    `flatten_and_segment` thresholds intensity, so on Pmyo-3 GCaMP it returns
    whichever part of the animal is currently fluorescing - which is the signal
    being measured. Mask area then reflects muscle activity rather than the
    animal's size, and every downstream conserved-area comparison inherits that
    confound.

    Two changes fix it, and both matter:

    1. **Background sigma.** The default 25 px is comparable to the worm's own
       width (~15-25 px here), so the Gaussian background estimate follows the
       animal and subtracts it away, leaving only the brightest core. Measured
       on real frames, sigma 25 failed outright - it segmented background noise
       at the frame edge - while sigma 50 captured whole animals including a
       fully coiled one. Above ~75 it began collapsing back to the bright hook
       on some frames.

    2. **Three populations, not two.** Multi-Otsu with three classes splits
       background / body / elevated signal, so the dim body joins the mask
       instead of being thresholded away with the background.

    Returns ``(body_mask, signal_mask)``. Use ``body_mask`` for morphology -
    length, area, coiling, calibration - and ``signal_mask`` for where calcium
    is elevated WITHIN that body. Never use the signal mask for geometry.

    This is offered alongside `flatten_and_segment`, not as a replacement:
    changing that default would silently alter every existing result. The
    sigma above is validated on one dataset only; check
    `mask_width_profile()` on your own frames before trusting a batch run.
    """
    try:
        from skimage.filters import threshold_multiotsu
    except Exception:
        return None, None
    gray = np.asarray(gray_full).astype(np.float32)
    if gray.ndim == 3:
        gray = gray[..., :3].mean(axis=2)
    bg = cv2.GaussianBlur(gray, (0, 0), sigmaX=float(bg_sigma),
                          borderType=cv2.BORDER_REPLICATE)
    flat = np.clip(gray - bg, 0, None)
    try:
        bg_body, body_peak = threshold_multiotsu(flat, classes=3)
    except Exception:
        return None, None
    outline = (flat > bg_body).astype(np.uint8) * 255
    outline = cv2.morphologyEx(
        outline, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9)))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(outline, connectivity=8)
    if count <= 1:
        return None, None
    largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    body = labels == largest
    # A "body" covering much of the frame is background, not an animal - the
    # failure mode seen at sigma 25, where the largest component was a noise
    # field along one edge.
    if body.mean() > 0.35:
        return None, None
    return body, body & (flat > body_peak)


# ---------------------------------------------------------------------------
# Adaptive bg_sigma: BODY_BG_SIGMA=50 was validated on one dataset only (see
# the module docstring's own caveat), and testing it against a second,
# independent recording (different day, different RNAi condition) showed it
# does not transfer - body area swung up to 32x within a single acquisition
# on the new data, meaning the mask was sometimes debris/background rather
# than the animal. This section replaces the single fixed constant with a
# per-acquisition search over a coarse sigma grid (a proxy for worm width /
# local contrast), ranked by how plausible the resulting mask looks as one
# elongated animal.
#
# The default this produces and the person's manual override are kept
# deliberately SEPARATE, not collapsed into one raw sigma value. A raw sigma
# slider means "the right value" is a different absolute number on a bright
# acquisition than on a dark one - the ace-1 recording needed a very
# different sigma than the egl-19 one it was tuned on - so a slider showing
# raw pixels is not comparable across recordings and forces a student to
# hunt from scratch every time. Instead: `estimate_body_bg_sigma` computes a
# per-acquisition default, and `bg_sigma_for_multiplier` applies a DIAL that
# is a multiplier on that default (1.0x = trust the estimate, 1.5x = more
# background subtraction than estimated, etc.) - meaningful regardless of
# how dark or bright the specific acquisition is.
#
# The same computation also drives the abstain gate: confidence comes from
# whether the winning sigma is backed by a plateau of similarly-plausible
# neighboring sigmas (real animals tend to segment sensibly across a RANGE
# of nearby sigmas) or is an isolated spike (more likely a fluke - debris
# that happened to look elongated at exactly one sigma). Low confidence means
# abstain, not "fall back to BODY_BG_SIGMA and pretend it's trustworthy."
# ---------------------------------------------------------------------------
SIGMA_SEARCH_GRID = tuple(range(20, 90, 5))
PLAUSIBLE_AREA_FRAC = (0.005, 0.30)   # a worm-sized blob, not noise or the frame
MIN_PLAUSIBLE_ASPECT = 1.8            # worms are elongated; blobs of noise are not
MIN_ESTIMATE_CONFIDENCE = 0.25        # below this, abstain rather than guess
BG_SIGMA_MULTIPLIER_BOUNDS = (0.4, 2.5)
BG_SIGMA_ABSOLUTE_BOUNDS = (10.0, 150.0)  # GaussianBlur needs a sane, positive sigma


def mask_plausibility_score(body, area_frac_range=PLAUSIBLE_AREA_FRAC,
                             min_aspect=MIN_PLAUSIBLE_ASPECT):
    """How much does `body` look like ONE elongated animal, not debris, a
    noise field, or an over-merged blob?

    Always returns the underlying measurements (`area_frac`, `aspect`,
    `border_touch_frac`). `score` is set to None when the mask fails a hard
    gate - implausible size, or not elongated enough - and otherwise rewards
    elongation while penalizing a mask that hugs the frame border, since a
    real animal only touches the border when it is genuinely exiting the
    frame, not along a whole edge.

    This ranks CANDIDATE sigmas against each other for the SAME frame. It is
    not a certificate that a passing mask is correct - a stubbier real worm,
    or a well-shaped patch of debris, can both score well. Treat a high score
    as "worth showing to a person," not as ground truth.
    """
    body = np.asarray(body, dtype=bool)
    if body.sum() == 0:
        return {"area_frac": 0.0, "aspect": None,
                "border_touch_frac": None, "score": None}
    area_frac = float(body.mean())
    body_u8 = body.astype(np.uint8) * 255
    contours, _ = cv2.findContours(body_u8, cv2.RETR_EXTERNAL,
                                    cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return {"area_frac": area_frac, "aspect": None,
                "border_touch_frac": None, "score": None}
    largest = max(contours, key=cv2.contourArea)
    (_, _), (rw, rh), _ = cv2.minAreaRect(largest)
    aspect = float(max(rw, rh) / max(min(rw, rh), 1e-6))
    border = np.zeros_like(body, dtype=bool)
    border[0:2, :] = True; border[-2:, :] = True
    border[:, 0:2] = True; border[:, -2:] = True
    border_touch_frac = float((body & border).sum() / max(int(body.sum()), 1))
    score = None
    if area_frac_range[0] <= area_frac <= area_frac_range[1] and aspect >= min_aspect:
        score = aspect - 3.0 * border_touch_frac
    return {"area_frac": area_frac, "aspect": aspect,
            "border_touch_frac": border_touch_frac, "score": score}


def estimate_body_bg_sigma(gray_full, sigma_grid=SIGMA_SEARCH_GRID,
                            min_confidence=MIN_ESTIMATE_CONFIDENCE,
                            return_table=False):
    """Compute a per-acquisition adaptive DEFAULT bg_sigma, with a confidence
    score and an abstain decision - not a raw value to hand a slider.

    Returns a dict:
      bg_sigma_default  - the adaptive estimate (int), or None if abstaining
      confidence        - 0..1, how much a person should trust this default
      abstain           - True when confidence < min_confidence
      abstain_reason    - human-readable, only set when abstaining
      table             - every candidate sigma's measurements, if requested

    Confidence has two parts. `breadth`: what fraction of the search grid
    produced ANY plausible mask at all (a very dark or low-contrast frame
    might pass none of them). `support`: whether the winning sigma's
    immediate neighbors in the grid also scored plausibly - a real animal
    tends to segment sensibly across a range of nearby sigmas, so a winner
    with no support from its neighbors is more likely an isolated fluke
    (debris that happened to look elongated at exactly one sigma) than a
    real detection. Confidence is not a statement about whether the CHOSEN
    mask is biologically correct, only about whether the search behaved like
    it found something real rather than noise.

    Feed `bg_sigma_default` into `bg_sigma_for_multiplier` together with a
    person's dial position - do not use this value directly as a raw sigma
    for a slider, see the module-level note above for why.
    """
    table = []
    for sigma in sigma_grid:
        body, _signal = segment_body_and_signal(gray_full, bg_sigma=sigma)
        row = {"bg_sigma": int(sigma), "body_px": None,
               "area_frac": None, "aspect": None,
               "border_touch_frac": None, "score": None}
        if body is not None:
            metrics = mask_plausibility_score(body)
            row.update(metrics)
            row["body_px"] = int(body.sum())
        table.append(row)

    passing = [r for r in table if r["score"] is not None]
    if not passing:
        result = {
            "bg_sigma_default": None, "confidence": 0.0, "abstain": True,
            "abstain_reason": (
                "no sigma in the search grid produced a plausible body mask "
                "on this frame - it is likely too dark or too low-contrast "
                "to estimate worm width reliably here. Do not fall back to "
                "a fixed default and trust it; review the frame by eye."),
        }
        if return_table:
            result["table"] = table
        return result

    best = max(passing, key=lambda r: r["score"])
    grid = list(sigma_grid)
    idx = grid.index(best["bg_sigma"])
    step = grid[1] - grid[0] if len(grid) > 1 else 0
    neighbor_sigmas = {best["bg_sigma"] - step, best["bg_sigma"] + step}
    neighbor_rows = [r for r in table if r["bg_sigma"] in neighbor_sigmas]
    support = (sum(1 for r in neighbor_rows if r["score"] is not None)
               / max(len(neighbor_rows), 1))
    breadth = len(passing) / len(table)
    confidence = float(np.clip(0.5 * support + 0.5 * breadth, 0.0, 1.0))
    abstain = confidence < min_confidence

    result = {
        "bg_sigma_default": None if abstain else best["bg_sigma"],
        "confidence": confidence,
        "abstain": abstain,
        "abstain_reason": (
            None if not abstain else
            f"the best candidate (sigma={best['bg_sigma']}) is not backed by "
            f"plausible masks at its neighboring sigmas (confidence "
            f"{confidence:.2f} < {min_confidence:.2f}) - it looks like an "
            f"isolated fluke rather than a real detection. Review the frame "
            f"by eye rather than trusting an automatic default here."),
    }
    if return_table:
        result["table"] = table
    return result


def bg_sigma_for_multiplier(bg_sigma_default, multiplier=1.0):
    """Apply a person's DIAL (a multiplier on the adaptive per-acquisition
    default, never a raw pixel value) and clamp to a workable range.

    multiplier=1.0 means "trust the adaptive estimate as-is." Values above
    or below that nudge away from the computed starting point rather than
    requiring a student to find an absolute number from scratch each time -
    see the module-level note on why a raw sigma slider does not transfer
    across differently-lit acquisitions.
    """
    multiplier = float(np.clip(multiplier, *BG_SIGMA_MULTIPLIER_BOUNDS))
    sigma = float(bg_sigma_default) * multiplier
    return float(np.clip(sigma, *BG_SIGMA_ABSOLUTE_BOUNDS))


def _ordered_skeleton_points(mask):
    skel = skeletonize(mask)
    ys, xs = np.nonzero(skel)
    pts = list(zip(xs.tolist(), ys.tolist()))
    if len(pts) <= 2:
        return pts
    ordered = [pts.pop(0)]
    while pts:
        last = ordered[-1]
        dists = [((p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2) for p in pts]
        j = int(np.argmin(dists))
        ordered.append(pts.pop(j))
    return ordered


def mask_length_and_area(mask):
    """Length proxy plus raw area.

    Uses external-contour perimeter / 2 rather than skeleton-point nearest-
    neighbor chaining. Chaining looked reasonable on a clean single-blob
    mask but was unstable (badly overestimated) as soon as a skeleton had
    branch points, e.g. right after a coil, a self-contact, or a mask that
    had just been cut by a frame edge, since greedy nearest-neighbor
    chaining has no way to know which branch is the 'real' path. Perimeter/2
    is a coarse approximation for a thin elongated blob (perimeter is
    roughly 2x length + 2x width, and width << length), but it stayed
    stable under the same test conditions where chaining did not, so it is
    the safer default for a conserved-length comparison. Neither is a
    substitute for the real tracker's signed midline length; both are
    triage-only proxies."""
    m = mask.astype(np.uint8) * 255
    contours, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return {"length_px": 0.0, "area_px": int(mask.sum()), "n_skel_pts": 0}
    c = max(contours, key=cv2.contourArea)
    length_px = cv2.arcLength(c, True) / 2.0
    pts = _ordered_skeleton_points(mask)
    return {
        "length_px": float(length_px),
        "area_px": int(mask.sum()),
        "n_skel_pts": len(pts),
    }


def touches_frame_edge(mask, margin=EDGE_MARGIN_PX):
    h, w = mask.shape
    edges = []
    if mask[:margin, :].any():
        edges.append("top")
    if mask[-margin:, :].any():
        edges.append("bottom")
    if mask[:, :margin].any():
        edges.append("left")
    if mask[:, -margin:].any():
        edges.append("right")
    return edges


# ---------------------------------------------------------------------------
# Coil-aware length via distance-transform cutting + skeleton-graph path
# search, adapted from Layana Castro, Puchalt & Sanchez-Salmeron (2020),
# "Improving skeleton algorithm for helping Caenorhabditis elegans
# trackers", Sci Rep 10:22247 (MIT-licensed reference implementation at
# github.com/playanaC/Skeletonization, MATLAB). Reimplemented here in
# Python from the published method description, not ported from their code.
#
# Core idea: a plain skeleton of a self-touching/coiled blob is unreliable
# because it grows spurious branch points wherever two strands of the same
# worm touch. Their fix cuts the blob back to background wherever it is
# thicker than a single worm strand should be (found via the distance
# transform vs. a calibrated max-width value), which separates the
# self-touching regions before skeletonizing, then finds skeleton path(s)
# through the result. This is a materially better foundation than either
# a raw skeleton chain or a contour-perimeter estimate, both of which broke
# down under coiling in earlier testing here.
# ---------------------------------------------------------------------------
def mask_width_profile(mask, pct=(10, 90)):
    """Local half-width (distance-transform value) sampled along the
    skeleton, used to build a width model at calibration time. Returns
    (typical_half_width, max_half_width) in px."""
    skel = skeletonize(mask)
    if skel.sum() == 0:
        return float("nan"), float("nan")
    dist = cv2.distanceTransform(mask.astype(np.uint8) * 255, cv2.DIST_L2, 5)
    vals = dist[skel]
    lo, hi = np.percentile(vals, pct)
    return float(lo), float(hi)


def background_transform_cut(mask, max_half_width_px, iterations=3):
    """Cut the mask back to background wherever it is thicker than the
    calibrated max half-width, separating self-touching/overlapping
    regions of the same worm. Iterative, per the source method, since one
    pass can leave a still-too-thick remainder at a severe overlap."""
    m = mask.copy()
    for _ in range(iterations):
        dist = cv2.distanceTransform(m.astype(np.uint8) * 255, cv2.DIST_L2, 5)
        too_thick = dist > max_half_width_px
        if not too_thick.any():
            break
        m = m & ~too_thick
    return m


def _skeleton_graph(skel_mask):
    """8-connected pixel adjacency graph over skeleton pixels, edge weight
    = Euclidean step distance (1.0 or sqrt(2))."""
    ys, xs = np.nonzero(skel_mask)
    coords = set(zip(xs.tolist(), ys.tolist()))
    g = nx.Graph()
    g.add_nodes_from(coords)
    for x, y in coords:
        for dx, dy in [(1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)]:
            nb = (x + dx, y + dy)
            if nb in coords:
                w = 1.0 if dx == 0 or dy == 0 else 1.4142135623730951
                g.add_edge((x, y), nb, weight=w)
    return g


def coil_aware_length(mask, max_half_width_px, target_length_px=None):
    """Cut self-touching regions apart using the distance-transform
    background-transform, skeletonize what remains, and sum the longest
    (diameter) path within each resulting connected skeleton component.
    Summing across components approximates the true arc length even when
    the cut splits a coil into two or more separate pieces, since the cut
    only removes the doubly-covered overlap pixels, not real body length.

    If target_length_px is given (the calibrated length), used only to
    sanity-bound the result for reporting, not to force-fit it.
    """
    cut = background_transform_cut(mask, max_half_width_px)
    skel = skeletonize(cut)
    if skel.sum() == 0:
        return {"length_px": 0.0, "n_components": 0}

    total_length = 0.0
    n_components = 0
    n, labeled = cv2.connectedComponents(skel.astype(np.uint8), connectivity=8)
    for label in range(1, n):
        comp_mask = labeled == label
        if comp_mask.sum() < 2:
            continue
        g = _skeleton_graph(comp_mask)
        if g.number_of_nodes() < 2:
            continue
        # graph diameter (longest shortest-path) approximates the
        # component's own end-to-end arc length
        endpoints = [n for n in g.nodes if g.degree[n] == 1]
        best = 0.0
        candidates = endpoints if len(endpoints) >= 2 else list(g.nodes)
        # bound candidate pairs checked for speed on larger skeletons
        for i, a in enumerate(candidates[:20]):
            lengths = nx.single_source_dijkstra_path_length(g, a)
            far = max(lengths.values()) if lengths else 0.0
            best = max(best, far)
        total_length += best
        n_components += 1

    return {"length_px": float(total_length), "n_components": n_components}


def polygon_to_mask(shape, points):
    """points: list of (x, y) from a real manual trace (e.g. the outline
    a user draws in the Hub tool). Use this for a trustworthy calibration."""
    mask = np.zeros(shape, dtype=np.uint8)
    pts = np.array([points], dtype=np.int32)
    cv2.fillPoly(mask, pts, 1)
    return mask.astype(bool)


def _with_width(calib, mask):
    typical_hw, max_hw = mask_width_profile(mask)
    calib["typical_half_width_px"] = typical_hw
    calib["max_half_width_px"] = max_hw
    # give a little headroom above the observed max so a straight worm's own
    # thickest point doesn't get cut; the cut is meant to catch genuine
    # overlap (two strands), not the animal's natural widest cross-section
    calib["cut_half_width_px"] = max_hw * 1.15 if not np.isnan(max_hw) else float("nan")
    calib["width_proxy"] = (calib["area_px"] / calib["length_px"]
                             if calib.get("length_px") else float("nan"))
    return calib


def calibrate_from_polygon(shape, points, head_point=None, tail_point=None):
    """head_point / tail_point: (x, y), matching the real tracker's own
    pattern of a user head click at calibration time. Optional; without
    them, coiled frames can still be flagged, just not resolved to a
    specific clean end."""
    mask = polygon_to_mask(shape, points)
    calib = mask_length_and_area(mask)
    calib["source"] = "manual_outline"
    calib["head_point"] = head_point
    calib["tail_point"] = tail_point
    calib = _with_width(calib, mask)
    # recompute length with the coil-aware method for self-consistency,
    # since this is now also what later frames get compared against
    if not np.isnan(calib["cut_half_width_px"]):
        coil_len = coil_aware_length(mask, calib["cut_half_width_px"])
        if coil_len["length_px"] > 0:
            calib["length_px"] = coil_len["length_px"]
    return calib


def calibrate_from_auto_segmentation(gray_full, **seg_kwargs):
    """Convenience only. Auto-segments the given frame and uses the result
    as calibration. Label any downstream report as using an unconfirmed
    calibration when this path is used instead of a real traced outline."""
    mask = flatten_and_segment(gray_full, **seg_kwargs)
    if mask is None:
        return None
    calib = mask_length_and_area(mask)
    calib["source"] = "auto_segmentation_unconfirmed"
    calib["head_point"] = None
    calib["tail_point"] = None
    calib = _with_width(calib, mask)
    if not np.isnan(calib["cut_half_width_px"]):
        coil_len = coil_aware_length(mask, calib["cut_half_width_px"])
        if coil_len["length_px"] > 0:
            calib["length_px"] = coil_len["length_px"]
    return calib


# ---------------------------------------------------------------------------
# Coil / self-overlap detection and clean-end identification
# ---------------------------------------------------------------------------
def skeleton_endpoints(mask):
    """Degree-1 points of the skeleton (its two tips for a simple worm
    shape, more for a coil with extra branch artifacts). Used to find
    candidate head/tail locations in a frame without relying on a user
    click every single frame."""
    skel = skeletonize(mask).astype(np.uint8)
    if skel.sum() < 2:
        return []
    kernel = np.array([[1, 1, 1], [1, 10, 1], [1, 1, 1]])
    neighbor_count = cv2.filter2D(skel, -1, kernel, borderType=cv2.BORDER_CONSTANT)
    endpoints = np.argwhere((neighbor_count == 11))  # skel pixel (10) + 1 neighbor
    return [(int(x), int(y)) for y, x in endpoints]


def local_width(mask, point, sample_radius=4):
    """Distance-transform-based local half-width at a point, doubled to a
    full width estimate. A 'clean' (non-overlapped) stretch of body reads
    close to the calibration's average width; a self-overlapped stretch
    reads noticeably thicker."""
    dist = cv2.distanceTransform(mask.astype(np.uint8) * 255, cv2.DIST_L2, 5)
    x, y = point
    y0, y1 = max(0, y - sample_radius), min(dist.shape[0], y + sample_radius + 1)
    x0, x1 = max(0, x - sample_radius), min(dist.shape[1], x + sample_radius + 1)
    patch = dist[y0:y1, x0:x1]
    if patch.size == 0:
        return float("nan")
    return 2.0 * float(patch.max())


def find_clean_end(mask, calib, width_tol_mult=1.4):
    """Among the skeleton endpoints, return the one whose local width is
    closest to the calibrated single-strand width, i.e. the end least
    likely to be sitting in a self-overlapped region. This only identifies
    a candidate clean anchor point, same role as the tracker's own trusted-
    anchor concept; it does not reconstruct the coiled path. Recovering the
    exact 2D path of the overlapped portion from length/area alone is not
    generally possible, multiple coiled configurations can share the same
    conserved length and area, so this is a starting point for a human
    reviewer or for a constrained search, not a full answer."""
    endpoints = skeleton_endpoints(mask)
    if not endpoints or "width_proxy" not in calib:
        return None
    calib_width = calib["area_px"] / calib["length_px"] * 2 if calib.get("length_px") else float("nan")
    # rough single-strand width estimate: area/length is an *average* over
    # the whole body incl. tapered head/tail, so treat it as a soft target
    scored = []
    for pt in endpoints:
        w = local_width(mask, pt)
        if np.isnan(w):
            continue
        scored.append((pt, w, abs(w - calib_width)))
    if not scored:
        return None
    scored.sort(key=lambda t: t[2])
    best_pt, best_w, _ = scored[0]
    is_clean = best_w <= width_tol_mult * calib_width if not np.isnan(calib_width) else None
    return {"point": best_pt, "local_width_px": best_w,
            "calibrated_width_px": calib_width, "likely_clean": is_clean}


# ---------------------------------------------------------------------------
# Per-frame evaluation against calibration
# ---------------------------------------------------------------------------
@dataclass
class FrameEval:
    frame_index: int
    # full_view | partial_out_of_frame | possible_collision | degraded | lost
    # | unverified_shape_change  (coil signature, classification not validated)
    # | coiled_self_overlap      (only when ENABLE_COIL_CLASSIFICATION is on)
    status: str
    length_frac: float = float("nan")
    area_frac: float = float("nan")
    width_frac: float = float("nan")
    visible_fraction_est: float = float("nan")
    exit_edges: list = field(default_factory=list)
    clean_end: dict = None
    note: str = ""


COIL_WIDTH_MULT = 1.25   # width this much above calibration suggests overlap
COIL_LENGTH_MAX = 0.85   # length must also be meaningfully shorter to call it a coil

# The coil branch is implemented per the published method but has NEVER been
# validated: every attempt to build a test case failed. Synthetic "fold" tests
# do not conserve area the way real self-overlap does, and the one real
# candidate frame turned out to be a two-worm collision once checked.
#
# Until a real same-worm straight-then-coiled frame pair exists, a frame
# matching this signature is reported as `unverified_shape_change` rather than
# `coiled_self_overlap`. The evidence and the coil hypothesis are preserved in
# the note - nothing is discarded - but no unverified classification is
# asserted, because a confident wrong label is worse than an honest unknown.
#
# Set ENABLE_COIL_CLASSIFICATION = True (or pass enable_coil=True) once a real
# test case is in the fixture set. See test_gcamp_recoverable.py, which has a
# placeholder that will fail loudly if this is enabled without one.
ENABLE_COIL_CLASSIFICATION = False
UNVERIFIED_COIL_STATUS = "unverified_shape_change"


def validate_coil_branch(straight_mask, coiled_mask, calib=None,
                          length_tol=LENGTH_TOL, area_tol=AREA_TOL):
    """Check the coil branch against a straight/coiled pair of the SAME animal.

    This is the ground truth the branch has never had, and it cannot be
    supplied in the abstract: it depends on the animal, the magnification and
    the segmentation. So it is asked for per recording. The user marks one
    frame where the animal is clearly extended and one where it is clearly
    coiled; both are segmented; and the classifier is run against them.

    The branch passes only if BOTH hold:
      * the straight frame reads full_view against its own calibration, and
      * the coiled frame is caught by the coil signature rather than landing
        in degraded, partial_out_of_frame or possible_collision.

    A pass licenses coil classification FOR THAT RECORDING and nothing more.
    A failure is informative in itself - it usually means the segmentation is
    not capturing the whole animal, in which case no downstream shape
    classification can be trusted either.

    WHAT A PASS DOES AND DOES NOT MEAN. It means the signature fires on a frame
    a person identified as coiled, and does not fire on one they identified as
    extended. It does NOT mean the signature is specific to coiling: anything
    genuinely shorter and wider at conserved area matches it - a different,
    stubbier animal would too. That is why the marked pair must be the SAME
    animal in the SAME recording, and why the frames chosen are recorded
    alongside the verdict, so a later reader can check what was actually
    marked.

    Returns a dict recording what happened, suitable for storing with results.
    """
    if straight_mask is None or coiled_mask is None:
        return {"validated": False, "reason": "a mask was missing",
                "straight_status": None, "coiled_status": None}
    if calib is None:
        calib = mask_length_and_area(straight_mask)
        calib["source"] = "coil_validation_straight_frame"
        calib = _with_width(calib, straight_mask)
        if not np.isnan(calib.get("cut_half_width_px", float("nan"))):
            coil_len = coil_aware_length(straight_mask, calib["cut_half_width_px"])
            if coil_len["length_px"] > 0:
                calib["length_px"] = coil_len["length_px"]

    straight_eval = evaluate_frame(straight_mask, calib, frame_index=-1,
                                    length_tol=length_tol, area_tol=area_tol,
                                    enable_coil=True)
    coiled_eval = evaluate_frame(coiled_mask, calib, frame_index=-2,
                                  length_tol=length_tol, area_tol=area_tol,
                                  enable_coil=True)

    straight_ok = straight_eval.status == "full_view"
    coil_ok = coiled_eval.status == "coiled_self_overlap"
    if straight_ok and coil_ok:
        reason = ("the marked straight frame reads full_view and the marked "
                  "coiled frame is caught by the coil signature")
    elif not straight_ok:
        reason = (f"the frame marked STRAIGHT did not read full_view against "
                  f"its own calibration (got {straight_eval.status}); the "
                  f"calibration frame itself is suspect, most often because "
                  f"the segmentation is not capturing the whole animal")
    else:
        reason = (f"the frame marked COILED was classified {coiled_eval.status}, "
                  f"not a coil (length {coiled_eval.length_frac:.2f}, area "
                  f"{coiled_eval.area_frac:.2f}, width {coiled_eval.width_frac:.2f} "
                  f"of calibration). If area is far from 1.0 the segmentation is "
                  f"losing part of the animal, which the coil test depends on")
    return {"validated": bool(straight_ok and coil_ok), "reason": reason,
            "straight_status": straight_eval.status,
            "coiled_status": coiled_eval.status,
            "coiled_length_frac": coiled_eval.length_frac,
            "coiled_area_frac": coiled_eval.area_frac,
            "coiled_width_frac": coiled_eval.width_frac,
            "thresholds": {"COIL_WIDTH_MULT": COIL_WIDTH_MULT,
                           "COIL_LENGTH_MAX": COIL_LENGTH_MAX},
            "calibration_length_px": calib.get("length_px"),
            "calibration_area_px": calib.get("area_px")}


def evaluate_frame(mask, calib, frame_index=-1, length_tol=LENGTH_TOL,
                    area_tol=AREA_TOL, edge_margin=EDGE_MARGIN_PX,
                    find_clean_end_on_coil=True,
                    enable_coil=ENABLE_COIL_CLASSIFICATION):
    if mask is None or mask.sum() == 0:
        return FrameEval(frame_index, "lost", note="no blob detected")

    area_px = int(mask.sum())
    cut_hw = calib.get("cut_half_width_px", float("nan"))
    if not np.isnan(cut_hw):
        length_result = coil_aware_length(mask, cut_hw)
        length_px = length_result["length_px"]
    else:
        # no width model available (e.g. hand-built calib dict without it);
        # fall back to the simpler contour estimate
        length_px = mask_length_and_area(mask)["length_px"]

    length_frac = (length_px / calib["length_px"]
                   if calib.get("length_px") else float("nan"))
    area_frac = (area_px / calib["area_px"]
                 if calib.get("area_px") else float("nan"))
    width_now = area_px / length_px if length_px else float("nan")
    width_frac = (width_now / calib["width_proxy"]
                  if calib.get("width_proxy") else float("nan"))
    edges = touches_frame_edge(mask, margin=edge_margin)

    # Coil / self-overlap: length drops but area is roughly conserved (not
    # lost off-frame, since there's no edge contact to explain a real loss),
    # so the same area packed into a shorter length reads as wider. This is
    # a different signature from a real partial exit, where BOTH length and
    # area drop together because mass genuinely left the frame, and
    # different from a segmentation failure, where area does not stay
    # conserved. Checked before the generic 'oversized'/'undersized'
    # buckets below since it has a more specific explanation.
    if (not np.isnan(length_frac) and not np.isnan(width_frac)
            and length_frac <= COIL_LENGTH_MAX and width_frac >= COIL_WIDTH_MULT
            and area_tol <= area_frac <= 1.15):
        clean_end = find_clean_end(mask, calib) if find_clean_end_on_coil else None
        note = ("length shorter and width larger than calibration with area "
                 "conserved: consistent with the animal coiling/self-"
                 "contacting rather than a real exit or a segmentation loss.")
        if clean_end is not None:
            note += (f" Candidate clean end at {clean_end['point']} "
                     f"({'likely clean' if clean_end['likely_clean'] else 'ambiguous'})"
                     " can anchor a partial midline; the overlapped portion's "
                     "exact path is not recoverable from length/area alone.")
        if not enable_coil:
            note = ("This frame matches the coil/self-overlap signature, but "
                    "that classification has never been validated against a "
                    "real coiled frame, so it is NOT asserted here. Evidence: "
                    + note + " Review the frame before treating it as a coil; "
                    "a two-worm collision has previously been mistaken for one.")
            return FrameEval(frame_index, UNVERIFIED_COIL_STATUS, length_frac,
                             area_frac, width_frac, clean_end=clean_end, note=note)
        return FrameEval(frame_index, "coiled_self_overlap", length_frac,
                          area_frac, width_frac, clean_end=clean_end, note=note)

    # An implausibly larger mask than calibration is a red flag either way,
    # but two different explanations produce two different signatures:
    #   - closing bridged in background texture: usually inflates AREA more
    #     than LENGTH (a blobby patch gets absorbed, not a coherent strand),
    #     so length_frac and area_frac disagree.
    #   - a second worm entering the frame and touching/crossing the
    #     tracked one: BOTH length and area jump together, roughly
    #     proportionally, since a second animal's own length and area both
    #     get added to the connected blob. This is not resolvable by
    #     adjusting thresholds, geometry alone can't say which pixels
    #     belong to which worm. It needs the same answer pBoc already uses
    #     for exactly this situation: a human marks the intruder's entry
    #     frame, a rough centerline, and exit frame, and those frames are
    #     excluded from the tracked worm's automated measurement rather
    #     than algorithmically disentangled.
    OVERSIZE_MULT = 1.3
    COLLISION_MULT = 1.4    # both dimensions jump together, above this
    oversized = ((not np.isnan(length_frac) and length_frac > OVERSIZE_MULT) or
                 (not np.isnan(area_frac) and area_frac > OVERSIZE_MULT))
    likely_collision = (not np.isnan(length_frac) and not np.isnan(area_frac)
                         and length_frac > COLLISION_MULT and area_frac > COLLISION_MULT)

    length_ok = np.isnan(length_frac) or length_tol <= length_frac <= OVERSIZE_MULT
    area_ok = np.isnan(area_frac) or area_tol <= area_frac <= OVERSIZE_MULT

    if likely_collision and not edges:
        return FrameEval(frame_index, "possible_collision", length_frac,
                          area_frac, width_frac,
                          note="length AND area both substantially larger than "
                               "calibration together, not touching an edge; "
                               "consistent with a second worm entering and "
                               "touching/crossing the tracked animal, not a "
                               "coil or a segmentation artifact. Needs a human "
                               "to mark the intruder (entry frame, rough "
                               "centerline, exit frame), same as pBoc's "
                               "distractor annotation; not algorithmically "
                               "resolvable from geometry alone.")

    if oversized and not edges:
        return FrameEval(frame_index, "degraded", length_frac, area_frac,
                          width_frac,
                          note="implausibly larger than calibration and not "
                               "touching an edge; likely closing bridged in "
                               "background texture or a second object")

    if length_ok and area_ok:
        return FrameEval(frame_index, "full_view", length_frac, area_frac,
                          width_frac, visible_fraction_est=1.0,
                          note="within calibrated length/area tolerance")

    if edges:
        # shorter than calibration AND touching an edge: consistent with
        # the animal partially exiting the field. Conserved length means
        # the deficit is off-frame, not gone.
        vis_frac = float(np.nanmin([length_frac, 1.0])) if not np.isnan(length_frac) else float("nan")
        return FrameEval(frame_index, "partial_out_of_frame", length_frac,
                          area_frac, width_frac, visible_fraction_est=vis_frac,
                          exit_edges=edges,
                          note=f"shorter than calibration and touching {edges}; "
                               f"~{vis_frac:.0%} of body estimated visible" if not np.isnan(vis_frac) else
                               "shorter than calibration and touching frame edge")

    # shorter than calibration but NOT touching an edge, and not matching the
    # coil signature above: length shouldn't change on its own, so this is a
    # segmentation problem, not a real exit
    return FrameEval(frame_index, "degraded", length_frac, area_frac, width_frac,
                      note="shorter than calibration but not touching any edge "
                           "and not matching the coil width signature; likely "
                           "a segmentation failure (low contrast, closing gap), "
                           "not a real animal event")


# ---------------------------------------------------------------------------
# Movie-level recoverability: contiguous runs, not a single pass/fail label
# ---------------------------------------------------------------------------
def summarize_recoverability(frame_evals, usable_statuses=("full_view", "partial_out_of_frame")):
    """Report contiguous usable runs (cycles), same principle as
    Single-worm swimming analysis's usable-coverage/contiguous-run
    reporting: a whole-movie average can conceal missing or fragmented
    data, so runs are reported explicitly instead of being collapsed."""
    runs = []
    current_start = None
    for i, fe in enumerate(frame_evals):
        usable = fe.status in usable_statuses
        if usable and current_start is None:
            current_start = i
        elif not usable and current_start is not None:
            runs.append((current_start, i - 1))
            current_start = None
    if current_start is not None:
        runs.append((current_start, len(frame_evals) - 1))

    runs_sorted = sorted(runs, key=lambda r: r[1] - r[0], reverse=True)
    n_usable = sum(1 for fe in frame_evals if fe.status in usable_statuses)
    n_full = sum(1 for fe in frame_evals if fe.status == "full_view")

    return {
        "n_frames_evaluated": len(frame_evals),
        "n_usable_frames": n_usable,
        "n_full_view_frames": n_full,
        "usable_fraction": n_usable / len(frame_evals) if frame_evals else float("nan"),
        "n_contiguous_usable_runs": len(runs),
        "longest_usable_run_frames": (runs_sorted[0][1] - runs_sorted[0][0] + 1) if runs_sorted else 0,
        "usable_runs": [(s, e, e - s + 1) for s, e in runs_sorted],
    }


# ---------------------------------------------------------------------------
# End-to-end convenience for a video file
# ---------------------------------------------------------------------------
def evaluate_movie_recoverability(video_path, calib=None, calib_frame_index=0,
                                   stride=1, max_frames=None, seg_kwargs=None):
    """calib: pre-computed calibration dict (e.g. from calibrate_from_polygon,
    i.e. a real human-traced outline). If None, auto-calibrates from
    calib_frame_index (unconfirmed, triage-only, see
    calibrate_from_auto_segmentation)."""
    seg_kwargs = seg_kwargs or {}
    cap = cv2.VideoCapture(str(video_path))
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    if calib is None:
        cap.set(cv2.CAP_PROP_POS_FRAMES, calib_frame_index)
        ok, frame = cap.read()
        if not ok:
            cap.release()
            return {"file": Path(video_path).name, "status": "unreadable"}
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        calib = calibrate_from_auto_segmentation(gray, **seg_kwargs)
        if calib is None:
            cap.release()
            return {"file": Path(video_path).name, "status": "no_calibration",
                     "note": "auto-segmentation found nothing on calibration frame"}

    idxs = list(range(0, n_frames, stride))
    if max_frames:
        idxs = idxs[:max_frames]

    frame_evals = []
    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
    for count, idx in enumerate(idxs):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            frame_evals.append(FrameEval(count, "lost", note="frame read failed"))
            continue
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = flatten_and_segment(gray, **seg_kwargs)
        frame_evals.append(evaluate_frame(mask, calib, frame_index=count))
    cap.release()

    summary = summarize_recoverability(frame_evals)
    summary["file"] = Path(video_path).name
    summary["calibration_source"] = calib.get("source", "unknown")
    return summary


# ---------------------------------------------------------------------------
# Sessions: mark where one continuous, single-identity stretch starts and
# ends, and where the next one begins. This is the answer to a folder or
# recording that contains more than one worm, or a worm plus a temporary
# intruder: a session is calibrated and evaluated completely on its own, so
# nothing from one identity leaks into another's conserved-length
# comparison. Boundaries are a human decision (a worm leaving, a new one
# being picked up, an identity change after a collision resolves), not
# something inferred silently from pixel statistics; suggest_session_
# boundaries() below is a review aid for finding candidates, not an
# auto-decider.
# ---------------------------------------------------------------------------
class FrameSource:
    """Wraps either a video file or a sorted folder of image stills behind
    one interface, so session logic doesn't care which it's given."""

    def __init__(self, path, pattern="*.tif"):
        self.path = Path(path)
        if self.path.is_dir():
            self.kind = "images"
            self.files = sorted(self.path.glob(pattern))
            self.n_frames = len(self.files)
        else:
            self.kind = "video"
            self._cap = cv2.VideoCapture(str(self.path))
            self.n_frames = int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT))

    def get_gray(self, idx):
        if self.kind == "images":
            if idx < 0 or idx >= len(self.files):
                return None
            arr = np.array(Image.open(self.files[idx]))
            if arr.ndim == 3:
                # green channel by convention for these GCaMP captures;
                # adjust here if a given dataset's channel order differs
                return arr[..., 1] if arr.shape[2] >= 2 else arr[..., 0]
            return arr
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self._cap.read()
        if not ok:
            return None
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    def label(self, idx):
        if self.kind == "images" and 0 <= idx < len(self.files):
            return self.files[idx].name
        return f"frame_{idx}"


@dataclass
class Session:
    start: int
    end: int              # inclusive
    label: str = ""
    calib_frame: int = None  # defaults to `start` if not given


def define_sessions(boundaries):
    """boundaries: list of (start, end) inclusive frame-index tuples, e.g.
    [(0, 40), (48, 104)]. Marking session start/end is the same kind of
    action as marking a track's usable interval elsewhere in the Hub."""
    return [Session(start=s, end=e, label=f"session_{i + 1}")
            for i, (s, e) in enumerate(boundaries)]


def suggest_session_boundaries(frame_source, stride=1, jump_mult=1.8):
    """Review aid, not a decision-maker: scan consecutive sampled frames'
    area for jumps large enough to be unlikely as the same animal
    continuing to move or bend, and return candidate cut points for a
    human to confirm or reject before defining real sessions. A gradual
    change (bending, slowly exiting frame) should not trigger this; only
    an abrupt jump between adjacent sampled frames should."""
    idxs = list(range(0, frame_source.n_frames, stride))
    areas = []
    for idx in idxs:
        gray = frame_source.get_gray(idx)
        if gray is None:
            areas.append(None)
            continue
        mask = flatten_and_segment(gray)
        areas.append(int(mask.sum()) if mask is not None else None)

    candidates = []
    for i in range(1, len(areas)):
        a0, a1 = areas[i - 1], areas[i]
        if a0 is None or a1 is None or a0 == 0:
            continue
        ratio = max(a1 / a0, a0 / a1)
        if ratio >= jump_mult:
            candidates.append({
                "between_frame_indices": (idxs[i - 1], idxs[i]),
                "between_labels": (frame_source.label(idxs[i - 1]),
                                   frame_source.label(idxs[i])),
                "area_ratio": round(ratio, 2),
            })
    return candidates


def run_session(frame_source, session, calib=None, seg_kwargs=None, stride=1):
    seg_kwargs = seg_kwargs or {}
    calib_idx = session.calib_frame if session.calib_frame is not None else session.start

    if calib is None:
        gray = frame_source.get_gray(calib_idx)
        if gray is None:
            return {"session": session.label, "status": "unreadable_calibration_frame"}
        calib = calibrate_from_auto_segmentation(gray, **seg_kwargs)
        if calib is None:
            return {"session": session.label, "status": "no_calibration",
                    "note": f"auto-segmentation found nothing on calibration "
                            f"frame {frame_source.label(calib_idx)}"}

    frame_evals = []
    idxs = list(range(session.start, session.end + 1, stride))
    for count, idx in enumerate(idxs):
        gray = frame_source.get_gray(idx)
        if gray is None:
            frame_evals.append(FrameEval(count, "lost",
                                          note=f"frame read failed at {frame_source.label(idx)}"))
            continue
        mask = flatten_and_segment(gray, **seg_kwargs)
        frame_evals.append(evaluate_frame(mask, calib, frame_index=count))

    summary = summarize_recoverability(frame_evals)
    summary["session"] = session.label
    summary["frame_index_range"] = (session.start, session.end)
    summary["calibration_frame"] = frame_source.label(calib_idx)
    summary["calibration_source"] = calib.get("source", "unknown")
    summary["frame_evals"] = [
        {"frame_index": fe.frame_index, "status": fe.status,
         "length_frac": fe.length_frac, "area_frac": fe.area_frac,
         "width_frac": fe.width_frac, "note": fe.note}
        for fe in frame_evals
    ]
    return summary


def run_sessions(frame_source, sessions, seg_kwargs=None, stride=1):
    """Each session gets its own calibration and its own evaluation, fully
    independent of every other session. This is the actual fix for the
    problem discovered earlier: one calibration silently applied across a
    folder containing different worms produced meaningless comparisons.
    Sessions are how a human tells the tool where those boundaries are."""
    return [run_session(frame_source, s, seg_kwargs=seg_kwargs, stride=stride)
            for s in sessions]


def parse_sessions_arg(s):
    """'0-40,48-104' -> [(0,40),(48,104)]"""
    boundaries = []
    for part in s.split(","):
        a, b = part.split("-")
        boundaries.append((int(a), int(b)))
    return boundaries


def generate_review_contact_sheet(frame_source, out_path, stride=1,
                                   cols=7, thumb_dpi=90, frames_per_page=None,
                                   rows_per_page=7):
    """Labeled grid(s) of contrast-stretched thumbnails, frame index/filename
    under each, for fast manual session-boundary marking on historical
    data with no organizational metadata: scan the grid, note where the
    identity visibly changes (size, pose discontinuity, a new animal),
    and turn those observations directly into --sessions ranges. This
    replaces opening files one at a time to make the same decision.
    Does not choose boundaries itself; suggest_session_boundaries() is
    the (weak) automatic signal, this is the actual practical path for
    a human to decide quickly.

    For large batches this paginates: frames_per_page (default
    cols * rows_per_page) go on each page, written as
    '{out_path stem}_pXX{suffix}'. A boundary that happens to fall right
    at a page break is still visible, each page's last thumbnail and the
    next page's first thumbnail are the adjacent frames, so nothing is
    hidden by the split, it's purely a rendering/file-size convenience.
    Returns the list of written page paths.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    out_path = Path(out_path)
    idxs = list(range(0, frame_source.n_frames, stride))
    if frames_per_page is None:
        frames_per_page = cols * rows_per_page

    pages = [idxs[i:i + frames_per_page]
             for i in range(0, len(idxs), frames_per_page)]
    written = []

    for page_num, page_idxs in enumerate(pages, start=1):
        rows = (len(page_idxs) + cols - 1) // cols
        fig, axes = plt.subplots(rows, cols, figsize=(3 * cols, 3 * rows))
        axes = np.atleast_1d(axes).flatten()

        for ax, idx in zip(axes, page_idxs):
            gray = frame_source.get_gray(idx)
            if gray is None:
                ax.set_title(f"[{idx}] unreadable")
                ax.axis("off")
                continue
            p99 = np.percentile(gray, 99.9)
            stretched = np.clip(gray.astype(float) / max(p99, 1) * 255, 0, 255).astype(np.uint8)
            ax.imshow(stretched, cmap="gray")
            ax.set_title(f"[{idx}] {frame_source.label(idx)}", fontsize=9)
            ax.axis("off")
        for ax in axes[len(page_idxs):]:
            ax.axis("off")

        if len(pages) > 1:
            fig.suptitle(f"page {page_num}/{len(pages)}  "
                         f"(frames {page_idxs[0]}-{page_idxs[-1]} of {frame_source.n_frames - 1})",
                         fontsize=11)
            page_path = out_path.with_name(f"{out_path.stem}_p{page_num:02d}{out_path.suffix}")
        else:
            page_path = out_path

        plt.tight_layout()
        plt.savefig(page_path, dpi=thumb_dpi)
        plt.close(fig)
        written.append(page_path)

    return written


if __name__ == "__main__":
    import argparse
    import json

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="video file OR folder of image stills")
    ap.add_argument("--pattern", default="*.tif",
                     help="glob pattern when source is a folder of stills")
    ap.add_argument("--stride", type=int, default=1)
    ap.add_argument("--sessions", type=str, default=None,
                     help="mark session boundaries as 'start-end,start-end,...' "
                          "frame indices, inclusive, e.g. '0-40,48-104'. Each "
                          "session is calibrated and evaluated independently. "
                          "If omitted, the whole source is treated as one "
                          "session (0 to last frame) -- only appropriate when "
                          "you already know it's a single continuous identity.")
    ap.add_argument("--calib-frame", type=int, default=None,
                     help="frame index to calibrate from, within each session "
                          "(defaults to that session's start frame)")
    ap.add_argument("--contact-sheet", type=str, default=None,
                     help="write a labeled thumbnail grid to this path and "
                          "exit, for eyeballing session boundaries on "
                          "historical data with no organizational metadata")
    ap.add_argument("--frames-per-page", type=int, default=None,
                     help="paginate the contact sheet at this many frames "
                          "per page (default: cols x 7); large folders "
                          "otherwise produce one unwieldy image")
    args = ap.parse_args()

    fs = FrameSource(args.source, pattern=args.pattern)

    if args.contact_sheet:
        pages = generate_review_contact_sheet(
            fs, args.contact_sheet, stride=args.stride,
            frames_per_page=args.frames_per_page)
        if len(pages) == 1:
            print(f"Wrote contact sheet to {pages[0]} ({fs.n_frames} frames). "
                  f"Pick boundaries by eye, then rerun with --sessions.")
        else:
            print(f"Wrote {len(pages)} contact sheet pages for {fs.n_frames} frames:")
            for p in pages:
                print(f"  {p}")
            print("Pick boundaries by eye across pages, then rerun with --sessions.")
        raise SystemExit(0)

    if args.sessions:
        boundaries = parse_sessions_arg(args.sessions)
    else:
        boundaries = [(0, fs.n_frames - 1)]
    sessions = define_sessions(boundaries)
    if args.calib_frame is not None:
        for s in sessions:
            s.calib_frame = args.calib_frame

    results = run_sessions(fs, sessions, stride=args.stride)
    print(json.dumps(results, indent=2, default=str))
