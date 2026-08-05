"""Choose a confidence level, and measure only where the data earn it.

THE PROBLEM. Every tool here has periods of differing confidence within one
recording - a worm that leaves focus, frames where the body is not separable, a
tracker that loses the midline and recovers. Reporting one number over the whole
recording averages the good with the bad and says nothing about which is which.

THE RULE THAT MAKES THIS SAFE. Spans that pass are NEVER joined end to end.
Stitching high-confidence sections into one continuous series is the obvious
thing to want and it manufactures data: a body-bend cycle spanning the join
would be measured across a discontinuity that never happened, and its period and
excursion would be inventions. Each span is analysed separately and results are
POOLED afterwards, which is a different operation and an honest one.

WHAT A CONFIDENCE SERIES IS. One value per frame, higher is better, on whatever
scale a tool already uses - tracking quality, body-background contrast, spine
coverage. This module does not invent confidence; it applies a threshold the
user chose to a series the tool already computed, and reports what that costs.
"""
from __future__ import annotations

import numpy as np


class GateError(Exception):
    """Refusals that name the consequence."""


# Named levels so a lab can speak in words rather than numbers, while the
# number stays visible in provenance. These are QUANTILES of the recording's
# own confidence, not absolute thresholds - absolute values mean different
# things in different tools and could not be compared.
LEVELS = {
    "any": 0.0,
    "permissive": 0.25,
    "balanced": 0.50,
    "strict": 0.75,
    "very strict": 0.90,
}


def qualifying_spans(confidence, threshold, min_length=1, max_gap=0):
    """Contiguous runs at or above `threshold`.

    `max_gap` bridges brief dips WITHIN a span - a single bad frame in an
    otherwise good stretch is usually a hiccup, not a change of regime. It
    never joins spans that are genuinely separated: the bridged frames are
    recorded, so a result can say how much of it was interpolated over rather
    than measured.
    """
    c = np.asarray(confidence, dtype=float)
    if c.ndim != 1:
        raise GateError(f"Confidence must be one value per frame, got shape "
                        f"{c.shape}.")
    good = np.isfinite(c) & (c >= threshold)
    if max_gap > 0:
        i = 0
        n = good.size
        while i < n:
            if good[i]:
                i += 1
                continue
            j = i
            while j < n and not good[j]:
                j += 1
            if 0 < i and j < n and (j - i) <= max_gap:
                good[i:j] = True
            i = max(j, i + 1)

    spans, start = [], None
    for i, v in enumerate(good):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= min_length:
                spans.append((start, i - 1))
            start = None
    if start is not None and good.size - start >= min_length:
        spans.append((start, int(good.size) - 1))
    return spans


def gate(confidence, level="balanced", threshold=None, min_length=1,
         max_gap=0, fps=None):
    """Apply a confidence level and report honestly what it kept and dropped.

    Returns a dict carrying the spans, the coverage, and - the part that
    matters - an explicit statement that the spans must not be concatenated.
    """
    c = np.asarray(confidence, dtype=float)
    finite = c[np.isfinite(c)]
    if finite.size == 0:
        raise GateError(
            "The confidence series is entirely missing, so no level can be "
            "applied. Measuring everything as though it qualified would report "
            "unusable frames as results.")
    if threshold is None:
        if level not in LEVELS:
            raise GateError(
                f"Unknown confidence level '{level}'. Choose one of "
                f"{', '.join(LEVELS)}, or pass an explicit threshold.")
        threshold = float(np.quantile(finite, LEVELS[level])) if LEVELS[level] > 0 \
            else float(np.nanmin(finite))

    spans = qualifying_spans(c, threshold, min_length=min_length,
                             max_gap=max_gap)
    kept = int(sum(b - a + 1 for a, b in spans))
    total = int(c.size)
    out = {
        "level": level if threshold is None else f"{level} (threshold {threshold:.4g})",
        "threshold": float(threshold),
        "spans": spans,
        "n_spans": len(spans),
        "frames_kept": kept,
        "frames_total": total,
        "coverage": round(kept / max(total, 1), 4),
        "longest_span_frames": max((b - a + 1 for a, b in spans), default=0),
        "min_length": min_length,
        "max_gap_bridged": max_gap,
        "spans_must_not_be_concatenated": True,
        "why": ("Each qualifying span is analysed separately and results are "
                "POOLED. Joining them end to end would put a discontinuity "
                "inside a cycle, and that cycle's period and amplitude would "
                "be inventions rather than measurements."),
    }
    if fps:
        out["seconds_kept"] = round(kept / float(fps), 3)
        out["span_seconds"] = [round((b - a + 1) / float(fps), 3)
                               for a, b in spans]
    if not spans:
        out["warning"] = (
            f"No span met this confidence level. The recording's confidence "
            f"ranges {np.nanmin(finite):.4g} to {np.nanmax(finite):.4g}; the "
            f"threshold is {threshold:.4g}. Lower the level, or accept that "
            f"this recording does not support the measurement.")
    elif out["coverage"] < 0.25:
        out["warning"] = (
            f"Only {100*out['coverage']:.0f}% of the recording qualifies. "
            f"Whatever is reported describes that fraction, not the animal's "
            f"behaviour over the whole recording.")
    return out


def sweep(confidence, levels=None, fps=None):
    """What each level would cost, so a choice can be informed rather than blind."""
    rows = []
    for name in (levels or list(LEVELS)):
        try:
            g = gate(confidence, level=name, fps=fps)
        except GateError:
            continue
        rows.append({"level": name, "threshold": round(g["threshold"], 5),
                     "coverage": g["coverage"], "n_spans": g["n_spans"],
                     "longest_span_frames": g["longest_span_frames"]})
    return rows
