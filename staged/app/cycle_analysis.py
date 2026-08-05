"""Per-CYCLE measurements, so cycles can be compared and correlated.

WHY THIS AND NOT `worm_kinetics.cycle_average`. That function already builds the
mean phase-locked waveform over body-bend cycles, and it does it well. What it
cannot do is answer "does a bigger bend go with a brighter cell?", because it
returns the AVERAGE cycle and averaging is exactly the operation that destroys
the cycle-to-cycle variation such a question is about.

This returns ONE ROW PER CYCLE - excursion, duration, peak brightness, peak
velocity, and when each peak occurred - so cycles become the unit of analysis
and can be correlated against each other.

CYCLES ARE NEVER FORMED ACROSS A CONFIDENCE GAP. Given spans from
`confidence_gate`, each span is cycled independently and the cycles pooled. A
cycle straddling a join would have a period and an amplitude that describe the
join rather than the animal.
"""
from __future__ import annotations

import numpy as np


class CycleError(Exception):
    """Refusals that name the consequence."""


def find_cycles(signal, fps=None, min_period_frames=4, detrend_window=None):
    """Cycle boundaries from upward zero-crossings of a detrended oscillation.

    Detrending is over a window, not the whole series: a worm that drifts or
    turns has a slowly moving mean, and subtracting one global mean would put
    every crossing on the same side of it and find no cycles at all.
    """
    from scipy import ndimage as ndi

    y = np.asarray(signal, dtype=float)
    if y.ndim != 1 or y.size < min_period_frames * 3:
        raise CycleError(
            f"Need a one-dimensional signal of at least "
            f"{min_period_frames * 3} samples to find cycles; got {y.shape}.")
    good = np.isfinite(y)
    if good.sum() < min_period_frames * 3:
        raise CycleError("Too much of the signal is missing to find cycles.")
    y = np.interp(np.arange(y.size), np.flatnonzero(good), y[good])

    if detrend_window is None:
        detrend_window = max(int(y.size // 4), min_period_frames * 4)
    baseline = ndi.uniform_filter1d(y, max(int(detrend_window), 3))
    c = y - baseline
    zc = np.flatnonzero((c[:-1] < 0) & (c[1:] >= 0))
    cycles = [(int(a), int(b)) for a, b in zip(zc[:-1], zc[1:])
              if b - a >= min_period_frames]
    return cycles, c


def cycle_table(cycles, detrended, signals=None, fps=None, span_offset=0,
                span_id=0):
    """One row per cycle: excursion, duration, and the peak of each signal.

    `signals` maps a name to a per-frame series measured on the same frames -
    cell brightness, velocity, whatever. Each contributes its peak value, its
    mean, and the PHASE at which it peaked, which is what makes questions like
    "does calcium peak before or after maximum bend" answerable.
    """
    rows = []
    signals = signals or {}
    for k, (a, b) in enumerate(cycles):
        seg = detrended[a:b + 1]
        if seg.size < 3:
            continue
        row = {
            "span_id": int(span_id),
            "cycle_id": int(k),
            "start_frame": int(a + span_offset),
            "end_frame": int(b + span_offset),
            "duration_frames": int(b - a + 1),
            "excursion": round(float(np.nanmax(seg) - np.nanmin(seg)), 6),
            "peak_positive": round(float(np.nanmax(seg)), 6),
            "peak_negative": round(float(np.nanmin(seg)), 6),
        }
        if fps:
            row["duration_s"] = round((b - a + 1) / float(fps), 4)
            row["frequency_hz"] = round(float(fps) / max(b - a + 1, 1), 4)
        for name, series in signals.items():
            s = np.asarray(series, dtype=float)[a:b + 1]
            if s.size == 0 or not np.isfinite(s).any():
                row[f"{name}_peak"] = None
                row[f"{name}_mean"] = None
                row[f"{name}_phase_at_peak"] = None
                continue
            i = int(np.nanargmax(s))
            row[f"{name}_peak"] = round(float(np.nanmax(s)), 6)
            row[f"{name}_mean"] = round(float(np.nanmean(s)), 6)
            # phase in turns (0..1) through the cycle, so cycles of different
            # duration are comparable
            row[f"{name}_phase_at_peak"] = round(i / max(s.size - 1, 1), 4)
        rows.append(row)
    return rows


def cycles_over_spans(signal, spans, signals=None, fps=None,
                      min_period_frames=4):
    """Cycle table pooled over confidence spans, each cycled independently.

    This is the join that must not happen anywhere else: spans are analysed
    separately and the resulting CYCLES are pooled. No cycle ever crosses a
    span boundary, so no period or excursion describes a discontinuity.
    """
    y = np.asarray(signal, dtype=float)
    all_rows, skipped = [], []
    for sid, (a, b) in enumerate(spans):
        seg = y[a:b + 1]
        sub = {k: np.asarray(v, dtype=float)[a:b + 1]
               for k, v in (signals or {}).items()}
        try:
            cycles, detrended = find_cycles(seg, fps=fps,
                                            min_period_frames=min_period_frames)
        except CycleError as exc:
            skipped.append({"span": [int(a), int(b)],
                            "frames": int(b - a + 1), "reason": str(exc)})
            continue
        all_rows.extend(cycle_table(cycles, detrended, sub, fps=fps,
                                    span_offset=a, span_id=sid))
    return {
        "cycles": all_rows,
        "n_cycles": len(all_rows),
        "n_spans_used": len({r["span_id"] for r in all_rows}),
        "n_spans_given": len(spans),
        "spans_skipped": skipped,
        "no_cycle_crosses_a_span_boundary": True,
        "note": ("Each confidence span was cycled independently and the cycles "
                 "pooled. Spans were never concatenated, so no cycle's period "
                 "or excursion describes a join between them."),
    }


def correlate(rows, x, y, min_n=8):
    """Correlate two per-cycle quantities, refusing when there are too few.

    A correlation over five cycles is not a finding, and reporting one with a
    confident-looking coefficient is how a fluctuation becomes a result. The
    refusal names the count rather than returning a number nobody should use.
    """
    xs = np.array([r.get(x) for r in rows], dtype=object)
    ys = np.array([r.get(y) for r in rows], dtype=object)
    ok = np.array([(a is not None and b is not None
                    and np.isfinite(float(a)) and np.isfinite(float(b)))
                   for a, b in zip(xs, ys)])
    n = int(ok.sum())
    if n < min_n:
        raise CycleError(
            f"Only {n} cycles have both {x} and {y}. A correlation over so few "
            f"is not a measurement - it would be reported with a coefficient "
            f"that looks like evidence. At least {min_n} are required.")
    a = np.array([float(v) for v in xs[ok]])
    b = np.array([float(v) for v in ys[ok]])
    r = float(np.corrcoef(a, b)[0, 1])
    # Spearman without scipy: correlation of ranks
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    rho = float(np.corrcoef(ra, rb)[0, 1])
    return {
        "x": x, "y": y, "n_cycles": n,
        "pearson_r": round(r, 4),
        "spearman_rho": round(rho, 4),
        "is_a_within_recording_correlation": True,
        "note": ("Cycles within one recording are not independent samples of a "
                 "population - they share the animal, the mount and the "
                 "session. This describes THIS recording; it is not evidence "
                 "about a genotype."),
    }
