"""Where the optical plane cut the animal, and what that does to brightness.

Andres's observation, and it has more reach than it first appears: a confocal
frame is a SINGLE SLICE through a roughly cylindrical animal, so how much
tissue the plane intersects - and at what angle - varies systematically, and
every one of those variations arrives as a brightness difference that is not
calcium.

THREE PREDICTIONS FOLLOW, and they are testable rather than rhetorical.

1. THE TRANSVERSE PROFILE SAYS WHERE THE PLANE CUT. A plane through a convex
   body near its equator meets the wall obliquely on both flanks and produces
   TWO DISTAL maxima; a plane nearer the top cuts the curved surface broadside
   and produces ONE CENTRAL maximum. So the shape of the across-body intensity
   profile is a readout of section depth, available in every frame without any
   extra acquisition.

2. IPSILATERAL AND CONTRALATERAL COMPARISONS ARE NOT EQUIVALENT. The two sides
   of one frame may be sectioned at different depths, so a left-right
   difference can be optics. Comparing the SAME quadrant across animals or
   across time is the safer contrast, and when the two must be compared the
   per-side RANGE should be reported beside the per-side level - a side that is
   dimmer AND compressed in range is being sectioned badly, where a side that
   is dimmer with an intact range may be genuinely dimmer.

3. THE ANTERIOR-POSTERIOR GRADIENT IS PARTLY GEOMETRY. This is the one that
   matters most and is easiest to miss. The animal TAPERS, so a flat plane sits
   near the equator at the midbody and nearer the top at the head and tail. The
   depth relative to the local radius therefore varies ALONG the body, and
   produces a head-to-tail brightness gradient with no biology in it at all -
   in an animal where a real proximal-to-distal gradient is exactly what the
   dystrophy question asks about.

The decisive test for (3) is cheap: does per-segment brightness track the local
BODY WIDTH? Width is set by anatomy and posture; calcium is not. If the two
move together along the body, the gradient is the section.
"""
from __future__ import annotations

import numpy as np


class SectionError(Exception):
    """Refusals that name the consequence."""


def transverse_profile(image, mask, spine, segment_index, n_seg=24,
                       half_width_px=18.0, samples=41):
    """Intensity across the body, perpendicular to the midline, at one segment.

    Sampled along the normal rather than along image rows, so the profile is
    across the ANIMAL and not across the picture - on a bent worm those are
    different directions and the second one measures the bend.
    """
    img = np.asarray(image, dtype=float)
    m = np.asarray(mask, dtype=bool)
    s = np.asarray(spine, dtype=float)
    if s.shape[0] < 3:
        raise SectionError("Need at least 3 spine points.")
    step = np.linalg.norm(np.diff(s, axis=0), axis=1)
    arc = np.r_[0.0, np.cumsum(step)]
    target = arc[-1] * (segment_index + 0.5) / n_seg
    i = int(np.clip(np.searchsorted(arc, target), 1, s.shape[0] - 2))

    tan = s[i + 1] - s[i - 1]
    n = np.linalg.norm(tan)
    if n == 0:
        raise SectionError("Degenerate spine tangent.")
    tan = tan / n
    perp = np.array([-tan[1], tan[0]])

    offs = np.linspace(-half_width_px, half_width_px, samples)
    vals, inside = [], []
    h, w = img.shape[:2]
    for o in offs:
        x, y = s[i] + perp * o
        xi, yi = int(round(x)), int(round(y))
        if 0 <= xi < w and 0 <= yi < h:
            vals.append(img[yi, xi]); inside.append(bool(m[yi, xi]))
        else:
            vals.append(np.nan); inside.append(False)
    return np.array(offs), np.array(vals, float), np.array(inside, bool)


def modality(offsets, values, inside, min_points=9):
    """Is the across-body profile ONE CENTRAL peak or TWO DISTAL ones?

    Central means the plane cut the curved surface broadside - nearer the top
    of the animal. Bimodal means it passed closer to the equator and met the
    wall obliquely on both flanks. That distinction is the section-depth
    readout, and it costs nothing to compute.
    """
    v = np.where(inside, values, np.nan)
    if np.isfinite(v).sum() < min_points:
        return {"shape": "unmeasurable",
                "why": "too little of the profile fell inside the body"}
    idx = np.flatnonzero(np.isfinite(v))
    lo, hi = idx[0], idx[-1]
    seg = v[lo:hi + 1]
    x = offsets[lo:hi + 1]
    mid = len(seg) // 2
    third = max(len(seg) // 3, 1)
    centre = np.nanmean(seg[third:-third]) if len(seg) > 2 * third else np.nan
    flanks = np.nanmean(np.r_[seg[:third], seg[-third:]])
    if not (np.isfinite(centre) and np.isfinite(flanks)):
        return {"shape": "unmeasurable", "why": "profile too short"}
    contrast = (centre - flanks) / max(centre + flanks, 1e-9)
    shape = ("central" if contrast > 0.05
             else "distal" if contrast < -0.05 else "flat")
    return {
        "shape": shape,
        "centre_minus_flank": round(float(contrast), 4),
        "centre": round(float(centre), 3), "flanks": round(float(flanks), 3),
        "width_px": float(x[-1] - x[0]),
        "means": ("cut broadside through the curved surface - the plane sits "
                  "away from the equator" if shape == "central" else
                  "met the wall obliquely on both flanks - the plane sits near "
                  "the equator" if shape == "distal" else
                  "no clear signature; the plane's depth cannot be read here"),
    }


def optical_gradient_test(rows, channel="green", stat="p90",
                          width_key="roi_area_px", body_segments=(8, 24)):
    """Does brightness along the body track LOCAL WIDTH? If so it is the section.

    THE DECISIVE TEST, and it is cheap. Width is set by anatomy and posture;
    calcium is not. A flat plane through a tapering animal produces a
    head-to-tail brightness gradient purely because the plane's depth relative
    to the local radius changes along the body - and that is indistinguishable
    by eye from a real proximal-to-distal gradient.

    Head segments are excluded by default: they carry extra reporters here, so
    including them would answer a different question loudly.
    """
    lo, hi = body_segments
    per_seg = {}
    for r in rows:
        s = r.get("segment")
        if s is None or not (lo <= s < hi):
            continue
        b = r.get(f"{channel}_{stat}")
        w = r.get(width_key)
        if b is None or w is None:
            continue
        d = per_seg.setdefault(s, {"b": [], "w": []})
        d["b"].append(float(b)); d["w"].append(float(w))
    if len(per_seg) < 6:
        raise SectionError(
            f"Only {len(per_seg)} body segments have both {channel}_{stat} and "
            f"{width_key}. A gradient over so few segments cannot be "
            f"distinguished from noise, let alone attributed.")

    segs = sorted(per_seg)
    bright = np.array([np.median(per_seg[s]["b"]) for s in segs])
    width = np.array([np.median(per_seg[s]["w"]) for s in segs])
    pos = np.array(segs, float)

    def r_of(a, b):
        if np.std(a) == 0 or np.std(b) == 0:
            return None
        return float(np.corrcoef(a, b)[0, 1])

    r_bw = r_of(bright, width)
    r_bp = r_of(bright, pos)
    r_wp = r_of(width, pos)

    verdict = "indeterminate"
    if r_bw is not None and abs(r_bw) > 0.7:
        verdict = ("brightness tracks width - EITHER optical sectioning OR a "
                   "reporter whose amount scales with tissue volume")
    elif r_bw is not None and abs(r_bw) < 0.3 and r_bp and abs(r_bp) > 0.5:
        verdict = ("a positional gradient that does NOT track width - "
                   "consistent with biology rather than sectioning")
    elif r_bw is not None and abs(r_bw) < 0.5 and r_bp is not None \
            and abs(r_bp) < 0.3:
        verdict = ("no appreciable gradient and little width coupling - this "
                   "channel shows no sign of the sectioning artefact")
    return {
        "channel": f"{channel}_{stat}", "n_segments": len(segs),
        "r_brightness_vs_width": None if r_bw is None else round(r_bw, 4),
        "r_brightness_vs_position": None if r_bp is None else round(r_bp, 4),
        "r_width_vs_position": None if r_wp is None else round(r_wp, 4),
        "verdict": verdict,
        "why_it_matters": (
            "A flat optical plane through a TAPERING animal sits near the "
            "equator at the midbody and nearer the top at the ends, so the "
            "section depth relative to the local radius varies along the body. "
            "That alone produces a head-to-tail brightness gradient, in an "
            "animal where a real proximal-to-distal gradient is exactly what "
            "the dystrophy question asks about."),
        "what_to_do": (
            "If brightness tracks width, report the gradient only after "
            "controlling for width, or compare the SAME segment across animals "
            "rather than across segments within one."),
        "coupling_is_not_proof": (
            "Brightness tracking width does NOT by itself mean an artefact. A "
            "structural or mitochondrial label reports how much tissue is "
            "present, so it SHOULD scale with the section's width; a "
            "concentration reporter like a cytoplasmic calcium indicator "
            "should not. The same correlation means different things in "
            "different channels, and which reporter is in which channel is "
            "information this module does not have."),
        "measured_on_this_recording_only": (
            "One animal. The concern is general; whether it bites is an "
            "empirical question per preparation, and on a mount where the "
            "plane sits near the equator along the whole body it may not bite "
            "at all - which is what the transverse profile can be used to "
            "check directly."),
    }


def side_comparison(rows, channel="green", stat="p90", body_segments=(8, 24)):
    """Level AND range per side, because a dim side may just be badly cut.

    Andres's point: if one side is consistently dimmer, look at the RANGE too.
    A side that is dimmer and compressed is being sectioned obliquely - it is
    losing signal at both ends. A side that is dimmer with its range intact may
    genuinely be dimmer. Reporting the level alone cannot tell them apart.
    """
    lo, hi = body_segments
    by = {}
    for r in rows:
        s, side = r.get("segment"), r.get("hemisegment")
        v = r.get(f"{channel}_{stat}")
        if s is None or side is None or v is None or not (lo <= s < hi):
            continue
        by.setdefault(side, []).append(float(v))
    if len(by) < 2:
        raise SectionError(
            f"Only {list(by)} present; a side comparison needs both.")
    out = {}
    for side, v in by.items():
        a = np.asarray(v)
        out[side] = {
            "n": int(a.size),
            "median": round(float(np.median(a)), 3),
            "p10": round(float(np.percentile(a, 10)), 3),
            "p90": round(float(np.percentile(a, 90)), 3),
            "range_p10_p90": round(float(np.percentile(a, 90)
                                         - np.percentile(a, 10)), 3),
        }
    sides = sorted(out, key=lambda s: -out[s]["median"])
    bright, dim = out[sides[0]], out[sides[1]]
    level_ratio = dim["median"] / max(bright["median"], 1e-9)
    range_ratio = dim["range_p10_p90"] / max(bright["range_p10_p90"], 1e-9)
    return {
        "channel": f"{channel}_{stat}", "sides": out,
        "brighter_side": sides[0], "dimmer_side": sides[1],
        "level_ratio": round(float(level_ratio), 4),
        "range_ratio": round(float(range_ratio), 4),
        "reading": (
            f"The {sides[1]} side sits at {level_ratio:.0%} of the {sides[0]} "
            f"side's level with {range_ratio:.0%} of its range. Range "
            f"compressed along with level points at OBLIQUE SECTIONING - that "
            f"side is losing signal at both ends, which optics does and "
            f"biology need not."
            if range_ratio < 0.75 else
            f"The {sides[1]} side sits at {level_ratio:.0%} of the {sides[0]} "
            f"side's level but keeps {range_ratio:.0%} of its range. A "
            f"preserved range is more consistent with the side genuinely being "
            f"dimmer than with it being badly cut."),
        "same_quadrant_is_safer": (
            "Comparing the SAME quadrant across animals or across time avoids "
            "this entirely. Left against right within one frame asks the two "
            "sides to have been sectioned equivalently, which the geometry "
            "does not guarantee."),
    }
