"""WWN2D: a reference library of what N2 does, and what to do with it.

The property that decides whether this is useful or maddening: a mutant
differing from N2 is the experiment SUCCEEDING, not a problem. If the tool
announces "not normal" every time a dystrophy model is slow, it will be muted
within a week and then catches nothing.

So the alarm is pointed at the N2 CONTROL - if a student's own wild type does
not look like wild type, every genotype beside it is suspect - and a mutant
difference is reported as information.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import n2_reference as n2   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("N2 reference - regression\n")

ON_FOOD = {"strain": "N2", "gait": "crawl", "food": "on", "assay": "kinematics",
           "temperature_c": 20, "age": "day1"}
OFF_FOOD = {**ON_FOOD, "food": "off"}

lib = {"entries": []}
n2.contribute(lib, metric="speed_mm_s",
              values=[0.10, 0.11, 0.12, 0.09, 0.105, 0.115, 0.10, 0.11],
              conditions=ON_FOOD, source="own_results", reviewed=True)
n2.contribute(lib, metric="speed_mm_s",
              values=[0.20, 0.21, 0.19, 0.22, 0.20, 0.21],
              conditions=OFF_FOOD, source="own_results", reviewed=True)

# --- conditions are part of the reference ------------------------------------
on = n2.lookup(lib, "speed_mm_s", ON_FOOD)
off = n2.lookup(lib, "speed_mm_s", OFF_FOOD)
check("a reference is found for the matching conditions", on["found"])
check("...and differs from the same metric under other conditions",
      abs(on["median"] - off["median"]) > 0.05,
      f"on food {on['median']:.3f}, off food {off['median']:.3f}")

odd = n2.lookup(lib, "speed_mm_s", {**ON_FOOD, "temperature_c": 25})
check("an unmatched condition returns NOTHING, not the closest thing",
      odd["found"] is False)
check("...naming that the wrong reference would look authoritative",
      "look authoritative while describing a different experiment"
      in odd["why"])
check("...while saying what else exists, so the gap is visible",
      odd["n_other_conditions"] == 2)

# --- a reference too thin to judge with --------------------------------------
thin = {"entries": []}
n2.contribute(thin, metric="speed_mm_s", values=[0.1, 0.12],
              conditions=ON_FOOD, source="literature", citation="somebody 2020")
t = n2.lookup(thin, "speed_mm_s", ON_FOOD)
check("a thin reference is returned but marked unusable",
      t["found"] is True and t["enough_to_judge"] is False)
check("...saying it is for seeing, not for judging",
      "not so it can be judged against" in t["caveat"])
check("...and a control check declines rather than guessing",
      n2.check_control(thin, metric="speed_mm_s", control_values=[0.9],
                       conditions=ON_FOOD)["checked"] is False)

# --- THE check that earns its keep -------------------------------------------
good = n2.check_control(lib, metric="speed_mm_s",
                        control_values=[0.10, 0.11, 0.105],
                        conditions=ON_FOOD)
check("a normal control passes quietly",
      good["checked"] and good["control_looks_normal"] is True
      and good["question"] is None)

bad = n2.check_control(lib, metric="speed_mm_s",
                       control_values=[0.02, 0.03, 0.025],
                       conditions=ON_FOOD)
check("an abnormal N2 control is caught",
      bad["control_looks_normal"] is False)
check("...naming that every genotype beside it is suspect",
      "every genotype run beside it today is suspect" in bad["question"])
check("...and pointing at the day rather than the animal",
      "more likely the day, the plate or a setting" in bad["question"])
check("...before anything else is interpreted",
      "before interpreting anything else" in bad["question"])

check("a run with no control says so",
      n2.check_control(lib, metric="speed_mm_s", control_values=[],
                       conditions=ON_FOOD)["checked"] is False)

# --- a mutant differing from N2 is NOT an alarm ------------------------------
mutant = n2.compare_strain(lib, metric="speed_mm_s",
                           values=[0.04, 0.045, 0.038],
                           conditions={**ON_FOOD, "strain": "dys-1"})
check("a slow mutant is compared without alarm",
      mutant["differs"] is True and "question" not in mutant)
check("...and reported as information", "note" in mutant)
check("...naming that it is usually what the experiment was for",
      "what the experiment was for" in mutant["note"],
      "the tool must not announce that the experiment worked")
check("...with the direction and size given",
      mutant["direction"] == "lower" and mutant["fold"] < 1)

same = n2.compare_strain(lib, metric="speed_mm_s", values=[0.105, 0.11],
                         conditions={**ON_FOOD, "strain": "dys-1"})
check("a mutant matching N2 is also reported, since that may be the finding",
      same["differs"] is False and "if a difference was expected" in
      same["note"])

# --- but N2 differing from N2 IS an alarm ------------------------------------
wrong_n2 = n2.compare_strain(lib, metric="speed_mm_s",
                             values=[0.30, 0.31, 0.29],
                             conditions=ON_FOOD)
check("N2 that does not behave like N2 raises a question",
      wrong_n2["is_n2"] and "question" in wrong_n2)
check("...naming that the run is more suspect than the animal",
      "suspect the run before the animal" in wrong_n2["question"])

# --- an unexpected DIRECTION is worth a question -----------------------------
inverted = n2.compare_strain(lib, metric="speed_mm_s",
                             values=[0.30, 0.31],
                             conditions={**ON_FOOD, "strain": "dys-1"},
                             expected_direction="lower")
check("a difference in the unexpected direction is questioned",
      "question" in inverted)
check("...offering both explanations",
      "the expectation is wrong" in inverted["question"] and
      "swapped label" in inverted["question"],
      "either a result, or something inverted in the run")

# --- the library cannot be poisoned automatically ----------------------------
try:
    n2.contribute(lib, metric="speed_mm_s", values=[9, 9, 9],
                  conditions=ON_FOOD, source="own_results", reviewed=False)
    check("unreviewed own results are refused", False)
except n2.ReferenceError as exc:
    check("unreviewed own results are refused", True)
    check("...naming that today's errors become tomorrow's normal",
          "wrong scale would become the reference" in str(exc),
          "an uncurated library defines normal as whatever happened")

try:
    n2.contribute(lib, metric="x", values=[1.0], conditions=ON_FOOD,
                  reviewed=True)
    check("a single value is refused", False)
except n2.ReferenceError as exc:
    check("a single value is refused", True)
    check("...naming that it would call every second measurement abnormal",
          "no spread would call every second measurement abnormal" in str(exc))

try:
    n2.contribute(lib, metric="x", values=[1.0, 2.0],
                  conditions={"gait": "crawl"}, reviewed=True)
    check("conditions without strain and assay are refused", False)
except n2.ReferenceError as exc:
    check("conditions without strain and assay are refused", True)
    check("...naming that on-food and off-food are different numbers",
          "on food and N2 off food are different numbers" in str(exc))

# --- honest state of the library ---------------------------------------------
cov = n2.coverage(lib, metrics=("speed_mm_s", "pumping_per_min",
                                "bend_amplitude_deg"))
check("coverage counts what can actually support a judgement",
      cov["n_metrics_usable"] == 1)
check("...and lists what is asked for but absent",
      set(cov["missing"]) == {"pumping_per_min", "bend_amplitude_deg"})
check("...describing a gap as the next thing to measure",
      "have none at all" in cov["why"])

# --- persistence ---------------------------------------------------------------
import tempfile   # noqa: E402
tmp = Path(tempfile.mkdtemp()) / "lib.json"
n2.save(lib, tmp)
check("the library round-trips",
      len(n2.load(tmp)["entries"]) == len(lib["entries"]))
tmp.write_text("{broken", encoding="utf-8")
try:
    n2.load(tmp)
    check("a corrupt library is refused", False)
except n2.ReferenceError as exc:
    check("a corrupt library is refused", True)
    check("...naming that both failure modes are silent",
          "neither failure announces itself" in str(exc),
          "it would either silence the check or make it fire on everything")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("N2_REFERENCE_PASS")
