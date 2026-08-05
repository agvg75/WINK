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


def shape_descriptors(segment, fps=None, prefix=""):
    """Waveform SHAPE within one cycle - how it rose, how it relaxed.

    Excursion says how far; these say how it got there and back. Two cycles of
    identical amplitude and identical period can have completely different rise
    and relaxation kinetics, and a tissue losing its contractile machinery is
    expected to change the second while leaving the first alone for a while.

    Timing is reported as a FRACTION of the cycle, not in seconds, so cycles at
    different rates are comparable - a slow cycle and a fast cycle with the same
    asymmetry give the same number. The absolute seconds are reported too,
    because a rate-independent shape change and a slowing are different findings.
    """
    s = np.asarray(segment, dtype=float)
    n = s.size
    out = {}
    if n < 3 or not np.isfinite(s).any():
        for k in ("time_to_peak_frac", "time_to_relax_frac", "asymmetry",
                  "rise_rate", "decay_rate", "time_to_peak_s",
                  "time_to_relax_s"):
            out[f"{prefix}{k}"] = None
        return out

    i_pk = int(np.nanargmax(s))
    # Relaxation runs from the peak to the lowest point AFTER it. Searching the
    # whole cycle would find a trough that preceded the peak and report a
    # negative relaxation time.
    tail = s[i_pk:]
    i_tr = i_pk + int(np.nanargmin(tail)) if tail.size > 1 else n - 1

    denom = max(n - 1, 1)
    rise_frac = i_pk / denom
    relax_frac = (i_tr - i_pk) / denom
    rise_s = (i_pk / float(fps)) if fps else None
    relax_s = ((i_tr - i_pk) / float(fps)) if fps else None

    amp_up = float(s[i_pk] - s[0])
    amp_dn = float(s[i_pk] - s[i_tr])
    out[f"{prefix}time_to_peak_frac"] = round(float(rise_frac), 4)
    out[f"{prefix}time_to_relax_frac"] = round(float(relax_frac), 4)
    out[f"{prefix}asymmetry"] = (round(float(rise_frac / (rise_frac + relax_frac)), 4)
                                 if (rise_frac + relax_frac) > 0 else None)
    out[f"{prefix}time_to_peak_s"] = round(rise_s, 5) if rise_s is not None else None
    out[f"{prefix}time_to_relax_s"] = round(relax_s, 5) if relax_s is not None else None
    out[f"{prefix}rise_rate"] = (round(amp_up / rise_s, 5)
                                 if fps and rise_s and rise_s > 0 else None)
    out[f"{prefix}decay_rate"] = (round(amp_dn / relax_s, 5)
                                  if fps and relax_s and relax_s > 0 else None)
    return out


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
        row.update(shape_descriptors(seg, fps=fps))
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
            # the same shape descriptors for the measured signal - a calcium
            # transient that takes longer to decay is a different finding from
            # one that peaks lower, and only the shape terms separate them
            row.update(shape_descriptors(s, fps=fps, prefix=f"{name}_"))
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


SHAPE_FIELDS = ("excursion", "duration_s", "time_to_peak_frac",
                "time_to_relax_frac", "asymmetry", "rise_rate", "decay_rate")


def shape_variability(rows, fields=None, min_n=8):
    """How much cycles DIFFER from each other - a dimension a mean cannot hold.

    Two animals can have identical mean excursion, identical mean time-to-peak
    and identical mean rate while one is metronomic and the other erratic. The
    mean is blind to that by construction, and it is the difference that a
    failing tissue may show first.

    This is not speculative. In the C. elegans defecation rhythm, knocking down
    the TRPM channels gon-2 and gtl-1 INCREASES cycle variability with NO CHANGE
    IN THE MEAN period - a phenotype invisible to any analysis reporting means.
    So the precedent exists in this animal; what is thin in the literature is
    applying the same treatment to the WAVEFORM SHAPE terms - rise time,
    relaxation time, per-cycle excursion - rather than only to cycle period.

    Reports both a plain CV and a ROBUST CV from the median absolute deviation,
    because one mis-detected cycle inflates an ordinary standard deviation far
    more than it moves a median, and the disagreement between the two is itself
    the signal that a detection needs looking at.
    """
    fields = list(fields or SHAPE_FIELDS)
    durations = [r.get("duration_frames") for r in rows
                 if r.get("duration_frames")]
    median_frames = float(np.median(durations)) if durations else None

    out, skipped = {}, {}
    for f in fields:
        vals = np.array([float(r[f]) for r in rows
                         if r.get(f) is not None and np.isfinite(float(r[f]))])
        if vals.size < min_n:
            skipped[f] = f"only {vals.size} cycles (need {min_n})"
            continue
        med = float(np.median(vals))
        mad = float(np.median(np.abs(vals - med)))
        mean = float(np.mean(vals))
        entry = {
            "n": int(vals.size),
            "median": round(med, 6),
            "iqr": round(float(np.percentile(vals, 75)
                               - np.percentile(vals, 25)), 6),
            "sd": round(float(np.std(vals, ddof=1)), 6),
            "cv": round(float(np.std(vals, ddof=1) / mean), 4) if mean else None,
            # 1.4826 puts the MAD on the same scale as a standard deviation
            # for normally distributed data, so the two CVs are comparable
            "robust_cv": (round(1.4826 * mad / abs(med), 4) if med else None),
        }
        # A timing fraction cannot be measured more finely than one frame. With
        # F frames in a cycle the quantisation step is 1/(F-1), and quantisation
        # alone produces an SD of step/sqrt(12) in a PERFECTLY regular animal.
        # Reporting variability below that floor would be reporting the camera.
        if f.endswith("_frac") or f == "asymmetry":
            if median_frames and median_frames > 1:
                step = 1.0 / (median_frames - 1)
                floor = step / np.sqrt(12.0)
                entry["timing_quantisation_sd"] = round(float(floor), 5)
                entry["above_quantisation_floor"] = bool(entry["sd"] > 2 * floor)
                if not entry["above_quantisation_floor"]:
                    entry["warning"] = (
                        f"SD {entry['sd']} is within twice the {floor:.4f} "
                        f"expected from frame quantisation alone at "
                        f"{median_frames:.0f} frames per cycle. Record faster "
                        f"before treating this as variability of the animal.")
        out[f] = entry

    return {
        "fields": out,
        "not_enough_cycles": skipped,
        "median_frames_per_cycle": median_frames,
        "is_a_separate_dimension_from_the_mean": True,
        "note": ("Variability across cycles is not a worse version of the mean, "
                 "it is a different measurement. Report both. Compare with "
                 "Levene's or Brown-Forsythe test, which compare SPREADS - a "
                 "t-test on the means will find nothing when only the spread "
                 "has changed."),
        "confound": ("Cycle-to-cycle spread rises with measurement noise as "
                     "well as with biology, so a dimmer or blurrier recording "
                     "looks more variable. Compare variability only across "
                     "recordings of matched exposure, magnification and rate, "
                     "or the imaging becomes the phenotype."),
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
