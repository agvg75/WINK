"""Changes that defy biology: too large, unprecedented, and spatially alone.

Andres's specification, and all three clauses are load-bearing:

    "at 5 fps a particular body segment is extremely unlikely to experience a
     60 degree change in angle - PARTICULARLY IF IT HASN'T THE ENTIRE
     RECORDING, particularly if THE SEGMENTS BEFORE AND AFTER DID NOT EITHER.
     That defies biology."

So an implausible change is one that is

  1. LARGE            in absolute terms for the frame rate,
  2. UNPRECEDENTED    against that segment's OWN history, and
  3. SPATIALLY ALONE  while its neighbours stayed quiet.

THE THIRD CLAUSE IS THE ONE THAT SEPARATES ARTEFACT FROM BEHAVIOUR, and it is
why a plain threshold does not work. Bodies are continuous: a real bend at one
place bends the places either side of it, so behaviour arrives as a spatially
coherent front. A tracking failure does not - a midline point snapping to the
wrong edge moves one segment while its neighbours carry on. Judge magnitude
alone and every vigorous animal is flagged; add coherence and only the
physically impossible is.

CLAUSE 2 MUST BE PER SEGMENT, not per animal. The head sweeps during foraging
and the tail whips while swimming; a threshold that suits the midbody condemns
the head all recording long. Each segment is compared with itself.

AND THE HISTORY MUST BE ROBUST. Using a standard deviation lets a large
artefact inflate the very spread it is being measured against, so the worst
events hide themselves. The median absolute deviation does not move.

The same three clauses apply to BRIGHTNESS, which is why this takes a grid
rather than knowing anything about curvature. Calcium in one myocyte does not
jump while its neighbours sit still.
"""
from __future__ import annotations

import numpy as np


class ImplausibleError(Exception):
    """Refusals that name the consequence."""


def _robust_scale(x):
    """MAD, scaled to be comparable with a standard deviation."""
    x = x[np.isfinite(x)]
    if x.size < 4:
        return np.nan
    med = np.median(x)
    return 1.4826 * float(np.median(np.abs(x - med)))


def step_sizes(grid):
    """Frame-to-frame change per segment. Gaps stay NaN rather than 0.

    A change measured ACROSS a gap is not a change - it is the difference
    between two frames that were never adjacent - so it must not be scored as
    one. Otherwise every dropout produces a pair of huge false steps at its
    edges, and the detector spends its time rediscovering the tracking it
    already knows failed.
    """
    g = np.asarray(grid, dtype=float)
    if g.ndim != 2 or g.shape[1] < 3:
        raise ImplausibleError(
            f"Need a (segment x frame) grid with at least 3 frames; got "
            f"{g.shape}.")
    d = np.abs(np.diff(g, axis=1))
    both = np.isfinite(g[:, :-1]) & np.isfinite(g[:, 1:])
    d[~both] = np.nan
    return d


def find(grid, absolute_min=None, own_z=6.0, neighbour_span=2,
         neighbour_ratio=0.45, min_history=20):
    """Locate changes that are large, unprecedented for the segment, and alone.

    `absolute_min` is the floor below which nothing is reported however unusual
    it is for that segment - a quiet segment's own history makes tiny wobbles
    look extreme, and without a floor a perfectly still animal generates pages
    of findings. For curvature at 5 fps something like 25-30 degrees is a
    sensible floor; for brightness it depends on the scale and should be set.

    `neighbour_ratio` is how large the neighbours' change may be, relative to
    the suspect one, before the event counts as spatially coherent - that is,
    as behaviour rather than artefact.
    """
    d = step_sizes(grid)
    n_seg, n_step = d.shape
    scales = np.array([_robust_scale(d[i]) for i in range(n_seg)])
    meds = np.array([np.nanmedian(d[i]) if np.isfinite(d[i]).any() else np.nan
                     for i in range(n_seg)])
    usable = np.array([int(np.isfinite(d[i]).sum()) for i in range(n_seg)])

    events = []
    for i in range(n_seg):
        if usable[i] < min_history or not np.isfinite(scales[i]) or scales[i] <= 0:
            continue
        for t in range(n_step):
            v = d[i, t]
            if not np.isfinite(v):
                continue
            if absolute_min is not None and v < absolute_min:
                continue
            z = (v - meds[i]) / scales[i]
            if z < own_z:
                continue
            lo = max(i - neighbour_span, 0)
            hi = min(i + neighbour_span + 1, n_seg)
            others = [d[j, t] for j in range(lo, hi)
                      if j != i and np.isfinite(d[j, t])]
            if not others:
                support = np.nan          # cannot judge coherence
                alone = False             # so do not claim it is alone
            else:
                support = float(np.nanmax(others) / v) if v > 0 else np.nan
                alone = support < neighbour_ratio
            if not alone:
                continue
            events.append({
                "segment": int(i), "frame": int(t + 1),
                "change": round(float(v), 4),
                "own_z": round(float(z), 2),
                "segment_typical": round(float(meds[i]), 4),
                "neighbour_support": (None if not np.isfinite(support)
                                      else round(float(support), 3)),
                "why": (f"segment {i} changed by {v:.1f} between frames "
                        f"{t} and {t + 1}; it typically changes "
                        f"{meds[i]:.1f}, and its neighbours changed at most "
                        f"{support * v:.1f} in the same step"),
            })

    events.sort(key=lambda e: -e["own_z"])
    return {
        "events": events,
        "n_events": len(events),
        "n_segments_scored": int(np.sum(usable >= min_history)),
        "segments_skipped": int(n_seg - np.sum(usable >= min_history)),
        "settings": {"absolute_min": absolute_min, "own_z": own_z,
                     "neighbour_span": neighbour_span,
                     "neighbour_ratio": neighbour_ratio},
        "three_clauses": (
            "Large in absolute terms, unprecedented against that segment's own "
            "history, and unaccompanied by its neighbours. All three are "
            "required: magnitude alone flags every vigorous animal, and it is "
            "spatial isolation that separates a tracking failure from a real "
            "bend, because a body is continuous and behaviour arrives as a "
            "coherent front."),
        "no_absolute_floor": (
            None if absolute_min is not None else
            "No absolute_min was set, so a segment that barely moves can have "
            "tiny wobbles flagged as extreme relative to its own quiet history. "
            "Set a floor in the units of this grid."),
    }


def sections(events, gap_frames=10, min_events=1):
    """Group events into the SECTIONS a person would review.

    Nobody inspects three hundred individual frames. Events within `gap_frames`
    of each other are one incident, which is also the honest unit: a midline
    that snaps to the wrong edge and stays there produces a burst, not a point,
    and reporting the burst as forty findings overstates how much is wrong.
    """
    if not events:
        return []
    by_frame = sorted(events, key=lambda e: e["frame"])
    out, cur = [], [by_frame[0]]
    for e in by_frame[1:]:
        if e["frame"] - cur[-1]["frame"] <= gap_frames:
            cur.append(e)
        else:
            out.append(cur)
            cur = [e]
    out.append(cur)
    return [{
        "start_frame": g[0]["frame"], "end_frame": g[-1]["frame"],
        "n_events": len(g),
        "segments": sorted({e["segment"] for e in g}),
        "peak_z": round(max(e["own_z"] for e in g), 2),
        "worst": max(g, key=lambda e: e["own_z"]),
    } for g in out if len(g) >= min_events]


def review_queue(grids, absolute_min=None, **kw):
    """Run over several named grids and return the sections needing review.

    `grids` maps a label - "curvature", "green dorsal" - to its grid, so one
    call covers a whole recording and the output says WHICH panel objected.
    """
    queue = []
    for label, g in grids.items():
        try:
            found = find(g, absolute_min=absolute_min, **kw)
        except ImplausibleError as exc:
            queue.append({"panel": label, "error": str(exc)})
            continue
        for s in sections(found["events"]):
            queue.append({"panel": label, **s})
    queue.sort(key=lambda s: -s.get("peak_z", 0))
    return {
        "sections": queue,
        "n_sections": len([q for q in queue if "peak_z" in q]),
        "for_montage": (
            "Each section is a span of frames and the segments that objected - "
            "enough to cut a clip with the tracking overlaid and ask a person "
            "whether it is correct. Sections, not frames: a midline that snaps "
            "to the wrong edge and stays there is one incident, and reporting "
            "it as forty findings overstates how much is wrong."),
    }
