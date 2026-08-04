"""Per-fibre segmentation: trace individual actin fibres and find where they end.

WHY THIS EXISTS. Two structural cues came from Andres that no smoothed field can
test:
  * actin fibres INSERT at a myocyte edge - they angle in and TERMINATE there
  * a myocyte END is a point where many fibres CONVERGE onto a single spot
Both are properties of individual fibres, and every cue built before this one
begins by blurring the striations away as nuisance. An attempt to test the first
found 205 endpoints in a field holding thousands of striations, because a simple
intensity threshold merges neighbouring fibres into blobs: that measured the
segmentation, not the biology.

WHAT THIS DOES NOT DO. It proposes fibres. It does not decide where a myocyte
ends, and a traced fibre is not a measurement of a sarcomere. Everything here
feeds a proposal a human checks.

SCALE IS THE WHOLE GAME. A fibre is roughly half a micrometre across and the
gaps between them about a micrometre, so at 0.09-0.12 um/px a fibre is only 4-6
pixels wide. Ridge filters must be given sigmas in that range; too large and
neighbouring fibres merge back into the blobs this module exists to avoid.
"""
from __future__ import annotations

import numpy as np

# A fibre is a ridge a few pixels wide. These are micrometres, converted to
# pixels per image, so the same numbers work across objectives.
FIBRE_WIDTH_UM = (0.25, 0.75)


def enhance_fibres(image, um_per_px, width_um=FIBRE_WIDTH_UM):
    """Ridge (tubeness) response tuned to actin fibre width.

    Sato/Frangi-style filters respond to locally tubular structure rather than
    to brightness, which is what separates two adjacent fibres of similar
    intensity - the exact case a threshold cannot handle.
    """
    from skimage.filters import sato

    img = np.asarray(image, dtype=float)
    lo, hi = [max(w / um_per_px, 1.0) for w in width_um]
    sigmas = np.linspace(lo, hi, 3)
    resp = sato(img, sigmas=sigmas, black_ridges=False)
    return resp, sigmas


def trace_fibres(image, um_per_px, percentile=70, min_length_um=1.5,
                 width_um=FIBRE_WIDTH_UM):
    """Skeletonise the fibre field and split it into individual segments.

    Segments are split AT JUNCTIONS. Without that, crossing or touching fibres
    label as one connected component and the skeleton becomes a handful of long
    branching curves with almost no endpoints - which is exactly the artefact
    that made the first insertion test meaningless.

    Returns a dict with the skeleton, per-segment pixel coordinates, and the
    endpoints of each segment.
    """
    from scipy import ndimage as ndi
    from skimage.morphology import skeletonize, remove_small_objects

    img = np.asarray(image, dtype=float)
    resp, sigmas = enhance_fibres(img, um_per_px, width_um)
    thr = np.percentile(resp, percentile)
    mask = resp > thr
    min_px = max(int((min_length_um / um_per_px) ** 1.0), 8)
    mask = remove_small_objects(mask, min_size=min_px)
    skel = skeletonize(mask)

    # neighbour count on the skeleton: 1 = endpoint, >2 = junction
    k = np.ones((3, 3), np.uint8)
    nb = ndi.convolve(skel.astype(np.uint8), k, mode="constant") - 1
    nb = np.where(skel, nb, 0)
    junctions = skel & (nb > 2)
    segments_mask = skel & ~junctions

    lab, n = ndi.label(segments_mask, structure=np.ones((3, 3)))
    min_seg_px = max(int(min_length_um / um_per_px), 4)
    segments, endpoints = [], []
    for i in range(1, n + 1):
        ys, xs = np.where(lab == i)
        if ys.size < min_seg_px:
            continue
        segments.append((ys, xs))
        # endpoints of THIS segment: skeleton pixels with one neighbour inside it
        sub = np.zeros_like(segments_mask)
        sub[ys, xs] = True
        nbs = ndi.convolve(sub.astype(np.uint8), k, mode="constant") - 1
        e = np.where(sub & (nbs <= 1))
        if e[0].size == 0:                     # a ring has no endpoint
            continue
        endpoints.append((e[0], e[1]))

    return {"response": resp, "sigmas": sigmas, "skeleton": skel,
            "junctions": junctions, "segments": segments,
            "endpoints": endpoints, "n_segments": len(segments),
            "threshold_percentile": percentile}


def endpoint_map(traced, shape, um_per_px, sigma_um=1.5):
    """Density of fibre TERMINATIONS - the actin-insertion cue.

    Smoothed only lightly and isotropically. The anisotropic smoothing used for
    seam evidence assumes a long thin feature; an insertion zone is compact, and
    stretching it along x would spread it over neighbouring cells.
    """
    from scipy import ndimage as ndi

    pts = np.zeros(shape, dtype=float)
    for ys, xs in traced["endpoints"]:
        pts[ys, xs] += 1.0
    return ndi.gaussian_filter(pts, sigma_um / um_per_px), int(pts.sum())


def convergence_map(traced, shape, um_per_px, radius_um=3.0):
    """Where many fibres CONVERGE on one spot - the myocyte-end cue.

    Andres, on the midbody field: at each end of a myocyte, anterior and
    posterior, many fibres converge onto a single point. That is a POINT
    feature and much more constrained than a boundary curve, which is why it is
    worth detecting on its own rather than as part of a line search.

    Convergence is scored as endpoint density weighted by how much the local
    fibre DIRECTIONS disagree: many ends meeting from a single direction is the
    edge of a field of view, while many ends meeting from different directions
    is a tip.
    """
    from scipy import ndimage as ndi

    H, W = shape
    ends_y, ends_x, dirs = [], [], []
    for (ys, xs), (sy, sx) in zip(traced["segments"], traced["endpoints"]):
        if sy.size == 0:
            continue
        # segment direction from its principal axis
        if ys.size >= 2:
            yy = ys - ys.mean()
            xx = xs - xs.mean()
            theta = 0.5 * np.arctan2(2 * (yy * xx).sum(),
                                     (xx ** 2).sum() - (yy ** 2).sum())
        else:
            theta = 0.0
        for k in range(sy.size):
            ends_y.append(sy[k]); ends_x.append(sx[k]); dirs.append(theta)

    if not ends_y:
        return np.zeros(shape), 0
    ends_y = np.asarray(ends_y); ends_x = np.asarray(ends_x)
    dirs = np.asarray(dirs)

    dens = np.zeros(shape); cd = np.zeros(shape); sd = np.zeros(shape)
    np.add.at(dens, (ends_y, ends_x), 1.0)
    np.add.at(cd, (ends_y, ends_x), np.cos(2 * dirs))
    np.add.at(sd, (ends_y, ends_x), np.sin(2 * dirs))

    r = radius_um / um_per_px
    dens_s = ndi.gaussian_filter(dens, r)
    cd_s = ndi.gaussian_filter(cd, r)
    sd_s = ndi.gaussian_filter(sd, r)
    with np.errstate(invalid="ignore", divide="ignore"):
        # 1 when directions all agree, 0 when they are spread out
        alignment = np.hypot(cd_s, sd_s) / np.maximum(dens_s, 1e-9)
    spread = np.clip(1.0 - alignment, 0.0, 1.0)
    return dens_s * spread, int(dens.sum())
