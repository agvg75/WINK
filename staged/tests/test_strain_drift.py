"""Strains drift - and drift shared across strains is not genetics.

Andres: worms accumulate roughly one deleterious mutation every three
generations, so every strain including N2 drifts; stocks are thawed to refresh
them. And drifts in length, frequency or velocity "are a tale of global
changes" - he learned that the hard way.

The decisive test is the separation: independent per-strain drift must read
differently from every strain moving together, because the second is the
incubator and the first is the worms.
"""
from pathlib import Path
import datetime as dt
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import strain_drift as sd   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("strain drift - regression\n")

START = dt.date(2025, 1, 1)


def rec(strain, metric, day, value, thaw=None):
    r = {"strain": strain, "metric": metric,
         "date": (START + dt.timedelta(days=day)).isoformat(),
         "value": value}
    if thaw:
        r["thaw_date"] = (START + dt.timedelta(days=thaw)).isoformat()
    return r


# --- one strain drifting -----------------------------------------------------
drifting = [rec("N2", "speed_mm_s", d, 0.120 - 0.00008 * d)
            for d in range(0, 400, 25)]
d1 = sd.drift(drifting, "N2", "speed_mm_s", since_thaw=False)
check("a real drift is detected", d1["measured"] and d1["drifting"])
check("...with a direction", d1["direction"] == "decreasing")
check("...expressed as fraction per 100 days, a unit a person can hold",
      abs(d1["fraction_per_100d"] + 0.0667) < 0.02,
      f"{d1['fraction_per_100d'] * 100:.1f}% per 100 d")
check("...and refuses to call it a conclusion about genetics",
      "never on its own a conclusion" in d1["caveat"])

steady = [rec("N2", "speed_mm_s", d, 0.110 + (0.001 if d % 50 else -0.001))
          for d in range(0, 400, 25)]
check("a steady strain is not called drifting",
      sd.drift(steady, "N2", "speed_mm_s", since_thaw=False)["drifting"]
      is False)

# --- too little to judge ------------------------------------------------------
few = [rec("N2", "speed_mm_s", d, 0.11) for d in (0, 40, 80)]
r_few = sd.drift(few, "N2", "speed_mm_s", since_thaw=False)
check("too few points is refused", r_few["measured"] is False)
check("...naming that a short line always has a slope",
      "line through noise" in r_few["why"])

burst = [rec("N2", "speed_mm_s", d, 0.11 - 0.001 * d) for d in range(0, 7)]
r_burst = sd.drift(burst, "N2", "speed_mm_s", since_thaw=False,
                   min_points=6)
check("points inside one week are a batch, not drift",
      r_burst["measured"] is False and "batch, not drift" in r_burst["why"],
      "a single bad week has exactly this shape")

# --- THE separation: independent drift vs a lab-wide change ------------------
independent = []
for d in range(0, 400, 25):
    independent.append(rec("N2", "speed_mm_s", d, 0.120 - 0.00008 * d))
    independent.append(rec("dys-1", "speed_mm_s", d, 0.050 + 0.00006 * d))
    independent.append(rec("pezo-1", "speed_mm_s", d, 0.090))
ind = sd.common_mode(independent, "speed_mm_s", ["N2", "dys-1", "pezo-1"])
check("strains drifting in different directions is NOT common-mode",
      ind["common"] is False)
check("...and that is named as the reassuring answer",
      "reassuring answer" in ind["why"],
      "independent genetic drift is what this looks like")

together = []
for d in range(0, 400, 25):
    factor = 1 - 0.0002 * d          # everything slows by the same fraction
    together.append(rec("N2", "speed_mm_s", d, 0.120 * factor))
    together.append(rec("dys-1", "speed_mm_s", d, 0.050 * factor))
    together.append(rec("pezo-1", "speed_mm_s", d, 0.090 * factor))
com = sd.common_mode(together, "speed_mm_s", ["N2", "dys-1", "pezo-1"])
check("every strain drifting together IS common-mode", com["common"] is True)
check("...naming that separate strains have no reason to move in step",
      "no reason to move in step" in com["question"])
check("...and pointing at what is shared, not at the worms",
      "incubator" in com["question"] and "food batch" in com["question"])
check("...warning that re-thawing would hide it",
      "will not fix a lab-wide change, and will hide it" in com["question"],
      "the expensive mistake this is meant to prevent")

check("one strain alone cannot establish common mode",
      sd.common_mode(together, "speed_mm_s", ["N2"])["checked"] is False)

# --- thaws are the anchor -----------------------------------------------------
with_thaw = [rec("N2", "speed_mm_s", d, 0.120 - 0.00008 * d, thaw=200)
             for d in range(0, 400, 25)]
anchored = sd.drift(with_thaw, "N2", "speed_mm_s", since_thaw=True)
check("drift is measured since the last thaw when one is known",
      anchored["since_thaw"] is True and anchored["n"] < len(with_thaw),
      "a refreshed line starts its history again")

reset = ([rec("N2", "len_um", d, 1100 - 0.5 * d, thaw=200)
          for d in range(100, 200, 20)] +
         [rec("N2", "len_um", d, 1100, thaw=200)
          for d in range(200, 320, 20)])
eff = sd.thaw_effect(reset, "N2", "len_um")
check("a thaw that resets the measurement is recognised",
      eff["checked"] and eff["changed_at_thaw"] is True)
check("...as what a refresh is supposed to do",
      "supposed to do" in eff["note"])

no_reset = [rec("N2", "len_um", d, 1000, thaw=200)
            for d in list(range(100, 200, 20)) + list(range(200, 320, 20))]
eff2 = sd.thaw_effect(no_reset, "N2", "len_um")
check("a thaw that does NOT reset it is a finding of its own",
      eff2["changed_at_thaw"] is False)
check("...offering both explanations",
      "frozen stock may already carry the change" in eff2["note"] and
      "never genetic" in eff2["note"],
      "frozen after the drift began, or not genetic at all")
check("no thaw date means the question cannot be asked",
      sd.thaw_effect(steady, "N2", "speed_mm_s")["checked"] is False)

# --- the report states its own multiplicity ----------------------------------
rep = sd.report(together, ["speed_mm_s"], ["N2", "dys-1", "pezo-1"],
                since_thaw=False)
check("the report counts how many combinations were examined",
      rep["n_tests"] == 3)
check("...saying a single drifting combination is weak evidence",
      "weak evidence" in rep["multiplicity"])
check("common-mode findings are listed separately and first",
      len(rep["common_mode"]) == 1 and
      "common-mode findings first" in rep["priority"])
check("...naming that re-thawing hides the cause for months",
      "hide the cause for a few months" in rep["priority"])

clean_rep = sd.report(independent, ["speed_mm_s"], ["N2", "dys-1", "pezo-1"],
                      since_thaw=False)
check("no common-mode drift is reported as such",
      clean_rep["common_mode"] == [] and
      "consistent with that strain's own history" in clean_rep["priority"])

# --- refusals ------------------------------------------------------------------
zeros = [rec("N2", "x", d, 0.0) for d in range(0, 400, 25)]
try:
    sd.drift(zeros, "N2", "x", since_thaw=False)
    check("a zero median is refused", False)
except sd.DriftError as exc:
    check("a zero median is refused", True)
    check("...naming that fractional change is undefined",
          "fractional change is undefined" in str(exc))

# --- the Reagent Hub is where thaws are recorded -----------------------------
# Andres: Mackenzie records a thaw in the hub, and it is passed to WINK. The
# hub holds the freezer, so it holds the log; this is where the two meet.
payload = {"thaws": [
    {"strain": "N2", "thaw_date": "2025-01-10", "outcome": "recovered",
     "is_refresh": True, "thawed_by": "MJ", "source_copy": "copy_2"},
    {"strain": "N2", "thaw_date": "2025-06-10", "outcome": "failed",
     "is_refresh": False},
    {"strain": "N2", "thaw_date": "2025-07-01", "outcome": "in_progress",
     "is_refresh": False},
    {"strain": "dys-1", "thaw_date": "2025-03-01", "outcome": "recovered",
     "is_refresh": True},
]}
anch = sd.thaw_records_from_hub(payload)
check("successful thaws become drift anchors", anch["n_anchors"] == 2)
check("a FAILED thaw is not an anchor", anch["n_skipped"] == 2)
check("...naming that it never restarted the line",
      any("did not restart the line" in s_["reason"]
          for s_ in anch["skipped"]),
      "treating it as a reset would make a real drift appear to vanish")
check("...but is still reported, since it explains a drift that did not reset",
      "explains a drift that did not reset" in anch["why"])
check("the anchor carries who thawed it and from which copy",
      anch["anchors"][0]["thawed_by"] == "MJ" and
      anch["anchors"][0]["source_copy"] == "copy_2",
      "copies frozen on different dates are different stocks")

rows_h = [rec("N2", "speed_mm_s", -30, 0.11),
          rec("N2", "speed_mm_s", 30, 0.10),
          rec("dys-1", "speed_mm_s", 100, 0.05)]
stamped = sd.attach_thaws(rows_h, anch["anchors"])
before, after = stamped[0], stamped[1]
check("a measurement taken BEFORE any thaw gets no anchor",
      "thaw_date" not in before,
      "otherwise old measurements look like they came from current stock")
check("a measurement after a thaw is stamped with it",
      after.get("thaw_date") == "2025-01-10")
check("...and with how long the line had been growing",
      after.get("days_since_thaw") == 21)
check("each strain gets its own thaw, not the latest overall",
      stamped[2].get("thaw_date") == "2025-03-01")

check("an empty payload yields no anchors and does not raise",
      sd.thaw_records_from_hub({"thaws": []})["n_anchors"] == 0)
check("a row missing its date is skipped with a reason",
      any("no strain or no date" in s_["reason"] for s_ in
          sd.thaw_records_from_hub(
              {"thaws": [{"strain": "N2", "is_refresh": True}]})["skipped"]))

# --- a missing thaw date starts the clock rather than blocking ---------------
# Andres: if a student does not enter a thaw date, day zero is today, and
# three months later the assistant can say "it has been AT LEAST three months
# since you thawed this strain". "At least" is doing real work in that
# sentence, and the code has to keep it.
TODAY = dt.date(2025, 8, 6)
seen_only = [rec("N2", "speed_mm_s", 90, 0.11)]      # first seen 2025-04-01
implied = sd.anchor_for("N2", seen_only, [], today=TODAY)
check("with no thaw recorded, first sight starts the clock",
      implied["kind"] == "first_seen")
check("...and it is marked a LOWER BOUND",
      implied["is_lower_bound"] is True,
      "the line may have been growing long before anyone measured it")
check("...naming that the true figure can only be larger",
      "possibly much more" in implied["why"])

msg = sd.since_thaw_message(implied)
check("the sentence says 'at least'", "at least" in msg["line"])
check("...and offers the fix", "Reagent Hub would make this exact"
      in msg["line"])
check("...and converts days into generations, which is the unit that matters",
      "generations" in msg["line"],
      "one deleterious mutation every three generations")

known = sd.anchor_for("N2", seen_only,
                      [{"strain": "N2", "thaw_date": "2025-01-10"}],
                      today=TODAY)
check("a recorded thaw supersedes first sight",
      known["kind"] == "thaw" and known["is_lower_bound"] is False)
check("...and the hedge disappears",
      "at least" not in sd.since_thaw_message(known)["line"],
      "a known date is not a floor")
check("...giving a longer elapsed time than the floor did",
      known["days_since"] > implied["days_since"],
      "which is exactly why the floor was only a floor")

recent = sd.anchor_for("N2", [rec("N2", "speed_mm_s", 210, 0.11)], [],
                       today=TODAY)
check("a recently-seen strain is not flagged as overdue",
      sd.since_thaw_message(recent)["past_reminder"] is False)
check("an old line IS flagged", msg["past_reminder"] is True)
check("...naming the mutation rate rather than just a date",
      "one deleterious mutation every three generations" in msg["line"])
check("...and recommending a fresh thaw before it reaches results",
      "before it shows up in results" in msg["line"])

check("a strain with nothing recorded at all says so",
      sd.anchor_for("ghost", seen_only, [], today=TODAY)["kind"] == "none")
check("...and the assistant stays silent about it",
      sd.since_thaw_message(
          sd.anchor_for("ghost", seen_only, [], today=TODAY))["say"] is False)

status = sd.refresh_status(["N2", "dys-1"],
                           seen_only + [rec("dys-1", "speed_mm_s", 200, 0.05)],
                           [{"strain": "dys-1", "thaw_date": "2025-07-01"}],
                           today=TODAY)
check("a status list separates guessed ages from known ones",
      status["n_lower_bound"] == 1 and status["n_overdue"] == 1)
check("...naming which strains are overdue", status["overdue"] == ["N2"])
check("...and that entering dates converts a floor into a fact",
      "converts a floor into a fact" in status["note"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("STRAIN_DRIFT_PASS")
