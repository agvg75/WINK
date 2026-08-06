"""Strains drift. Track it, and tell genetic drift from the lab changing.

Andres: worms mutate - roughly one new deleterious mutation every three
generations, per Moerman - so every strain in the lab, N2 included, drifts.
Stocks are thawed every few months to refresh them. And the comparison can do
more work than catching a bad batch: it can track a strain over time, where
drifts in length, frequency or velocity "are a tale of global changes". He
learned that the hard way.

THE MOST USEFUL SIGNAL IS THE ONE SHARED ACROSS STRAINS, and it is the reason
this is a separate module rather than a trend line in the reference library.
If N2 slows, that could be N2 accumulating mutations. If N2 AND dys-1 AND
pezo-1 all slow by a similar amount over the same months, the worms did not
mutate in concert - the incubator, the food batch, the scoring, a setting or
an operator changed. Genetic drift is per-strain and independent; a lab change
is common-mode. Separating them is the whole point, and it is exactly what a
supervisor notices over years and a student cannot.

THAWS ARE THE NATURAL ANCHOR. Drift accumulates in a thawed line and is meant
to reset when the stock is refreshed. So drift is measured SINCE THE LAST THAW
rather than since the beginning of time, and a thaw that does not reset it is
itself a finding: either the frozen stock carries the change, or the cause was
never genetic.

WHAT THIS CANNOT DO, stated because the temptation is real. It cannot prove
causation. A trend and a season look identical over one year. Multiple strains
and multiple metrics mean many chances to find a slope, so the multiplicity is
reported. And a drift detected here is a reason to sequence, re-thaw or check
the incubator - never on its own a conclusion about genetics.
"""
from __future__ import annotations

import datetime as _dt
import math

import numpy as np

MIN_POINTS = 6          # below this a "trend" is a line through noise
MIN_SPAN_DAYS = 30      # a trend inside one week is a batch, not drift
COMMON_TOLERANCE = 0.4  # log-space agreement for calling drift common-mode


class DriftError(Exception):
    """Refusals that name the consequence."""


def _days(d):
    if isinstance(d, _dt.datetime):
        return d.date().toordinal()
    if isinstance(d, _dt.date):
        return d.toordinal()
    return _dt.date.fromisoformat(str(d)[:10]).toordinal()


def _series(records, strain, metric, since=None):
    rows = [r for r in records
            if str(r.get("strain", "")).lower() == str(strain).lower()
            and r.get("metric") == metric
            and r.get("value") is not None]
    out = []
    for r in rows:
        try:
            day = _days(r["date"])
        except Exception:
            continue
        if since is not None and day < since:
            continue
        out.append((day, float(r["value"]), r))
    return sorted(out)


def last_thaw(records, strain, before=None):
    """When this strain was most recently refreshed from frozen stock."""
    thaws = []
    for r in records:
        if str(r.get("strain", "")).lower() != str(strain).lower():
            continue
        t = r.get("thaw_date")
        if not t:
            continue
        try:
            day = _days(t)
        except Exception:
            continue
        if before is None or day <= before:
            thaws.append(day)
    return max(thaws) if thaws else None


def drift(records, strain, metric, *, since_thaw=True, min_points=MIN_POINTS):
    """Is this strain's measurement trending, and by how much?

    Reported as fractional change per 100 days, which is a unit a person can
    hold: "3% slower per 100 days" is actionable where a regression slope in
    mm/s/day is not.
    """
    anchor = last_thaw(records, strain) if since_thaw else None
    pts = _series(records, strain, metric, since=anchor)
    if len(pts) < min_points:
        return {
            "strain": strain, "metric": metric, "measured": False,
            "n": len(pts),
            "why": (f"{len(pts)} point(s) since "
                    f"{'the last thaw' if anchor else 'the start'}; at least "
                    f"{min_points} are needed. A line through fewer points is "
                    f"a line through noise, and it will always have a slope."),
        }
    days = np.array([p[0] for p in pts], dtype=float)
    vals = np.array([p[1] for p in pts], dtype=float)
    span = days.max() - days.min()
    if span < MIN_SPAN_DAYS:
        return {
            "strain": strain, "metric": metric, "measured": False,
            "n": len(pts), "span_days": float(span),
            "why": (f"All {len(pts)} points fall within {span:.0f} days. That "
                    f"is a batch, not drift - a single bad week would produce "
                    f"exactly this shape."),
        }
    med = float(np.median(vals))
    if med == 0:
        raise DriftError(
            f"{strain}/{metric} has a median of zero, so fractional change is "
            f"undefined. Report the absolute slope instead, or check whether "
            f"the column is really a measurement.")
    slope, intercept = np.polyfit(days, vals, 1)
    resid = vals - (slope * days + intercept)
    scatter = float(np.median(np.abs(resid))) * 1.4826
    # Significance without pretending to a p-value: how big is the total
    # change against the scatter of the points it is drawn through?
    total = float(slope * span)
    ratio = abs(total) / scatter if scatter > 0 else float("inf")
    return {
        "strain": strain, "metric": metric, "measured": True,
        "n": len(pts), "span_days": float(span),
        "since_thaw": bool(anchor), "thaw_day": anchor,
        "median": med,
        "fraction_per_100d": float(slope * 100.0 / med),
        "total_fraction": float(total / med),
        "scatter": scatter,
        "change_over_scatter": round(ratio, 2),
        "drifting": bool(ratio >= 2.0),
        "direction": "increasing" if slope > 0 else "decreasing",
        "caveat": ("A trend and a season look identical over a single year. "
                   "This is a reason to re-thaw, sequence or check the "
                   "incubator - never on its own a conclusion about "
                   "genetics."),
    }


def common_mode(records, metric, strains, *, since_thaw=False,
                tolerance=COMMON_TOLERANCE):
    """Are all these strains drifting together? Then it is not genetics.

    THE POINT OF THE MODULE. Genetic drift is per-strain and independent -
    separate lines accumulating separate mutations have no reason to move in
    step. A shared direction and a similar magnitude across unrelated strains
    is a lab change: incubator, food batch, scoring, a setting, an operator.

    Deliberately measured WITHOUT the thaw anchor by default, because a lab
    change does not care when a stock was refreshed and anchoring would chop
    the signal into pieces.
    """
    per = {}
    for s in strains:
        d = drift(records, s, metric, since_thaw=since_thaw)
        if d.get("measured"):
            per[s] = d
    if len(per) < 2:
        return {"checked": False, "n_strains": len(per),
                "why": ("At least two strains with enough data are needed. "
                        "One strain drifting is a fact about that strain; "
                        "only several drifting together distinguishes a lab "
                        "change from genetics.")}
    fracs = {s: d["fraction_per_100d"] for s, d in per.items()}
    directions = {s: (1 if v > 0 else -1) for s, v in fracs.items()}
    same_way = len(set(directions.values())) == 1
    mags = [abs(v) for v in fracs.values() if v != 0]
    if not mags or not same_way:
        return {
            "checked": True, "common": False, "per_strain": fracs,
            "why": ("The strains are not drifting the same way. That is what "
                    "independent genetic drift looks like, and it is the "
                    "reassuring answer - a lab-wide change would move them "
                    "together."),
        }
    logs = [math.log10(m) for m in mags]
    agree = (max(logs) - min(logs)) <= tolerance
    mean_frac = float(np.mean(list(fracs.values())))
    out = {"checked": True, "common": bool(agree), "per_strain": fracs,
           "mean_fraction_per_100d": mean_frac,
           "n_strains": len(per), "drifting_strains":
           [s for s, d in per.items() if d["drifting"]]}
    if agree:
        out["question"] = (
            f"All {len(per)} strains are drifting the same way in {metric}, "
            f"by a similar amount - about {abs(mean_frac) * 100:.1f}% per 100 "
            f"days, "
            f"{'upward' if mean_frac > 0 else 'downward'}. Separate strains "
            f"accumulate separate mutations and have no reason to move in "
            f"step, so this is very unlikely to be genetic. Look at what is "
            f"shared: the incubator, the food batch, the plates, the scoring, "
            f"a changed setting, or who is running the assay. Re-thawing will "
            f"not fix a lab-wide change, and will hide it for a while.")
    else:
        out["why"] = (
            f"All {len(per)} strains move the same way but by very different "
            f"amounts, so a single shared cause is not obvious. Worth "
            f"watching rather than acting on.")
    return out


def thaw_effect(records, strain, metric, *, window_days=120):
    """Did refreshing the stock actually reset the measurement?

    A thaw that does NOT reset a drift is a finding in itself: either the
    frozen stock already carries the change - it was frozen after the drift
    began - or the cause was never genetic and a new tube will not help.
    """
    day = last_thaw(records, strain)
    if day is None:
        return {"checked": False,
                "why": f"No thaw date recorded for {strain}. Without it, "
                       f"drift cannot be anchored to anything and a reset "
                       f"cannot be distinguished from a trend."}
    before = [v for d, v, _ in _series(records, strain, metric)
              if day - window_days <= d < day]
    after = [v for d, v, _ in _series(records, strain, metric)
             if day <= d <= day + window_days]
    if len(before) < 3 or len(after) < 3:
        return {"checked": False, "n_before": len(before),
                "n_after": len(after),
                "why": ("At least three measurements each side of the thaw "
                        "are needed. Fewer compares two anecdotes.")}
    b, a = float(np.median(before)), float(np.median(after))
    scatter = float(np.median(np.abs(np.array(before + after) -
                                     np.median(before + after)))) * 1.4826
    shifted = abs(a - b) > 2 * scatter if scatter > 0 else a != b
    return {
        "checked": True, "strain": strain, "metric": metric,
        "before": b, "after": a, "thaw_day": day,
        "changed_at_thaw": bool(shifted),
        "fold": round(a / b, 3) if b else None,
        "note": (
            f"The thaw shifted {metric} from {b:g} to {a:g}. That is what a "
            f"refresh is supposed to do when a line has drifted."
            if shifted else
            f"{metric} did not change at the thaw ({b:g} then {a:g}). If the "
            f"line had been drifting, the frozen stock may already carry the "
            f"change - it was frozen after the drift began - or the cause was "
            f"never genetic, in which case a new tube will not help."),
    }


def report(records, metrics, strains, *, since_thaw=True):
    """Everything worth saying, with the multiplicity stated."""
    tests = 0
    findings, commons = [], []
    for metric in metrics:
        for strain in strains:
            d = drift(records, strain, metric, since_thaw=since_thaw)
            tests += 1
            if d.get("measured") and d["drifting"]:
                findings.append(d)
        c = common_mode(records, metric, strains)
        if c.get("checked") and c.get("common"):
            commons.append({"metric": metric, **c})
    return {
        "n_tests": tests,
        "drifting": findings,
        "common_mode": commons,
        "multiplicity": (
            f"{tests} strain-metric combinations were examined. At any "
            f"ordinary threshold some will trend by chance, so a single "
            f"drifting combination is weak evidence. Several strains moving "
            f"together on one metric is much stronger, which is why the "
            f"common-mode result is listed separately."),
        "priority": (
            "Look at the common-mode findings first. A lab-wide change "
            "explains many apparent per-strain drifts at once, and re-thawing "
            "in response to it will hide the cause for a few months rather "
            "than fix it."
            if commons else
            "No common-mode drift found, so any per-strain trend here is at "
            "least consistent with that strain's own history."),
    }


def thaw_records_from_hub(payload):
    """Turn the Reagent Hub's /api/thaws/ export into drift-anchor records.

    Andres: Mackenzie records a thaw in the hub, and it is passed to WINK.
    The hub is where the freezer lives, so it is where the thaw log belongs;
    this is the only place the two systems meet.

    ONLY SUCCESSFUL THAWS BECOME ANCHORS. The export deliberately includes
    failed and in-progress attempts, because a gap in the record and a thaw
    that failed mean different things when a drift does not reset - but an
    attempt that did not recover never restarted the line, and treating it as
    a reset would make a real drift appear to vanish at exactly the moment
    somebody tried to fix it.
    """
    rows = payload.get("thaws", payload) if isinstance(payload, dict) else payload
    out, skipped = [], []
    for t in rows or []:
        strain = t.get("strain")
        when = t.get("thaw_date")
        if not strain or not when:
            skipped.append({**t, "reason": "no strain or no date"})
            continue
        if not t.get("is_refresh"):
            skipped.append({**t, "reason": f"outcome {t.get('outcome')!r} "
                                           f"did not restart the line"})
            continue
        out.append({"strain": strain, "thaw_date": when,
                    "thawed_by": t.get("thawed_by"),
                    "source_copy": t.get("source_copy")})
    return {
        "anchors": out, "n_anchors": len(out),
        "skipped": skipped, "n_skipped": len(skipped),
        "why": (f"{len(out)} successful thaw(s) will anchor drift analysis; "
                f"{len(skipped)} attempt(s) were recorded but did not restart "
                f"a line, so they are not anchors. A failed thaw is still "
                f"worth knowing about - it explains a drift that did not "
                f"reset when somebody expected it to."),
    }


def attach_thaws(records, anchors):
    """Stamp measurement records with the thaw that was current when taken.

    A measurement inherits the MOST RECENT thaw at or before its own date, not
    the latest one overall - otherwise every historical measurement would look
    as though it came from the current stock, and drift within an older line
    would be attributed to the newer one.
    """
    by_strain = {}
    for a in anchors:
        by_strain.setdefault(str(a["strain"]).lower(), []).append(
            _days(a["thaw_date"]))
    for v in by_strain.values():
        v.sort()

    out = []
    for r in records:
        rec = dict(r)
        days = by_strain.get(str(r.get("strain", "")).lower(), [])
        try:
            when = _days(r["date"])
        except Exception:
            out.append(rec)
            continue
        prior = [d for d in days if d <= when]
        if prior:
            rec["thaw_date"] = _dt.date.fromordinal(prior[-1]).isoformat()
            rec["days_since_thaw"] = when - prior[-1]
        out.append(rec)
    return out
