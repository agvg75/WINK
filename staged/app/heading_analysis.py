"""Headings binned in time, because the preference reverses during the assay.

Bainbridge et al. 2019 (J Comp Physiol A) measured the preferred angle rotating
by about 180 degrees over a 90-minute assay, passing through an interval with
no detectable preference: 0-30 min at 183 deg (r=0.65, p<0.001), 30-60 min not
significant (r=0.13, p=0.7), 60-90 min r=0.35, p=0.12.

WHY A SINGLE MEAN HEADING IS NOT A WEAKER VERSION OF THIS, but a wrong one. A
mean pooled over the whole assay averages the first half against the second and
lands near zero. That reads as "no preference" when the truth is two opposite
strong preferences, and nothing in the summary distinguishes the two cases.
Time binning is not a refinement here; without it the headline number is an
artefact of the averaging window.

THREE CONVENTIONS FROM THAT PAPER, EACH FIXING A DIFFERENT BIAS:

  5% TRACK SEGMENTS. Animals cross the field of view at very different speeds,
  so weighting by raw samples lets the slowest dominate. Speed is not
  independent of orientation, so that bias has a direction. Binning every track
  into the same number of proportional segments makes fast and slow animals
  contribute equally.

  10-MINUTE WINDOWS, assigned by when a segment BEGAN, grouped into 30-minute
  intervals - the timescale on which the reversal happens.

  THE ASSAY IS THE STATISTICAL UNIT, following Landler et al. 2018. Animals on
  one plate share a plate, a batch, an experimenter and a day; pooling them
  treats those as independent and inflates n by the number of worms. Each assay
  contributes ONE heading per window.

HEADINGS ARE MEASURED AGAINST THE FIELD AT THAT MOMENT. With a static field
that is a constant; with a swept or rotating one it is not, and comparing a
late segment against the starting direction would rotate the answer by however
much the field had turned.
"""
from __future__ import annotations

import numpy as np

from orientation_core import mean_resultant, rayleigh_test, wrap_degrees

WINDOW_S = 600.0        # 10 minutes
INTERVAL_S = 1800.0     # 30 minutes
SEGMENTS_PER_TRACK = 20  # 5% each


class HeadingError(Exception):
    """Refusals that name the consequence."""


def _field_angle(field, time_s):
    """Field direction in degrees at this instant, from an angle or a provider."""
    if field is None:
        raise HeadingError(
            "A field direction is required. A heading is an angle RELATIVE to "
            "the stimulus, so without it these are compass bearings in room "
            "coordinates and will encode which way the bench faces.")
    if isinstance(field, (int, float)):
        return float(field)
    if hasattr(field, "applied_at"):
        vec = np.asarray(field.applied_at(time_s), dtype=float)
        if float(np.linalg.norm(vec[:2])) == 0:
            return None
        return float(np.degrees(np.arctan2(vec[1], vec[0])))
    if hasattr(field, "sample"):
        s = field.sample(0.0, 0.0, time_s)
        if s.direction_xyz is None:
            return None
        return float(np.degrees(np.arctan2(s.direction_xyz[1],
                                           s.direction_xyz[0])))
    raise HeadingError(f"Cannot get a field direction from {type(field)}.")


def track_directional_vectors(rows, field, n_segments=SEGMENTS_PER_TRACK,
                              t0=None):
    """One heading per 5% of a track, each relative to the field at its start.

    Returns dicts with the segment's start time, so the caller can bin them by
    when they BEGAN - which is the paper's convention and matters because a
    segment can straddle a window boundary.
    """
    rows = sorted(rows, key=lambda r: float(r["time_s"]))
    if len(rows) < 2:
        return []
    times = np.asarray([float(r["time_s"]) for r in rows])
    xs = np.asarray([float(r["x_mm"]) for r in rows])
    ys = np.asarray([float(r["y_mm"]) for r in rows])
    start, end = times[0], times[-1]
    if end <= start:
        return []
    origin = start if t0 is None else float(t0)
    edges = np.linspace(start, end, int(n_segments) + 1)
    out = []
    for i in range(int(n_segments)):
        a, b = edges[i], edges[i + 1]
        xa, ya = float(np.interp(a, times, xs)), float(np.interp(a, times, ys))
        xb, yb = float(np.interp(b, times, xs)), float(np.interp(b, times, ys))
        dx, dy = xb - xa, yb - ya
        dist = float(np.hypot(dx, dy))
        if dist <= 0:
            # A segment with no displacement has no direction. Recording it as
            # zero degrees would add a spurious vote for the field direction.
            continue
        fld = _field_angle(field, a)
        if fld is None:
            continue
        heading = np.degrees(np.arctan2(dy, dx))
        out.append({
            "segment": i, "t_start_s": a - origin, "t_end_s": b - origin,
            "displacement_mm": dist,
            "heading_deg": float(wrap_degrees(heading)),
            "field_deg": fld,
            "relative_deg": float(wrap_degrees(heading - fld)),
        })
    return out


def assay_window_headings(tracks, field, *, window_s=WINDOW_S,
                          n_segments=SEGMENTS_PER_TRACK,
                          participation_radius_mm=None, center_xy_mm=None,
                          duration_s=None):
    """One mean heading per time window for ONE assay.

    `participation_radius_mm` implements the source's rule that an animal must
    move more than 5 mm from the start position to count. Animals that never
    do are not slow participants; they did not participate, and averaging
    their jitter into the population heading adds direction-free noise that
    lowers r without lowering anyone's confidence in it.
    """
    by_worm = {}
    for r in tracks:
        by_worm.setdefault(str(r.get("worm_id")), []).append(r)
    t0 = min(float(r["time_s"]) for r in tracks) if tracks else 0.0

    excluded = []
    vectors = []
    for worm, rows in sorted(by_worm.items()):
        if participation_radius_mm:
            if center_xy_mm is None:
                raise HeadingError(
                    "A participation radius needs a centre to measure from.")
            far = max(float(np.hypot(float(r["x_mm"]) - center_xy_mm[0],
                                     float(r["y_mm"]) - center_xy_mm[1]))
                      for r in rows)
            if far < float(participation_radius_mm):
                excluded.append({"worm_id": worm, "max_radius_mm": far})
                continue
        vectors.extend(track_directional_vectors(rows, field, n_segments, t0))

    windows = {}
    for v in vectors:
        idx = int(v["t_start_s"] // float(window_s))
        windows.setdefault(idx, []).append(v["relative_deg"])

    out = {}
    for idx, angles in sorted(windows.items()):
        stat = mean_resultant(angles)
        out[idx] = {
            "window_index": idx,
            "t_start_s": idx * float(window_s),
            "mean_heading_deg": stat["mean_angle_deg"],
            "resultant_length": stat["resultant_length"],
            "n_segments": stat["n"],
        }
    return {
        "windows": out,
        "n_worms": len(by_worm),
        "n_participated": len(by_worm) - len(excluded),
        "excluded_non_participants": excluded,
        "n_segments_total": len(vectors),
        "window_s": float(window_s),
    }


def population_intervals(assays, *, interval_s=INTERVAL_S, window_s=WINDOW_S,
                         unit="assay_window"):
    """Pool ACROSS assays. `unit` decides what counts as an independent draw.

    "assay_window" is the published convention: each assay contributes one
    heading per 10-minute window, so a 30-minute interval receives three per
    assay and n is about three times the number of plates.

    "assay" collapses those three to one mean per assay per interval, so n IS
    the number of plates.

    THE TWO DISAGREE, AND MEASURABLY. Simulated animals given fixed random
    headings - no preference at all - produced significant intervals in about
    half of runs under "assay_window", because the three windows of one assay
    are the same six plates measured three times, and the Rayleigh test treats
    them as eighteen independent draws. Under "assay" the same data behaves.
    A tell-tale is that all three intervals of a run then agree closely, which
    is what correlated resampling looks like from outside.

    THIS IS NOT SIMPLY AN ERROR IN THE SOURCE PROTOCOL. When the heading
    genuinely differs between windows - which is the phenomenon being studied -
    the windows do carry independent information and collapsing them throws it
    away. The trade is real. What is not defensible is treating them as
    independent WITHOUT saying so, so both are computed and reported and the
    default stays with the published convention for comparability.
    """
    if unit not in {"assay_window", "assay"}:
        raise HeadingError("unit must be 'assay_window' or 'assay'.")
    per_interval = {}
    for a in assays:
        per_assay_interval = {}
        for idx, w in a["windows"].items():
            if w["mean_heading_deg"] is None:
                continue
            key = int(idx * float(window_s) // float(interval_s))
            per_assay_interval.setdefault(key, []).append(w["mean_heading_deg"])
        for key, angles in per_assay_interval.items():
            if unit == "assay_window":
                per_interval.setdefault(key, []).extend(angles)
            else:
                collapsed = mean_resultant(angles)["mean_angle_deg"]
                if collapsed is not None:
                    per_interval.setdefault(key, []).append(collapsed)

    out = {}
    for key, angles in sorted(per_interval.items()):
        stat = mean_resultant(angles)
        ray = rayleigh_test(angles)
        out[key] = {
            "interval_index": key,
            "t_start_s": key * float(interval_s),
            "t_end_s": (key + 1) * float(interval_s),
            "mean_heading_deg": stat["mean_angle_deg"],
            "resultant_length": stat["resultant_length"],
            "n_units": stat["n"],
            "unit": ("assay-window mean heading" if unit == "assay_window"
                     else "assay mean heading"),
            "rayleigh_p": ray["p"],
            "oriented": bool(ray["p"] is not None and ray["p"] < 0.05),
        }
    return out


def analyse(assays, field, *, window_s=WINDOW_S, interval_s=INTERVAL_S,
            n_segments=SEGMENTS_PER_TRACK, participation_radius_mm=None,
            center_xy_mm=None):
    """The whole protocol, and the comparison that shows why it is needed."""
    per_assay = [
        assay_window_headings(t, field, window_s=window_s,
                              n_segments=n_segments,
                              participation_radius_mm=participation_radius_mm,
                              center_xy_mm=center_xy_mm)
        for t in assays]
    intervals = population_intervals(per_assay, interval_s=interval_s,
                                     window_s=window_s, unit="assay_window")
    conservative = population_intervals(per_assay, interval_s=interval_s,
                                        window_s=window_s, unit="assay")

    # The pooled-over-everything number, computed ONLY so it can be shown
    # against the binned one. It is what a naive analysis reports.
    all_angles = [w["mean_heading_deg"] for a in per_assay
                  for w in a["windows"].values()
                  if w["mean_heading_deg"] is not None]
    pooled = mean_resultant(all_angles)
    pooled_ray = rayleigh_test(all_angles)

    out = {
        "per_assay": per_assay,
        "intervals": intervals,
        "intervals_assay_as_unit": conservative,
        "n_assays": len(assays),
        "pooled_over_whole_assay": {
            "mean_heading_deg": pooled["mean_angle_deg"],
            "resultant_length": pooled["resultant_length"],
            "rayleigh_p": pooled_ray["p"],
        },
        "warnings": [],
    }

    oriented = [i for i in intervals.values() if i["oriented"]]
    if len(oriented) >= 2:
        spread = _max_angular_spread([i["mean_heading_deg"] for i in oriented])
        out["max_interval_separation_deg"] = spread
        if spread > 90:
            out["warnings"].append(
                f"Preferred heading differs by {spread:.0f} degrees between "
                f"intervals that are each individually oriented. The pooled "
                f"figure of r={pooled['resultant_length']:.2f} averages those "
                f"against each other and is not a weaker version of the "
                f"result - it is a different and wrong one. Report by "
                f"interval.")
    if pooled["resultant_length"] is not None and oriented:
        best = max(i["resultant_length"] for i in oriented)
        if best > pooled["resultant_length"] * 1.5:
            out["warnings"].append(
                f"The strongest interval has r={best:.2f} against a pooled "
                f"r={pooled['resultant_length']:.2f}. Pooling is hiding most "
                f"of the effect.")
    # Counted in ASSAYS, not in units. An interval holds one heading per
    # 10-minute window per assay, so n_units is about three times the number
    # of assays and warning on it would look reassuring at two plates.
    if len(assays) < 5:
        out["warnings"].append(
            f"Only {len(assays)} assay(s). The unit here is the assay-window, "
            f"not the animal, so adding worms to a plate will not raise n - "
            f"more plates will. Each assay contributes about "
            f"{int(interval_s // window_s)} headings per interval, which is "
            f"why n_units looks larger than the number of plates.")
    # The disagreement between the two units is the thing worth surfacing:
    # an interval significant only under the published convention is resting
    # on windows treated as independent when they are the same plates again.
    disagree = [k for k in intervals
                if intervals[k]["oriented"]
                and not conservative.get(k, {}).get("oriented", False)]
    if disagree:
        out["warnings"].append(
            f"Interval(s) {disagree} are significant with the assay-WINDOW as "
            f"the unit but not with the ASSAY as the unit. The three windows "
            f"of an interval are the same plates measured three times, so the "
            f"published convention counts n as roughly 3x the number of "
            f"plates. Simulated animals with no preference at all reached "
            f"significance about half the time this way. Treat these "
            f"intervals as unconfirmed until there are more plates.")
        out["unit_disagreement"] = disagree
    out["independence_caveat"] = (
        "Following Landler et al. 2018 the animal is not the unit, which "
        "removes the worst pseudoreplication. The windows WITHIN one assay "
        "are still not fully independent of each other - they share a plate, "
        "a batch and a day - so n_units overstates the independent n by up to "
        f"the {int(interval_s // window_s)} windows per interval. The source "
        "protocol accepts this; it is recorded here rather than hidden.")
    return out


def _max_angular_spread(angles):
    a = np.radians(np.asarray(angles, dtype=float))
    best = 0.0
    for i in range(len(a)):
        for j in range(i + 1, len(a)):
            d = abs(np.degrees(np.angle(np.exp(1j * (a[i] - a[j])))))
            best = max(best, d)
    return float(best)
