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
    return {
        "dtype": str(dtype),
        "bit_depth_container": 16 if dtype == np.uint16 else 8,
        "grey_levels_used": levels,
        "grey_levels_available": full_scale + 1,
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
