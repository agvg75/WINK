"""Look at a student's results and ask about the numbers that cannot be right.

Andres: the assistant should look at what the student is doing, at their data
and results, and - knowing what the module measures and what is biologically
feasible - say "what's this here? this doesn't make sense, you should look at
it."

THE DETECTION IS ARITHMETIC, NOT A LANGUAGE MODEL, and that is deliberate. An
assistant that invents a problem teaches students to dismiss it, and one that
misses a real problem while sounding confident is worse than silence. So every
finding here comes from a comparison a person could check by hand. The
language model's job is to explain a finding and answer questions about it,
never to decide whether there is one.

THREE KINDS OF SUSPICIOUS, in increasing order of how much they prove:

  OUTSIDE BIOLOGY. A sarcomere is not 38 um long. This catches unit errors,
  calibration errors and typos - the class that produced the 20x scale error
  in this project's own history.

  INTERNALLY INCONSISTENT. Area against length times width; speed against
  distance over time. Stronger evidence than a range, because ranges shift
  with strain, age and condition while arithmetic does not. A row that
  contradicts itself is wrong whatever the biology.

  UNPRECEDENTED HERE. A value far from the rest of this student's own data.
  Weakest, because a real effect looks like this too - so it is phrased as a
  question and never as an error.

EVERYTHING IS PHRASED AS A QUESTION. Andres asked for "what's this here?" and
that is right: the student may be correct and the range wrong. A tool that
says "this is an error" when it means "this is unusual" spends its credibility
and then gets ignored.

RANGES CARRY THEIR SOURCE, and where a number is an editable lab convention
rather than a literature value it says so. A plausibility limit with no
provenance is one person's guess wearing the clothes of a fact.
"""
from __future__ import annotations

import math

import numpy as np


class PlausibilityError(Exception):
    """Refusals that name the consequence."""


# Ranges are DELIBERATELY GENEROUS. A false alarm costs more than a missed
# outlier here, because a check that cries wolf gets switched off and then
# catches nothing at all. These bound the physically possible, not the typical.
RANGES = {
    "body_length_um": {
        "lo": 200, "hi": 1800,
        "means": "whole-animal length",
        "source": "L1 ~250 um to a large gravid adult ~1.3-1.5 mm",
        "confidence": "high",
    },
    "body_width_um": {
        "lo": 10, "hi": 200,
        "means": "whole-animal width",
        "source": "L1 ~15 um to a gravid adult ~80-100 um",
        "confidence": "high",
    },
    "sarcomere_um": {
        "lo": 0.8, "hi": 6.0,
        "means": "sarcomere spacing",
        "source": ("matches the CHECK_CALIBRATION band already used in "
                   "myocyte_morphometry"),
        "confidence": "high",
    },
    "crawl_speed_mm_s": {
        "lo": 0.0, "hi": 0.5,
        "means": "crawling speed on agar",
        "source": "typically 0.1-0.2 mm/s; 0.5 is a generous ceiling",
        "confidence": "medium",
    },
    "swim_bend_hz": {
        "lo": 0.2, "hi": 4.0,
        "means": "swimming body-bend frequency",
        "source": "swimming is roughly 1-2 Hz; 4 is a ceiling",
        "confidence": "medium",
    },
    "crawl_undulation_hz": {
        "lo": 0.05, "hi": 1.5,
        "means": "crawling undulation frequency",
        "source": "roughly 0.3-0.5 Hz on agar",
        "confidence": "medium",
    },
    "pumping_per_min": {
        "lo": 0, "hi": 350,
        "means": "pharyngeal pumping rate",
        "source": "well-fed adults peak around 250-300 per minute",
        "confidence": "medium",
    },
    "defecation_cycle_s": {
        "lo": 20, "hi": 200,
        "means": "defecation cycle period",
        "source": "about 45-50 s in well-fed adults; wide bounds for mutants",
        "confidence": "medium",
    },
    "myocyte_area_um2": {
        "lo": 20, "hi": 5000,
        "means": "single body-wall myocyte area",
        "source": "LAB CONVENTION - not a literature value, edit freely",
        "confidence": "low",
    },
}

# Relations a row must satisfy regardless of what the biology is doing.
# (name, columns, check, message) - each returns True when CONSISTENT.
CONSISTENCY = [
    {
        "name": "area_vs_bounding_box",
        "needs": ("area_um2", "length_um", "width_um"),
        "why": ("A shape cannot cover more area than the box that contains "
                "it. If it does, the three numbers were not measured from the "
                "same object or not in the same units."),
        "test": lambda r: r["area_um2"] <= r["length_um"] * r["width_um"] * 1.05,
    },
    {
        "name": "area_not_impossibly_thin",
        "needs": ("area_um2", "length_um", "width_um"),
        "why": ("The area is under 5% of its bounding box, which is thinner "
                "than any real outline. Usually one of the three is in "
                "different units from the others."),
        "test": lambda r: r["area_um2"] >= r["length_um"] * r["width_um"] * 0.05,
    },
    {
        "name": "speed_vs_distance_and_time",
        "needs": ("speed_mm_s", "distance_mm", "duration_s"),
        "why": ("Mean speed disagrees with distance divided by time by more "
                "than 20%. One of the three has been computed differently "
                "from the others."),
        "test": lambda r: (r["duration_s"] <= 0 or
                           abs(r["speed_mm_s"] -
                               r["distance_mm"] / r["duration_s"]) <=
                           0.2 * max(abs(r["speed_mm_s"]), 1e-9)),
    },
    {
        "name": "length_exceeds_width",
        "needs": ("length_um", "width_um"),
        "why": ("Width exceeds length. Either the axes are swapped or a "
                "coiled animal was measured as if straight."),
        "test": lambda r: r["length_um"] >= r["width_um"],
    },
]


def _num(value):
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def check_value(quantity, value, ranges=None):
    """Is one number outside what biology allows?"""
    table = ranges or RANGES
    spec = table.get(quantity)
    if spec is None:
        return {"quantity": quantity, "known": False,
                "why": (f"No plausibility range is defined for {quantity!r}, "
                        f"so nothing is claimed about it. An undefined "
                        f"quantity is silent rather than assumed fine.")}
    v = _num(value)
    if v is None:
        return {"quantity": quantity, "known": True, "value": value,
                "plausible": False, "kind": "not_a_number",
                "question": (f"{quantity} reads {value!r}, which is not a "
                             f"number. Was this column measured, or is it a "
                             f"placeholder?")}
    ok = spec["lo"] <= v <= spec["hi"]
    out = {"quantity": quantity, "known": True, "value": v, "plausible": ok,
           "range": [spec["lo"], spec["hi"]], "means": spec["means"],
           "source": spec["source"], "confidence": spec["confidence"]}
    if not ok:
        factor = (v / spec["hi"]) if v > spec["hi"] else (spec["lo"] / v if v
                                                          else float("inf"))
        out["kind"] = "outside_biology"
        out["question"] = (
            f"{spec['means']} reads {v:g}, which is outside the "
            f"{spec['lo']}-{spec['hi']} range that is physically possible - "
            f"about {factor:.0f}x beyond it. Worth checking before anything "
            f"downstream uses it. A wrong scale or a unit mix-up produces "
            f"exactly this, and both are easy to fix and hard to notice.")
        if spec["confidence"] == "low":
            out["question"] += (
                " Note this particular range is a lab convention rather than "
                "a literature value, so the range may be what needs changing.")
    return out


def check_row(row, ranges=None):
    """One row: ranges on every known column, then internal consistency."""
    findings = []
    for key, value in row.items():
        res = check_value(key, value, ranges)
        if res.get("known") and not res.get("plausible", True):
            findings.append(res)

    numeric = {k: _num(v) for k, v in row.items()}
    numeric = {k: v for k, v in numeric.items() if v is not None}
    for rule in CONSISTENCY:
        if not all(n in numeric for n in rule["needs"]):
            continue
        try:
            consistent = bool(rule["test"](numeric))
        except (ZeroDivisionError, ValueError):
            continue
        if not consistent:
            findings.append({
                "kind": "inconsistent", "rule": rule["name"],
                "columns": list(rule["needs"]),
                "values": {n: numeric[n] for n in rule["needs"]},
                "question": (
                    f"These do not agree with each other: "
                    + ", ".join(f"{n}={numeric[n]:g}" for n in rule["needs"])
                    + ". " + rule["why"]),
            })
    return findings


def check_table(rows, ranges=None, *, unusual_z=5.0, min_rows=8):
    """A whole results table: per-row checks, then what is unusual for THIS data.

    The dataset-relative check is deliberately last and deliberately weakest.
    A real effect looks like an outlier, so it is offered as a question about
    a row rather than as a problem with it.
    """
    rows = list(rows)
    if not rows:
        raise PlausibilityError(
            "No rows to check. An empty result is indistinguishable from a "
            "clean one unless somebody says which it was.")

    # Column medians over the PLAUSIBLE values only. Including the bad rows
    # would drag the reference toward them, which is precisely the direction
    # that hides a systematic error affecting a whole recording.
    medians = {}
    cols = set()
    for r in rows:
        cols |= {k for k, v in r.items() if _num(v) is not None}
    for col in cols:
        vals = []
        for r in rows:
            v = _num(r.get(col))
            if v is None:
                continue
            spec = (ranges or RANGES).get(col)
            if spec and not (spec["lo"] <= v <= spec["hi"]):
                continue
            vals.append(v)
        if vals:
            medians[col] = float(np.median(vals))

    per_row, all_findings = {}, []
    for i, row in enumerate(rows):
        found = check_row(row, ranges)
        for f in found:
            if f.get("quantity") in medians:
                f["dataset_median"] = medians[f["quantity"]]
        if found:
            per_row[i] = found
            all_findings.extend(found)

    unusual = []
    if len(rows) >= min_rows:
        cols = set()
        for r in rows:
            cols |= {k for k, v in r.items() if _num(v) is not None}
        for col in sorted(cols):
            vals = np.array([_num(r.get(col)) for r in rows], dtype=object)
            keep = np.array([v is not None for v in vals])
            x = np.array([v for v in vals if v is not None], dtype=float)
            if x.size < min_rows or np.ptp(x) == 0:
                continue
            med = float(np.median(x))
            mad = float(np.median(np.abs(x - med))) * 1.4826
            if mad <= 0:
                continue
            idx = np.nonzero(keep)[0]
            for pos, value in zip(idx, x):
                z = abs(value - med) / mad
                if z >= unusual_z:
                    unusual.append({
                        "kind": "unusual_here", "row": int(pos), "column": col,
                        "value": float(value), "median": med, "z": round(z, 1),
                        "question": (
                            f"Row {pos + 1}: {col} is {value:g}, about "
                            f"{z:.0f} robust standard deviations from the "
                            f"median of {med:g} for this dataset. That may be "
                            f"a real effect - a genuine finding looks exactly "
                            f"like this - so it is worth a look rather than a "
                            f"correction."),
                    })

    return {
        "n_rows": len(rows),
        "n_rows_with_findings": len(per_row),
        "by_row": per_row,
        "outside_biology": [f for f in all_findings
                            if f.get("kind") == "outside_biology"],
        "inconsistent": [f for f in all_findings
                         if f.get("kind") == "inconsistent"],
        "unusual_here": unusual,
        "clean": not all_findings and not unusual,
        "note": ("Nothing looked wrong. That is not a guarantee the numbers "
                 "are right - only that they are inside the ranges checked "
                 "and agree with each other."
                 if not all_findings and not unusual else None),
    }


def common_cause(findings, *, tolerance=0.25):
    """Are these several problems, or one problem seen several times?

    A student who mis-set the scale gets a flag on sarcomere length, on body
    length, and on width - three messages for one mistake, and none of them
    says what the mistake was. Five separate complaints about one error is how
    a check becomes noise.

    If the out-of-range quantities are all wrong by a SIMILAR FACTOR, that is
    a single scale or unit error, and saying so once is worth more than
    listing the symptoms. The factors must agree within `tolerance` in log
    space - otherwise these really are separate problems and collapsing them
    would hide one.
    """
    ranged = [f for f in findings if f.get("kind") == "outside_biology"
              and isinstance(f.get("value"), (int, float))]
    if len(ranged) < 2:
        return None
    factors = []
    for f in ranged:
        # REFERENCE AGAINST THE STUDENT'S OWN DATA where possible, not against
        # the centre of the allowed range. Ranges differ enormously in width -
        # sarcomere spans 0.8-6.0 while body length spans 200-1800 - so
        # dividing by each range's centre gives three different factors for
        # one scale error and the pattern disappears. The median of the other
        # rows is the right comparison because it is what the SAME quantity
        # looks like when it was measured correctly.
        ref = f.get("dataset_median")
        if ref is None:
            lo, hi = f["range"]
            ref = math.sqrt(max(lo, 1e-9) * hi)
        if f["value"] <= 0 or ref <= 0:
            return None
        factors.append(f["value"] / ref)
    logs = [math.log10(x) for x in factors]
    spread = max(logs) - min(logs)
    if spread > tolerance:
        return None
    factor = 10 ** (sum(logs) / len(logs))
    direction = "too large" if factor > 1 else "too small"
    shown = factor if factor > 1 else 1 / factor
    return {
        "single_cause": True,
        "factor": round(factor, 4),
        "n_quantities": len(ranged),
        "quantities": [f["quantity"] for f in ranged],
        "question": (
            f"All {len(ranged)} of these are {direction} by roughly the same "
            f"amount - about {shown:.0f}x: "
            + ", ".join(f["quantity"] for f in ranged) +
            f". That pattern is one scale or unit error rather than "
            f"{len(ranged)} separate problems. Check the calibration for this "
            f"recording before changing anything else; if the scale is wrong "
            f"the measurements can be corrected arithmetically without "
            f"re-measuring anything."),
    }


def brief(result, limit=6):
    """What the assistant should actually say, worst evidence first."""
    lines = []
    for f in result["inconsistent"][:limit]:
        lines.append("These numbers contradict each other. " + f["question"])

    # One cause explained beats three symptoms listed. The individual
    # findings are still in the result for anyone who wants them; they are
    # simply not what the assistant leads with.
    cause = common_cause(result["outside_biology"])
    if cause:
        lines.append(cause["question"])
        result["common_cause"] = cause
    else:
        for f in result["outside_biology"][:limit]:
            lines.append(f["question"])

    # An outlier caused by the scale error already explained is not news.
    explained = set(cause["quantities"]) if cause else set()
    for f in result["unusual_here"][:limit]:
        if f.get("column") in explained:
            continue
        lines.append(f["question"])
    if not lines:
        return {"say_something": False, "lines": [],
                "why": result.get("note")}
    return {
        "say_something": True, "lines": lines,
        "ordering": ("Contradictions first, then values outside biology, then "
                     "what is merely unusual here. A row that disagrees with "
                     "itself is wrong whatever the biology; an outlier might "
                     "be the result."),
    }
