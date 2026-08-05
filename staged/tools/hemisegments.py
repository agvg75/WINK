"""Cut the body into per-side muscle ROIs and measure them. The last piece of
extraction that Fiji still did.

Given a head-first spine, a body mask and a ventral sign, this produces one ROI
per (segment, side) and measures each channel inside it - the per-segment
intensities that `worm_rgbcamp_analysis` and `worm_kinetics` already expect.
Everything downstream of here has been Python all along.

TWO DECISIONS DO THE WORK.

ASSIGN PIXELS BY NEAREST SPINE POINT, NOT BY PERPENDICULAR SLABS. The obvious
construction - walk along the midline and cut a perpendicular band at each
segment boundary - fails on exactly the animals we care about. On the inside of
a bend the perpendiculars converge and cross, so a pixel falls in two bands at
once, while on the outside they diverge and leave gaps. The error grows with
curvature, which means it is worst in the frames where the muscle is doing the
most. A nearest-point assignment is a Voronoi partition along the spine: every
body pixel belongs to exactly one segment, at any curvature, by construction.

SIDES COME FROM THE SIGN OF THE CROSS PRODUCT with the local tangent, using the
same convention as `head_tail.signed_curvature`. That is what lets a ventral
sign measured from bending asymmetry be applied to pixels.

AND IF DORSAL/VENTRAL IS NOT KNOWN, SAY LEFT AND RIGHT. A confident-looking
`dorsal` label on a coin-flip is worse than an honest `left`: the analysis will
pool it with real dorsal data and nothing downstream can tell. `dorsal_known`
travels with every row.
"""
from __future__ import annotations

import numpy as np


class HemisegmentError(Exception):
    """Refusals that name the consequence."""


N_SEG = 24          # one per body-wall myocyte. Anatomy, not a resolution knob.


def _muscle_fractions(n_seg):
    """Cumulative cell boundaries as fractions of body length, from the one
    definition of the muscle-size profile that already exists.

    IMPORTED, NOT REIMPLEMENTED. `app/myocyte_schematic.boundaries` holds the
    profile the RGBCaMP extractor measures with, and the schematic is drawn from
    it precisely so the numbering a student checks against cannot drift from the
    numbering the tools measure with. A second copy here would reintroduce that
    drift silently: segments would still be produced, still be numbered 0..23,
    and simply describe different pieces of the animal.
    """
    import sys
    from pathlib import Path
    app_dir = Path(__file__).resolve().parents[1] / "app"
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    try:
        from myocyte_schematic import boundaries
    except ImportError as exc:                            # pragma: no cover
        raise HemisegmentError(
            f"Could not load the muscle-size profile from "
            f"app/myocyte_schematic.py ({exc}). Refusing to fall back on "
            f"equal-length segments: they would still be numbered 0..23 and "
            f"would simply describe different pieces of the animal than every "
            f"other tool, with nothing to show for it.")
    return np.asarray(boundaries(n_seg), dtype=float)


def segment_bounds(spine, n_seg=N_SEG, profile="anatomical"):
    """Split the spine into n_seg segments along its ARC LENGTH.

    SEGMENTS ARE NOT EQUAL IN LENGTH, and that is the point. Body-wall muscles
    are SHORTER AT THE ENDS AND LARGER IN THE MIDBODY, so cutting the body into
    equal pieces would put segment boundaries in the middle of real cells - and
    the numbering would then still read 0..23 while meaning something else than
    it does everywhere else in WINK. On the shared profile the midbody cell is
    about 1.8x the length of an end cell.

    `profile="uniform"` gives equal arc length. It exists for measurements that
    genuinely want even bins along the body and is NOT anatomical: its segments
    do not correspond to myocytes and must not be labelled as though they do.

    Arc length, not point index, in both cases: a raw traced spine is unevenly
    sampled, and equal-index segments would be different physical lengths that
    still get compared with each other.
    """
    s = np.asarray(spine, dtype=float)
    if s.ndim != 2 or s.shape[1] != 2 or s.shape[0] < 3:
        raise HemisegmentError(
            f"A spine must be (N, 2) with at least 3 points; got {s.shape}.")
    if n_seg < 1:
        raise HemisegmentError("n_seg must be at least 1.")
    step = np.linalg.norm(np.diff(s, axis=0), axis=1)
    arc = np.r_[0.0, np.cumsum(step)]
    total = arc[-1]
    if total <= 0:
        raise HemisegmentError("The spine has zero length.")

    if profile == "anatomical":
        edges = _muscle_fractions(n_seg) * total
    elif profile == "uniform":
        edges = np.linspace(0.0, total, n_seg + 1)
    else:
        raise HemisegmentError(
            f"profile must be 'anatomical' or 'uniform', not {profile!r}.")

    # segment index of each spine point, clipped so the tail point lands in the
    # last segment rather than one past it
    idx = np.clip(np.searchsorted(edges, arc, side="right") - 1, 0, n_seg - 1)
    return idx, arc, edges


def assign(mask, spine, n_seg=N_SEG, ventral_sign=None,
           dorsal_known=False, profile="anatomical"):
    """Label every body pixel with (segment, side).

    Returns a dict with `segment` and `side` arrays over the mask, where side is
    +1 or -1 by the cross-product convention, plus the label to use for each.
    """
    m = np.asarray(mask, dtype=bool)
    s = np.asarray(spine, dtype=float)
    seg_of_point, _, _ = segment_bounds(s, n_seg, profile)

    ys, xs = np.nonzero(m)
    if ys.size == 0:
        raise HemisegmentError("The mask is empty; there is nothing to cut.")
    pts = np.column_stack([xs, ys]).astype(float)          # (x, y)

    # nearest spine point for every body pixel
    d2 = ((pts[:, None, 0] - s[None, :, 0]) ** 2
          + (pts[:, None, 1] - s[None, :, 1]) ** 2)
    nearest = np.argmin(d2, axis=1)

    tangent = np.gradient(s, axis=0)
    tn = np.linalg.norm(tangent, axis=1, keepdims=True)
    tn[tn == 0] = 1.0
    tangent = tangent / tn

    rel = pts - s[nearest]
    t = tangent[nearest]
    # z of tangent x offset: same turn-sense convention as signed_curvature
    cross = t[:, 0] * rel[:, 1] - t[:, 1] * rel[:, 0]
    side = np.where(cross >= 0, 1, -1)

    seg = np.zeros(m.shape, dtype=int) - 1
    sid = np.zeros(m.shape, dtype=int)
    seg[ys, xs] = seg_of_point[nearest]
    sid[ys, xs] = side

    if dorsal_known and ventral_sign in (1, -1):
        labels = {int(ventral_sign): "ventral", int(-ventral_sign): "dorsal"}
    else:
        labels = {1: "left", -1: "right"}

    return {
        "segment": seg, "side": sid, "labels": labels,
        "dorsal_known": bool(dorsal_known and ventral_sign in (1, -1)),
        "n_seg": int(n_seg),
        "assignment": ("nearest spine point - a Voronoi partition along the "
                       "midline, so every body pixel belongs to exactly one "
                       "segment at any curvature. Perpendicular slabs cross on "
                       "the inside of a bend and gap on the outside, worst in "
                       "the frames where the muscle is most active."),
        "side_note": (
            "Dorsal and ventral are known and labelled."
            if (dorsal_known and ventral_sign in (1, -1)) else
            "Dorsal/ventral was NOT established, so sides are reported as left "
            "and right. A confident-looking 'dorsal' on a coin flip would be "
            "pooled with real dorsal data and nothing downstream could tell."),
    }


def segment_kinematics(spine, n_seg=N_SEG, um_per_px=None,
                       profile="anatomical", baseline_frac=0.10):
    """Per-segment angle and curvature, measured over a WIDE ENOUGH BASELINE.

    THE FIRST VERSION PRODUCED NOISE, and the kymogram made it obvious: a
    crawling worm should show clean diagonal banding as the body wave travels,
    and instead the curvature panel was speckle. The cause was the baseline.
    Turning was measured between the first and last tangent INSIDE each
    segment - about four points of a hundred-point midline - so the estimate
    was dominated by tracing jitter rather than by the animal's posture. Twenty
    four segments of a resampled spine simply do not each contain enough points
    to differentiate.

    Curvature is now measured at each segment's CENTRE over a baseline that is
    a fixed fraction of body length (`baseline_frac`, default a tenth), which
    is a real physical distance rather than however many points happened to
    fall in a segment. Segments still tile the body; the measurement window
    overlaps between neighbours, which is correct - curvature is a property of
    a place on the body, not of a bin.

    Angle stays local to the segment: it is the segment's own orientation and
    a wide baseline would blur exactly what it reports.
    """
    s = np.asarray(spine, dtype=float)
    idx, arc, edges = segment_bounds(s, n_seg, profile)
    total = float(arc[-1])
    half = max(total * float(baseline_frac) / 2.0, 1e-6)

    rows = []
    for k in range(n_seg):
        sel = np.flatnonzero(idx == k)
        if sel.size < 2:
            rows.append({"segment": k, "seg_angle_deg": None,
                         "seg_curv_deg": None, "seg_length_px": 0.0})
            continue
        a, b = s[sel[0]], s[sel[-1]]
        v = b - a
        ang = float(np.degrees(np.arctan2(v[1], v[0])))
        length = float(arc[sel[-1]] - arc[sel[0]])

        # Centre of this segment in arc length, then a window of +/- half a
        # baseline about it, clipped to the body.
        centre = 0.5 * (arc[sel[0]] + arc[sel[-1]])
        lo = np.searchsorted(arc, max(centre - half, arc[0]))
        hi = np.searchsorted(arc, min(centre + half, arc[-1]))
        lo, hi = int(np.clip(lo, 0, s.shape[0] - 1)), int(np.clip(hi, 0, s.shape[0] - 1))
        if hi - lo >= 2:
            mid = (lo + hi) // 2
            t0 = s[mid] - s[lo]
            t1 = s[hi] - s[mid]
            n0, n1 = np.linalg.norm(t0), np.linalg.norm(t1)
            if n0 > 0 and n1 > 0:
                cross = t0[0] * t1[1] - t0[1] * t1[0]
                dot = float(np.dot(t0, t1))
                curv = float(np.degrees(np.arctan2(cross, dot)))
            else:
                curv = None
        else:
            curv = None

        row = {"segment": k, "seg_angle_deg": round(ang, 4),
               "seg_curv_deg": None if curv is None else round(curv, 4),
               "seg_length_px": round(length, 3),
               "curv_baseline_px": round(2 * half, 2)}
        if um_per_px:
            row["seg_length_um"] = round(length * float(um_per_px), 3)
        rows.append(row)
    return rows


def measure(channels, assignment, min_pixels=8):
    """One row per (segment, side), with the brightness statistics per channel.

    WHAT IS REPORTED, AND WHICH ONE TO USE.

      mean    the average over the ROI. This is what the existing dF/F work
              uses (`worm_rgbcamp_analysis.add_dff`), and what the Fiji column
              contract carries. Sensitive to anything bright that is not muscle.
      median  robust to a handful of bright pixels. ADDED HERE, and for a real
              reason: a hemisegment ROI is a GEOMETRIC BAND of body pixels, not
              a segmentation of muscle. It contains hypodermis, gut, and
              whatever autofluorescence or coelomocyte happens to lie in it, so
              the mean is pulled by tissue that is not the thing being measured.
      p90     a robust peak. Use this rather than `max` when you want "how
              bright did this muscle get".
      max     the single brightest pixel. Kept because the contract has it, but
              it is one pixel: a hot camera pixel, a cosmic ray or a gut granule
              sets it, and it will not reproduce.
      p10     a robust low value - the mirror of p90.
      min     the DARKEST PIXEL in the ROI. Read the warning below before using
              it as a resting-calcium measure.

    RESTING CALCIUM IS NOT THE `min` COLUMN. This matters because elevated
    resting calcium in dystrophic muscle is a real finding of this lab's, and
    the column whose name suggests it does not carry it. `min` is a SPATIAL
    minimum - the darkest pixel present on that frame - and on the hand-curated
    extraction its median across hemisegments is 0.0. It is pinned to the
    darkest background pixel that happened to fall inside the band, and it moves
    when the band's edge moves.

    The resting level is a TEMPORAL low percentile of the background-subtracted
    mean, which is what `worm_kinetics.resting_calcium` computes (10th
    percentile of `green_bgsub`, deliberately not of dF/F0, which subtracts its
    own baseline and so cannot report a resting shift by construction). On the
    same file that is 10.1 against an overall mean of 44.9 - a muscle at rest,
    not a dark pixel.

    `median`, `p90` and `p10` are additions; `min`, `mean` and `max` are
    unchanged, so nothing downstream breaks.
    """

    seg, sid = assignment["segment"], assignment["side"]
    labels = assignment["labels"]
    shapes = {k: np.asarray(v).shape for k, v in channels.items()}
    if any(sh != seg.shape for sh in shapes.values()):
        raise HemisegmentError(
            f"Channels {shapes} do not match the frame {seg.shape}. Measuring "
            f"through a mismatched frame would return intensities from the "
            f"wrong pixels without any error.")

    rows, skipped = [], 0
    for k in range(assignment["n_seg"]):
        for s_val in (1, -1):
            sel = (seg == k) & (sid == s_val)
            n = int(sel.sum())
            if n < min_pixels:
                skipped += 1
                continue
            row = {"segment": k, "hemisegment": labels[s_val],
                   "side_sign": int(s_val), "roi_area_px": n,
                   "dorsal_known": assignment["dorsal_known"]}
            for name, img in channels.items():
                v = np.asarray(img, dtype=float)[sel]
                v = v[np.isfinite(v)]
                if v.size == 0:
                    for stat in ("min", "p10", "mean", "median", "p90", "max"):
                        row[f"{name}_{stat}"] = None
                    continue
                row[f"{name}_min"] = round(float(v.min()), 4)
                row[f"{name}_mean"] = round(float(v.mean()), 4)
                row[f"{name}_p10"] = round(float(np.percentile(v, 10)), 4)
                row[f"{name}_median"] = round(float(np.median(v)), 4)
                row[f"{name}_p90"] = round(float(np.percentile(v, 90)), 4)
                row[f"{name}_max"] = round(float(v.max()), 4)
            rows.append(row)
    return {
        "rows": rows, "n_rows": len(rows), "n_skipped": skipped,
        "min_pixels": min_pixels,
        "statistics": {
            "mean": "average over the ROI; what dF/F uses. Pulled by anything "
                    "bright in the band that is not muscle.",
            "median": "robust to a few bright pixels. Prefer it when gut "
                      "autofluorescence or a coelomocyte lies in the band.",
            "p90": "a robust peak - use instead of max for 'how bright did "
                   "this get'.",
            "max": "ONE pixel. A hot pixel or a gut granule sets it and it "
                   "will not reproduce. Kept for contract compatibility.",
            "p10": "a robust low value; the mirror of p90.",
            "min": ("the DARKEST PIXEL in the ROI - on real data its median is "
                    "0.0. NOT a resting-calcium measure: that is a TEMPORAL "
                    "low percentile of the background-subtracted mean, which "
                    "worm_kinetics.resting_calcium computes."),
        },
        "roi_is_geometric": (
            "A hemisegment is a BAND OF BODY PIXELS on one side of the "
            "midline, not a segmentation of muscle. It contains hypodermis, "
            "gut and whatever else lies in it, which is why the median is "
            "worth having alongside the mean."),
        "area_note": ("roi_area_px is reported because a bent worm has unequal "
                      "segment areas by geometry - the outside of a bend holds "
                      "more pixels. Comparing raw areas across frames measures "
                      "posture, not muscle."),
        "skipped_note": (f"{skipped} hemisegments had fewer than {min_pixels} "
                         f"pixels and were dropped rather than reported from a "
                         f"handful of pixels. Expect this at the tail tip, "
                         f"where the body is too thin to have two sides."
                         if skipped else "No hemisegment was too small."),
    }


def extract_frame(channels, mask, spine, n_seg=N_SEG, ventral_sign=None,
                  dorsal_known=False, um_per_px=None, min_pixels=8,
                  profile="anatomical"):
    """Everything for one frame: ROIs, intensities and per-segment kinematics.

    The spine must already be ordered HEAD FIRST - see head_tail.identify_head
    and apply_head_call. This does not check, because it cannot: a reversed
    spine is a perfectly valid spine, and the error would be silent here and
    visible only as an inverted anterior-posterior gradient much later.
    """
    a = assign(mask, spine, n_seg, ventral_sign, dorsal_known, profile)
    m = measure(channels, a, min_pixels=min_pixels)
    kin = {r["segment"]: r
           for r in segment_kinematics(spine, n_seg, um_per_px, profile)}
    for row in m["rows"]:
        row.update({k: v for k, v in kin[row["segment"]].items()
                    if k != "segment"})
    m["dorsal_known"] = a["dorsal_known"]
    m["side_note"] = a["side_note"]
    m["head_first_assumed"] = (
        "The spine was taken to be ordered head first. If it was not, every "
        "anterior-posterior gradient in these rows is reversed and dorsal and "
        "ventral are swapped, with nothing here to indicate it.")
    return m
