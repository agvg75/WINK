"""Two-pass event detection: cheap everywhere, expensive where the rhythm says
something is missing.

Andres's design, and it is better than a uniform threshold. Detect cycles with
the ordinary detector, work out the animal's own period, flag the intervals that
came out TOO LONG to be one cycle, and rescan just those windows with a more
sensitive and more expensive method.

WHY THE LOGIC IS EXACTLY RIGHT FOR THE DEFECT IT FIXES. `pboc_engine` merges
events closer than 5 s into one. A merge does not remove an interval - it
FUSES two into a single long one. So every merge leaves a signature of precisely
the kind this looks for, and the correction is targeted rather than a blanket
loosening of the threshold that would buy back the missed events at the cost of
false ones everywhere else.

IT IS ALSO THE ONLY VERSION THAT IS SAFE ACROSS GENOTYPES. Lowering the
threshold globally changes sensitivity for every animal, and if dystrophic
animals sit closer to the threshold the change lands unevenly and looks like
biology. Rescanning only where the animal's OWN rhythm is violated keeps the
comparison honest: an animal with a metronomic record is never rescanned, so
nothing about it can change.

NOTHING IS SILENT. The report says how many windows were suspect, how many
events were recovered, and which intervals changed. A pipeline that quietly
found more events in the sick animals would be indistinguishable from a
phenotype.
"""
from __future__ import annotations

import numpy as np


class RescanError(Exception):
    """Refusals that name the consequence."""


def suspect_intervals(event_frames, fps, spans=None, tolerance=1.6,
                      min_intervals=6, max_multiple=None):
    """Intervals too long to be one cycle of this animal's own rhythm.

    The period is taken from the MEDIAN interval, not the mean: if events have
    genuinely been missed, the resulting long intervals drag a mean upward and
    the test then fails to notice the very thing it is looking for.

    `tolerance` is how many median periods an interval may reach before it is
    suspect. 1.6 sits between a jittery single cycle and a fused pair.
    `max_multiple` caps how many events a window may be credited with, so a
    genuine multi-minute arrest is not reported as forty missed pumps.
    """
    ev = np.asarray(sorted(int(e) for e in event_frames), dtype=int)
    if ev.size < min_intervals + 1:
        raise RescanError(
            f"Only {ev.size} events. The animal's own period cannot be "
            f"estimated from so few, and rescanning against a period guessed "
            f"from noise would invent events wherever the guess was low.")

    if spans:
        pairs = []
        for a, b in spans:
            inside = ev[(ev >= a) & (ev <= b)]
            pairs += list(zip(inside[:-1], inside[1:]))
    else:
        pairs = list(zip(ev[:-1], ev[1:]))
    if len(pairs) < min_intervals:
        raise RescanError(
            f"Only {len(pairs)} intervals inside the qualifying spans; "
            f"at least {min_intervals} are needed to define a period.")

    gaps = np.array([b - a for a, b in pairs], dtype=float)
    period = float(np.median(gaps))
    if period <= 0:
        raise RescanError("The median interval is zero; events coincide.")

    out = []
    for (a, b), g in zip(pairs, gaps):
        if g > tolerance * period:
            n = int(round(g / period)) - 1          # events likely fused away
            if max_multiple is not None:
                n = min(n, int(max_multiple))
            out.append({"start_frame": int(a), "end_frame": int(b),
                        "gap_frames": int(g),
                        "gap_periods": round(float(g / period), 3),
                        "expected_missing": max(n, 1)})
    return {
        "period_frames": round(period, 3),
        "period_s": round(period / float(fps), 4),
        "n_intervals": len(pairs),
        "suspect": out,
        "n_suspect": len(out),
        "tolerance": tolerance,
        "why_median": ("The period comes from the MEDIAN interval. Missed "
                       "events lengthen intervals, so a mean would be dragged "
                       "up by exactly the problem being looked for and the "
                       "test would stop noticing it."),
    }


def rescan(event_frames, fps, rescanner, spans=None, tolerance=1.6,
           min_intervals=6, max_multiple=None, guard_edges=2):
    """Re-examine the suspect windows and return a corrected event train.

    `rescanner(start_frame, end_frame)` is supplied by the caller and returns
    any additional event frames it finds strictly inside that window - a more
    sensitive detector, a matched filter, whatever is worth the time when it
    only has to run on a handful of windows.

    `guard_edges` keeps recovered events away from the window's own endpoints,
    which are already-detected events; without it the rescan re-finds them and
    reports each one as a recovery.
    """
    found = suspect_intervals(event_frames, fps, spans, tolerance,
                              min_intervals, max_multiple)
    original = sorted(int(e) for e in event_frames)
    recovered, per_window = [], []
    for w in found["suspect"]:
        a, b = w["start_frame"], w["end_frame"]
        try:
            extra = list(rescanner(a, b) or [])
        except Exception as exc:                          # pragma: no cover
            per_window.append({**w, "error": str(exc), "recovered": 0})
            continue
        keep = sorted({int(e) for e in extra
                       if a + guard_edges < int(e) < b - guard_edges})
        recovered += keep
        per_window.append({**w, "recovered": len(keep),
                           "frames": keep,
                           "still_long": len(keep) < w["expected_missing"]})

    corrected = sorted(set(original) | set(recovered))
    unresolved = [w for w in per_window if w.get("still_long")]
    return {
        "events_before": len(original),
        "events_after": len(corrected),
        "recovered": len(recovered),
        "corrected_events": corrected,
        "period_s": found["period_s"],
        "n_suspect_windows": found["n_suspect"],
        "windows": per_window,
        "n_unresolved": len(unresolved),
        "audit": (
            f"{found['n_suspect']} of {found['n_intervals']} intervals "
            f"exceeded {tolerance}x the animal's median period. Rescanning "
            f"those windows recovered {len(recovered)} events; "
            f"{len(unresolved)} windows are still longer than one period "
            f"afterwards."),
        "not_silent": (
            "Report this number with the result. A pipeline that quietly found "
            "more events in the sick animals would be indistinguishable from a "
            "phenotype, and the recovery rate is itself worth comparing across "
            "genotypes - if it differs, the first-pass detector is behaving "
            "differently in the two groups and that is a finding about the "
            "tool."),
        "unrescanned_animals_unchanged": (
            "An animal whose intervals were all within tolerance was never "
            "rescanned, so nothing about it can have changed. That is what "
            "keeps a two-pass method safe to use across genotypes where "
            "loosening a global threshold would not be."),
    }


def recovery_rate_by_group(reports, groups):
    """Did the rescan recover events unevenly between genotypes?

    THE CHECK THAT MATTERS FOR A GENOTYPE COMPARISON. If the second pass
    recovers far more events in one group, the first-pass detector was
    performing differently in the two, and any difference in the FINAL counts
    is partly a difference in detection. Better to see that than to publish it.
    """
    by = {}
    for rep, g in zip(reports, groups):
        d = by.setdefault(g, {"animals": 0, "before": 0, "recovered": 0,
                              "suspect_windows": 0})
        d["animals"] += 1
        d["before"] += rep["events_before"]
        d["recovered"] += rep["recovered"]
        d["suspect_windows"] += rep["n_suspect_windows"]
    for g, d in by.items():
        d["recovery_fraction"] = round(
            d["recovered"] / max(d["before"] + d["recovered"], 1), 4)
        d["windows_per_animal"] = round(
            d["suspect_windows"] / max(d["animals"], 1), 3)
    fracs = [d["recovery_fraction"] for d in by.values()]
    spread = (max(fracs) - min(fracs)) if len(fracs) > 1 else 0.0
    return {
        "by_group": by,
        "recovery_spread": round(float(spread), 4),
        "uneven": bool(spread > 0.05),
        "interpretation": (
            f"Recovery differs by {spread:.1%} between groups. The first-pass "
            f"detector is behaving differently in them, so part of any "
            f"difference in final event counts is detection rather than "
            f"biology. Report both passes."
            if spread > 0.05 else
            f"Recovery is even across groups ({spread:.1%} spread), so the "
            f"second pass is not preferentially rescuing one of them."),
    }
