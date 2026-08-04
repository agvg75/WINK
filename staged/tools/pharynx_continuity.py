"""Pharyngeal muscle CONTINUITY - interruptions, not shape.

ANDRES'S SPECIFICATION, and the reason this measures what it measures. In a
degenerating pharynx the muscle is INTERRUPTED: there are holes where muscle
should be. Separately, a worm that fixes poorly ends up with a BENT pharynx -
but bent is not broken. So continuity is a feature of degeneration that is
independent of shape, and shape is contaminated by fixation quality.

That solves the confound rather than correcting for it. A shape-based measure
would mix disease with mounting quality and no amount of statistics would
separate them afterwards. This is measured in a frame that bending cannot
change: the muscle is unrolled about the lumen, so a curved pharynx and a
straight one of the same health give the same answer, while a hole gives a
different one whatever the shape around it.

WHAT A HOLE IS NOT. Absent signal has two causes and only one is biology: the
muscle can be gone, or the light can be. A dim region deep in a stack, a
bleached patch, or a fold that shadows part of the organ all read as "no
actin". Every metric here therefore carries the local intensity context, and
`confidence` falls when the surrounding tissue is too dim to distinguish an
absent muscle from an unlit one. A gap reported without that context is not a
measurement, it is an accusation.
"""
from __future__ import annotations

import numpy as np


class ContinuityError(Exception):
    """Refusals that name the consequence."""


def unroll_about_lumen(image, centreline, um_per_px, radius_um=12.0,
                       n_radial=48, arc_step_um=0.5):
    """Resample the pharynx into (arc length along lumen) x (radius) space.

    This is the step that makes the measurement shape-invariant. Bending moves
    the lumen through the image but does not change how much muscle sits at a
    given distance along it, so a bent pharynx and a straight one of equal
    health unroll to the same picture. Any measure taken here inherits that
    invariance for free, rather than needing a shape correction that would
    itself have to be validated.
    """
    from scipy import ndimage as ndi

    img = np.asarray(image, dtype=float)
    H, W = img.shape
    cy = np.asarray(centreline, dtype=float)
    if cy.size != W:
        raise ContinuityError(
            f"The centreline has {cy.size} points for an image {W} columns "
            f"wide. Every position here is measured along the lumen, so a "
            f"mismatch would silently shift the whole unrolled map.")

    # arc length along the lumen, so a bent pharynx is not foreshortened
    dy = np.gradient(cy)
    ds = np.hypot(np.ones_like(dy), dy) * um_per_px
    arc = np.concatenate([[0.0], np.cumsum(ds)[:-1]])
    total = float(arc[-1])
    n_arc = max(int(total / arc_step_um), 8)
    arc_grid = np.linspace(0, total, n_arc)
    x_at = np.interp(arc_grid, arc, np.arange(W))
    y_at = np.interp(x_at, np.arange(W), cy)

    # local normal to the lumen
    slope = np.interp(x_at, np.arange(W), np.gradient(cy))
    norm = np.hypot(1.0, slope)
    ny, nx = 1.0 / norm, -slope / norm          # unit normal (y, x)

    radii = np.linspace(-radius_um, radius_um, n_radial) / um_per_px
    ys = y_at[None, :] + radii[:, None] * ny[None, :]
    xs = x_at[None, :] + radii[:, None] * nx[None, :]
    unrolled = ndi.map_coordinates(img, [ys, xs], order=1, mode="constant",
                                   cval=np.nan)
    return {"unrolled": unrolled, "arc_um": arc_grid,
            "radius_um": radii * um_per_px, "length_um": total,
            "n_arc": n_arc, "n_radial": n_radial}


def continuity_metrics(unrolled, arc_um, radius_um, tissue_percentile=60,
                       min_gap_um=1.5, dim_fraction=0.25):
    """Where is the muscle interrupted, and how confident is that?

    `filled_fraction` is the share of the muscle band carrying actin signal.
    `gaps` are runs along the lumen where a whole cross-section is empty - the
    holes Andres describes - measured in micrometres so they are comparable
    between animals and objectives.

    THE HONEST PART is `confidence`. Signal can be absent because the muscle is
    gone or because the light was. Where the surrounding tissue is itself dim,
    an empty cross-section cannot be told from an unlit one, and those runs are
    reported SEPARATELY as `unlit_um` rather than counted as damage. A pipeline
    that folded them together would report bleaching as dystrophy.
    """
    u = np.asarray(unrolled, dtype=float)
    finite = np.isfinite(u)
    if finite.sum() < u.size * 0.2:
        raise ContinuityError(
            "Most of the unrolled band falls outside the image, so continuity "
            "cannot be measured over it. Crop or re-centre the lumen first - a "
            "fraction computed over a mostly-absent band would look like "
            "severe damage.")

    vals = u[finite]
    # Threshold from the DYNAMIC RANGE, not from a percentile of the values.
    # A percentile lands wherever most pixels are, which in a band that is
    # mostly background is exactly the background level - a knife edge, where
    # interpolation noise alone flips pixels either side. That is not a
    # fixture artefact: it made a 12 um hole read as 10% lit instead of 0%,
    # so a real hole scored as intact muscle.
    lo = float(np.percentile(vals, 20))
    hi = float(np.percentile(vals, 95))
    span = hi - lo
    if span <= 0:
        raise ContinuityError(
            "The unrolled band has no intensity range at all - every pixel is "
            "the same value. Continuity cannot be judged, and reporting a "
            "filled fraction from a flat image would be meaningless.")
    thr = lo + 0.25 * span
    bright = np.where(finite, u > thr, False)

    per_arc = bright.mean(axis=0)               # share of the cross-section lit
    # DISTINGUISHING A HOLE FROM AN UNLIT STRETCH is the whole difficulty here,
    # because both have no muscle signal. The discriminator is the BACKGROUND,
    # not the peak:
    #   * muscle gone, light fine  -> background normal, no bright band
    #   * light did not arrive     -> even background and autofluorescence dark
    # Testing the peak instead cannot separate them - a hole has no peak either,
    # so every hole would be dismissed as unlit and degeneration would measure
    # as zero. Testing the median fails the other way: muscle occupies only a
    # third of the band, so the median is background everywhere and the test
    # never fires, counting genuinely unlit stretches as damage.
    intensity = np.where(finite, u, np.nan)
    per_arc_floor = np.nanpercentile(intensity, 10, axis=0)
    overall_floor = float(np.nanpercentile(vals, 10))
    too_dim = per_arc_floor < max(overall_floor, 1e-12) * dim_fraction

    step = float(np.mean(np.diff(arc_um))) if arc_um.size > 1 else 1.0
    min_run = max(int(min_gap_um / max(step, 1e-9)), 1)

    def runs(mask):
        out, start = [], None
        for i, v in enumerate(mask):
            if v and start is None:
                start = i
            elif not v and start is not None:
                if i - start >= min_run:
                    out.append((start, i))
                start = None
        if start is not None and len(mask) - start >= min_run:
            out.append((start, len(mask)))
        return out

    empty = per_arc <= 0.05
    gap_runs = runs(empty & ~too_dim)
    unlit_runs = runs(empty & too_dim)

    gaps = [{"start_um": float(arc_um[a]),
             "end_um": float(arc_um[min(b, len(arc_um) - 1)]),
             "length_um": float(arc_um[min(b, len(arc_um) - 1)] - arc_um[a])}
            for a, b in gap_runs]
    gap_total = float(sum(g["length_um"] for g in gaps))
    unlit_total = float(sum(arc_um[min(b, len(arc_um) - 1)] - arc_um[a]
                            for a, b in unlit_runs))
    length = float(arc_um[-1] - arc_um[0]) if arc_um.size else 0.0

    measurable = max(length - unlit_total, 1e-9)
    return {
        "length_um": round(length, 3),
        "filled_fraction": round(float(np.nanmean(per_arc)), 4),
        "n_gaps": len(gaps),
        "gap_total_um": round(gap_total, 3),
        "gap_fraction_of_measurable": round(gap_total / measurable, 4),
        "largest_gap_um": round(max([g["length_um"] for g in gaps], default=0.0), 3),
        "gaps": gaps,
        "unlit_um": round(unlit_total, 3),
        "unlit_fraction": round(unlit_total / max(length, 1e-9), 4),
        "measurable_length_um": round(measurable, 3),
        "confidence": round(float(1.0 - unlit_total / max(length, 1e-9)), 4),
        "confidence_meaning": ("share of the pharynx bright enough that an "
                               "absent muscle can be told from an unlit one"),
        "confidence_calibrated": False,
        "shape_invariant": True,
        "note": ("Measured after unrolling about the lumen, so bending - which "
                 "poor fixation causes and disease does not - cannot change "
                 "these numbers. Runs too dim to judge are reported as "
                 "unlit_um and excluded from the gap fraction rather than "
                 "counted as damage."),
    }


def compare(control, mutant):
    """Put two animals side by side without pretending it is a statistic.

    Two animals are two animals. This reports the difference and says plainly
    that it is not evidence of a group effect, because a single pair cannot
    distinguish a genotype from an individual, a mount, or a session.
    """
    keys = ("filled_fraction", "gap_fraction_of_measurable", "n_gaps",
            "largest_gap_um", "confidence")
    rows = {k: (control.get(k), mutant.get(k)) for k in keys}
    weakest = min(control.get("confidence", 0), mutant.get("confidence", 0))
    return {
        "per_animal": rows,
        "lower_confidence_of_the_pair": weakest,
        "is_a_statistic": False,
        "note": ("A comparison of two animals. It cannot separate genotype "
                 "from individual, mount or imaging session, and the pair is "
                 "only as trustworthy as its dimmer member "
                 f"(confidence {weakest}). Treat as a look, not a result."),
    }
