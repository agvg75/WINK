"""Measure a short test recording, so the acquisition check has real numbers.

`acquisition_check.check()` decides whether a recording supports a given
measurement, but it decides from DECLARED numbers - the frame rate and scale
someone typed into a form. Those are exactly the numbers that go wrong. A
recording captured at 7.5 fps and written with a 30 fps header, analysed at a
declared 2 um/px when the truth was nearer 10, reported 1.17 Hz and 124 um/s
for animals that were actually near 0.29 Hz and 155 um/s. Nothing objected,
because nothing had looked at the pixels.

This module looks at the pixels. It measures what can be measured from the
recording itself - how long the animals actually are, how much of the sensor
range is in use, whether the frame is in focus - and hands those to the
check instead of taking someone's word for it.

WHAT IT DELIBERATELY DOES NOT DO. It does not measure frame rate from a folder
of images, because the files do not carry one and file timestamps record when
they were written rather than when they were exposed. For a video it reads the
header and says so, since a header is a claim too.

THE BODY LENGTH IS MEASURED WITHOUT A SCALE, on purpose. Length in pixels is
what every floor in acquisition_check is written against, and it is knowable
from the image alone. Bringing um/px into it would make the one solid
measurement depend on the declared number most likely to be wrong.
"""
from __future__ import annotations

from math import sqrt
from pathlib import Path

import cv2
import numpy as np

# Objects are selected relative to each other rather than against a pixel
# count, so this works at any magnification. The animals are the largest
# moving objects in a plate recording; debris is smaller by a wide margin.
LARGEST_FRACTION = 0.50       # "large" means this fraction of the biggest
KEEP_BAND = (0.40, 2.50)      # x the median of the large objects
MIN_OBJECTS_FOR_LENGTH = 3
SATURATION_TOLERANCE = 0.01   # 1% of pixels at full scale is already a lot


def _elongated_length_px(area, perimeter):
    """Length of a long thin object from its area and perimeter.

    Treats the animal as a bent rectangle: P ~ 2(L+W) and A ~ LW, so L is the
    larger root of L^2 - (P/2)L + A = 0. Better than a bounding box, which
    collapses as soon as the animal curls - and a curled animal is the normal
    case, not the exception.
    """
    disc = perimeter * perimeter - 16.0 * area
    if disc <= 0:
        return None          # too round to be a worm at this magnification
    return (perimeter + sqrt(disc)) / 4.0


def _illumination(gray_u8):
    """The frame with the animals removed, estimated from the frame itself.

    A median blur wider than an animal is thick keeps uneven illumination and
    discards anything narrow, so subtracting it leaves the animals whatever
    their polarity against the agar.

    THIS REPLACED A TEMPORAL MEDIAN, which fails on precisely the recording
    this module exists to read. A crawling animal covers about a quarter of a
    body length per second; over a ten second test clip it barely leaves its
    own outline, so a median across frames CONTAINS the animals and
    subtracting it leaves only the undulating edges. Measured on a fixture of
    160 px animals: the temporal version reported 55 px and ten objects per
    frame where there were five. Motion is not available in a short clip and
    must not be required.
    """
    h, w = gray_u8.shape[:2]
    k = int(min(h, w) / 10) | 1
    return cv2.medianBlur(gray_u8, max(9, min(k, 61)))


def _frame_indices(n, wanted):
    if n <= wanted:
        return list(range(n))
    return list(np.unique(np.linspace(0, n - 1, wanted).astype(int)))


def measure_body_length_px(gray_frames, *, background=None):
    """Median animal length in pixels, measured from the segmentation itself.

    Returns (length_px, detail). `length_px` is None when too few elongated
    objects were found to take a median of - which is itself a finding, and
    usually means the animals are too small to segment or nothing moved.
    """
    stack = [np.asarray(f, dtype=np.uint8) for f in gray_frames]
    lengths, per_frame_counts, areas_seen = [], [], []

    for frame in stack:
        bg = _illumination(frame) if background is None else np.asarray(
            background, dtype=np.uint8)
        diff = cv2.GaussianBlur(cv2.absdiff(frame, bg), (3, 3), 0)
        if diff.max() < 3:
            per_frame_counts.append(0)
            continue
        _, mask = cv2.threshold(diff, 0, 255,
                                cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Speckle has to go before anything is measured from shape: a
        # perimeter is enormously sensitive to a ragged edge, and the length
        # below is computed from one.
        mask = cv2.morphologyEx(
            mask, cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
        count, _, stats, _ = cv2.connectedComponentsWithStats(mask)
        areas = np.array([stats[i, cv2.CC_STAT_AREA] for i in range(1, count)])
        if not len(areas):
            per_frame_counts.append(0)
            continue
        # Self-calibrating selection: the animals are the largest moving
        # objects, and "large" is defined against the LARGEST object in this
        # same frame. Defining it against a count instead - the median of the
        # top twenty, say - breaks whenever there are fewer animals than that,
        # because the median is then mostly debris and the animals get
        # rejected as outliers. Measured on a five-animal fixture: 160 px
        # animals were reported as 59 px.
        biggest = float(areas.max())
        typical = float(np.median(areas[areas >= LARGEST_FRACTION * biggest]))
        keep = (areas >= typical * KEEP_BAND[0]) & (areas <= typical * KEEP_BAND[1])
        per_frame_counts.append(int(keep.sum()))
        areas_seen.extend(areas[keep].tolist())

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_NONE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if not (typical * KEEP_BAND[0] <= area <= typical * KEEP_BAND[1]):
                continue
            length = _elongated_length_px(area, cv2.arcLength(contour, True))
            if length:
                lengths.append(length)

    detail = {
        "n_length_samples": len(lengths),
        "objects_per_frame": (round(float(np.mean(per_frame_counts)), 1)
                              if per_frame_counts else 0.0),
        "median_object_area_px": (round(float(np.median(areas_seen)), 1)
                                  if areas_seen else None),
    }
    if len(lengths) < MIN_OBJECTS_FOR_LENGTH:
        detail["note"] = (
            "Too few elongated moving objects to measure a length. Either the "
            "animals are too small to segment at this magnification, or "
            "nothing moved between the sampled frames.")
        return None, detail
    detail["length_spread_px"] = round(
        float(np.percentile(lengths, 90) - np.percentile(lengths, 10)), 1)
    return float(np.median(lengths)), detail


# A directional shadow is deliberate lab technique for pumping and defecation,
# chosen for contrast, so it is a property of the ASSAY rather than of the rig
# on a given day. Its absence on a recording intended for those readouts should
# be caught at the scope, not discovered at analysis.
SHADOW_MIN_CONSISTENCY = 0.55     # resultant length of the direction vectors
SHADOW_MIN_CONTRAST = 12.0        # counts between the lit and shadow sides
SHADOW_OFFSET_PX = 30


def texture_foreground(gray, *, percentile=95.5, close=31):
    """The animal, by fine texture. See motion signature spec 5.4.0.

    A bacterial lawn has broad topography and no fine structure; the animal has
    cuticle striation. Intensity and relief both fail here because the lawn has
    plenty of both.
    """
    f = np.asarray(gray, dtype=np.float32)
    span = float(f.max() - f.min())
    if span < 1:
        return None
    f = (f - f.min()) / span * 255.0
    band = (cv2.GaussianBlur(f, (0, 0), 1.0)
            - cv2.GaussianBlur(f, (0, 0), 3.0))
    energy = cv2.GaussianBlur(np.abs(band), (0, 0), 6.0)
    mask = (energy >= np.percentile(energy, percentile)).astype(np.uint8) * 255
    mask = cv2.morphologyEx(
        mask, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close, close)))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count < 2:
        return None
    best = 1 + int(np.argmax([stats[i, cv2.CC_STAT_AREA]
                              for i in range(1, count)]))
    return (labels == best).astype(np.uint8), f


def measure_shadow(gray, *, offset=SHADOW_OFFSET_PX):
    """Direction and strength of the shadow cast beside the animal.

    Samples the raw image a fixed distance either side of the body midline,
    perpendicular to the LOCAL body axis, and averages the direction pointing
    toward the darker side.

    Returns azimuth in image convention - 0 = shadow to the right, 90 = below,
    180 = left, 270 = above - plus `consistency`, the resultant length of those
    directions. Consistency near 1 means every sample agreed; near 0 means
    there is no directional shadow at all, which is a finding rather than a
    failure: an animal immersed in an OP50 lawn casts little shadow under
    oblique light.
    """
    from skimage.morphology import skeletonize

    found = texture_foreground(gray)
    if found is None:
        return None
    worm, f = found
    if worm.sum() < 4000:
        return None
    skel = skeletonize(worm > 0)
    ys, xs = np.nonzero(skel)
    if len(ys) < 40:
        return None
    pts = np.stack([xs, ys], 1).astype(float)
    height, width = f.shape
    vectors = []
    for k in range(0, len(pts), 3):
        p = pts[k]
        near = pts[np.hypot(*(pts - p).T) < 12]
        if len(near) < 5:
            continue
        centred = near - near.mean(0)
        u, _, _ = np.linalg.svd(centred.T @ centred / len(near))
        perp = np.array([-u[1, 0], u[0, 0]])
        a = np.round(p + perp * offset).astype(int)
        b = np.round(p - perp * offset).astype(int)
        if not (0 <= a[0] < width and 0 <= a[1] < height
                and 0 <= b[0] < width and 0 <= b[1] < height):
            continue
        delta = float(f[a[1], a[0]] - f[b[1], b[0]])
        if abs(delta) < 2:
            continue
        vectors.append(perp * (-1 if delta > 0 else 1) * abs(delta))
    if len(vectors) < 10:
        return None
    V = np.array(vectors)
    strength = np.linalg.norm(V, axis=1)
    unit = V / np.clip(strength[:, None], 1e-9, None)
    mean = unit.mean(0)
    consistency = float(np.linalg.norm(mean))
    azimuth = float(np.degrees(np.arctan2(mean[1], mean[0]))) % 360
    contrast = float(np.median(strength))
    directional = (consistency >= SHADOW_MIN_CONSISTENCY
                   and contrast >= SHADOW_MIN_CONTRAST)
    return {
        "azimuth_deg": round(azimuth, 1),
        "direction": _compass(azimuth),
        "consistency": round(consistency, 3),
        "contrast": round(contrast, 1),
        "directional": directional,
        "n_samples": len(vectors),
    }


def measure_shadow_over_frames(gray_frames, *, limit=25):
    """Shadow direction pooled across frames. ONE FRAME IS NOT ENOUGH.

    Measured on the pezo-1 CRISPR set: a single frame of `41921_cop1367` gave
    146 degrees at consistency 0.56, while pooling 25 frames of the same
    recording gave 94 degrees at 0.86. A single posture puts most of the body
    at one angle, so the perpendicular samples are correlated and the estimate
    inherits the animal's shape rather than the lighting.
    """
    per_frame = []
    for frame in list(gray_frames)[:limit]:
        result = measure_shadow(frame)
        if result:
            per_frame.append(result)
    if not per_frame:
        return None
    angles = np.radians([p["azimuth_deg"] for p in per_frame])
    mx, my = float(np.cos(angles).mean()), float(np.sin(angles).mean())
    consistency = float(np.hypot(mx, my))
    azimuth = float(np.degrees(np.arctan2(my, mx))) % 360
    contrast = float(np.median([p["contrast"] for p in per_frame]))
    return {
        "azimuth_deg": round(azimuth, 1),
        "direction": _compass(azimuth),
        "consistency": round(consistency, 3),
        "contrast": round(contrast, 1),
        "directional": (consistency >= SHADOW_MIN_CONSISTENCY
                        and contrast >= SHADOW_MIN_CONTRAST),
        "n_frames": len(per_frame),
    }


def _compass(angle):
    names = [(0, "right"), (45, "below-right"), (90, "below"),
             (135, "below-left"), (180, "left"), (225, "above-left"),
             (270, "above"), (315, "above-right")]
    return min(names, key=lambda t: min(abs(angle - t[0]),
                                        360 - abs(angle - t[0])))[1]


# A textureless background is plain agar or liquid. Worms neither pump nor
# defecate without food, so those readouts were never possible there - which
# makes substrate a CHEAP ELIGIBILITY GATE rather than a segmentation detail.
# Measured at the LAWN'S OWN SCALE, which is its wrinkles - not at the
# animal's cuticle scale, and not at the sensor-noise scale. Separation on the
# frozen six: lawns score 17.6 to 31.9, a worm off food scores 4.71.
SUBSTRATE_SIGMA = (6.0, 24.0)
SUBSTRATE_TEXTURE_MIN = 10.0


def detect_substrate(gray_frames, *, limit=8):
    """Lawn or not, from background texture. An eligibility gate, not a hint.

    The reasoning, which is what makes this cheap and reliable:

    * Worms do not pump or defecate without food.
    * So neither readout occurs on plain agar or in liquid.
    * Neither of those provides background texture.
    * The texture foreground rule needs a lawn, and pumping and defecation
      only happen on a lawn.

    So the rule is available exactly where those readouts exist. There is no
    coverage gap and no preparation-aware selector is needed.

    The consequence for the schema matters more than the detection: on a
    textureless background pumping and defecation get **present = null**, not
    present = false. The recording could not support the observation, so its
    silence is not evidence about the animal, and it never enters the eligible
    pool. That is the section 8 distinction, derived from the substrate rather
    than from looking and failing to find anything.
    """
    scores = []
    for frame in list(gray_frames)[:limit]:
        f = np.asarray(frame, dtype=np.float32)
        span = float(f.max() - f.min())
        if span < 1:
            continue
        lo, hi = np.percentile(f, [1, 99])
        f = (f - lo) / max(float(hi - lo), 1.0) * 255.0
        # THE SCALE MATTERS AS MUCH AS THE MEASURE. Two earlier versions were
        # wrong at this line. Sensor noise lives at sigma 1-3 and BOTH
        # substrates have it, so measuring there separates nothing: lawns
        # scored 1.44-1.64 against 1.24 off food. The lawn's own structure is
        # its wrinkles, at sigma 6-24, where the same recordings score
        # 17.6-31.9 against 4.71.
        structure = np.abs(
            cv2.GaussianBlur(f, (0, 0), SUBSTRATE_SIGMA[0])
            - cv2.GaussianBlur(f, (0, 0), SUBSTRATE_SIGMA[1]))
        # MEASURE THE BACKGROUND, WITH THE ANIMAL REMOVED. The animal is the
        # most finely textured thing in any of these frames, so including it
        # measures the worm rather than the substrate.
        found = texture_foreground(f)
        background = np.ones(f.shape, bool)
        if found is not None:
            worm = cv2.dilate(found[0], np.ones((41, 41), np.uint8))
            background = worm == 0
        if background.sum() < f.size * 0.2:
            continue
        # ABSOLUTE energy, not a ratio to a coarser band. An earlier version
        # divided fine by coarse, which INVERTS on the case this gate exists
        # for: a textureless background has almost no coarse energy either, so
        # the quotient explodes. Measured on a worm off food, that version
        # scored 148 where the lawns scored 17 - the highest score of the six
        # went to the one recording with no lawn at all.
        scores.append(float(np.percentile(structure[background], 90)))
    if not scores:
        return None
    score = float(np.median(scores))
    textured = score >= SUBSTRATE_TEXTURE_MIN
    return {
        "texture_score": round(score, 2),
        "threshold": SUBSTRATE_TEXTURE_MIN,
        "substrate": "lawn" if textured else "textureless",
        "textured": textured,
        "supports_feeding_readouts": textured,
        "note": ("Background carries fine texture, consistent with a bacterial "
                 "lawn. Pumping and defecation are possible here."
                 if textured else
                 "Background is textureless, so this is plain agar or liquid. "
                 "Worms do not pump or defecate without food, so those "
                 "readouts were NEVER POSSIBLE in this recording. They must "
                 "be reported as present = null, not present = false - the "
                 "recording could not support the observation, and its "
                 "silence is not evidence about the animal."),
    }


# Tip extension. The stopping rule is deliberately tight, because the tail is
# where the animal's texture is weakest and an over-eager extension runs off
# into the substrate exactly where the evidence is thinnest.
TIP_STEP_PX = 3.0
TIP_MAX_STEPS = 40
TIP_MIN_RATIO = 1.6        # x the background's own fine energy
TIP_PATIENCE = 2           # consecutive failing steps before stopping


def _skeleton_ends(worm, *, prune=12):
    """Midline points and its TRUE ends, with spurs pruned first.

    A skeleton of any real outline sprouts short spurs from boundary
    irregularities, and each one is an endpoint. Counting ends without pruning
    reports a clean single animal as branched - measured on `5521_cop1524`,
    which is a whole animal traced correctly and reported three ends.

    Pruning shortens every branch equally, so genuine ends survive and spurs
    below `prune` pixels vanish.
    """
    from skimage.morphology import skeletonize
    skel = skeletonize(worm > 0)
    if skel.sum() < 20:
        return None, None
    kernel = np.ones((3, 3), np.uint8)
    pruned = skel.astype(np.uint8)
    for _ in range(int(prune)):
        neighbours = cv2.filter2D(pruned, -1, kernel,
                                  borderType=cv2.BORDER_CONSTANT) - pruned
        tips = (pruned > 0) & (neighbours <= 1)
        if not tips.any():
            break
        pruned[tips] = 0
    if pruned.sum() < 10:
        pruned = skel.astype(np.uint8)      # pruned everything; keep the raw
    ys, xs = np.nonzero(pruned)
    pts = np.stack([xs, ys], 1).astype(float)
    neighbours = cv2.filter2D(pruned, -1, kernel,
                              borderType=cv2.BORDER_CONSTANT) - pruned
    end_mask = (pruned > 0) & (neighbours <= 1)
    ey, ex = np.nonzero(end_mask)
    ends = np.stack([ex, ey], 1).astype(float)
    return pts, ends


def extend_tips(gray, worm, *, step=TIP_STEP_PX, max_steps=TIP_MAX_STEPS):
    """Grow the mask along the body axis while the animal's texture persists.

    THE STOPPING BAND IS NOT THE SUBSTRATE BAND. The lawn's wrinkles live at
    sigma 6-24, which is what `detect_substrate` measures. Extending on that
    band would walk straight into the substrate, and would do so at the tail
    where the animal's own signal is weakest. This tests the FINE band, sigma
    1-3, where the lawn is quiet and the cuticle is not.

    The threshold is the background's own fine energy times TIP_MIN_RATIO, so
    it adapts per recording rather than being a fixed number.

    Returns (extended_mask, detail). `detail` records how far each end grew,
    because **a length that is mostly extension must be visibly different from
    one that is mostly measured** and extension must never enter
    `body_length_px` silently.
    """
    f = np.asarray(gray, dtype=np.float32)
    span = float(f.max() - f.min())
    if span < 1:
        return worm, {"extended_px": [], "extension_total_px": 0.0}
    f = (f - f.min()) / span * 255.0
    fine = cv2.GaussianBlur(
        np.abs(cv2.GaussianBlur(f, (0, 0), 1.0)
               - cv2.GaussianBlur(f, (0, 0), 3.0)), (0, 0), 4.0)
    outside = cv2.dilate(worm, np.ones((61, 61), np.uint8)) == 0
    if outside.sum() < 1000:
        return worm, {"extended_px": [], "extension_total_px": 0.0}
    floor = float(np.percentile(fine[outside], 95)) * TIP_MIN_RATIO

    pts, ends = _skeleton_ends(worm)
    if pts is None or len(ends) == 0:
        return worm, {"extended_px": [], "extension_total_px": 0.0,
                      "note": "no skeleton endpoints to extend from"}
    dist = cv2.distanceTransform(worm, cv2.DIST_L2, 5)
    radius = max(3.0, float(np.median(dist[dist > 0])))
    grown = worm.copy()
    height, width = worm.shape
    per_end = []
    for end in ends[:2]:
        near = pts[np.hypot(*(pts - end).T) < 25]
        if len(near) < 4:
            per_end.append(0.0)
            continue
        direction = end - near.mean(0)
        norm = np.linalg.norm(direction)
        if norm < 1e-6:
            per_end.append(0.0)
            continue
        direction = direction / norm
        travelled, misses = 0.0, 0
        for _ in range(max_steps):
            probe_at = end + direction * (travelled + step)
            x, y = int(round(probe_at[0])), int(round(probe_at[1]))
            if not (0 <= x < width and 0 <= y < height):
                break
            patch = fine[max(0, y - 3):y + 4, max(0, x - 3):x + 4]
            if patch.size and float(patch.max()) >= floor:
                travelled += step
                misses = 0
                cv2.circle(grown, (x, y), int(round(radius)), 1, -1)
            else:
                misses += 1
                if misses >= TIP_PATIENCE:
                    break
                travelled += step
        per_end.append(round(travelled, 1))
    grown = cv2.morphologyEx(grown, cv2.MORPH_CLOSE,
                             np.ones((7, 7), np.uint8))
    return grown, {
        "extended_px": per_end,
        "extension_total_px": round(float(sum(per_end)), 1),
        "fine_energy_floor": round(floor, 2),
    }


def posture_flags(worm, *, border=2):
    """Reasons this animal cannot be measured, rather than a repaired number.

    Two exclusions, both of which currently produce believable wrong lengths:

    * **Off frame.** Part of the animal is outside the field, so any length is
      a length of the visible part. Not repairable.
    * **Self-overlapping.** A hairpin or omega whose limbs the mask has
      bridged. The traced distance is then the doubled path, not a body
      length. Detected from local width: where two limbs merge the distance
      transform is far above the body's own median.
    """
    height, width = worm.shape
    ys, xs = np.nonzero(worm)
    if not len(ys):
        return {"measurable": False, "reasons": ["no animal"]}
    touches = (xs.min() <= border or ys.min() <= border
               or xs.max() >= width - 1 - border
               or ys.max() >= height - 1 - border)
    dist = cv2.distanceTransform(worm, cv2.DIST_L2, 5)
    pts, ends = _skeleton_ends(worm)
    widths = None
    fat_fraction = 0.0
    if pts is not None:
        widths = 2.0 * dist[pts[:, 1].astype(int), pts[:, 0].astype(int)]
        typical = float(np.median(widths[widths > 0]))
        fat_fraction = float(np.mean(widths > typical * 1.7)) if typical else 0
    reasons = []
    if touches:
        reasons.append("the animal touches the frame edge, so part of it is "
                       "out of view and any length is a length of the visible "
                       "part")
    if fat_fraction > 0.08:
        reasons.append(f"{fat_fraction:.0%} of the midline is more than 1.7x "
                       f"the body's own width, which is two limbs of a "
                       f"self-overlapping posture merged by the mask - the "
                       f"traced distance is a doubled path, not a length")
    # END COUNT IS NOT AN EXCLUSION CRITERION, and an earlier version made it
    # one. Swept against known cases, no spur-prune length separates them: at
    # a prune of 45 a clean whole animal and a known fragment both report two
    # ends or fewer, while an off-frame animal reports four. It is reported as
    # a diagnostic and nothing is excluded on it.
    n_ends = 0 if pts is None else len(ends)
    return {
        "measurable": not reasons,
        "reasons": reasons,
        "touches_frame_edge": bool(touches),
        "merged_limb_fraction": round(fat_fraction, 3),
        "n_midline_ends": int(n_ends),
    }


def continues_beyond(worm, labels, stats, own_label, *, reach=220,
                     corridor_deg=35, min_area_fraction=0.12,
                     min_area_floor=400):
    """Does the animal carry on into another component past a tip?

    THE CASE THIS EXISTS FOR. `42821_AG406` in the frozen development set is a
    fragment of an animal that mostly lies outside the field, plus a partial
    second worm. Its mask stops SHORT of the frame edge, so the edge test does
    not fire, and it reports a completely believable 478 px. That is the
    "largest component" hazard arriving inside the development set.

    A mask that has stopped early leaves the rest of the animal sitting in
    another component, roughly along the body axis. Looking for one is a
    direct test of "there is more animal than this", where the edge test only
    asks "did I reach the wall".
    """
    pts, ends = _skeleton_ends(worm)
    if pts is None or not len(ends):
        return {"continues": False, "hits": []}
    # THE CONTINUATION MUST BE WORM-SIZED, not merely present. Scored against
    # any component over a fixed 400 px, a lawn speck inside the corridor
    # excluded `5521_cop1524` - the one animal in the set known to be traced
    # correctly end to end. A real continuation of a body is a substantial
    # piece of it, so the floor is relative to the animal already found.
    own_area = float(worm.sum())
    min_area = max(min_area_floor, own_area * min_area_fraction)
    hits = []
    for end in ends:
        near = pts[np.hypot(*(pts - end).T) < 25]
        if len(near) < 4:
            continue
        direction = end - near.mean(0)
        norm = np.linalg.norm(direction)
        if norm < 1e-6:
            continue
        direction = direction / norm
        for index in range(1, stats.shape[0]):
            if index == own_label or stats[index, cv2.CC_STAT_AREA] < min_area:
                continue
            cx = stats[index, cv2.CC_STAT_LEFT] + stats[index, cv2.CC_STAT_WIDTH] / 2
            cy = stats[index, cv2.CC_STAT_TOP] + stats[index, cv2.CC_STAT_HEIGHT] / 2
            offset = np.array([cx, cy]) - end
            distance = float(np.linalg.norm(offset))
            if distance < 1 or distance > reach:
                continue
            cosine = float(np.dot(offset / distance, direction))
            if cosine >= np.cos(np.radians(corridor_deg)):
                hits.append({"area": int(stats[index, cv2.CC_STAT_AREA]),
                             "distance_px": round(distance, 1),
                             "off_axis_deg": round(
                                 float(np.degrees(np.arccos(
                                     min(max(cosine, -1), 1)))), 1)})
    return {
        "continues": bool(hits),
        "hits": hits,
        "reason": (f"the body axis runs on into {len(hits)} further "
                   f"component(s) within {reach} px, so this mask is a "
                   f"FRAGMENT of a longer animal and its length is the length "
                   f"of the fragment" if hits else ""),
    }


# The stage 1 length vocabulary. `body_length_method` takes exactly one of
# these, so a consumer can tell how a length was obtained without reading the
# provenance.
LENGTH_METHOD_PERCENTILE = "percentile_persistent"
LENGTH_METHOD_COHERENT = "coherent_motion"
LENGTH_METHOD_FAILED = "failed"
# A percentile point is "flat" below this much change per point. Not a tuned
# number - it is the resolution at which a shoulder is worth calling one.
SHOULDER_FLAT_PCT_PER_POINT = 0.35
SHOULDER_MIN_WIDTH = 6           # percentile points
SHOULDER_SEARCH = (70, 99)


def persistent_length(lengths, *, flat=SHOULDER_FLAT_PCT_PER_POINT,
                      min_width=SHOULDER_MIN_WIDTH, search=SHOULDER_SEARCH,
                      min_frames=8):
    """Body length from a distribution of per-frame traced lengths.

    THE PERCENTILE IS DELIBERATELY NOT PINNED, and this is the whole point of
    the function. A coiled animal traces short and a stretched one long, so a
    single frame samples a posture rather than an animal. Taking a high
    percentile of many postures is meant to recover the animal - but only if
    the distribution actually settles.

    **The distribution chooses the percentile, and the choice is falsifiable:**

    * If there is a **shoulder** - a run of percentile points across which the
      value stops changing much - take from inside it. The value is then
      insensitive to exactly where in the shoulder it was taken, which is what
      makes it a measurement rather than a selection.
    * If the curve **climbs steadily to the maximum with no shoulder**, that is
      evidence something is still varying with posture. Picking a percentile
      there papers over the dependence instead of resolving it, so this
      returns `defensible=False` and the caller must not set a scale from it.

    Written this way so that "95 because it sounds reasonable" is visibly not
    what happened. Measured on the frozen development set, three of five
    recordings had no shoulder, so this refuses more often than not on that
    data - which is the correct behaviour there, not a failure of the method.
    """
    values = np.asarray([v for v in np.asarray(lengths, dtype=float)
                         if np.isfinite(v) and v > 0])
    if values.size < min_frames:
        return {
            "body_length_px": None,
            "body_length_method": LENGTH_METHOD_FAILED,
            "defensible": False,
            "n_frames": int(values.size),
            "note": (f"only {values.size} measurable frames, below the {min_frames} "
                     f"needed for a distribution to mean anything"),
        }
    points = np.arange(search[0], search[1] + 1)
    curve = np.percentile(values, points)
    # Percent change per percentile point, which is scale free and so
    # comparable between recordings of different magnification.
    slope = np.diff(curve) / np.clip(curve[:-1], 1e-9, None) * 100.0
    flat_mask = slope < flat

    best_start = best_len = None
    run_start = None
    for i, is_flat in enumerate(list(flat_mask) + [False]):
        if is_flat and run_start is None:
            run_start = i
        elif not is_flat and run_start is not None:
            if best_len is None or (i - run_start) > best_len:
                best_start, best_len = run_start, i - run_start
            run_start = None

    if best_len is None or best_len < min_width:
        return {
            "body_length_px": round(float(np.percentile(values, 90)), 1),
            "body_length_method": LENGTH_METHOD_PERCENTILE,
            "defensible": False,
            "shoulder_found": False,
            "n_frames": int(values.size),
            "spread_iqr_pct": round(float(
                (np.percentile(values, 75) - np.percentile(values, 25))
                / np.median(values) * 100), 1),
            "max_flat_run_points": int(best_len or 0),
            "note": ("no shoulder: the distribution climbs steadily, so a "
                     "percentile choice would paper over posture dependence "
                     "rather than resolve it. The p90 above is reported for "
                     "inspection ONLY and must not be used to set a scale."),
        }

    lo = int(points[best_start])
    hi = int(points[min(best_start + best_len, len(points) - 1)])
    take = (lo + hi) / 2.0
    return {
        "body_length_px": round(float(np.percentile(values, take)), 1),
        "body_length_method": LENGTH_METHOD_PERCENTILE,
        "defensible": True,
        "shoulder_found": True,
        "shoulder_percentiles": [lo, hi],
        "percentile_used": round(take, 1),
        "n_frames": int(values.size),
        "spread_iqr_pct": round(float(
            (np.percentile(values, 75) - np.percentile(values, 25))
            / np.median(values) * 100), 1),
        "note": (f"taken from inside a shoulder spanning percentiles {lo} to "
                 f"{hi}, where the value changes by less than {flat}% per "
                 f"percentile point, so it does not depend on exactly where "
                 f"in that range it was read"),
    }


def measured_bit_depth(frames):
    """Effective bit depth from the QUANTISATION STEP, not from the container.

    A declared bit depth is a claim about the container. What matters for any
    ratio, threshold or normalisation is how many codes can actually occur.

    Two ways a container lies, and they need different tests:

    * **Low-range**: 12-bit data in a 16-bit word, so nothing exceeds 4095.
      Detectable from the maximum.
    * **Left-shifted**: 8-bit data shifted into the top of a 16-bit word, so
      values DO reach 65535 but only every 128th code occurs. **Invisible to a
      maximum test** and detectable only from the step between adjacent codes.

    The second case is the one found on this lab's own recordings, and it is
    the one a max-based check misses.

    Returns levels actually available, the step, and the effective bits.
    """
    stack = np.stack([np.asarray(f) for f in frames]) if not isinstance(
        frames, np.ndarray) else np.asarray(frames)
    if stack.ndim == 4:
        stack = stack[..., 0]
    if stack.ndim == 2:
        stack = stack[None, ...]
    full_scale = 65535 if stack.dtype == np.uint16 else 255
    # Per frame, then pooled by median: across frames the union fills in codes
    # no single frame contains and the step collapses to 1.
    steps = []
    for frame in stack:
        unique = np.unique(frame)
        if unique.size > 1:
            steps.append(int(np.min(np.diff(unique))))
    step = int(np.median(steps)) if steps else 1
    available = int((full_scale + 1) // max(step, 1))
    return {
        "quantisation_step": step,
        "levels_available": available,
        "effective_bits": round(float(np.log2(max(available, 2))), 1),
        "container_bits": 16 if stack.dtype == np.uint16 else 8,
        "observed_max": int(stack.max()),
        "left_shifted": step > 1,
    }


def measure_intensity(raw_frames):
    """Sensor-range findings, in the terms that made a calcium series useless.

    A recording where almost every pixel is zero and only a few dozen grey
    levels are ever used is not a dim recording that can be rescued by
    normalising. There is nothing in it to normalise.
    """
    stack = np.stack([np.asarray(f) for f in raw_frames])
    if stack.ndim == 4:
        stack = stack[..., 0]
    dtype = stack.dtype
    full_scale = 65535 if dtype == np.uint16 else 255
    flat = stack.ravel()
    if flat.size > 4_000_000:
        flat = flat[:: flat.size // 4_000_000]
    levels = int(np.unique(flat).size)
    # Delegated, NOT reimplemented. An earlier version computed the step here
    # as well as in measured_bit_depth() and the two disagreed - 1560 usable
    # levels against 512 on the same recording, because they sampled different
    # frames. Two implementations of one measurement is the same class of
    # defect this whole audit is about.
    depth = measured_bit_depth(stack)
    return {
        "dtype": str(dtype),
        "bit_depth_container": depth["container_bits"],
        "quantisation_step": depth["quantisation_step"],
        "bit_depth_effective": depth["effective_bits"],
        "left_shifted": depth["left_shifted"],
        "grey_levels_used": levels,
        "grey_levels_available": depth["levels_available"],
        "zero_fraction": round(float((flat == 0).mean()), 4),
        "saturated_fraction": round(float((flat >= full_scale).mean()), 5),
        "mean": round(float(flat.mean()), 2),
        "p99": float(np.percentile(flat, 99)),
        "max": int(flat.max()),
    }


def measure_focus(gray_frame):
    """Variance of the Laplacian - higher is sharper.

    Only comparable within a rig and magnification, so it is reported rather
    than thresholded. A number that cannot be compared to anything should not
    be allowed to fail a recording on its own.
    """
    a = np.asarray(gray_frame, dtype=np.float32)
    return round(float(cv2.Laplacian(a, cv2.CV_32F).var()), 2)


def probe(source, *, sample_frames=40, declared_fps=None, um_per_px=None,
          body_length_um=1140.0):
    """Everything measurable about a short test recording.

    `source` is anything the toolset already reads: an image folder, a TIFF
    stack, or a video.
    """
    from population_swimming import list_frames, read_gray   # lazy: heavy

    frames = list_frames(source)
    n = len(frames)
    if not n:
        raise ValueError(
            f"{source} holds no readable frames. A test recording has to "
            f"contain something to measure.")
    picks = _frame_indices(n, sample_frames)
    raw = [frames[i] for i in picks]
    gray = [read_gray(f) for f in raw]

    header_fps = getattr(getattr(frames, "movie", None), "fps", None)
    source_kind = getattr(getattr(frames, "movie", None), "source_kind", None)
    # A folder of images has no frame rate to read; movie_core defaults the
    # attribute to 1.0, which would otherwise read as a measurement.
    if source_kind != "video":
        header_fps = None

    body_px, length_detail = measure_body_length_px(gray)
    out = {
        "source": str(source),
        "source_kind": source_kind or "frames",
        "n_frames": n,
        "frame_shape": tuple(int(x) for x in np.asarray(gray[0]).shape[:2]),
        "frames_sampled": len(picks),
        "header_fps": float(header_fps) if header_fps else None,
        "declared_fps": float(declared_fps) if declared_fps else None,
        "body_length_px": round(body_px, 1) if body_px else None,
        "body_length_detail": length_detail,
        "intensity": measure_intensity(raw),
        "focus_laplacian_var": measure_focus(gray[len(gray) // 2]),
        "declared_um_per_px": float(um_per_px) if um_per_px else None,
        "shadow": measure_shadow_over_frames(gray),
        "substrate": detect_substrate(gray),
        "bit_depth": measured_bit_depth(raw),
        "disagreements": [],
    }

    # TWO SEGMENTATIONS, REPORTED SIDE BY SIDE RATHER THAN RECONCILED. The
    # spatial-illumination rule above is the general one; the fine-texture
    # rule is validated on lawn recordings only. Where both run and disagree,
    # say so out loud instead of silently preferring one - the texture rule is
    # not yet tested across the whole population it would become the default
    # for.
    texture_len = None
    found = texture_foreground(gray[len(gray) // 2])
    if found is not None:
        worm, _ = found
        contours, _ = cv2.findContours(worm, cv2.RETR_EXTERNAL,
                                       cv2.CHAIN_APPROX_NONE)
        if contours:
            best = max(contours, key=cv2.contourArea)
            texture_len = _elongated_length_px(cv2.contourArea(best),
                                               cv2.arcLength(best, True))
    out["body_length_px_texture"] = (round(texture_len, 1) if texture_len
                                     else None)
    # NOT the stage 1 vocabulary. This probe's length is a single-pass median
    # over sampled frames, which is a different measurement from stage 1's
    # persistent percentile - so it is labelled separately rather than
    # borrowing a name that would imply it went through persistent_length().
    out["body_length_source"] = "spatial_illumination_median"
    if body_px and texture_len:
        ratio = max(body_px, texture_len) / max(min(body_px, texture_len), 1e-6)
        out["body_length_methods_agree"] = ratio <= 1.35
        if ratio > 1.35:
            out["segmentation_disagreement"] = (
                f"The two segmentations disagree about body length: "
                f"{body_px:.0f} px from the spatial-illumination rule and "
                f"{texture_len:.0f} px from the fine-texture rule, a factor "
                f"of {ratio:.2g}. The texture rule is validated on lawn "
                f"recordings and the illumination rule is the general one; "
                f"neither is silently preferred here. On a lawn recording "
                f"trust the texture figure, and confirm by overlaying the "
                f"mask on the raw pixels before using either.")

    # The two claims worth cross-examining, because both have silently
    # corrupted a real result in this lab.
    if out["header_fps"] and out["declared_fps"]:
        ratio = out["header_fps"] / out["declared_fps"]
        if not 0.9 <= ratio <= 1.1:
            out["disagreements"].append(
                f"The video header says {out['header_fps']:g} fps and you "
                f"declared {out['declared_fps']:g}. Speed and frequency are "
                f"both linear in frame rate, so whichever is wrong scales "
                f"every reported number by {ratio:.2g}x. Settle this before "
                f"analysing anything.")
    if um_per_px and body_px:
        implied_px = float(body_length_um) / float(um_per_px)
        ratio = implied_px / body_px
        if not 0.67 <= ratio <= 1.5:
            out["disagreements"].append(
                f"At the declared {float(um_per_px):g} um/px a "
                f"{body_length_um:g} um animal would be {implied_px:.0f} px "
                f"long, but the animals in this recording measure "
                f"{body_px:.0f} px - a factor of {ratio:.2g}. Either the "
                f"scale is wrong or these are not the animals you think they "
                f"are.")
    return out


def measured_um_per_px(body_length_px, body_length_um=1140.0):
    """The scale implied by a measured animal, for feeding the check.

    Used when nothing has been calibrated: every floor in acquisition_check is
    really a floor on pixels per animal, so a scale derived from the measured
    length puts the check on the measurement rather than on a declaration.
    """
    if not body_length_px:
        return None
    return float(body_length_um) / float(body_length_px)


# A day 1 adult is about this long. Much of the archive carries no calibration
# metadata at all, and a known animal is the only ruler in the frame.
DAY1_ADULT_UM = 1100.0


def um_per_px_from_adult_length(body_length_px, *, stage="undulation",
                                adult_um=DAY1_ADULT_UM):
    """Scale from a known day 1 adult. STAGE-DEPENDENT - read this.

    This is the motion-signature spec's stage 1 output that gives a scale to
    recordings with no calibration metadata, which is most of the archive.

    IT IS ONLY AS GOOD AS THE LENGTH IT IS GIVEN, and that length comes from
    a segmentation. `stage` records which route produced it, because the
    routes are not equally trustworthy and a scale carries that all the way
    into every micrometre it converts:

      undulation       length from a resolved body wave. Best available.
      coherent_motion  length from a moving region with no wave resolved.
                       Wider uncertainty; the spec requires it be marked.
      failed           no length. Returns None rather than a number.

    IT ALSO ASSUMES THE SEGMENTED OBJECT IS THE ANIMAL. On the pezo-1 CRISPR
    set the animals are lit obliquely and cast a dark shadow alongside the
    body; an intensity threshold segments the SHADOW, which is a different
    shape and a different length. A scale derived from that is wrong and
    looks entirely reasonable. Confirm what was segmented before trusting a
    scale from this function.
    """
    if not body_length_px or stage == "failed":
        return None
    return {
        "um_per_px": float(adult_um) / float(body_length_px),
        "body_length_px": float(body_length_px),
        "assumed_adult_um": float(adult_um),
        "stage": stage,
        "caveat": ("derived from an assumed day 1 adult length, not from a "
                   "calibration target; only valid if the segmented object "
                   "is the whole animal and the animal is a day 1 adult"),
    }
