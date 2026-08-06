"""WWN2D: what would N2 do? A reference library, and what to do with it.

Andres wants a library of N2's known performance for every metric measured -
from the lab's own results where possible and the literature otherwise - so a
student gets told "woah, that ain't normal".

THE OBVIOUS VERSION WOULD BE MADDENING, and getting this right is the whole
design. Deviating from N2 is the POINT of most experiments here. A dystrophin
model SHOULD be slower; a pezo-1 mutant SHOULD move differently. A tool that
announces "not normal" on every mutant result is announcing that the
experiment worked, and it will be muted within a week - after which it catches
nothing.

SO THE REFERENCE IS AIMED SOMEWHERE ELSE. Three questions, and only the first
two are reliable:

  1. IS THE N2 CONTROL NORMAL? If a student's own wild-type control does not
     look like N2, every genotype on that plate is suspect and the problem is
     the day, not the animal. This is the check that earns its keep, and it is
     the one a supervisor actually performs walking past.

  2. IS THIS DEVIATION PHYSICALLY POSSIBLE? A mutant may be slower. It may not
     be slower than zero, or faster than any nematode. That is plausibility,
     handled in plausibility.py, and it applies to every strain.

  3. IS THIS MUTANT UNUSUAL FOR ITS OWN HISTORY? Once the lab has measured a
     strain repeatedly, its own past is a better reference than N2 ever was.

A REFERENCE IS NOT A NUMBER, IT IS A DISTRIBUTION UNDER CONDITIONS. N2 crawls
at a different speed on food and off it, at 20 and 25 degrees, on day 1 and
day 5. A single "N2 speed" would fire constantly and mean nothing. Every entry
therefore carries its conditions, and a lookup that cannot match conditions
says so rather than returning the closest thing.

EVERY ENTRY CARRIES ITS n AND ITS SOURCE. A reference built from three
recordings is not evidence that a fourth is abnormal, and it says so. Entries
from this lab's own results are marked apart from literature values, because
the lab's own rig, scoring and conditions are what a student's run should be
compared against.

BUILDING THE LIBRARY FROM OWN RESULTS IS BETTER AND MORE DANGEROUS. Better,
because it captures this rig. More dangerous, because an uncurated library
bakes today's errors into tomorrow's reference - a run measured at the wrong
scale would become "normal". So `contribute` refuses anything not marked as
reviewed.
"""
from __future__ import annotations

import datetime as _dt
import json
import math
from pathlib import Path

import numpy as np

DEFAULT_LIBRARY = Path(
    r"L:\10_AGVG LAB\Lab Tools\n2_reference_library.json")

# Conditions that change what normal IS. A reference is only valid for a run
# that matches on these; anything else is a different measurement.
CONDITION_KEYS = ("strain", "gait", "food", "temperature_c", "age",
                  "assay")

MIN_N_TO_JUDGE = 5


class ReferenceError(Exception):
    """Refusals that name the consequence."""


def _key(conditions):
    return "|".join(f"{k}={str(conditions.get(k, '')).strip().lower()}"
                    for k in CONDITION_KEYS)


def load(path=None):
    p = Path(path or DEFAULT_LIBRARY)
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"entries": [], "created_utc": _dt.datetime.now(
            _dt.timezone.utc).isoformat()}
    except json.JSONDecodeError as exc:
        raise ReferenceError(
            f"{p} is not valid JSON ({exc}). This library is what every "
            f"'that is not normal' judgement is made against - a corrupt one "
            f"would either silence the check or make it fire on everything, "
            f"and neither failure announces itself.")


def save(library, path=None):
    p = Path(path or DEFAULT_LIBRARY)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(library, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return str(p)


def contribute(library, *, metric, values, conditions, source="own_results",
               reviewed=False, note="", citation=""):
    """Add measurements to the library. Reviewed data only.

    An uncurated library bakes today's mistakes into tomorrow's definition of
    normal: a run measured at the wrong scale, added automatically, would make
    that scale error the reference. So this refuses anything unreviewed, and
    the refusal is the feature.
    """
    if source == "own_results" and not reviewed:
        raise ReferenceError(
            "Own results must be marked reviewed before entering the "
            "library. An automatic contribution would make today's errors "
            "into tomorrow's definition of normal - a run measured at the "
            "wrong scale would become the reference it is checked against.")
    vals = [float(v) for v in values
            if v is not None and math.isfinite(float(v))]
    if len(vals) < 2:
        raise ReferenceError(
            f"{metric}: at least two values are needed to describe a spread. "
            f"A single measurement is an anecdote, and a library entry with "
            f"no spread would call every second measurement abnormal.")
    missing = [k for k in ("strain", "assay") if not conditions.get(k)]
    if missing:
        raise ReferenceError(
            f"Conditions must include {missing}. A reference without its "
            f"strain and assay is not a reference - N2 on food and N2 off "
            f"food are different numbers, and so are crawling and swimming.")
    arr = np.asarray(vals, dtype=float)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median))) * 1.4826
    library.setdefault("entries", []).append({
        "metric": metric,
        "conditions": {k: conditions.get(k) for k in CONDITION_KEYS},
        "key": _key(conditions),
        "n": len(vals),
        "median": median,
        "mad": mad,
        "p10": float(np.percentile(arr, 10)),
        "p90": float(np.percentile(arr, 90)),
        "min": float(arr.min()), "max": float(arr.max()),
        "source": source, "citation": citation, "note": note,
        "added_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
    })
    return library


def lookup(library, metric, conditions):
    """The reference for this metric under THESE conditions, or nothing.

    Deliberately does not fall back to a looser match. Returning N2-on-food
    when asked about N2-off-food would be worse than returning nothing,
    because the answer would look authoritative and be about a different
    experiment.
    """
    want = _key(conditions)
    exact = [e for e in library.get("entries", [])
             if e["metric"] == metric and e["key"] == want]
    if not exact:
        near = [e for e in library.get("entries", [])
                if e["metric"] == metric]
        return {
            "found": False, "metric": metric,
            "n_other_conditions": len(near),
            "why": (f"No reference for {metric} under these exact conditions. "
                    f"{len(near)} entr(y/ies) exist for {metric} under other "
                    f"conditions and are deliberately NOT used - N2 on food "
                    f"and N2 off food are different numbers, and answering "
                    f"with the wrong one would look authoritative while "
                    f"describing a different experiment."),
            "other_conditions": [e["conditions"] for e in near][:5],
        }
    # Pool if several entries match, weighting by n.
    total_n = sum(e["n"] for e in exact)
    median = sum(e["median"] * e["n"] for e in exact) / total_n
    mad = sum(e["mad"] * e["n"] for e in exact) / total_n
    return {
        "found": True, "metric": metric, "n": total_n,
        "median": median, "mad": mad,
        "sources": sorted({e["source"] for e in exact}),
        "citations": sorted({e["citation"] for e in exact if e["citation"]}),
        "enough_to_judge": total_n >= MIN_N_TO_JUDGE,
        "caveat": (None if total_n >= MIN_N_TO_JUDGE else
                   f"Only {total_n} observation(s) behind this reference. "
                   f"That is not enough to call a new measurement abnormal - "
                   f"it is reported so the number can be seen, not so it can "
                   f"be judged against."),
    }


def check_control(library, *, metric, control_values, conditions,
                  z_warn=3.0):
    """Does this run's own wild-type control look like N2?

    THE CHECK THAT EARNS ITS KEEP. If the control is off, every genotype
    measured beside it is suspect and the problem belongs to the day rather
    than to any animal. It is also the check a supervisor actually performs
    walking past a student's screen.
    """
    ref = lookup(library, metric, {**conditions, "strain": "N2"})
    if not ref["found"]:
        return {"checked": False, "why": ref["why"]}
    if not ref["enough_to_judge"]:
        return {"checked": False, "why": ref["caveat"]}
    vals = [float(v) for v in control_values if v is not None]
    if not vals:
        return {"checked": False,
                "why": "No control values were given. A run without a "
                       "wild-type control cannot be checked this way, which "
                       "is itself worth knowing."}
    obs = float(np.median(vals))
    z = abs(obs - ref["median"]) / ref["mad"] if ref["mad"] > 0 else 0.0
    off = z >= z_warn
    return {
        "checked": True, "metric": metric, "observed": obs,
        "expected": ref["median"], "z": round(z, 2),
        "fold": round(obs / ref["median"], 3) if ref["median"] else None,
        "control_looks_normal": not off,
        "n_reference": ref["n"],
        "question": (None if not off else
                     f"The N2 control measured {obs:g} for {metric}, against "
                     f"{ref['median']:g} expected from {ref['n']} previous "
                     f"observations - {z:.1f} robust SD away. If the control "
                     f"is off, every genotype run beside it today is suspect, "
                     f"and the cause is more likely the day, the plate or a "
                     f"setting than any animal. Worth resolving before "
                     f"interpreting anything else from this run."),
    }


def compare_strain(library, *, metric, values, conditions,
                   expected_direction=None, z_note=3.0):
    """How does this strain compare with N2 - as information, not alarm.

    A mutant differing from N2 is the experiment succeeding. This reports the
    difference and its direction, and raises a question ONLY when the
    difference contradicts what was expected, or when the strain IS N2 and
    should therefore have matched.
    """
    strain = str(conditions.get("strain", "")).strip()
    ref = lookup(library, metric, {**conditions, "strain": "N2"})
    if not ref["found"] or not ref["enough_to_judge"]:
        return {"compared": False,
                "why": ref.get("why") or ref.get("caveat")}
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"compared": False, "why": "No values given."}
    obs = float(np.median(vals))
    z = (obs - ref["median"]) / ref["mad"] if ref["mad"] > 0 else 0.0
    direction = "higher" if z > 0 else "lower"
    out = {
        "compared": True, "strain": strain, "metric": metric,
        "observed": obs, "n2_expected": ref["median"],
        "z": round(z, 2), "direction": direction,
        "fold": round(obs / ref["median"], 3) if ref["median"] else None,
        "differs": abs(z) >= z_note,
        "is_n2": strain.upper() == "N2",
    }
    if out["is_n2"] and out["differs"]:
        out["question"] = (
            f"This is N2, but {metric} is {abs(z):.1f} robust SD {direction} "
            f"than N2 normally measures. When the wild type does not behave "
            f"like the wild type, suspect the run before the animal.")
    elif expected_direction and out["differs"] and \
            direction != expected_direction:
        out["question"] = (
            f"{strain} differs from N2 in {metric}, but {direction} rather "
            f"than the {expected_direction} that was expected. Either the "
            f"expectation is wrong - which is a result - or something in the "
            f"run is inverted, such as a swapped label or a sign convention.")
    elif out["differs"]:
        out["note"] = (
            f"{strain} measures {abs(z):.1f} robust SD {direction} than N2 "
            f"for {metric}. That is a difference, not a problem - it is "
            f"usually what the experiment was for.")
    else:
        out["note"] = (
            f"{strain} is within normal N2 range for {metric}. Worth knowing "
            f"if a difference was expected.")
    return out


def coverage(library, metrics=()):
    """Which metrics have a usable N2 reference, and which do not.

    The honest state of the library. A gap is not a failure - it is the next
    thing worth measuring - and knowing where the gaps are is what makes the
    library grow deliberately rather than by accident.
    """
    entries = library.get("entries", [])
    have = {}
    for e in entries:
        if str(e["conditions"].get("strain", "")).upper() != "N2":
            continue
        have.setdefault(e["metric"], {"n": 0, "conditions": [],
                                      "sources": set()})
        have[e["metric"]]["n"] += e["n"]
        have[e["metric"]]["conditions"].append(e["conditions"])
        have[e["metric"]]["sources"].add(e["source"])
    usable = {m: v for m, v in have.items() if v["n"] >= MIN_N_TO_JUDGE}
    asked = list(metrics)
    missing = [m for m in asked if m not in usable]
    return {
        "n_metrics_with_any_data": len(have),
        "n_metrics_usable": len(usable),
        "usable": {m: {"n": v["n"], "sources": sorted(v["sources"])}
                   for m, v in usable.items()},
        "thin": {m: v["n"] for m, v in have.items() if m not in usable},
        "missing": missing,
        "why": (f"{len(usable)} metric(s) have at least {MIN_N_TO_JUDGE} N2 "
                f"observations and can support a judgement. "
                f"{len(have) - len(usable)} have some data but too little. "
                + (f"{len(missing)} asked-for metric(s) have none at all."
                   if missing else "")),
    }
