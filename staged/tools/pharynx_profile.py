"""Pharynx geometry along the lumen: width profile and segment landmarks.

WHY THIS IS NOT THE BODY-WALL CODE. Body-wall myocyte boundaries run
LONGITUDINALLY and were found with a left-to-right seam search. The pharynx is a
radially symmetric pump: the lumen runs its whole length and everything is
arranged about it, so its segments - procorpus, metacorpus, isthmus, terminal
bulb - differ mainly in WIDTH along that axis. That makes this a 1-D profile
problem, and `fibre_orientation.trace_seams` would be the wrong search direction
here in exactly the way a transverse search was wrong for body wall.

VALIDATED against two hand-marked fields (Andres Vidal-Gadea, unassisted,
230518_pezo-1.lif series 4 and 2). Both bulbs are located within a few
micrometres of the marked centres, and the isthmus reads as the expected
minimum:
    field B   metacorpus 30.1 um   isthmus  2.5 um   terminal 24.8 um
    field A   metacorpus 20.9 um   isthmus 11.9 um   terminal 11.9 um
Field A's terminal bulb is under-measured and the cause is not yet known, so
treat a single field's absolute widths with suspicion and prefer the ordering.
"""
from __future__ import annotations

import numpy as np


def detect_lumen(image, um_per_px, tissue_percentile=65, smooth_um=3.0,
                 require_confident=True):
    """Find the lumen without hand marks: the DARK path running through the organ.

    NOT RELIABLE YET, AND IT REFUSES RATHER THAN PRETENDING. Measured against
    the two hand-marked fields, the traced centreline sits 3.7 and 8.1 um from
    the marked one (median). The pharynx is roughly 25 um wide, so that is a
    large fraction of its radius, and every continuity measure is taken about
    this line - a centreline several micrometres out distorts the unrolled map
    everywhere at once.

    PREFER A HAND-MARKED LUMEN. It is a single stroke; Andres drew it on two
    fields in seconds. Requiring it keeps the measurement usable today and
    keeps a person in the loop, rather than gating a working metric behind a
    detector that does not yet work. Pass `require_confident=False` only to
    inspect what the detector proposes, never to measure from it unchecked.

    Needed because continuity is measured about the lumen, and only two fields
    have it marked by hand. Every dystrophic stack would otherwise be
    unmeasurable.

    The lumen is a dark line flanked by bright muscle, running the length of the
    pharynx - which is the same shape of problem as a myocyte seam, so the same
    dynamic-programming tracer is reused with darkness as the evidence. It walks
    left to right one pixel of y at a time, so a pharynx lying roughly along the
    image axis is assumed; rotate into the animal's frame first (animal_frame)
    if it does not.

    Returns (centreline, report). The report carries the contrast between the
    traced path and the tissue either side of it, because a path is always
    returned - the tracer cannot fail - and a low contrast means it followed
    nothing in particular.
    """
    from scipy import ndimage as ndi
    import fibre_orientation as fo

    img = np.asarray(image, dtype=float)
    H, W = img.shape
    sm = ndi.gaussian_filter(img, max(smooth_um / um_per_px, 1.0))
    tissue = sm > np.percentile(sm, tissue_percentile)
    tissue = ndi.binary_closing(tissue, np.ones((9, 9)))
    tissue = ndi.binary_fill_holes(tissue)
    if tissue.sum() < 0.01 * tissue.size:
        raise ValueError(
            "Almost no tissue was found, so there is no organ to locate a "
            "lumen inside. Every continuity measure is taken about the lumen, "
            "so proceeding would measure a line through background.")

    # DARKNESS ALONE IS NOT A LUMEN. A first version traced the darkest path
    # inside the tissue and left the pharynx entirely - in one field it dropped
    # below the organ after 75 um and followed a dark band beside it - because
    # the tissue mask is really "inside the worm", and the worm contains other
    # dark things. The gut is dark. The space beside the pharynx is dark.
    #
    # What distinguishes the lumen is that it is dark WITH BRIGHT MUSCLE ON
    # BOTH SIDES. A dark band at the edge of an organ has bright tissue on one
    # side only, so requiring both shoulders excludes it. This is a matched
    # filter for the structure rather than a threshold on intensity.
    inside = ndi.gaussian_filter(tissue.astype(float), 2.0) > 0.5
    r = max(int(4.0 / um_per_px), 2)
    up = np.roll(sm, r, axis=0)
    down = np.roll(sm, -r, axis=0)
    shoulders = np.minimum(up, down)          # BOTH sides must be bright
    lumen_like = shoulders - sm
    lumen_like[:r] = 0.0
    lumen_like[-r:] = 0.0
    ev = np.where(inside, lumen_like, -1e6)
    span = np.ptp(ev[inside]) if inside.any() else 1.0
    ev = np.where(inside, (ev - ev[inside].min()) / max(span, 1e-9), -1.0)

    ys, xs = np.nonzero(inside)
    guide = np.full(W, float(np.median(ys)))
    path, score = fo.trace_seam_guided(ev, guide, prior_um=25.0,
                                       um_per_px=um_per_px, max_slope=1)
    centre = ndi.uniform_filter1d(path.astype(float),
                                  max(int(smooth_um / um_per_px), 3))

    # contrast: how much darker the path is than the tissue a little either side
    off = max(int(3.0 / um_per_px), 2)
    on_vals, off_vals = [], []
    for x in range(W):
        c = int(round(centre[x]))
        if not (0 <= c < H) or not inside[c, x]:
            continue
        on_vals.append(sm[c, x])
        for d in (-off, off):
            y = c + d
            if 0 <= y < H and inside[y, x]:
                off_vals.append(sm[y, x])
    contrast = (float(np.median(off_vals) - np.median(on_vals))
                if on_vals and off_vals else 0.0)
    rel = contrast / max(float(np.median(off_vals)) if off_vals else 1.0, 1e-9)
    report = {"mean_evidence": round(float(score), 4),
              "lumen_contrast": round(contrast, 4),
              "relative_contrast": round(float(rel), 4),
              "looks_like_a_lumen": bool(rel > 0.10),
              "note": ("A path is always returned - the tracer cannot fail. "
                       "relative_contrast near zero means it followed nothing "
                       "in particular, and continuity measured about it would "
                       "be meaningless.")}
    if require_confident and not report["looks_like_a_lumen"]:
        raise ValueError(
            f"No convincing lumen was found: the traced path is only "
            f"{100 * rel:.1f}% darker than the tissue beside it, so it may not "
            f"be following the lumen at all. Every continuity measure is taken "
            f"about this line, so a wrong one distorts the whole result rather "
            f"than adding noise to it.\n\n"
            f"Mark the lumen by hand instead - it is a single stroke - or pass "
            f"require_confident=False to inspect what was proposed.")
    return centre, report


def lumen_centreline(lumen_mask, um_per_px, smooth_um=5.0):
    """One lumen y per column, interpolated across gaps and smoothed."""
    from scipy import ndimage as ndi

    mask = np.asarray(lumen_mask, dtype=bool)
    H, W = mask.shape
    cy = np.full(W, np.nan)
    for x in range(W):
        ys = np.where(mask[:, x])[0]
        if ys.size:
            cy[x] = ys.mean()
    ok = np.isfinite(cy)
    if ok.sum() < 2:
        raise ValueError(
            "The lumen mask covers fewer than two columns, so no centreline can "
            "be built. Every width here is measured about the lumen, so without "
            "it nothing downstream means anything.")
    filled = np.interp(np.arange(W), np.arange(W)[ok], cy[ok])
    return ndi.uniform_filter1d(filled, max(int(smooth_um / um_per_px), 3))


def width_profile(tissue_mask, centreline, um_per_px_y, gap_tol_um=2.0,
                  smooth_um=3.0, um_per_px_x=None):
    """Tissue extent about the lumen, walking OUTWARD from the centreline.

    Deliberately NOT the connected component containing the lumen. The lumen is
    a DARK line, so that component is frequently tiny or empty and the
    measurement collapses - it reported a 25 um terminal bulb as 3.8 um. Walking
    outward and stopping at the first sustained gap tolerates the dark lumen in
    the middle while still ending at the outer boundary of the organ.
    """
    from scipy import ndimage as ndi

    mask = np.asarray(tissue_mask, dtype=bool)
    H, W = mask.shape
    cy = np.asarray(centreline, dtype=float)
    gap_tol = max(int(gap_tol_um / um_per_px_y), 2)
    out = np.zeros(W)
    for x in range(W):
        c = int(round(cy[x]))
        total = 0
        for step in (-1, +1):
            run_gap, y = 0, c
            while 0 <= y < H:
                if mask[y, x]:
                    total += 1
                    run_gap = 0
                else:
                    run_gap += 1
                    if run_gap > gap_tol:
                        break
                y += step
        out[x] = total * um_per_px_y
    px = um_per_px_x if um_per_px_x else um_per_px_y
    return ndi.uniform_filter1d(out, max(int(smooth_um / px), 3))


def radialness(angles, coherence, centreline, image, um_per_px,
               min_coherence=0.2, bright_percentile=60):
    """How radial the local fibres are about the lumen: +1 radial, -1 axial.

    Pharyngeal muscle is arranged RADIALLY about the lumen while body-wall
    muscle runs along the animal, and those are near-orthogonal - so the same
    structure tensor used for body wall separates the two tissues when asked
    this question instead.

    Measured on the marked fields: median radialness inside the pharynx +0.535
    and +0.757, against +0.037 and +0.460 outside it. Real and consistent.

    NOTE it did NOT improve the width profile, and made one field slightly
    worse. It is kept because identifying pharyngeal tissue is useful in its
    own right, not because it fixed the width measurement - the fix there was
    the outward walk in width_profile().
    """
    from scipy import ndimage as ndi

    ang = np.asarray(angles, dtype=float)
    coh = np.asarray(coherence, dtype=float)
    if ang.ndim == 3:
        a2 = np.deg2rad(np.nanmean(ang, axis=0) * 2.0)
        c2 = np.nanmean(coh, axis=0)
    else:
        a2 = np.deg2rad(ang * 2.0)
        c2 = coh
    fib = (np.degrees(np.arctan2(np.sin(a2), np.cos(a2))) / 2.0) % 180.0

    cy = np.asarray(centreline, dtype=float)
    tangent = np.degrees(np.arctan2(np.gradient(cy), 1.0))
    radial = (tangent + 90.0) % 180.0            # perpendicular to the lumen
    H, W = fib.shape
    radial_map = np.broadcast_to(radial[None, :], (H, W))

    d = np.abs(fib - radial_map) % 180.0
    dev = np.minimum(d, 180.0 - d)
    img = np.asarray(image, dtype=float)
    usable = (img > np.percentile(img, bright_percentile)) & (c2 > min_coherence)
    raw = np.where(usable, np.cos(np.deg2rad(2 * dev)), np.nan)
    return ndi.gaussian_filter(np.nan_to_num(raw), 2.0 / um_per_px), usable


def find_bulbs(width, um_per_px, min_separation_um=20.0):
    """Locate the two bulbs as maxima of the width profile, isthmus between.

    Returns positions in micrometres. Two bulbs are EXPECTED - metacorpus and
    terminal - but the count is not forced: if the profile supports only one,
    one is returned and the shortfall reported, because a landmark invented to
    reach an expected count is indistinguishable downstream from a measured one.
    """
    from scipy.signal import find_peaks

    w = np.asarray(width, dtype=float)
    pk, props = find_peaks(w, distance=max(int(min_separation_um / um_per_px), 3),
                           prominence=0.5)
    order = np.argsort(-props["prominences"])
    pk = pk[order][:2]
    pk.sort()
    result = {"bulbs_um": (pk * um_per_px).tolist(), "n_bulbs": int(pk.size)}
    if pk.size == 2:
        seg = w[pk[0]:pk[1]]
        if seg.size:
            result["isthmus_um"] = float((pk[0] + int(np.argmin(seg))) * um_per_px)
            result["isthmus_width_um"] = float(seg.min())
            result["bulb_widths_um"] = [float(w[p]) for p in pk]
    else:
        result["shortfall_note"] = (
            f"Expected two bulbs (metacorpus and terminal) but the width "
            f"profile supports {pk.size}. The missing one is NOT invented - a "
            f"landmark placed to reach a count cannot be told from a measured "
            f"one further down the pipeline.")
    return result
