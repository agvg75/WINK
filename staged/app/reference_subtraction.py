"""Detect worms by subtracting one frame from the rest of the movie.

Andres: wrmtrckr uses an effective approach where one frame is subtracted from
the rest of the movie, and in the donut assay it should work particularly well
- all the worms start at the centre, and they are excluded from analysis until
they cross the central ROI line, so subtracting the STARTING frame leaves just
the worms.

WHY THE STARTING FRAME AND NOT A MEDIAN, which is the usual choice and is
wrong here. A median over the movie builds a background from what each pixel
shows most of the time, so anything that stays put becomes background and
vanishes. In a time-to-leave assay the animals that stay put are exactly the
CENSORED OBSERVATIONS - the ones that never crossed - and they are the most
informative animals in the experiment. A median background would delete them,
and their absence would look like a cleaner dataset rather than a missing
category. The fraction that crossed would then be computed over the survivors
of a filter, and it would come out too high.

WHAT THE REFERENCE FRAME COSTS. Every worm present in the reference leaves a
negative ghost where it was. That is normally a serious defect, and here it is
almost free: the ghost sits where the animals started, which is inside the
central ROI, which is excluded from analysis anyway. That is Andres's point
and it is worth checking rather than assuming - `ghost_check` confirms the
ghosts really do fall inside the excluded region, because if the animals were
not all at the centre when the reference was taken, the assumption quietly
stops holding and the ghosts become false detections in the scored area.

THE MAGNET CANCELS TOO, which matters more than it sounds. A ring magnet is a
large, dark, static object with an edge exactly where the measurement happens.
Any absolute-threshold detector will fight it forever; subtraction removes it
completely because it does not move.
"""
from __future__ import annotations

import numpy as np


class SubtractionError(Exception):
    """Refusals that name the consequence."""


def _gray(frame):
    a = np.asarray(frame, dtype=float)
    return a.mean(axis=2) if a.ndim == 3 else a


def subtract(frame, reference, *, polarity="dark"):
    """Reference-subtracted image, as a positive-going difference.

    `polarity` says whether worms are darker or brighter than background.

    IT DEFAULTS TO "dark" RATHER THAN AUTO-DETECTING, and that is a correction
    of the obvious design. Deciding polarity from which tail of the difference
    is heavier fails on exactly this assay: a worm that LEAVES the centre puts
    a positive bump where it was, precisely as strong as the negative dip
    where it reappeared, so the two tails are equal and the choice is a coin
    flip. Tested here, it flipped, and the detector then found the ghost at
    the centre instead of the two animals - one blob, in the wrong place, with
    every appearance of success.

    "auto" remains available but requires `exclude` so the ghost region is out
    of the comparison, since that is the only way the tails mean what they
    look like they mean.
    """
    f, r = _gray(frame), _gray(reference)
    if f.shape != r.shape:
        raise SubtractionError(
            f"Frame {f.shape} and reference {r.shape} are different sizes, so "
            f"they cannot be subtracted. A resized or cropped reference would "
            f"align to the wrong pixels and produce edge artefacts that look "
            f"like animals.")
    diff = f - r
    if polarity == "dark":
        return -diff, polarity
    if polarity == "bright":
        return diff, polarity
    raise SubtractionError(
        "polarity must be 'dark' or 'bright'. Use auto_polarity() with an "
        "excluded ROI if it genuinely has to be inferred - inferring it from "
        "the raw difference is a coin flip on this assay, because the ghost a "
        "departing worm leaves is exactly as strong as the worm.")


def auto_polarity(frame, reference, exclude=None):
    """Infer polarity, but only outside the ghost region.

    `exclude` is (center_px, radius_px) - the central ROI the animals started
    in and which is not scored. With the ghosts excluded the heavier tail
    really is the animals; without them excluded it is a coin flip, so this
    refuses rather than guessing.
    """
    if exclude is None:
        raise SubtractionError(
            "Polarity cannot be inferred without excluding the region the "
            "animals started in. Their ghosts are as strong as they are, so "
            "the two tails of the difference are equal and the answer would "
            "be arbitrary. Pass exclude=((cx, cy), radius) or state the "
            "polarity outright.")
    diff = _gray(frame) - _gray(reference)
    (cx, cy), rad = exclude
    h, w = diff.shape
    yy, xx = np.mgrid[0:h, 0:w]
    outside = np.hypot(xx - float(cx), yy - float(cy)) > float(rad)
    vals = diff[outside]
    return "dark" if abs(float(vals.min())) >= abs(float(vals.max())) \
        else "bright"


def detect(frame, reference, *, threshold_sd=4.0, min_area_px=20,
           max_area_px=None, polarity="dark", exclude=None):
    """Blobs that appeared since the reference frame.

    Threshold is in robust standard deviations of the difference image, not
    absolute counts, so the same settings survive a change of illumination or
    exposure - which an absolute threshold does not, silently.

    `exclude` is (center_px, radius_px): the central ROI the animals started
    in and which is not scored. Masking it removes the ghosts entirely, which
    is precisely why this reference works for this assay - the one artefact
    the method creates lands in the one place nothing is measured.
    """
    diff, polarity = subtract(frame, reference, polarity=polarity)
    mad = float(np.median(np.abs(diff - np.median(diff))))
    noise = mad * 1.4826
    if noise <= 0:
        raise SubtractionError(
            "The difference image has no measurable variation, so no "
            "threshold can be set relative to it. Either the frame IS the "
            "reference, or the movie has been through a filter that removed "
            "the noise the threshold depends on.")
    mask = diff > threshold_sd * noise
    if exclude is not None:
        (cx, cy), rad = exclude
        h, w = mask.shape
        yy, xx = np.mgrid[0:h, 0:w]
        mask = mask & (np.hypot(xx - float(cx), yy - float(cy)) > float(rad))
    labels, n = _label(mask)
    blobs = []
    for i in range(1, n + 1):
        ys, xs = np.nonzero(labels == i)
        area = len(xs)
        if area < min_area_px:
            continue
        if max_area_px and area > max_area_px:
            continue
        weights = diff[ys, xs]
        blobs.append({
            "label": i, "area_px": int(area),
            "x_px": float(np.average(xs, weights=weights)),
            "y_px": float(np.average(ys, weights=weights)),
            "mean_over_background": float(np.mean(weights) / noise),
        })
    blobs.sort(key=lambda b: -b["area_px"])
    return {"blobs": blobs, "n_found": len(blobs), "polarity": polarity,
            "noise": noise, "threshold": threshold_sd * noise, "mask": mask}


def _label(mask):
    """Connected components. scipy if present, otherwise a flood fill.

    Not worth a hard dependency for one function, and a tool that refuses to
    run because scipy is missing is worse than one that is slower.
    """
    try:
        from scipy import ndimage
        return ndimage.label(mask)
    except ImportError:
        pass
    labels = np.zeros(mask.shape, dtype=int)
    current = 0
    h, w = mask.shape
    for sy in range(h):
        for sx in range(w):
            if not mask[sy, sx] or labels[sy, sx]:
                continue
            current += 1
            stack = [(sy, sx)]
            labels[sy, sx] = current
            while stack:
                y, x = stack.pop()
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        ny, nx = y + dy, x + dx
                        if (0 <= ny < h and 0 <= nx < w and mask[ny, nx]
                                and not labels[ny, nx]):
                            labels[ny, nx] = current
                            stack.append((ny, nx))
    return labels, current


def ghost_check(reference, later, *, center_px, roi_radius_px,
                threshold_sd=4.0, polarity="dark"):
    """Do the reference frame's animals really all sit inside the excluded ROI?

    The whole reason the starting frame is a good reference here is that its
    ghosts land where nothing is scored. That holds only if the animals really
    were all at the centre when it was taken. If someone picks a later frame -
    or the worms had already begun to disperse - the ghosts become negative
    holes in the SCORED area, where they will suppress real detections rather
    than create them, which is the harder failure to notice.

    A GHOST IS SOMETHING THAT LEFT, so this needs a later frame to compare
    against, and looking for dark objects in the reference alone does not
    work. Tried that first: it found the ring magnet, which is large, dark,
    entirely outside the central ROI and not a ghost at all, because it never
    moves and therefore cancels perfectly in the subtraction. Differencing
    against a later frame excludes every static object by construction.
    """
    # A dark animal present in the reference and gone later makes the
    # reference DARKER than the later frame there, so later - reference is
    # positive at a ghost. Getting this backwards finds where the animals
    # ARRIVED instead of where they left, which is the same pixel count in the
    # wrong place and passes casual inspection.
    diff = _gray(later) - _gray(reference)
    if polarity == "bright":
        diff = -diff
    mad = float(np.median(np.abs(diff - np.median(diff))))
    noise = mad * 1.4826 or 1e-9
    # Positive here means "the reference was darker than later" - a dark
    # animal that has since moved away. That is exactly a ghost.
    mask = diff > threshold_sd * noise
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return {"checked": False,
                "why": "Nothing in the reference frame has moved away by the "
                       "later frame, so there are no ghosts to place."}
    r = np.hypot(xs - float(center_px[0]), ys - float(center_px[1]))
    outside = int(np.count_nonzero(r > float(roi_radius_px)))
    frac = outside / len(r)
    ok = frac < 0.05
    return {
        "checked": True,
        "pixels_in_reference": int(len(r)),
        "fraction_outside_roi": round(frac, 4),
        "ghosts_confined_to_excluded_roi": bool(ok),
        "why": (None if ok else
                f"{frac:.0%} of what stands out in the reference frame lies "
                f"OUTSIDE the excluded central ROI. Their ghosts will fall in "
                f"the scored area as negative holes, suppressing real "
                f"detections rather than creating them - the harder failure "
                f"to notice. Either the animals had begun to disperse when "
                f"this frame was taken, or the reference is not the starting "
                f"frame. Pick an earlier one."),
    }


def _box_blur(img, k):
    k = int(k) | 1
    pad = k // 2
    padded = np.pad(img, pad, mode="edge")
    out = np.zeros_like(img, dtype=float)
    csum = padded.cumsum(axis=0).cumsum(axis=1)
    csum = np.pad(csum, ((1, 0), (1, 0)))
    h, w = img.shape
    out = (csum[k:k + h, k:k + w] - csum[0:h, k:k + w]
           - csum[k:k + h, 0:w] + csum[0:h, 0:w]) / (k * k)
    return out


def compare_with_median(frames, reference_index=0, *, center_px=None,
                        roi_radius_px=None):
    """What a median background would delete that a reference frame keeps.

    The point is not that median subtraction is bad - it is usually better.
    The point is that in a time-to-leave assay it removes the animals that
    never left, and those are the observations the measurement most depends
    on.
    """
    stack = np.stack([_gray(f) for f in frames])
    if len(stack) < 3:
        raise SubtractionError(
            "At least three frames are needed to form a median background to "
            "compare against.")
    median = np.median(stack, axis=0)
    ref = stack[int(reference_index)]
    last = stack[-1]
    d_ref = np.abs(last - ref)
    d_med = np.abs(last - median)
    noise = (float(np.median(np.abs(d_ref - np.median(d_ref)))) * 1.4826) or 1e-9
    ref_hits = int(np.count_nonzero(d_ref > 4 * noise))
    med_hits = int(np.count_nonzero(d_med > 4 * noise))
    out = {
        "reference_signal_px": ref_hits,
        "median_signal_px": med_hits,
        "median_loses_px": max(0, ref_hits - med_hits),
        "why": ("A median background is built from what each pixel shows most "
                "of the time, so an animal that stays put becomes part of it "
                "and disappears. In a time-to-leave assay those are the "
                "censored observations - the animals that never crossed - and "
                "losing them makes the fraction that crossed come out too "
                "high while the data look cleaner."),
    }
    if center_px is not None and roi_radius_px:
        h, w = median.shape
        yy, xx = np.mgrid[0:h, 0:w]
        inside = (np.hypot(xx - center_px[0], yy - center_px[1])
                  <= float(roi_radius_px))
        out["reference_ghost_px_inside_roi"] = int(
            np.count_nonzero((np.abs(ref - median) > 4 * noise) & inside))
        out["reference_ghost_px_outside_roi"] = int(
            np.count_nonzero((np.abs(ref - median) > 4 * noise) & ~inside))
    return out
