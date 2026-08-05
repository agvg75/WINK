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


def interior_holes(image, um_per_px, tissue_percentile=60, min_area_um2=2.0,
                   close_um=1.0):
    """Enclosed voids INSIDE the muscle, with the perimeter intact.

    Andres, on a dystrophic terminal bulb: "the perimeter is intact, but inside
    there is a hole." That is a different topology from an interruption, and
    `continuity_metrics` cannot see it - that function asks whether a
    cross-section along the lumen is empty, and a bulb with a hole in the
    middle still has muscle all the way round, so every cross-section is
    occupied and it scores as perfectly continuous.

    An enclosed void is exactly what fill-holes finds: the difference between
    the filled tissue mask and the tissue itself. A void that opens to the
    outside is not counted, which is the point - that is the perimeter being
    broken, a different thing again.
    """
    from scipy import ndimage as ndi

    img = np.asarray(image, dtype=float)
    lo, hi = np.percentile(img, [20, 99])
    if hi <= lo:
        raise ContinuityError(
            "The image has no intensity range, so tissue cannot be separated "
            "from background and a 'hole' would be meaningless.")
    tissue = img > lo + 0.25 * (hi - lo)
    k = max(int(close_um / um_per_px), 1)
    tissue = ndi.binary_closing(tissue, np.ones((k, k)))
    filled = ndi.binary_fill_holes(tissue)
    voids = filled & ~tissue

    lab, n = ndi.label(voids)
    px_area = um_per_px ** 2
    holes = []
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) * px_area
        if area < min_area_um2:
            continue
        ys, xs = np.nonzero(m)
        holes.append({
            "area_um2": round(area, 3),
            "centroid_y_um": round(float(ys.mean()) * um_per_px, 2),
            "centroid_x_um": round(float(xs.mean()) * um_per_px, 2),
            "equivalent_diameter_um": round(2.0 * np.sqrt(area / np.pi), 3),
        })
    holes.sort(key=lambda h: -h["area_um2"])
    tissue_area = float(filled.sum()) * px_area
    total = sum(h["area_um2"] for h in holes)
    return {
        "n_interior_holes": len(holes),
        "hole_area_um2": round(total, 3),
        "hole_fraction_of_organ": round(total / max(tissue_area, 1e-9), 5),
        "largest_hole_um2": round(holes[0]["area_um2"], 3) if holes else 0.0,
        "holes": holes[:20],
        "organ_area_um2": round(tissue_area, 3),
        "note": ("Enclosed voids only - a gap that opens to the outside is a "
                 "broken perimeter, which is a different lesion and is not "
                 "counted here."),
    }


def bright_scar(image, um_per_px, sigma_um=1.0, z_threshold=3.0,
                min_area_um2=1.0):
    """Abnormally BRIGHT regions - scar tissue, not absence.

    The other half of Andres's description: alongside holes, a degenerating
    pharynx shows "extra bright scar tissue". Every measure written before this
    looked for missing signal, so a lesion made of EXCESS signal was invisible
    to all of them.

    Brightness is judged against the organ's own distribution, in robust units
    (median and MAD), because absolute intensity varies with laser power,
    exposure and depth and cannot be compared between animals.
    """
    from scipy import ndimage as ndi

    img = ndi.gaussian_filter(np.asarray(image, dtype=float),
                              max(sigma_um / um_per_px, 0.8))
    lo, hi = np.percentile(img, [20, 99])
    tissue = img > lo + 0.25 * (hi - lo)
    if tissue.sum() < 100:
        raise ContinuityError("Too little tissue to judge scarring against.")
    vals = img[tissue]
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med))) * 1.4826
    if mad <= 0:
        raise ContinuityError(
            "The tissue has no intensity variation, so 'abnormally bright' has "
            "no meaning here.")
    z = (img - med) / mad
    scar = tissue & (z > z_threshold)
    lab, n = ndi.label(scar)
    px_area = um_per_px ** 2
    patches = []
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) * px_area
        if area < min_area_um2:
            continue
        patches.append({"area_um2": round(area, 3),
                        "peak_z": round(float(z[m].max()), 2)})
    patches.sort(key=lambda p: -p["area_um2"])
    organ = float(tissue.sum()) * px_area
    total = sum(p["area_um2"] for p in patches)
    return {
        "n_scar_patches": len(patches),
        "scar_area_um2": round(total, 3),
        "scar_fraction_of_organ": round(total / max(organ, 1e-9), 5),
        "patches": patches[:20],
        "z_threshold": z_threshold,
        "note": ("Brightness judged against the organ's own median and MAD, "
                 "not an absolute level - laser power, exposure and depth all "
                 "move absolute intensity and none of them are pathology."),
    }


def cortex_mask(shape, centreline, um_per_px, inner_frac=0.35, outer_um=None):
    """The CORTEX half of the organ - outer, away from the lumen.

    Andres: the damage is "concentrated to the cortex half of the organs. the
    center has the lumen so it is intrinsically non radial". That second clause
    is why an earlier version reported 53% of the fibre area as coiled - it was
    measuring deviation-from-radial through the core, where radial is not the
    expectation and never was. Excluding the inner fraction is not a tuning
    choice; the core is a different structure.
    """
    H, W = int(shape[0]), int(shape[1])
    cy = np.asarray(centreline, dtype=float)
    yy = np.arange(H)[:, None]
    r = np.abs(yy - cy[None, :]) * um_per_px
    if outer_um is None:
        outer_um = float(np.percentile(r, 99))
    return (r >= inner_frac * outer_um) & (r <= outer_um), r


def radial_congruence(angles, coherence, expected_angle_map, um_per_px,
                      window_um=2.0):
    """Do neighbouring fibres AGREE with each other, as healthy ones do?

    Andres describes a "loss of radial congruence" - not merely fibres pointing
    the wrong way, but neighbours disagreeing where they used to march
    together. That is a different quantity from deviation-from-expected: a
    whole patch could be rotated and still be congruent, while a tangle is
    incongruent even if it averages to the right direction.
    """
    from scipy import ndimage as ndi

    a = np.asarray(angles, dtype=float)
    c = np.asarray(coherence, dtype=float)
    w = max(window_um / um_per_px, 2.0)
    d = np.deg2rad(a * 2.0)
    C = ndi.gaussian_filter(np.cos(d) * c, w)
    S = ndi.gaussian_filter(np.sin(d) * c, w)
    Wt = ndi.gaussian_filter(c, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        congruence = np.hypot(C, S) / np.maximum(Wt, 1e-9)
    return np.clip(congruence, 0.0, 1.0)


def fibre_bending(angles, coherence, um_per_px, window_um=1.5):
    """How much each fibre BENDS along itself - curved rather than straight.

    Andres: broken fibres "are bent rather than straight". A bent fibre can
    still average to the right direction, so deviation-from-expected misses it
    entirely; what changes is the turn ALONG the fibre. Measured as the rate of
    orientation change in the direction the fibre runs.
    """
    from scipy import ndimage as ndi

    a = np.deg2rad(np.asarray(angles, dtype=float))
    # gradient of the doubled angle, handled as a unit vector field so the
    # 0/180 wrap does not create false turns
    cx, sx = np.cos(2 * a), np.sin(2 * a)
    gcy, gcx = np.gradient(cx)
    gsy, gsx = np.gradient(sx)
    turn = np.sqrt(gcy ** 2 + gcx ** 2 + gsy ** 2 + gsx ** 2) / (2.0 * um_per_px)
    w = max(window_um / um_per_px, 2.0)
    c = np.asarray(coherence, dtype=float)
    num = ndi.gaussian_filter(turn * c, w)
    den = ndi.gaussian_filter(c, w)
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 1e-9, num / np.maximum(den, 1e-9), 0.0)


def coiled_filaments(image, um_per_px, expected_angle_map=None,
                     coil_window_um=0.2, min_area_um2=1.0):
    """Filaments that have DETACHED and lost axial orientation - they coil.

    Andres's third damage feature. Healthy pharyngeal fibres run radially about
    the lumen in a consistent local direction; detached ones curl, so within a
    small neighbourhood their orientation turns through a large angle instead
    of staying put.

    Measured as DEVIATION FROM THE EXPECTED DIRECTION, not as raw local
    variability. In a radially organised organ the orientation turns everywhere
    by construction - that is what "radial" means - so a spread measure would
    score healthy muscle as coiled and the metric would be worthless. What
    marks a detached filament is that it points somewhere the local anatomy
    does not.

    `expected_angle_map` should give the expected fibre direction in degrees at
    each pixel. With none supplied it is taken as radial about the tissue's
    centroid, which is right for a bulb and wrong for the isthmus - so supply
    it when the geometry is known.

    Deliberately not the same as low coherence either: empty space has low
    coherence, and scoring it as disorder would make every hole look like a
    tangle. Only places with real fibre signal are considered.
    """
    from scipy import ndimage as ndi
    import fibre_orientation as fo

    img = np.asarray(image, dtype=float)
    angles, coh = fo.structure_tensor_2d(img, sigma=1.5, rho=3.0)
    lo, hi = np.percentile(img, [20, 99])
    tissue = img > lo + 0.25 * (hi - lo)
    has_fibre = tissue & (coh > 0.25)
    if has_fibre.sum() < 100:
        raise ContinuityError(
            "Too little coherent fibre signal to judge coiling. An image with "
            "no resolvable filaments cannot show detached ones.")

    if expected_angle_map is None:
        ys, xs = np.nonzero(tissue)
        cy, cx = float(ys.mean()), float(xs.mean())
        yy, xx = np.mgrid[0:img.shape[0], 0:img.shape[1]]
        expected_angle_map = np.degrees(np.arctan2(yy - cy, xx - cx)) % 180.0
    expected = np.asarray(expected_angle_map, dtype=float)

    # BARELY SMOOTH AT ALL. The structure tensor above already averages over
    # sigma and rho, so anything added here is pure dilution. Measured on a
    # fixture where a detached filament sits at 84.9 degrees from expected and
    # healthy radial tissue at 7.1 - excellent separation - smoothing with
    # sigma 16 px across a 5 px filament pulled that 85 down to 26 and nothing
    # was detected at all. The lesion is one filament wide; the support must
    # not be wider than the lesion.
    dev = fo._angular_difference(angles, expected)      # 0..90 degrees
    sigma = max(coil_window_um / um_per_px, 1.0)
    wgt = np.where(has_fibre, coh, 0.0)
    dev_s = (ndi.gaussian_filter(dev * wgt, sigma)
             / np.maximum(ndi.gaussian_filter(wgt, sigma), 1e-9))
    spread = np.clip(dev_s / 90.0, 0.0, 1.0)   # 0 = as expected, 1 = across it

    coiled = has_fibre & (spread > 0.45)
    lab, n = ndi.label(coiled)
    px_area = um_per_px ** 2
    patches = []
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) * px_area
        if area < min_area_um2:
            continue
        patches.append({"area_um2": round(area, 3),
                        "mean_spread": round(float(spread[m].mean()), 3)})
    patches.sort(key=lambda p: -p["area_um2"])
    fibre_area = float(has_fibre.sum()) * px_area
    total = sum(p["area_um2"] for p in patches)
    return {
        "n_coiled_patches": len(patches),
        "coiled_area_um2": round(total, 3),
        "coiled_fraction_of_fibre": round(total / max(fibre_area, 1e-9), 5),
        "patches": patches[:20],
        "note": ("Measured only where there IS fibre signal. Low coherence "
                 "alone is not coiling - empty space has low coherence too, "
                 "and scoring it as disorder would make every hole look like "
                 "a tangle."),
    }


def disrupted_fibres(image, um_per_px, centreline, inner_frac=0.35,
                     bend_threshold=None, congruence_threshold=0.5,
                     min_area_um2=1.0):
    """Disrupted fibres in the CORTEX: bent, and no longer congruent.

    THIS IS THE VALIDATED MEASURE. Scored against Andres's hand-marked coiled
    fibres on a real dys-1 pharynx, P(marked > unmarked median):

        fibre bending, cortex only        0.849
        loss of congruence, cortex only   0.827
        either measure over the whole organ  ~0.5   (useless)
        deviation from radial, cortex     0.374   (below chance)

    Three things that specification got right and an earlier version did not:

    * "BENT rather than straight" is literal. A detached fibre can still average
      to the right direction, so deviation-from-expected misses it; what changes
      is the turn ALONG the fibre.
    * "loss of radial CONGRUENCE" is about neighbours disagreeing, which is a
      different quantity again - a whole patch can be rotated and stay
      congruent.
    * "concentrated to the CORTEX half... the center has the lumen so it is
      intrinsically non radial". Measuring through the core is why an earlier
      version reported 53% of the fibre area as coiled: radial was never the
      expectation there.

    Requires the lumen centreline, because cortex and core cannot be told apart
    without it. `coiled_filaments` remains for the no-lumen case, but it scores
    far worse and should not be preferred when a centreline is available.
    """
    from scipy import ndimage as ndi
    import fibre_orientation as fo

    img = np.asarray(image, dtype=float)
    angles, coh = fo.structure_tensor_2d(img, sigma=1.5, rho=3.0)
    lo, hi = np.percentile(img, [20, 99])
    tissue = img > lo + 0.25 * (hi - lo)
    has_fibre = tissue & (coh > 0.25)
    if has_fibre.sum() < 100:
        raise ContinuityError(
            "Too little coherent fibre signal to judge disruption. An image "
            "with no resolvable filaments cannot show broken ones.")

    cortex, r_um = cortex_mask(img.shape, centreline, um_per_px,
                               inner_frac=inner_frac)
    region = has_fibre & cortex
    if region.sum() < 100:
        raise ContinuityError(
            f"The cortex band holds too little fibre signal "
            f"({int(region.sum())} px). Check the centreline - if it does not "
            f"follow the lumen, the cortex is not where this thinks it is.")

    slope = np.gradient(np.asarray(centreline, dtype=float))
    expected = np.broadcast_to(
        ((np.degrees(np.arctan2(slope, 1.0)) + 90.0) % 180.0)[None, :],
        img.shape)
    bend = fibre_bending(angles, coh, um_per_px)
    cong = radial_congruence(angles, coh, expected, um_per_px)

    if bend_threshold is None:
        # relative to this organ's own healthy tissue, since bending in
        # absolute units depends on resolution and fibre thickness
        bend_threshold = float(np.percentile(bend[region], 75))
    disrupted = region & ((bend > bend_threshold) | (cong < congruence_threshold))

    lab, n = ndi.label(disrupted)
    px_area = um_per_px ** 2
    patches = []
    for i in range(1, n + 1):
        m = lab == i
        area = float(m.sum()) * px_area
        if area < min_area_um2:
            continue
        patches.append({"area_um2": round(area, 3),
                        "mean_bending": round(float(bend[m].mean()), 4),
                        "mean_congruence": round(float(cong[m].mean()), 4)})
    patches.sort(key=lambda p: -p["area_um2"])
    cortex_area = float(region.sum()) * px_area
    total = sum(p["area_um2"] for p in patches)
    return {
        "n_disrupted_patches": len(patches),
        "disrupted_area_um2": round(total, 3),
        "disrupted_fraction_of_cortex": round(total / max(cortex_area, 1e-9), 5),
        "cortex_fibre_area_um2": round(cortex_area, 3),
        "median_bending_cortex": round(float(np.median(bend[region])), 4),
        "median_congruence_cortex": round(float(np.median(cong[region])), 4),
        "patches": patches[:20],
        "bend_threshold": round(float(bend_threshold), 4),
        "measured_in": "cortex only (inner core excluded - it holds the lumen)",
        "validated_against": ("hand-marked coiled fibres on one dys-1 pharynx: "
                              "bending 0.849, congruence 0.827"),
    }


def damage_report(image, um_per_px, centreline=None):
    """All three damage features Andres described, side by side.

    Deliberately NOT combined into a single score. They are different lesions
    with different causes, and a total would hide which one an animal actually
    has - the thing a person looking at the image can see at a glance and would
    want the numbers to preserve.

    Supply `centreline` whenever it is known. Without it the fibre measure falls
    back to `coiled_filaments`, which cannot separate cortex from core and
    scored far worse against real marks - it reported half the fibre area as
    disrupted. The fallback exists so an unmarked image still returns something;
    it is not an equivalent.
    """
    out = {"interior_holes": None, "bright_scar": None, "coiled_filaments": None,
           "disrupted_fibres": None, "refusals": {}}
    for name, fn in (("interior_holes", interior_holes),
                     ("bright_scar", bright_scar)):
        try:
            out[name] = fn(image, um_per_px)
        except ContinuityError as exc:
            out["refusals"][name] = str(exc)

    if centreline is not None:
        try:
            out["disrupted_fibres"] = disrupted_fibres(image, um_per_px,
                                                       centreline)
        except ContinuityError as exc:
            out["refusals"]["disrupted_fibres"] = str(exc)
        out["fibre_measure_used"] = "disrupted_fibres (validated)"
    else:
        try:
            out["coiled_filaments"] = coiled_filaments(image, um_per_px)
        except ContinuityError as exc:
            out["refusals"]["coiled_filaments"] = str(exc)
        out["fibre_measure_used"] = "coiled_filaments (FALLBACK - no centreline)"
        out["fallback_warning"] = (
            "No lumen centreline was supplied, so cortex and core could not be "
            "separated and the weaker measure was used. On real tissue it "
            "reported half the fibre area as disrupted. Supply a centreline.")
    out["combined_score"] = None
    out["why_no_combined_score"] = (
        "Holes, scarring and coiling are different lesions. A single number "
        "would hide which one an animal has, which is exactly what a person "
        "reading the image can see and would want kept.")
    return out


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
