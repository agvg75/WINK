"""Rhythm and regularity from discrete events - pumps, defecation cycles, bends.

WHY THE CARDIAC MEASURES. The C. elegans pharynx is MYOGENIC: it generates its
own rhythm and uses homologues of most ion channels, pumps and transporters that
define vertebrate cardiac physiology, with neural input modulating rate much as
autonomic input modulates the heart. So the right vocabulary for its rhythm is
the one cardiology already validated for beat-to-beat variability - RMSSD,
SDNN, the Poincare descriptors - rather than something invented here.

That matters for damage scoring. Structural measures say what the tissue looks
like; rhythm says whether it still works. Anchoring a damage scale to measured
function avoids the circularity that dogs histopathological grading, where
scales are validated against the agreement of the people applying them.

THE SAME LOGIC APPLIES TO ANY EVENT TRAIN, which is why this takes frames and
an fps rather than living inside the pumping tool. Three uses, spanning three
orders of magnitude in period:

  pharyngeal pumps    ~0.2 s     tools/pharynx
  body bends          ~1 s       cycle starts from cycle_analysis.find_cycles
  defecation cycles   ~45 s      pboc_engine.candidate_events -> "peak_frame"

Defecation is the one with real precedent: wild-type period is ~45 s with an SD
near 3 s, a CV of 6-7%, which makes it one of the most precise rhythms known in
any animal - and knocking down the TRPM channels gon-2 and gtl-1 raises that
variability WITHOUT changing the mean period. A mean-only analysis sees nothing.

WATCH THE RECORDING LENGTH FOR THE SLOW ONES. min_events is a count of
INTERVALS, so eight defecation intervals need about SIX MINUTES of continuous
qualifying recording; at the pumping rate the same eight take two seconds. The
refusal below will say so rather than returning statistics over three cycles.

THE RULE, same as everywhere else here: an interval that spans a gap in
confidence is NOT an interval. Events are grouped by span, intervals computed
within each, and the intervals POOLED. Concatenating spans would invent a long
interval at every join and read as an arrhythmic pause that never happened.
"""
from __future__ import annotations

import numpy as np


class RhythmError(Exception):
    """Refusals that name the consequence."""


def intervals_within_spans(event_frames, spans, fps):
    """Inter-event intervals, never crossing a span boundary.

    Returns (intervals_s, per_span_counts). An event exactly on a boundary
    belongs to the span containing it; intervals are formed only between
    consecutive events inside the same span.
    """
    ev = np.asarray(sorted(int(e) for e in event_frames), dtype=int)
    out, counts = [], []
    for a, b in spans:
        inside = ev[(ev >= a) & (ev <= b)]
        counts.append(int(inside.size))
        if inside.size >= 2:
            out.append(np.diff(inside) / float(fps))
    intervals = np.concatenate(out) if out else np.array([], dtype=float)
    return intervals, counts


def rhythm_metrics(event_frames, spans, fps, min_events=8,
                   pause_multiple=3.0):
    """Rate and regularity, in the vocabulary cardiology already validated.

    - rate_hz, mean/median interval
    - SDNN: standard deviation of intervals; overall variability
    - CV: SDNN over the mean, so recordings at different rates compare
    - RMSSD: root mean square of SUCCESSIVE differences - beat-to-beat
      irregularity, insensitive to slow drift in rate, which is the point
    - Poincare SD1/SD2: short-term and long-term variability; SD1/SD2 near 1
      means the rhythm carries no memory from one interval to the next
    - pauses: intervals far longer than typical, counted separately because an
      arrest is a different event from a jittery rhythm and averaging them
      together hides both
    """
    ivs, counts = intervals_within_spans(event_frames, spans, fps)
    n_events = int(sum(counts))
    if ivs.size < min_events:
        raise RhythmError(
            f"Only {ivs.size} intervals from {n_events} events inside the "
            f"qualifying spans. Regularity statistics over so few describe "
            f"noise, and would be reported with the same confident-looking "
            f"numbers as a real measurement. At least {min_events} are needed.")

    med = float(np.median(ivs))
    pause_mask = ivs > pause_multiple * med
    steady = ivs[~pause_mask]
    if steady.size < 3:
        steady = ivs

    d = np.diff(steady)
    sd1 = float(np.std(d) / np.sqrt(2)) if d.size else float("nan")
    sd2v = 2 * np.var(steady) - 0.5 * np.var(d) if d.size else float("nan")
    sd2 = float(np.sqrt(max(sd2v, 0.0))) if d.size else float("nan")

    return {
        "n_events": n_events,
        "n_intervals": int(ivs.size),
        "events_per_span": counts,
        # Rate from the MEAN of steady intervals, not the median. Events land on
        # integer frames, so a true period that is not a whole number of frames
        # alternates between two values - a 7.5-frame period becomes 7, 8, 7, 8 -
        # and the median picks one of them, biasing the rate by several percent.
        # The mean averages the quantisation out. Pauses are already excluded,
        # which is what would otherwise make a mean the wrong choice.
        "rate_hz": (round(1.0 / float(np.mean(steady)), 4)
                    if steady.size and np.mean(steady) > 0 else None),
        "mean_interval_s": round(float(np.mean(steady)), 5),
        "median_interval_s": round(med, 5),
        "sdnn_s": round(float(np.std(steady)), 5),
        "cv": round(float(np.std(steady) / max(np.mean(steady), 1e-9)), 4),
        "rmssd_s": round(float(np.sqrt(np.mean(d ** 2))), 5) if d.size else None,
        "poincare_sd1_s": round(sd1, 5) if d.size else None,
        "poincare_sd2_s": round(sd2, 5) if d.size else None,
        "sd1_over_sd2": round(sd1 / sd2, 4) if d.size and sd2 > 0 else None,
        "n_pauses": int(pause_mask.sum()),
        "longest_pause_s": round(float(ivs.max()), 4) if ivs.size else None,
        "pause_definition": f"interval longer than {pause_multiple}x the median",
        "pauses_excluded_from_variability": True,
        "note": ("Intervals were formed only WITHIN confidence spans and then "
                 "pooled - none crosses a gap, so no join is reported as a "
                 "pause. Pauses are counted separately from variability "
                 "because an arrest and a jittery rhythm are different "
                 "findings and averaging them hides both."),
        "vocabulary": ("RMSSD, SDNN and the Poincare descriptors are the "
                       "cardiac beat-to-beat measures, used here because the "
                       "pharynx is myogenic and shares most of the ion "
                       "channels that define cardiac physiology."),
    }


def ordinal_guard(values, name="score"):
    """Refuse to average an ordinal scale, and say why.

    Histopathology guidance is explicit that computing a mean of ordinal grades
    assumes equal intervals the data do not have, and that summing them into a
    disease index is incorrect - yet roughly 70% of published papers report
    ordinal scores as means and standard deviations. This makes the correct
    handling the easy path: median, quartiles, and the full distribution.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        raise RhythmError(f"No values supplied for '{name}'.")
    levels, counts = np.unique(v, return_counts=True)
    return {
        "name": name,
        "n": int(v.size),
        "median": float(np.median(v)),
        "q1": float(np.percentile(v, 25)),
        "q3": float(np.percentile(v, 75)),
        "distribution": {float(a): int(b) for a, b in zip(levels, counts)},
        "mean_deliberately_not_reported": True,
        "why": ("This is an ORDINAL scale. A mean assumes the distance from "
                "grade 1 to 2 equals the distance from 2 to 3, which no "
                "grading scheme guarantees. Compare with non-parametric tests "
                "(Mann-Whitney, Kruskal-Wallis), not t-tests."),
    }
