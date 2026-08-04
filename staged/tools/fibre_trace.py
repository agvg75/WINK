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


# Minimum fibre-segment length before its endpoints are counted, per region.
# Head and midbody want OPPOSITE settings, and this is the third independent
# parameter where that is true - so the region split is structural, not a
# nuisance. Region is recorded in the lab's file names, so a pipeline can pick
# without asking anyone.
#   midbody  every endpoint counts        80.1% vs 71.8% at a 2 um filter
#   head     short fragments must be cut  45.8% vs 32.4% with no filter
# WHY the two regions differ is NOT known, and a plausible explanation was
# tested and refuted rather than left standing:
#   * "the head field fragments more" - FALSE. Head fibre segments are LONGER
#     (mean 15.1 um) than midbody (9.2 um).
#   * "headedness is body taper, since the animal tapers at head and tail and
#     holds diameter at midbody" (Andres) - NOT SUPPORTED by what could be
#     measured here: head taper 0.173 um/um against midbody 0.244, the wrong
#     way round, and within-field correlation between taper and segment length
#     is weak and inconsistent in sign (+0.14 midbody, -0.11 head).
# That test is WEAK though and does not settle the taper idea: both fields are
# 150-185 um crops of a ~1000 um animal, and the width measured is the muscle
# band inside a hand-chosen crop, so it reflects the framing as much as the
# animal. Testing it properly needs fields at known positions along one animal,
# or a low-magnification whole-worm image to measure the taper profile.
# Until then these values are EMPIRICAL, fitted on one field each, and should
# not be presented as though the mechanism were understood.
MIN_SEGMENT_UM = {"midbody": 0.0, "head": 2.0, "posterior": 2.0, None: 0.0}


def boundary_evidence(image, angles, coherence, um_per_px, reach_um=25.0,
                      percentile=55, edge_margin_um=6.0, region=None,
                      min_segment_um=None):
    """Myocyte boundary evidence from FIBRES ALONE - the best combination found.

    Two cues, both derived from individual fibres rather than from intensity:
      * endpoint density - where fibres terminate, which marks the whole
        boundary
      * convergence vote - where fibres converge, which marks the ENDS of a
        boundary specifically

    Multiplied, not added. Measured on the held-out midbody field:
        endpoints x convergence   80.1% recall, median error 0.99 um
        endpoints + convergence   71.1%
        max(endpoints, converg.)  66.5%
        endpoints alone           49.7%
        convergence alone         47.2%
        valley+alignment+thickness 33.1%   (the previous intensity-based set)

    WHY THE PRODUCT. The two are complementary in SCOPE, not alternatives.
    Relative elevation on that field: convergence 0.667 at a vertex against
    0.291 on a boundary away from one, endpoints 0.843 against 0.718. So
    endpoints say a boundary passes here and convergence says this part of it
    is an end. Their product is high only where both agree. They are positively
    correlated (+0.09 on boundaries), so an OR discards the agreement that
    carries the information.

    WHAT IS DELIBERATELY EXCLUDED, and why it matters more than what is
    included: the intensity-derived cues - valley, alignment, thickness - are
    NOT used. Including them alongside these two dropped recall from 80.1% to
    38.7%, because a weighted geometric mean is an AND and the weakest member
    sets the ceiling. Three rounds of work went into adding cues to a set whose
    worst members were the limit. Do not add cues here without measuring
    end-to-end recall on a field that had no part in the decision.
    """
    from scipy import ndimage as ndi

    if min_segment_um is None:
        min_segment_um = MIN_SEGMENT_UM.get(region, 0.0)
    traced = trace_fibres(image, um_per_px, percentile=percentile)
    shape = np.asarray(image).shape
    pts = np.zeros(shape, dtype=float)
    for (sy, sx), (ey, ex) in zip(traced["segments"], traced["endpoints"]):
        if len(sy) * um_per_px < min_segment_um:
            continue
        pts[ey, ex] += 1.0
    n_ends = int(pts.sum())
    ends_map = ndi.gaussian_filter(pts, 1.5 / um_per_px)
    vote, count = convergence_vote(angles, coherence, um_per_px,
                                   reach_um=reach_um)
    # Votes pile up against the frame edge because rays terminate there. That
    # is a property of the field of view, not a myocyte end.
    m = int(edge_margin_um / um_per_px)
    if m > 0:
        vote[:, :m] = 0; vote[:, -m:] = 0
        vote[:m, :] = 0; vote[-m:, :] = 0

    E = _norm01(ends_map)
    C = _norm01(vote)
    return {"endpoints": E, "convergence": C, "combined": np.sqrt(E * C),
            "n_endpoints": n_ends, "min_segment_um": float(min_segment_um),
            "region": region,
            "combiner": "sqrt(endpoints * convergence); intensity cues "
                        "deliberately excluded"}


def _norm01(a, lo_pct=5, hi_pct=99):
    a = np.asarray(a, dtype=float)
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    if hi <= lo:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def convergence_vote(angles, coherence, um_per_px, reach_um=25.0,
                     min_coherence=0.25, step_um=0.5):
    """Find myocyte VERTICES by letting every fibre vote along its own direction.

    Andres's observation, and the reason this beats counting terminations:
    actin fibres begin deviating from parallel toward the insertion point well
    BEFORE they reach it, often a long way before. So the vertex is inferable
    from the direction field far away from it - which means it can be found
    even when the insertion itself is not resolved, and endpoint density cannot
    do that because it needs the termination to be visible.

    Each coherent pixel casts votes along its fibre bearing, forwards and
    backwards. Direction is accumulated as well as count, because a straight
    fibre votes along its whole length and would otherwise light up as a ridge:
    what marks a vertex is votes arriving from MANY DIFFERENT bearings.
    Parallel fibres all vote on the same bearing and cancel; converging ones
    accumulate.

    Returns (vote_map, count_map). The vote map is count weighted by directional
    spread, so it peaks at convergence points rather than along fibres.
    """
    from scipy import ndimage as ndi

    ang = np.asarray(angles, dtype=float)
    coh = np.asarray(coherence, dtype=float)
    if ang.ndim == 3:
        w = np.where(coh >= min_coherence, coh, 0.0)
        d = np.deg2rad(ang * 2.0)
        C = (np.cos(d) * w).sum(axis=0)
        S = (np.sin(d) * w).sum(axis=0)
        Wt = w.sum(axis=0)
        with np.errstate(invalid="ignore", divide="ignore"):
            theta = (np.arctan2(S, C) / 2.0)
        strength = np.where(Wt > 0, np.hypot(C, S) / np.maximum(Wt, 1e-9), 0.0)
        strength = np.where(Wt > 0, strength, 0.0)
    else:
        theta = np.deg2rad(ang)
        strength = np.where(coh >= min_coherence, coh, 0.0)

    H, W = theta.shape
    ys, xs = np.nonzero(strength > 0)
    if ys.size == 0:
        return np.zeros((H, W)), np.zeros((H, W))
    th = theta[ys, xs]
    wt = strength[ys, xs]
    dy_dir, dx_dir = np.sin(th), np.cos(th)

    count = np.zeros((H, W))
    cd = np.zeros((H, W))
    sd = np.zeros((H, W))
    reach = int(reach_um / um_per_px)
    step = max(int(step_um / um_per_px), 1)
    # Skip s = 0: a pixel voting for itself would just reproduce the fibre.
    for s in list(range(-reach, 0, step)) + list(range(step, reach + 1, step)):
        ty = np.rint(ys + s * dy_dir).astype(int)
        tx = np.rint(xs + s * dx_dir).astype(int)
        ok = (ty >= 0) & (ty < H) & (tx >= 0) & (tx < W)
        if not ok.any():
            continue
        idx = (ty[ok], tx[ok])
        np.add.at(count, idx, wt[ok])
        np.add.at(cd, idx, wt[ok] * np.cos(2 * th[ok]))
        np.add.at(sd, idx, wt[ok] * np.sin(2 * th[ok]))

    smooth = 2.0 / um_per_px
    count_s = ndi.gaussian_filter(count, smooth)
    cd_s = ndi.gaussian_filter(cd, smooth)
    sd_s = ndi.gaussian_filter(sd, smooth)
    with np.errstate(invalid="ignore", divide="ignore"):
        alignment = np.hypot(cd_s, sd_s) / np.maximum(count_s, 1e-9)
    spread = np.clip(1.0 - alignment, 0.0, 1.0)
    return count_s * spread, count_s


def convergence_vote_curved(angles, coherence, um_per_px, reach_um=25.0,
                            min_coherence=0.25, step_um=0.5, subsample=2):
    """Convergence vote that FOLLOWS the fibre instead of firing a straight ray.

    The straight-ray version smears its peaks, and the reason is geometric: if
    fibres are already curving toward the insertion - which is Andres's whole
    observation, that they deviate from parallel well before reaching it - then
    a tangent fired from any point lands somewhere short of where the fibre
    actually goes. Every pixel misses in a slightly different direction, so a
    real convergence spreads into a broad warm region rather than a peak.

    Here each vote walks the orientation field one step at a time, re-reading
    the local direction as it goes, so a curving fibre is followed around its
    curve. Orientation is undirected, so at each step the sense is resolved by
    taking whichever of the two directions continues the current heading.
    """
    from scipy import ndimage as ndi

    ang = np.asarray(angles, dtype=float)
    coh = np.asarray(coherence, dtype=float)
    if ang.ndim == 3:
        w = np.where(coh >= min_coherence, coh, 0.0)
        d = np.deg2rad(ang * 2.0)
        C = (np.cos(d) * w).sum(axis=0)
        S = (np.sin(d) * w).sum(axis=0)
        Wt = w.sum(axis=0)
        theta = np.arctan2(S, C) / 2.0
        strength = np.where(Wt > 0, np.hypot(C, S) / np.maximum(Wt, 1e-9), 0.0)
    else:
        theta = np.deg2rad(ang)
        strength = np.where(coh >= min_coherence, coh, 0.0)

    H, W = theta.shape
    ys, xs = np.nonzero(strength > 0)
    if ys.size == 0:
        return np.zeros((H, W)), np.zeros((H, W))
    if subsample > 1:
        keep = ((ys % subsample == 0) & (xs % subsample == 0))
        ys, xs = ys[keep], xs[keep]
    wt0 = strength[ys, xs]

    count = np.zeros((H, W))
    cd = np.zeros((H, W))
    sd = np.zeros((H, W))
    step = max(step_um / um_per_px, 0.5)
    n_steps = int(reach_um / um_per_px / step)

    for sense in (+1.0, -1.0):
        py = ys.astype(float).copy()
        px = xs.astype(float).copy()
        th0 = theta[ys, xs]
        hy = sense * np.sin(th0)
        hx = sense * np.cos(th0)
        alive = np.ones(py.shape, dtype=bool)
        for _ in range(n_steps):
            iy = np.clip(np.rint(py).astype(int), 0, H - 1)
            ix = np.clip(np.rint(px).astype(int), 0, W - 1)
            t = theta[iy, ix]
            dy_, dx_ = np.sin(t), np.cos(t)
            # undirected: keep the sense that continues the current heading
            flip = (dy_ * hy + dx_ * hx) < 0
            dy_ = np.where(flip, -dy_, dy_)
            dx_ = np.where(flip, -dx_, dx_)
            hy, hx = dy_, dx_
            py = py + step * dy_
            px = px + step * dx_
            alive &= (py >= 0) & (py < H) & (px >= 0) & (px < W)
            if not alive.any():
                break
            iy = np.clip(np.rint(py).astype(int), 0, H - 1)[alive]
            ix = np.clip(np.rint(px).astype(int), 0, W - 1)[alive]
            wv = wt0[alive]
            hh = np.arctan2(hy[alive], hx[alive])
            np.add.at(count, (iy, ix), wv)
            np.add.at(cd, (iy, ix), wv * np.cos(2 * hh))
            np.add.at(sd, (iy, ix), wv * np.sin(2 * hh))

    smooth = 2.0 / um_per_px
    count_s = ndi.gaussian_filter(count, smooth)
    cd_s = ndi.gaussian_filter(cd, smooth)
    sd_s = ndi.gaussian_filter(sd, smooth)
    with np.errstate(invalid="ignore", divide="ignore"):
        alignment = np.hypot(cd_s, sd_s) / np.maximum(count_s, 1e-9)
    return count_s * np.clip(1.0 - alignment, 0.0, 1.0), count_s


def find_vertices(vote_map, um_per_px, min_separation_um=8.0, max_vertices=40):
    """Peaks of the convergence vote - candidate myocyte ends."""
    from skimage.feature import peak_local_max

    pk = peak_local_max(np.asarray(vote_map, dtype=float),
                        min_distance=max(int(min_separation_um / um_per_px), 3),
                        num_peaks=int(max_vertices), exclude_border=False)
    scores = np.asarray(vote_map)[pk[:, 0], pk[:, 1]] if len(pk) else np.array([])
    order = np.argsort(-scores)
    return pk[order], scores[order]


def pair_vertices(vertices, scores, angles, coherence, um_per_px,
                  min_length_um=15.0, max_length_um=90.0, max_offset_um=12.0):
    """Pair vertices that FACE each other, as the two ends of one myocyte.

    Andres: for most of this lab's work the myocytes are fully contained in the
    image, so both ends are present and facing each other. That is a strong
    structural constraint rather than an observation to rediscover - a lone
    vertex is suspect, while a facing pair is evidence for one cell.

    Pairs are required to lie roughly along the body axis and to be separated
    by a plausible myocyte length, and each vertex is used at most once.
    """
    verts = np.asarray(vertices, dtype=float)
    if verts.ndim != 2 or verts.shape[0] < 2:
        return []
    n = verts.shape[0]
    lo = min_length_um / um_per_px
    hi = max_length_um / um_per_px
    off = max_offset_um / um_per_px

    cands = []
    for i in range(n):
        for j in range(i + 1, n):
            dy = verts[j, 0] - verts[i, 0]
            dx = verts[j, 1] - verts[i, 1]
            dist = float(np.hypot(dy, dx))
            if not (lo <= dist <= hi):
                continue
            if abs(dy) > off:            # must face along the body axis
                continue
            cands.append((float(scores[i] + scores[j]), i, j, dist))

    cands.sort(reverse=True)
    used, pairs = set(), []
    for sc, i, j, dist in cands:
        if i in used or j in used:
            continue
        used.add(i); used.add(j)
        pairs.append({"a": tuple(verts[i].astype(int)),
                      "b": tuple(verts[j].astype(int)),
                      "length_um": dist * um_per_px, "score": sc})
    return pairs


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
