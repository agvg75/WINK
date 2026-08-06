"""What this recording can actually give you: centroids, or centroids and spines.

Andres's workflow: the tracker shows a frame, the user scrolls to one where the
worms are no longer in a pile, and traces one or more midlines by hand. From
those traces the program works out whether spines are recoverable or only
centroids. Centroids should always be recoverable and give a first pass. If
spines are recoverable too, the user opts in and gets them - which is what
allows turning strategies and body orientation relative to the field.

THE USER'S TRACES ARE THE MEASUREMENT, not a hint. A person drawing a midline
on a real frame establishes how long the animal is in pixels, how wide, how
well separated from its neighbours and how far above background - on THIS
recording, with THIS objective and THIS illumination. No heuristic over the
whole movie is as reliable, and it costs one frame of somebody's attention.

THE TWO TIERS ARE NOT BETTER AND WORSE, they answer different questions, and
the distinction that matters most here is easy to lose:

    A CENTROID GIVES YOU THE DIRECTION OF TRAVEL.
    A SPINE GIVES YOU THE ORIENTATION OF THE BODY.

Those are the same thing only while an animal crawls forward. During a
reversal the body points one way and the track goes the other, and in a
magnetic assay "was the animal aligned with the field" is a question about the
BODY. Answering it from centroids silently substitutes heading for orientation
and gets reversals exactly backwards.

WHY WIDTH IS THE BINDING CONSTRAINT. A midline is the centre of a shape, and
you cannot find the centre of something two pixels across - there is no
interior. Length matters too, but through a different mechanism: the midline
has to carry enough points to support however many segments are asked for.
This project has already shipped a curvature panel that turned out to be
speckle because the baseline gave roughly four midline points per segment.
That is the failure this module exists to predict rather than discover.
"""
from __future__ import annotations

import numpy as np

# Defaults are floors, not targets. Each is the point below which the
# measurement stops meaning anything, not the point where it becomes good.
MIN_WIDTH_PX = 4.0          # a midline needs an interior to be the centre of
MIN_PX_PER_SEGMENT = 4.0    # below this, curvature per segment is speckle
MIN_CONTRAST = 3.0          # worm-to-background, in background standard devs
# Separation is measured between MIDLINES, and each body extends half a width
# either side of its own. So a midline gap of exactly one body width means the
# two animals are already touching, and a threshold set there fires only after
# they have merged. 1.5 leaves a margin for the animals to be near-contact,
# which is enough to join their segmented outlines.
MIN_SEPARATION_FACTOR = 1.5

TIERS = {
    "centroid": {
        "enables": ("position", "speed", "track direction", "dispersal",
                    "chemotaxis and donut crossing indices",
                    "time to cross a boundary"),
        "prevents": ("body orientation relative to the stimulus",
                     "omega turns and deep bends",
                     "turning strategy",
                     "head and tail assignment",
                     "any curvature measure"),
    },
    "spine": {
        "enables": ("everything the centroid tier gives",
                    "body orientation relative to the field vector",
                    "omega turns, deep bends and turning strategy",
                    "curvature along the body",
                    "head and tail assignment"),
        "prevents": (),
    },
}


class TractabilityError(Exception):
    """Refusals that name the consequence."""


def _polyline_length(points):
    p = np.asarray(points, dtype=float)
    if p.ndim != 2 or p.shape[0] < 2 or p.shape[1] != 2:
        raise TractabilityError(
            "A traced midline needs at least two (x, y) points. A single "
            "point gives a position but no length, and length is what decides "
            "whether a spine can carry the requested segments.")
    return float(np.sum(np.hypot(*np.diff(p, axis=0).T)))


def _profile_width(frame, points, samples=9, half_window=15):
    """Body width in pixels, from intensity profiles across the traced line.

    Full width at half the worm-to-background depth, measured perpendicular to
    the midline and taken as the MEDIAN across several stations - a mean would
    be dragged by the one profile that crossed a neighbouring animal.
    """
    img = np.asarray(frame, dtype=float)
    if img.ndim == 3:
        img = img.mean(axis=2)
    p = np.asarray(points, dtype=float)
    h, w = img.shape
    background = float(np.median(img))
    widths = []
    idx = np.linspace(0, len(p) - 2, min(samples, max(len(p) - 1, 1)))
    for i in idx:
        i = int(i)
        d = p[i + 1] - p[i]
        n = np.linalg.norm(d)
        if n == 0:
            continue
        normal = np.asarray([-d[1], d[0]]) / n
        mid = (p[i] + p[i + 1]) / 2.0
        ts = np.arange(-half_window, half_window + 1, dtype=float)
        xs = np.clip(np.round(mid[0] + normal[0] * ts).astype(int), 0, w - 1)
        ys = np.clip(np.round(mid[1] + normal[1] * ts).astype(int), 0, h - 1)
        line = img[ys, xs]
        depth = line - background
        peak = depth[np.argmax(np.abs(depth))]
        if peak == 0:
            continue
        # Half-depth crossing, in whichever polarity the worm has - dark on
        # bright and bright on dark are both common here and assuming one
        # would report zero width for the other.
        over = np.abs(depth) >= abs(peak) / 2.0
        if over.any():
            widths.append(float(np.count_nonzero(over)))
    if not widths:
        raise TractabilityError(
            "No intensity profile across the traced line rose above "
            "background. Either the trace is not on an animal or the contrast "
            "is too low to measure - both mean a width cannot be established, "
            "and width is what decides whether a midline can be fitted.")
    return float(np.median(widths)), background


def trace_stats(traces, frame=None, um_per_px=None):
    """Turn hand-traced midlines into the numbers the tiers are decided on."""
    if not traces:
        raise TractabilityError(
            "At least one traced midline is needed. The whole point is to "
            "measure this recording rather than assume a typical one.")
    lengths = [_polyline_length(t) for t in traces]
    out = {
        "n_traced": len(traces),
        "length_px": {"median": float(np.median(lengths)),
                      "min": float(np.min(lengths)),
                      "max": float(np.max(lengths))},
    }
    if um_per_px:
        out["length_um"] = {k: v * float(um_per_px)
                            for k, v in out["length_px"].items()}
    if len(traces) > 1:
        gaps = []
        for i, a in enumerate(traces):
            for b in traces[i + 1:]:
                a2, b2 = np.asarray(a, dtype=float), np.asarray(b, dtype=float)
                d = np.hypot(a2[:, None, 0] - b2[None, :, 0],
                             a2[:, None, 1] - b2[None, :, 1])
                gaps.append(float(d.min()))
        out["min_separation_px"] = float(np.min(gaps))
    if frame is not None:
        widths, background = [], None
        for t in traces:
            w, background = _profile_width(frame, t)
            widths.append(w)
        out["width_px"] = {"median": float(np.median(widths)),
                           "min": float(np.min(widths))}
        img = np.asarray(frame, dtype=float)
        if img.ndim == 3:
            img = img.mean(axis=2)
        # BACKGROUND noise, by MAD rather than the whole-image standard
        # deviation. The worm contributes to that standard deviation, so
        # dividing by it is circular: a faint animal on a clean field lowers
        # the denominator as fast as it lowers the numerator and scores as
        # HIGH contrast. A 3-count worm measured 7.4 sd that way. MAD ignores
        # the animal because the animal is the outlier.
        mad = float(np.median(np.abs(img - np.median(img))))
        noise = mad * 1.4826
        peaks = []
        for t in traces:
            p = np.asarray(t, dtype=float).astype(int)
            ys = np.clip(p[:, 1], 0, img.shape[0] - 1)
            xs = np.clip(p[:, 0], 0, img.shape[1] - 1)
            peaks.append(float(np.median(np.abs(img[ys, xs] - background))))
        signal = float(np.median(peaks))
        if noise <= 0:
            # A background with no variation at all is synthetic, or the image
            # has been through a filter that destroyed the noise the estimate
            # depends on. Either way the ratio is not meaningful and a large
            # number would be read as excellent contrast.
            out["contrast_sd"] = None
            out["contrast_note"] = (
                "The background has no measurable variation, so a "
                "contrast-to-noise ratio cannot be formed. This is normal for "
                "a synthetic image and suspicious for a real one - a denoising "
                "filter that removes the noise also removes the only reference "
                "the boundary reliability can be judged against.")
        else:
            out["contrast_sd"] = signal / noise
        out["signal_over_background"] = signal
        out["background_noise"] = noise
    return out


def assess(stats, *, n_seg=24, min_width_px=MIN_WIDTH_PX,
           min_px_per_segment=MIN_PX_PER_SEGMENT, min_contrast=MIN_CONTRAST):
    """Which tier this recording supports, and why - never a bare verdict.

    Centroids are always available: a blob that can be found at all has a
    centre of mass. The question is only ever whether spines are recoverable
    ON TOP of that, so the answer is a tier plus the reasons, and the reasons
    are what a person needs in order to change the acquisition.
    """
    reasons, blockers = [], []
    length = stats.get("length_px", {}).get("median")
    width = stats.get("width_px", {}).get("median")

    if width is None:
        blockers.append(
            "Body width was not measured, so whether a midline can be fitted "
            "is unknown. Pass the frame the traces were drawn on.")
    elif width < min_width_px:
        blockers.append(
            f"The body is {width:.1f} px across, below the {min_width_px:.0f} "
            f"px floor. A midline is the centre of a shape and there is no "
            f"interior to find the centre of - the fitted spine would follow "
            f"pixel noise. Get closer or use a higher magnification.")
    else:
        reasons.append(f"body {width:.1f} px across, enough to have an interior")

    if length is not None:
        per_seg = length / max(int(n_seg), 1)
        if per_seg < min_px_per_segment:
            blockers.append(
                f"At {length:.0f} px long there are only {per_seg:.1f} px per "
                f"segment for n_seg={n_seg}, below the "
                f"{min_px_per_segment:.0f} px floor. This project has already "
                f"shipped a curvature panel that was speckle for exactly this "
                f"reason. Either raise magnification or ask for fewer "
                f"segments - {int(length / min_px_per_segment)} would fit.")
        else:
            reasons.append(
                f"{length:.0f} px long gives {per_seg:.1f} px per segment "
                f"at n_seg={n_seg}")

    contrast = stats.get("contrast_sd")
    if contrast is not None and contrast < min_contrast:
        blockers.append(
            f"The animals stand {contrast:.1f} background standard deviations "
            f"clear, below {min_contrast:.0f}. A boundary that cannot be found "
            f"reliably cannot be thinned to a reliable midline.")
    elif contrast is not None:
        reasons.append(f"{contrast:.1f} sd above background")

    sep = stats.get("min_separation_px")
    if sep is not None and width and sep < width * MIN_SEPARATION_FACTOR:
        blockers.append(
            f"Two traced midlines come within {sep:.1f} px, under "
            f"{MIN_SEPARATION_FACTOR:g} body widths ({width:.1f} px each). "
            f"Since each body reaches half a width either side of its "
            f"midline, that means the animals are touching or nearly so - "
            f"they merge into one shape and the midline runs from one worm "
            f"into the other. Choose a frame after they have separated, "
            f"which is what the scrubber is for.")

    tier = "centroid" if blockers else "spine"
    return {
        "tier": tier,
        "spine_recoverable": tier == "spine",
        "centroid_recoverable": True,
        "why": ("Spines can be fitted: " + "; ".join(reasons)
                if tier == "spine" else
                "Centroids only. " + " ".join(blockers)),
        "reasons": reasons,
        "blockers": blockers,
        "n_seg_checked": int(n_seg),
        "max_supported_n_seg": (int(length / min_px_per_segment)
                                if length else None),
        "enables": list(TIERS[tier]["enables"]),
        "prevents": list(TIERS[tier]["prevents"]),
        "the_distinction_that_matters": (
            "A centroid gives the direction of TRAVEL; a spine gives the "
            "orientation of the BODY. They agree only while the animal crawls "
            "forward. During a reversal the body points one way and the track "
            "goes the other, so answering 'was the animal aligned with the "
            "field' from centroids substitutes heading for orientation and "
            "gets reversals backwards."
            if tier == "centroid" else
            "Body orientation is available independently of travel direction, "
            "so alignment with the field remains meaningful through "
            "reversals."),
    }


def plan(assessment, *, wants_orientation=False, wants_turning=False):
    """What to run now, and what the first pass will and will not answer.

    Centroids run either way - that is the first pass. Spines are opt-in per
    Andres, because they cost time and the person should choose knowingly
    rather than have the tool decide for them.
    """
    tier = assessment["tier"]
    out = {"run_centroids": True, "offer_spines": assessment["spine_recoverable"],
           "first_pass": "centroid tracking", "warnings": []}
    blocked = [name for name, want in
               (("body orientation relative to the stimulus", wants_orientation),
                ("turning strategy, omegas and deep bends", wants_turning))
               if want]
    if blocked and tier == "centroid":
        out["warnings"].append(
            "You asked for " + " and ".join(blocked) +
            ", which needs spines, and this recording does not support them: "
            + assessment["why"] +
            " The centroid pass will still run and is still valid for "
            "position, speed and crossing times.")
        out["blocked_goals"] = blocked
    elif blocked:
        out["warnings"].append(
            "Spines are recoverable, so " + " and ".join(blocked) +
            " is available - but it is opt-in and will not be computed unless "
            "asked for.")
    return out
