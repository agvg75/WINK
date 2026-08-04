"""Local fibre orientation from a phalloidin stack, and myocyte edges from it.

WHY ORIENTATION AND NOT INTENSITY. Phalloidin labels actin, so what is imaged is
FIBRES, not cell boundaries. There is no intensity edge at a myocyte border -
both sides are bright - which is why intensity segmentation fails there and will
keep failing however it is tuned. The boundary is not an intensity feature.

It is an orientation feature. Within one myocyte the fibres run at a consistent
angle; the neighbouring cell's run at a different one. The border is where the
dominant local orientation turns, or where alignment collapses in the gap. That
is computable: a structure tensor gives a dominant direction and a coherence per
neighbourhood, and boundaries fall out as discontinuities in that field.

WHY THIS NEEDS THE STACK. In a maximum projection the orientation field is an
average over superimposed quadrants, which smears exactly the signal being keyed
on. This lab already acquires so as to stop shy of the contralateral side,
precisely to keep the other side's muscle out of the projection - so the depth
information needed here is already being collected on purpose.

WHAT THIS MODULE DOES NOT DO. It proposes candidate dividers; it does not decide
where a myocyte ends. Every output is a proposal for a human, and the moment
proposals are shown, marks made against them stop being clean ground truth (see
docs/specs/muscle_boundary_volume_spec.md §5). Bank unassisted marks first.
"""
from __future__ import annotations

import numpy as np

# Acquisition facts this module is built around, from the lab's own practice:
#   * images are zoomed to a region - head (pharynx), midbody (vulva) or
#     posterior (tail) - and the region is recorded in the file name
#   * most are oriented anterior-left, which matters most at midbody where the
#     vulva fixes position along the body but not which way is anterior
#   * depth stops short of the contralateral side on purpose
# so the z extent is NOT the animal's extent and nothing here may assume it is.
REGIONS = ("head", "midbody", "posterior")


def structure_tensor_2d(plane, sigma=2.0, rho=4.0):
    """Dominant fibre angle and coherence for one plane.

    Returns (angle_deg, coherence) where angle is in [0, 180) - fibres are
    undirected, so 10 degrees and 190 degrees are the same fibre - and
    coherence is 0..1: how consistently aligned that neighbourhood is.

    Coherence is what makes this usable rather than merely computable. A
    neighbourhood with no fibres has a meaningless dominant angle, and reporting
    it as though it were a measurement is how an orientation map turns into
    confident noise.
    """
    from scipy import ndimage as ndi

    img = np.asarray(plane, dtype=float)
    smooth = ndi.gaussian_filter(img, sigma)
    gy, gx = np.gradient(smooth)
    # Tensor components, then smoothed over the integration scale rho. rho is
    # what sets "local" - too small and every fibre is its own region, too large
    # and a true boundary is averaged away.
    jxx = ndi.gaussian_filter(gx * gx, rho)
    jyy = ndi.gaussian_filter(gy * gy, rho)
    jxy = ndi.gaussian_filter(gx * gy, rho)

    diff = jxx - jyy
    denom = np.hypot(diff, 2.0 * jxy)
    trace = jxx + jyy
    with np.errstate(invalid="ignore", divide="ignore"):
        coherence = np.where(trace > 1e-12, denom / trace, 0.0)
    # Eigenvector of the SMALLEST eigenvalue is along the fibre.
    angle = 0.5 * np.arctan2(2.0 * jxy, diff)
    angle_deg = (np.degrees(angle) + 90.0) % 180.0
    return angle_deg, np.clip(coherence, 0.0, 1.0)


def orientation_volume(stack, sigma=2.0, rho=4.0, mask=None):
    """Per-plane orientation and coherence for a (Z, Y, X) stack.

    Applied plane by plane rather than as a 3-D tensor on purpose: the lab's
    stacks are anisotropic - z spacing is several times the lateral pixel - so a
    3-D neighbourhood would be badly elongated in depth and would mix planes
    that are physically far apart.
    """
    stack = np.asarray(stack)
    if stack.ndim != 3:
        raise ValueError(
            f"Expected a (Z, Y, X) stack, got shape {stack.shape}. Orientation "
            f"is computed per plane, so the depth axis must be explicit.")
    angles = np.zeros(stack.shape, dtype=float)
    coherence = np.zeros(stack.shape, dtype=float)
    for z in range(stack.shape[0]):
        a, c = structure_tensor_2d(stack[z], sigma=sigma, rho=rho)
        if mask is not None:
            c = np.where(mask[z], c, 0.0)
        angles[z], coherence[z] = a, c
    return angles, coherence


def pick_actin_channel(stack, sigma=1.5, rho=6.0, min_coherence=0.35,
                       min_bright_fraction=0.005):
    """Which channel holds the actin, or None if none of them does.

    Returning None is the point. An argmax always names a winner, and on an
    unstained acquisition that winner is whatever channel happens to have the
    most texture - in this lab's no-phalloidin controls that is the TRANSMITTED
    LIGHT channel, and the pipeline then reports gut texture as muscle
    architecture with no outward sign anything went wrong. Verified against
    230518_pezo-1.lif: the stained series has p99=73 in the phalloidin channel,
    the controls have p99=0.0 and 1.0.

    Note these controls are not blank images - the lab does not mount and image
    a worm without some signal to justify it, so a reporter is usually present
    in another channel. The test therefore cannot be 'is anything bright'; it
    has to be 'is there aligned fibrous signal', which is what coherence over
    genuinely bright voxels measures.

    Returns (channel_index, report). channel_index is None when no channel
    qualifies, and report carries the per-channel numbers either way so a
    refusal can be inspected rather than merely obeyed.
    """
    n_c = stack.shape[1] if stack.ndim == 4 else 1
    zmid = stack.shape[0] // 2
    per_channel, best, best_score = [], None, 0.0
    for c in range(n_c):
        plane = (stack[zmid, c] if stack.ndim == 4 else stack[zmid]).astype(float)
        p99 = float(np.percentile(plane, 99))
        bright = plane > max(p99 * 0.5, 1.0)
        frac = float(bright.mean())
        # A fluorescence channel is mostly BACKGROUND - dark everywhere the
        # label is not. A transmitted-light / DIC channel has no dark
        # background at all, and it is textured enough to score respectable
        # coherence, so without this test it wins the unstained controls and
        # gut texture gets reported as muscle. Measured: this lab's DIC channel
        # sits at background_ratio ~0.65 in both stained and unstained series,
        # the phalloidin channel at ~0.02. That is a structural difference
        # between imaging modes, not a threshold tuned to one dataset.
        ratio = float(np.median(plane) / p99) if p99 > 0 else 1.0
        transmitted = ratio > 0.25
        if transmitted or frac < min_bright_fraction or p99 <= 1.0:
            per_channel.append({
                "channel": c, "p99": p99, "bright_fraction": frac,
                "background_ratio": ratio, "coherence": 0.0,
                "qualifies": False,
                "rejected_because": ("looks like transmitted light, not "
                                     "fluorescence" if transmitted else
                                     "too little signal above background")})
            continue
        _, coh = structure_tensor_2d(plane, sigma=sigma, rho=rho)
        score = float(coh[bright].mean())
        qualifies = score >= min_coherence
        per_channel.append({"channel": c, "p99": p99, "bright_fraction": frac,
                            "background_ratio": ratio, "coherence": score,
                            "qualifies": qualifies,
                            "rejected_because": None if qualifies else
                            "signal present but not aligned into fibres"})
        if qualifies and score > best_score:
            best, best_score = c, score

    report = {"channels": per_channel, "chosen": best,
              "min_coherence": min_coherence}
    if best is None:
        report["refusal"] = (
            "No channel carries aligned fibrous signal (best coherence over "
            "bright voxels was below {:.2f}). Measuring anyway would report "
            "whatever channel has the most texture - typically transmitted "
            "light - as muscle architecture.".format(min_coherence))
    return best, report


def _angular_difference(a, b):
    """Smallest angle between two undirected orientations, in degrees."""
    d = np.abs(a - b) % 180.0
    return np.minimum(d, 180.0 - d)


def divider_profile(angles, coherence, axis_is_x=True, min_coherence=0.15):
    """Turn the orientation field into a 1-D signal along the body axis.

    Myocytes tile along the length, so a boundary shows as a turn in the
    coherence-weighted mean angle as you walk along that axis. Weighting by
    coherence is what keeps empty background from voting.
    """
    angles = np.asarray(angles, dtype=float)
    coherence = np.asarray(coherence, dtype=float)
    if angles.ndim == 3:
        angles = angles.reshape(-1, *angles.shape[-2:])
        coherence = coherence.reshape(-1, *coherence.shape[-2:])
    else:
        angles = angles[None]
        coherence = coherence[None]

    weights = np.where(coherence >= min_coherence, coherence, 0.0)
    axis = 1 if axis_is_x else 2          # collapse the OTHER lateral axis
    # Circular mean on doubled angles, because fibres are undirected.
    doubled = np.deg2rad(angles * 2.0)
    sx = (np.cos(doubled) * weights).sum(axis=(0, axis))
    sy = (np.sin(doubled) * weights).sum(axis=(0, axis))
    support = weights.sum(axis=(0, axis))
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_angle = (np.degrees(np.arctan2(sy, sx)) / 2.0) % 180.0
    mean_angle = np.where(support > 0, mean_angle, np.nan)
    return mean_angle, support


def orientation_step_map(angles, coherence, window_x=60, window_y=40,
                         min_coherence=0.15):
    """2-D map of how much the fibre direction turns across each location.

    The 1-D version collapses the image onto the body axis, which averages
    together structures that are simply different - cuticle, one quadrant, the
    next - and destroys the signal. Myocytes are RHOMBOID and tile in two
    dimensions, so the boundary is a slanted curve and the evidence for it has
    to stay 2-D.

    Compares the coherence-weighted mean orientation in a box to the left of
    each pixel against a box to its right, using doubled angles so undirected
    fibres average correctly.
    """
    from scipy import ndimage as ndi

    angles = np.asarray(angles, dtype=float)
    coherence = np.asarray(coherence, dtype=float)
    if angles.ndim == 3:                       # collapse depth first
        w = np.where(coherence >= min_coherence, coherence, 0.0)
        d = np.deg2rad(angles * 2.0)
        C = (np.cos(d) * w).sum(axis=0)
        S = (np.sin(d) * w).sum(axis=0)
        W = w.sum(axis=0)
    else:
        w = np.where(coherence >= min_coherence, coherence, 0.0)
        d = np.deg2rad(angles * 2.0)
        C, S, W = np.cos(d) * w, np.sin(d) * w, w

    box = (window_y, window_x)
    Cb = ndi.uniform_filter(C, box)
    Sb = ndi.uniform_filter(S, box)
    Wb = ndi.uniform_filter(W, box)

    half = max(window_x // 2, 1)
    def shift(a, k):
        return np.roll(a, k, axis=1)

    out = np.zeros(C.shape, dtype=float)
    left = (shift(Cb, half), shift(Sb, half), shift(Wb, half))
    right = (shift(Cb, -half), shift(Sb, -half), shift(Wb, -half))
    with np.errstate(invalid="ignore", divide="ignore"):
        al = (np.degrees(np.arctan2(left[1], left[0])) / 2.0) % 180.0
        ar = (np.degrees(np.arctan2(right[1], right[0])) / 2.0) % 180.0
        out = _angular_difference(al, ar)
    # Where either side had no aligned signal the comparison is meaningless.
    support = np.minimum(left[2], right[2])
    out = np.where(support > 0, out, 0.0)
    out[:, :half] = 0.0
    out[:, -half:] = 0.0
    return out, support


def brightness_step_map(image, um_per_px, cell_um=30.0, striation_um=2.0):
    """2-D map of where per-cell staining brightness steps.

    Phalloidin penetrates each myocyte individually, so each cell carries its
    own brightness - varying smoothly inside the cell and stepping at the
    neighbour. Three scales are superimposed and only the middle one is
    biology, so this is a BAND-pass: blur out the sarcomere striations, then
    subtract the illumination and depth falloff, which is much stronger than
    the per-cell steps and would otherwise dominate any gradient.
    """
    from scipy import ndimage as ndi

    img = np.asarray(image, dtype=float)
    s_small = max(striation_um / um_per_px, 0.8)
    s_large = max(cell_um * 1.5 / um_per_px, s_small * 3)
    banded = ndi.gaussian_filter(img, s_small) - ndi.gaussian_filter(img, s_large)
    gy, gx = np.gradient(banded)
    grad = ndi.gaussian_filter(np.hypot(gy, gx), s_small)
    return grad, banded


def _norm(a, lo_pct=50, hi_pct=99):
    a = np.asarray(a, dtype=float)
    lo, hi = np.percentile(a, [lo_pct, hi_pct])
    if hi <= lo:
        return np.zeros_like(a)
    return np.clip((a - lo) / (hi - lo), 0.0, 1.0)


def boundary_evidence(angles, coherence, image, um_per_px, **kw):
    """Combine two INDEPENDENT cues into myocyte-boundary evidence.

    Andres's framing, and the same shape as the pBoC three-detector design:
    fibre orientation tends to break between myocytes, AND each cell has a
    mostly unique brightness signature. Either alone is weak. The two
    COINCIDING is the strong indicator.

    The independence is not an assumption here, it is a property that is
    tested: the structure tensor's angle derives from gradient DIRECTION, which
    is invariant to intensity scaling, so a pure brightness step produces no
    angle turn - see the adversarial case in tests/test_fibre_orientation.py.
    That is what licenses treating agreement as evidence rather than as two
    views of the same measurement.

    Combined with a GEOMETRIC mean, so evidence collapses if either cue is
    absent. An arithmetic mean would let one loud cue carry a boundary on its
    own, which is exactly the failure this design exists to prevent.

    Returns a dict keeping the cues SEPARATE as well as combined - so a human
    can see which cue fired where, and disagreement stays visible instead of
    being averaged into a single confident-looking number.
    """
    turn, support = orientation_step_map(angles, coherence,
                                         window_x=kw.get("window_x", 60),
                                         window_y=kw.get("window_y", 40))
    grad, banded = brightness_step_map(image, um_per_px,
                                       cell_um=kw.get("cell_um", 30.0))
    a = _norm(turn)
    b = _norm(grad)
    return {
        "orientation_step": turn,
        "brightness_step": grad,
        "brightness_banded": banded,
        "orientation_norm": a,
        "brightness_norm": b,
        "combined": np.sqrt(a * b),
        "combiner": "geometric mean - both cues required",
        "support": support,
    }


def longitudinal_evidence(image, angles, coherence, um_per_px,
                          row_um=10.0, striation_um=1.5):
    """Evidence for a LONGITUDINAL myocyte seam at each pixel.

    Andres's hand marks settled the geometry: 99% of boundary ink runs within
    30 degrees of the body axis. Cells tile in rows stacked across the width,
    so a seam is a step ACROSS y, not along x. Everything here is therefore
    differentiated in y - the transpose of the first, wrong, design.

    Two cues, kept separate:
      * brightness - each myocyte takes up phalloidin individually, so the
        band-passed intensity steps between rows. Differentiated across y.
      * fibre continuity - at a seam one cell's striations end and the next's
        begin, usually offset. The fibres either side are nearly PARALLEL
        there, so an angle-turn detector is the wrong instrument; what breaks
        is alignment, which shows as a coherence trough.
    """
    from scipy import ndimage as ndi

    img = np.asarray(image, dtype=float)
    s_small = max(striation_um / um_per_px, 0.8)
    s_row = max(row_um / um_per_px, s_small * 2)

    # Band-pass, then step across y. Smooth ALONG x much harder than across y:
    # a seam is coherent over a long run in x and thin in y, so anisotropic
    # smoothing raises it above texture without blurring the thing being found.
    banded = ndi.gaussian_filter(img, s_small) - ndi.gaussian_filter(img, s_row)
    dy = ndi.gaussian_filter1d(banded, s_small, axis=0, order=1)
    # Elongate along x, but only mildly. Smoothing hard in x flattens the
    # evidence into horizontal bands, and the traced path then cannot follow a
    # boundary that slants - which is most of them, since myocytes are
    # rhomboid. The anisotropy has to be enough to suppress texture and no
    # more.
    bright = ndi.gaussian_filter(np.abs(dy), (s_small, s_row * 0.75))

    # Alignment trough, likewise mildly elongated along x.
    coh2d = np.nanmean(np.asarray(coherence, dtype=float), axis=0) \
        if np.asarray(coherence).ndim == 3 else np.asarray(coherence, dtype=float)
    coh_s = ndi.gaussian_filter(coh2d, (s_small, s_row * 0.75))
    trough = np.clip(ndi.gaussian_filter(coh_s, (s_row, s_row)) - coh_s, 0, None)

    # Normalise from a LOW floor. The default _norm clips at the median, which
    # zeroes half the field; a geometric mean of two such maps is exact zero
    # almost everywhere and the path search then runs on noise rather than on
    # evidence. Seam tracing needs a graded field, not a sparse one.
    a, b = _norm(bright, 5, 99), _norm(trough, 5, 99)
    return {"brightness_step_y": bright, "alignment_trough": trough,
            "brightness_norm": a, "alignment_norm": b,
            "combined": np.sqrt(a * b), "banded": banded}


def trace_seams(evidence, n_seams=6, min_separation_px=12, max_slope=1):
    """Find the strongest left-to-right seams through an evidence map.

    Dynamic programming over paths that step at most `max_slope` pixels in y
    per column. That constraint is the anatomy: a myocyte seam drifts gently
    across the field, so a path free to jump would fit noise, and a path
    forced straight could not follow a rhomboid edge. It also makes a vertical
    boundary structurally impossible to return, which is the failure mode the
    first design produced.

    Seams are taken strongest-first with a suppression band between them, so
    one strong boundary cannot be reported several times over.
    """
    E = np.asarray(evidence, dtype=float)
    H, W = E.shape
    avail = np.ones(H, dtype=bool)
    seams, scores = [], []

    for _ in range(int(n_seams)):
        work = np.where(avail[:, None], E, -1e6)
        cost = np.full((H, W), -np.inf)
        back = np.zeros((H, W), dtype=int)
        cost[:, 0] = work[:, 0]
        offs = list(range(-max_slope, max_slope + 1))
        for x in range(1, W):
            best = np.full(H, -np.inf)
            bidx = np.zeros(H, dtype=int)
            for o in offs:
                shifted = np.full(H, -np.inf)
                if o < 0:
                    shifted[-o:] = cost[:H + o, x - 1]
                elif o > 0:
                    shifted[:H - o] = cost[o:, x - 1]
                else:
                    shifted = cost[:, x - 1]
                better = shifted > best
                best = np.where(better, shifted, best)
                bidx = np.where(better, o, bidx)
            cost[:, x] = work[:, x] + best
            back[:, x] = bidx

        end = int(np.argmax(cost[:, -1]))
        if not np.isfinite(cost[end, -1]) or cost[end, -1] < -1e5:
            break
        path = np.zeros(W, dtype=int)
        path[-1] = end
        for x in range(W - 1, 0, -1):
            # back holds the OFFSET o such that shifted[y] == cost[y + o],
            # i.e. the predecessor row is y + o. Subtracting it instead of
            # adding walks every path the wrong way.
            path[x - 1] = np.clip(path[x] + back[path[x], x], 0, H - 1)
        mean_e = float(E[path, np.arange(W)].mean())
        seams.append(path)
        scores.append(mean_e)
        for x in range(W):
            lo = max(path[x] - min_separation_px, 0)
            hi = min(path[x] + min_separation_px + 1, H)
            avail[lo:hi] = False
        if not avail.any():
            break

    order = np.argsort([-s for s in scores])
    return [seams[i] for i in order], [scores[i] for i in order]


def _windowed_mean_angle(mean_angle, lo, hi):
    """Circular mean of undirected angles over a slice, NaNs ignored."""
    seg = mean_angle[lo:hi]
    seg = seg[np.isfinite(seg)]
    if seg.size == 0:
        return np.nan
    d = np.deg2rad(seg * 2.0)
    return (np.degrees(np.arctan2(np.sin(d).sum(), np.cos(d).sum())) / 2.0) % 180.0


def propose_dividers(mean_angle, support, expected=None, min_turn_deg=8.0,
                     min_separation=10, window=12):
    """Candidate myocyte boundaries: where the mean fibre angle turns.

    `window` MUST be at least the tensor's integration scale rho, and is the
    detail that decides whether this works at all. The structure tensor smooths
    over rho, so a step change in fibre angle arrives as a ramp about 2*rho
    wide. Comparing adjacent samples across that ramp measures the ramp's slope,
    not the turn: a genuine 38-degree boundary reads as 6 degrees per step and
    is discarded as noise. Comparing a window BEFORE against a window AFTER
    recovers the full turn. Set window too small and every real boundary
    vanishes; too large and neighbouring boundaries average into each other.

    `expected` is the number of dividers anticipated - 23 between 24 cells in a
    quadrant, or fewer for the zoomed-to-a-region images this lab actually
    acquires - which turns an open-ended segmentation into a far more
    constrained problem. It is a PRIOR, not a quota: if the field only supports
    nine defensible turns, nine are returned and the shortfall is reported.
    Padding to the expected count would manufacture boundaries that would be
    indistinguishable, downstream, from measured ones.
    """
    mean_angle = np.asarray(mean_angle, dtype=float)
    support = np.asarray(support, dtype=float)
    n = mean_angle.size
    window = max(2, int(window))
    turn = np.full(n, np.nan)
    for i in range(window, n - window):
        a = _windowed_mean_angle(mean_angle, i - window, i)
        b = _windowed_mean_angle(mean_angle, i + 1, i + 1 + window)
        if np.isfinite(a) and np.isfinite(b):
            turn[i] = _angular_difference(a, b)

    usable = np.isfinite(turn) & (support > 0)
    order = np.argsort(np.where(usable, -np.nan_to_num(turn, nan=-1), 1))
    picked = []
    for idx in order:
        if not usable[idx] or turn[idx] < min_turn_deg:
            continue
        if any(abs(idx - p) < min_separation for p in picked):
            continue
        picked.append(int(idx))
        if expected is not None and len(picked) >= expected:
            break

    picked.sort()
    result = {
        "dividers": picked,
        "n_found": len(picked),
        "expected": expected,
        "min_turn_deg": float(min_turn_deg),
        "window": window,
        "turn_profile": turn,
    }
    if expected is not None and len(picked) < expected:
        result["shortfall"] = expected - len(picked)
        result["shortfall_note"] = (
            f"Found {len(picked)} defensible turns against {expected} expected. "
            f"The remainder are NOT padded in: a boundary invented to reach a "
            f"quota would look exactly like a measured one.")
    return result
