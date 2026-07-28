"""Compact, reusable descriptive summaries for result-review windows."""
from __future__ import annotations

import numpy as np


def population_track_summary(summary, accepted=None):
    total = len(summary)
    accepted_count = (int(sum(bool(accepted.get(int(t), False))
                              for t in summary.track_id))
                      if accepted is not None else
                      int((~summary.needs_review.astype(bool)).sum()))
    freq = summary.get("spine_bend_frequency_hz")
    freq = freq[np.isfinite(freq)] if freq is not None else []
    duration = summary.duration_s if "duration_s" in summary else []
    flagged = int(summary.needs_review.astype(bool).sum()) if "needs_review" in summary else 0
    if len(freq):
        frequency_text = (f"frequency median {np.median(freq):.2f} Hz "
                          f"(range {np.min(freq):.2f}–{np.max(freq):.2f}, n={len(freq)})")
    else:
        frequency_text = "frequency unavailable"
    median_duration = np.median(duration) if len(duration) else np.nan
    return (f"Tracks: {total} total, {accepted_count} accepted, {flagged} QC-flagged  |  "
            f"median duration {median_duration:.1f} s  |  {frequency_text}")


def table_review_summary(table, value_columns=()):
    """One-line, metric-neutral description for a table review plot."""
    parts = [f"Rows: {len(table):,}"]
    for identity in ("worm_id", "plate_id", "cohort_id"):
        if identity in table:
            parts.append(f"{identity.replace('_', ' ')}s: {table[identity].nunique()}")
    if "time_s" in table and len(table):
        time = table["time_s"].dropna()
        if len(time): parts.append(f"time: {time.min():.1f}–{time.max():.1f} s")
    for column in value_columns:
        if column in table:
            values = table[column].replace([np.inf, -np.inf], np.nan).dropna()
            if len(values):
                parts.append(f"{column.replace('_', ' ')}: median {np.median(values):.3g} "
                             f"({np.min(values):.3g}–{np.max(values):.3g})")
    return "  |  ".join(parts)
