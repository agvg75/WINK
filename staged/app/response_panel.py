"""Everything the stimulus might change, not just which way the animal points.

Andres: "There are many parameters that may be influenced by the stimulus."

TAXIS IS ONE HYPOTHESIS AMONG SEVERAL, and orientation measures test only it. A
field that changes how FAST animals move, how often they turn, how long their
runs are or how deeply they bend is acting on the animal without steering it.
That is kinesis rather than taxis, it is a real and separately reportable
result, and a study that measures only heading will record it as a null.

So the panel is split by what each measure needs:

  DIRECTIONAL measures require a field reference and answer "which way".
  NON-DIRECTIONAL measures need no reference at all and answer "how much".

The split matters because the non-directional ones can be computed in the
CANCELLED-FIELD and SHAM conditions too, where "which way" is undefined. Those
are the conditions that say whether an effect on speed is the field or the
coil, and an orientation-only analysis cannot use them for anything.

MANY MEASURES MEANS MANY CHANCES TO BE WRONG. Testing a dozen response
variables at p<0.05 gives roughly even odds of one significant result from
nothing at all. The panel therefore reports what threshold a finding must
clear given how many were examined, and it counts everything computed, not
everything reported - deciding which to report after seeing them is the same
error wearing a different hat.

POSTURE NEEDS SPINES. Body curvature, bend depth and omega turns cannot be had
from centroids, and `requires` says so per measure so the panel degrades to
what the recording can support instead of returning zeros. See tractability.py.
"""
from __future__ import annotations

import math

import numpy as np

MEASURES = {
    # --- non-directional: computable with no field reference ---------------
    "speed_mm_s": {
        "kind": "non_directional", "requires": "centroid",
        "means": "mean instantaneous speed",
        "hypothesis": "orthokinesis - the field changes how fast they move",
    },
    "path_length_mm": {
        "kind": "non_directional", "requires": "centroid",
        "means": "total distance travelled",
        "hypothesis": "activity change independent of direction",
    },
    "net_displacement_mm": {
        "kind": "non_directional", "requires": "centroid",
        "means": "start-to-end distance",
        "hypothesis": "dispersal change",
    },
    "tortuosity": {
        "kind": "non_directional", "requires": "centroid",
        "means": "path length divided by net displacement",
        "hypothesis": ("klinokinesis - the field changes how much they turn "
                       "without changing which way they end up"),
    },
    "turn_rate_hz": {
        "kind": "non_directional", "requires": "centroid",
        "means": "large heading changes per second",
        "hypothesis": "klinokinesis",
    },
    "reversal_rate_hz": {
        "kind": "non_directional", "requires": "centroid",
        "means": "heading changes beyond 120 degrees per second",
        "hypothesis": "the field modulates reversal frequency",
    },
    "dwell_fraction": {
        "kind": "non_directional", "requires": "centroid",
        "means": "fraction of time below a speed threshold",
        "hypothesis": "the field changes the tendency to pause",
    },
    "abs_turn_deg": {
        "kind": "non_directional", "requires": "centroid",
        "means": "mean absolute heading change per step",
        "hypothesis": "klinokinesis",
    },
    # --- directional: need a field reference --------------------------------
    "heading_r": {
        "kind": "directional", "requires": "centroid",
        "means": "polar concentration of headings about the field",
        "hypothesis": "magnetotaxis, directed",
    },
    "axial_r": {
        "kind": "directional", "requires": "centroid",
        "means": "axial concentration, ignoring polarity",
        "hypothesis": ("alignment with the field line in either direction - "
                       "invisible to a polar test"),
    },
    "turn_bias_deg": {
        "kind": "directional", "requires": "centroid",
        "means": "mean signed turn, positive being toward the field",
        "hypothesis": ("weathervaning - steering gradually toward the field "
                       "rather than choosing a heading outright"),
    },
    # --- posture: needs spines ----------------------------------------------
    "body_curvature_deg": {
        "kind": "non_directional", "requires": "spine",
        "means": "mean absolute body curvature",
        "hypothesis": "the field changes posture or gait",
    },
    "body_field_angle_deg": {
        "kind": "directional", "requires": "spine",
        "means": "body axis relative to the field, independent of travel",
        "hypothesis": ("the animal ORIENTS its body to the field even while "
                       "travelling elsewhere - undetectable from centroids"),
    },
    "deep_bend_rate_hz": {
        "kind": "non_directional", "requires": "spine",
        "means": "deep bends or omega turns per second",
        "hypothesis": "the field triggers reorientation manoeuvres",
    },
}

DWELL_MM_S = 0.02
TURN_DEG = 30.0
REVERSAL_DEG = 120.0


class PanelError(Exception):
    """Refusals that name the consequence."""


def _headings(rows):
    xs = np.asarray([float(r["x_mm"]) for r in rows])
    ys = np.asarray([float(r["y_mm"]) for r in rows])
    ts = np.asarray([float(r["time_s"]) for r in rows])
    dx, dy, dt = np.diff(xs), np.diff(ys), np.diff(ts)
    keep = dt > 0
    step = np.hypot(dx, dy)
    moved = keep & (step > 0)
    ang = np.degrees(np.arctan2(dy[moved], dx[moved]))
    return xs, ys, ts, dx, dy, dt, step, keep, moved, ang


def track_measures(rows, field_deg=None, tier="centroid"):
    """The panel for one animal. Missing inputs give None, never zero."""
    rows = sorted(rows, key=lambda r: float(r["time_s"]))
    if len(rows) < 3:
        return {}
    xs, ys, ts, dx, dy, dt, step, keep, moved, ang = _headings(rows)
    out = {}
    span = float(ts[-1] - ts[0])
    speeds = step[keep] / dt[keep]
    out["speed_mm_s"] = float(np.mean(speeds)) if speeds.size else None
    out["path_length_mm"] = float(np.sum(step))
    out["net_displacement_mm"] = float(np.hypot(xs[-1] - xs[0], ys[-1] - ys[0]))
    out["tortuosity"] = (out["path_length_mm"] / out["net_displacement_mm"]
                         if out["net_displacement_mm"] > 0 else None)
    out["dwell_fraction"] = (float(np.mean(speeds < DWELL_MM_S))
                             if speeds.size else None)

    if ang.size >= 2:
        turns = np.degrees(np.angle(np.exp(1j * np.radians(np.diff(ang)))))
        out["abs_turn_deg"] = float(np.mean(np.abs(turns)))
        out["turn_rate_hz"] = (float(np.count_nonzero(np.abs(turns) > TURN_DEG)
                                     / span) if span > 0 else None)
        out["reversal_rate_hz"] = (
            float(np.count_nonzero(np.abs(turns) > REVERSAL_DEG) / span)
            if span > 0 else None)
    if field_deg is not None and ang.size:
        rel = np.degrees(np.angle(np.exp(1j * np.radians(ang - field_deg))))
        out["heading_r"] = float(abs(np.mean(np.exp(1j * np.radians(rel)))))
        out["axial_r"] = float(abs(np.mean(np.exp(2j * np.radians(rel)))))
        if ang.size >= 2:
            # Positive when a step turned the animal toward the field.
            before = np.abs(rel[:-1])
            after = np.abs(rel[1:])
            out["turn_bias_deg"] = float(np.mean(before - after))

    if tier == "spine":
        curv = [r.get("body_curvature_deg") for r in rows
                if r.get("body_curvature_deg") is not None]
        if curv:
            out["body_curvature_deg"] = float(np.mean(np.abs(curv)))
        body = [r.get("body_angle_deg") for r in rows
                if r.get("body_angle_deg") is not None]
        if body and field_deg is not None:
            rel = np.degrees(np.angle(np.exp(
                1j * np.radians(np.asarray(body, dtype=float) - field_deg))))
            out["body_field_angle_deg"] = float(np.degrees(np.angle(
                np.mean(np.exp(1j * np.radians(rel))))))
        deep = [r for r in rows if r.get("deep_bend")]
        if deep and span > 0:
            out["deep_bend_rate_hz"] = len(deep) / span
    return out


def panel(tracks, field_deg=None, *, tier="centroid", window_s=None):
    """The panel per animal, optionally split into time windows.

    Windows are the same idea as in heading_analysis: early animals and late
    animals may differ in every one of these, not only in heading.
    """
    by_worm = {}
    for r in tracks:
        by_worm.setdefault(str(r.get("worm_id")), []).append(r)
    t0 = min(float(r["time_s"]) for r in tracks) if tracks else 0.0

    out = {}
    for worm, rows in sorted(by_worm.items()):
        rows = sorted(rows, key=lambda r: float(r["time_s"]))
        if window_s is None:
            out[worm] = {0: track_measures(rows, field_deg, tier)}
            continue
        buckets = {}
        for r in rows:
            idx = int((float(r["time_s"]) - t0) // float(window_s))
            buckets.setdefault(idx, []).append(r)
        out[worm] = {i: track_measures(g, field_deg, tier)
                     for i, g in sorted(buckets.items())}
    return out


def summarise(panel_result, measure, window=None):
    """Pool one measure across animals. None-safe, and says how many were lost."""
    vals, missing = [], 0
    for worm, windows in panel_result.items():
        for idx, m in windows.items():
            if window is not None and idx != window:
                continue
            v = m.get(measure)
            if v is None:
                missing += 1
            else:
                vals.append(float(v))
    if not vals:
        return {"measure": measure, "n": 0, "mean": None, "missing": missing}
    return {"measure": measure, "n": len(vals),
            "mean": float(np.mean(vals)), "sd": float(np.std(vals, ddof=1))
            if len(vals) > 1 else None, "missing": missing}


def required_threshold(n_measures, alpha=0.05, method="bonferroni"):
    """What a finding must clear, given how many measures were examined.

    Counted on everything COMPUTED, not everything reported. Choosing which
    measures to show after seeing them is the same error wearing a different
    hat, and it is the easier one to commit by accident.
    """
    n = max(int(n_measures), 1)
    if method == "bonferroni":
        thresh = alpha / n
    elif method == "sidak":
        thresh = 1 - (1 - alpha) ** (1.0 / n)
    else:
        raise PanelError("method must be 'bonferroni' or 'sidak'.")
    return {
        "n_measures": n, "alpha": alpha, "method": method,
        "required_p": thresh,
        "chance_of_one_false_positive": 1 - (1 - alpha) ** n,
        "why": (f"With {n} measures examined at alpha={alpha}, the chance of "
                f"at least one significant result from nothing at all is "
                f"{(1 - (1 - alpha) ** n):.0%}. A finding here should clear "
                f"p<{thresh:.4f} unless it was predicted in advance - in which "
                f"case say so, and it stands on its own."),
    }


def available(tier):
    """Which measures this recording can actually support."""
    ok = [k for k, v in MEASURES.items()
          if v["requires"] == "centroid" or tier == "spine"]
    blocked = [k for k in MEASURES if k not in ok]
    return {
        "tier": tier, "available": ok, "unavailable": blocked,
        "why": (None if not blocked else
                f"{len(blocked)} measure(s) need spines and this recording "
                f"gives centroids only: {', '.join(blocked)}. Body angle "
                f"relative to the field is among them, and it is the one that "
                f"can show an animal orienting its body to the field while "
                f"travelling somewhere else - which no centroid measure can "
                f"detect."),
    }


def kinesis_versus_taxis(findings):
    """Read a panel the way the two hypotheses require.

    `findings` maps measure name -> whether it differed from control.
    """
    direc = [m for m, hit in findings.items()
             if hit and MEASURES.get(m, {}).get("kind") == "directional"]
    non = [m for m, hit in findings.items()
           if hit and MEASURES.get(m, {}).get("kind") == "non_directional"]
    if direc and not non:
        verdict, why = "taxis", (
            "Direction changed and the non-directional measures did not: the "
            "animals steered without moving differently.")
    elif non and not direc:
        verdict, why = "kinesis", (
            "The animals moved differently without steering - speed, turning "
            "or pausing changed while heading did not. This is a real result "
            "and an orientation-only analysis would have recorded it as a "
            "null.")
    elif direc and non:
        verdict, why = "both", (
            "Both direction and locomotion changed. Check whether the "
            "directional effect survives once speed and turn rate are "
            "accounted for - a slower animal samples the field differently.")
    else:
        verdict, why = "no_effect", (
            "Neither directional nor non-directional measures moved.")
    return {"verdict": verdict, "why": why,
            "directional_hits": direc, "non_directional_hits": non}
