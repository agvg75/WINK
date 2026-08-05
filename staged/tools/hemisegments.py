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


def segment_bounds(spine, n_seg):
    """Split the spine into n_seg parts of equal ARC LENGTH.

    Equal arc length, not equal index: a resampled spine is usually already
    evenly spaced, but a raw traced one is not, and equal-index segments would
    then be different physical lengths that still get compared with each other.
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
    edges = np.linspace(0.0, total, n_seg + 1)
    # segment index of each spine point, clipped so the tail point lands in the
    # last segment rather than one past it
    idx = np.clip(np.searchsorted(edges, arc, side="right") - 1, 0, n_seg - 1)
    return idx, arc, edges


def assign(mask, spine, n_seg, ventral_sign=None, dorsal_known=False):
    """Label every body pixel with (segment, side).

    Returns a dict with `segment` and `side` arrays over the mask, where side is
    +1 or -1 by the cross-product convention, plus the label to use for each.
    """
    m = np.asarray(mask, dtype=bool)
    s = np.asarray(spine, dtype=float)
    seg_of_point, _, _ = segment_bounds(s, n_seg)

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


def segment_kinematics(spine, n_seg, um_per_px=None):
    """Per-segment angle and curvature, for the kinematics columns."""
    s = np.asarray(spine, dtype=float)
    idx, arc, edges = segment_bounds(s, n_seg)
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
        # turning across the segment, in degrees
        if sel.size >= 3:
            t0 = s[sel[1]] - s[sel[0]]
            t1 = s[sel[-1]] - s[sel[-2]]
            cross = t0[0] * t1[1] - t0[1] * t1[0]
            dot = float(np.dot(t0, t1))
            curv = float(np.degrees(np.arctan2(cross, dot)))
        else:
            curv = None
        row = {"segment": k, "seg_angle_deg": round(ang, 4),
               "seg_curv_deg": None if curv is None else round(curv, 4),
               "seg_length_px": round(length, 3)}
        if um_per_px:
            row["seg_length_um"] = round(length * float(um_per_px), 3)
        rows.append(row)
    return rows


def measure(channels, assignment, min_pixels=8):
    """One row per (segment, side), with min/mean/max of each channel.

    `channels` maps a name to a 2-D image on the same frame - e.g.
    {"green": g, "red": r}. Rows carry `roi_area_px` because a bent worm has
    unequal segment areas by geometry: the outside of a bend simply contains
    more pixels. That is a fact about posture, not about muscle, and comparing
    raw areas across frames measures bending.
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
                    row[f"{name}_min"] = row[f"{name}_mean"] = None
                    row[f"{name}_max"] = None
                    continue
                row[f"{name}_min"] = round(float(v.min()), 4)
                row[f"{name}_mean"] = round(float(v.mean()), 4)
                row[f"{name}_max"] = round(float(v.max()), 4)
            rows.append(row)
    return {
        "rows": rows, "n_rows": len(rows), "n_skipped": skipped,
        "min_pixels": min_pixels,
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


def extract_frame(channels, mask, spine, n_seg=12, ventral_sign=None,
                  dorsal_known=False, um_per_px=None, min_pixels=8):
    """Everything for one frame: ROIs, intensities and per-segment kinematics.

    The spine must already be ordered HEAD FIRST - see head_tail.identify_head
    and apply_head_call. This does not check, because it cannot: a reversed
    spine is a perfectly valid spine, and the error would be silent here and
    visible only as an inverted anterior-posterior gradient much later.
    """
    a = assign(mask, spine, n_seg, ventral_sign, dorsal_known)
    m = measure(channels, a, min_pixels=min_pixels)
    kin = {r["segment"]: r for r in segment_kinematics(spine, n_seg, um_per_px)}
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
