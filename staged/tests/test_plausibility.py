"""Ask about the numbers that cannot be right.

Andres: the assistant should look at a student's results and say "what's this
here? this doesn't make sense, you should look at it."

The properties under test are that detection is arithmetic rather than
guesswork, that a contradiction outranks a range violation, that an outlier is
offered as a question because a real finding looks exactly like one, and that
an unknown column produces silence rather than a confident opinion.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import plausibility as pl   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("plausibility - regression\n")

# --- outside biology ----------------------------------------------------------
bad = pl.check_value("sarcomere_um", 38.0)
check("a 38 um sarcomere is caught", bad["plausible"] is False)
check("...as a question, not a verdict",
      "Worth checking" in bad["question"] and "?" not in bad["question"][:20],
      "the student may be right and the range wrong")
check("...naming the two usual causes",
      "wrong scale" in bad["question"] and "unit mix-up" in bad["question"],
      "this is the class that produced the 20x error in this project")
check("a normal sarcomere passes",
      pl.check_value("sarcomere_um", 1.6)["plausible"] is True)

check("a worm 12 mm long is caught",
      pl.check_value("body_length_um", 12000)["plausible"] is False)
check("an L1 is not caught", pl.check_value("body_length_um", 250)["plausible"])
check("a gravid adult is not caught",
      pl.check_value("body_length_um", 1400)["plausible"],
      "ranges bound the possible, not the typical - a false alarm gets the "
      "check switched off")

# --- unknown quantities are silent -------------------------------------------
unknown = pl.check_value("mystery_index", 999999)
check("an unknown quantity is not judged", unknown["known"] is False)
check("...and says so rather than passing it as fine",
      "silent rather than assumed fine" in unknown["why"])

# --- a value that is not a number ---------------------------------------------
nan = pl.check_value("body_length_um", "n/a")
check("a non-numeric measurement is flagged",
      nan["plausible"] is False and nan["kind"] == "not_a_number")
check("...asking whether it was measured at all",
      "placeholder" in nan["question"])

# --- internal consistency is stronger than a range ---------------------------
row = {"area_um2": 900000, "length_um": 1000, "width_um": 80}
found = pl.check_row(row)
kinds = {f["kind"] for f in found}
check("an area larger than its bounding box is caught",
      "inconsistent" in kinds)
check("...naming that the numbers cannot share units",
      any("same units" in f.get("question", "") for f in found))

thin = pl.check_row({"area_um2": 10, "length_um": 1000, "width_um": 80})
check("an impossibly thin outline is caught too",
      any(f.get("rule") == "area_not_impossibly_thin" for f in thin))

swapped = pl.check_row({"length_um": 60, "width_um": 900})
check("width exceeding length is caught",
      any(f.get("rule") == "length_exceeds_width" for f in swapped))
check("...offering both explanations",
      any("axes are swapped" in f.get("question", "") and
          "coiled" in f.get("question", "") for f in swapped))

speed = pl.check_row({"speed_mm_s": 0.5, "distance_mm": 1.0,
                      "duration_s": 100.0})
check("a speed that disagrees with distance over time is caught",
      any(f.get("rule") == "speed_vs_distance_and_time" for f in speed),
      "0.5 mm/s against 1 mm in 100 s")
check("a consistent speed row passes",
      not pl.check_row({"speed_mm_s": 0.01, "distance_mm": 1.0,
                        "duration_s": 100.0}))

check("consistency needs all its columns, and is silent otherwise",
      pl.check_row({"area_um2": 900000}) == [],
      "half a rule is not a finding")

# --- unusual for THIS dataset -------------------------------------------------
rows = [{"body_length_um": 1100 + i} for i in range(20)]
rows.append({"body_length_um": 1700})
res = pl.check_table(rows)
check("a value far from the rest of the data is noticed",
      len(res["unusual_here"]) >= 1)
check("...phrased as possibly a real effect",
      any("genuine finding looks exactly like this" in u["question"]
          for u in res["unusual_here"]),
      "an outlier and a discovery are the same shape")
check("...and it is still inside biology, so not called an error",
      res["outside_biology"] == [])

check("a small table gets no outlier hunting",
      pl.check_table([{"body_length_um": 1100},
                      {"body_length_um": 1700}])["unusual_here"] == [],
      "five points cannot establish what is unusual")

# --- a clean table -------------------------------------------------------------
clean = pl.check_table([{"body_length_um": 1100 + i, "body_width_um": 70}
                        for i in range(12)])
check("a clean table reports clean", clean["clean"] is True)
check("...without claiming the numbers are right",
      "not a guarantee" in clean["note"],
      "only that they are inside the ranges checked")

# --- what the assistant actually says ----------------------------------------
mixed = pl.check_table(
    [{"sarcomere_um": 1.6, "area_um2": 100, "length_um": 50,
      "width_um": 10} for _ in range(10)] +
    [{"sarcomere_um": 38.0, "area_um2": 900000, "length_um": 1000,
      "width_um": 80}])
say = pl.brief(mixed)
check("the assistant is given something to say",
      say["say_something"] is True)
check("contradictions come before range violations",
      "contradict each other" in say["lines"][0],
      "a row that disagrees with itself is wrong whatever the biology")
check("...and the ordering is explained, not implicit",
      "might be the result" in say["ordering"])
check("a clean table gives the assistant nothing to say",
      pl.brief(clean)["say_something"] is False,
      "silence is the right output when nothing is wrong")

# --- provenance of the limits themselves -------------------------------------
check("every range carries its source",
      all(r.get("source") for r in pl.RANGES.values()))
check("...and its confidence", all(r.get("confidence") in
                                   ("high", "medium", "low")
                                   for r in pl.RANGES.values()))
lab = pl.check_value("myocyte_area_um2", 99999)
check("a low-confidence limit says the RANGE may be what is wrong",
      "range may be what needs changing" in lab["question"],
      "a limit with no provenance is a guess wearing the clothes of a fact")

try:
    pl.check_table([])
    check("an empty table is refused", False)
except pl.PlausibilityError as exc:
    check("an empty table is refused", True)
    check("...naming that empty and clean are indistinguishable",
          "indistinguishable from a clean one" in str(exc))

# --- one cause beats three symptoms ------------------------------------------
# A student who mis-set the scale gets a flag on sarcomere length, on body
# length and on width: three messages for one mistake, none of which says what
# the mistake was. Five complaints about one error is how a check becomes
# noise and gets ignored.
scaled = [{"sarcomere_um": 1.55 + 0.05 * i, "body_length_um": 1100 + 10 * i,
           "body_width_um": 72} for i in range(10)]
scaled.append({"sarcomere_um": 31.5, "body_length_um": 22400,
               "body_width_um": 1460})
res_s = pl.check_table(scaled)
say_s = pl.brief(res_s)
check("three symptoms collapse into one diagnosis",
      len(say_s["lines"]) == 1, f"{len(say_s['lines'])} lines")
check("...naming the factor, close to the real 20.3x error",
      18 <= res_s["common_cause"]["factor"] <= 22,
      f"{res_s['common_cause']['factor']:.1f}x")
check("...and saying it is one error rather than three problems",
      "rather than 3 separate problems" in say_s["lines"][0])
check("...pointing at calibration before anything else",
      "Check the calibration" in say_s["lines"][0])
check("...and that no re-measurement is needed",
      "without re-measuring anything" in say_s["lines"][0],
      "the pixel geometry is still right; only the conversion was wrong")
check("the outlier flags for the same columns are suppressed as already "
      "explained",
      not any("robust standard deviations" in l for l in say_s["lines"]))

different = [{"sarcomere_um": 1.6, "pumping_per_min": 250} for _ in range(10)]
different.append({"sarcomere_um": 38.0, "pumping_per_min": 900})
res_d = pl.check_table(different)
check("genuinely different problems are NOT collapsed",
      "common_cause" not in pl.brief(res_d) and
      pl.common_cause(res_d["outside_biology"]) is None,
      "collapsing these would hide one of them")
check("...and both are still reported",
      len(pl.brief(res_d)["lines"]) >= 2)

check("a single out-of-range value has no pattern to report",
      pl.common_cause([{"kind": "outside_biology", "value": 99,
                        "range": [1, 2], "quantity": "x"}]) is None,
      "one point cannot establish a common factor")

check("the reference is the student's own data, not the range centre",
      any(f.get("dataset_median") is not None
          for f in res_s["outside_biology"]),
      "ranges differ in width, so range centres give three different factors "
      "for one error and the pattern disappears")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PLAUSIBILITY_PASS")
