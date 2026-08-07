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
    unique = np.unique(flat)
    levels = int(unique.size)
    # A 16-BIT CONTAINER IS NOT 16 BITS OF DATA. These cameras write 8-bit
    # values left-shifted into a 16-bit word, so the quantisation step is 128
    # and only 512 of the 65536 codes can ever occur. Comparing levels against
    # the container failed a perfectly good recording at 333 of 65536, when
    # the honest figure was 333 of 512.
    #
    # The step must be measured PER FRAME and pooled by median. Taking it
    # across pooled frames gives 2 instead of 128, because separate frames sit
    # at slightly different offsets and their union fills in codes that no
    # single frame contains.
    steps = []
    for frame in stack:
        u = np.unique(frame)
        if u.size > 1:
            steps.append(int(np.min(np.diff(u))))
    step = int(np.median(steps)) if steps else 1
    available = int((full_scale + 1) // max(step, 1))
    return {
        "dtype": str(dtype),
        "bit_depth_container": 16 if dtype == np.uint16 else 8,
        "quantisation_step": step,
        "bit_depth_effective": round(float(np.log2(max(available, 2))), 1),
        "grey_levels_used": levels,
        "grey_levels_available": available,
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
        "disagreements": [],
    }

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
