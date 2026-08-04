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
