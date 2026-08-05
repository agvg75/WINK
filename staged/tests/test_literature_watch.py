"""The weekly literature watch, and the discipline that keeps it honest.

The property that matters is negative again: a weekly loop that tests every
candidate against the same held-out fixtures will eventually promote one on a
margin that means nothing. Not through carelessness - the best of N noisy draws
is high by construction. These checks are what stops that.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import literature_watch as lw   # noqa: E402
import method_provenance as mp  # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("literature watch - regression\n")

# --- the watch list -------------------------------------------------------
targets = set(mp.METHODS) | set(mp.OPEN_PROBLEMS)
dangling = [b for w in lw.WATCH_TOPICS.values()
            for b in w["bears_on"] + w["open_problems"] if b not in targets]
check("every watch topic attaches to a real method or open problem",
      not dangling, "; ".join(dangling[:3]) if dangling else
      f"{len(lw.WATCH_TOPICS)} topics")
check("every open problem is watched by at least one topic",
      not (set(mp.OPEN_PROBLEMS)
           - {p for w in lw.WATCH_TOPICS.values() for p in w["open_problems"]}
           - {"no_fiji_parity_check", "dv_untested_on_real_animals"}),
      "unwatched: " + ", ".join(sorted(
          set(mp.OPEN_PROBLEMS)
          - {p for w in lw.WATCH_TOPICS.values() for p in w["open_problems"]})))

brief = lw.weekly_brief()
check("the brief lists the searches to run", "bioRxiv" in brief
      and "myocyte_boundary" in brief)
check("...and the rules for spending held-out data",
      "ONE held-out evaluation" in brief)
check("...and names the protected validation set",
      "open_biology_validation_set" in brief
      and "Never used by this process" in lw.PROTECTED_DATA[
          "open_biology_validation_set"])
check("the protected set is NOT reachable as a benchmark fixture",
      not any("open_biology" in str(b) for b in lw.BENCHMARKS.values()))

# --- screening ------------------------------------------------------------
cand = lw.screen(
    title="A better ridge filter for dim membranes", source="bioRxiv",
    url="https://example.org/preprint", bears_on=["valley_operator"],
    claim="Higher localisation than Hessian ridge filters at low SNR.",
    why_relevant="Directly the operator fibre_trace uses.")
check("a candidate is recorded attached to what it could displace",
      cand["bears_on"] == ["valley_operator"] and cand["stage"] == "screened")

try:
    lw.screen("Unrelated", "arXiv", "u", ["not_a_method"], "c", "w")
    check("a candidate attaching to nothing is refused", False)
except lw.WatchError as exc:
    check("a candidate attaching to nothing is refused", True)
    check("...naming what would happen to it",
          "nobody ever acts on" in str(exc))

# --- the plan is stated before the run ------------------------------------
plan = lw.evaluation_plan(cand, "myocyte_boundary_recall")
check("the plan states the margin in advance",
      plan["min_improvement"] == 0.05 and plan["why_that_margin"])
check("...runs on development data, reserving the held-out set",
      "midbody" in plan["run_on"] and "head" in plan["heldout_reserved"])
check("...and requires speed and accuracy separately",
      "seconds per field" in plan["also_track"]
      and "hides which case you are in" in plan["speed_and_accuracy_separately"])
check("...listing the data this process must not touch",
      "open_biology_validation_set" in plan["protected"])

try:
    lw.evaluation_plan(cand, "invented_benchmark")
    check("evaluating against an unstated benchmark is refused", False)
except lw.WatchError as exc:
    check("evaluating against an unstated benchmark is refused", True)
    check("...saying a threshold chosen afterwards is not a threshold",
          "not a threshold" in str(exc))

# --- THE KEY ONE: the margin must grow with the number of candidates ------
first = lw.multiplicity_guard(0.06, n_candidates_tested=1, min_improvement=0.05)
check("a first candidate clearing the margin is established",
      first["established"] is True, f"required {first['required_now']}")

twentieth = lw.multiplicity_guard(0.06, n_candidates_tested=20,
                                  min_improvement=0.05)
check("the SAME margin is not established as the twentieth candidate",
      twentieth["established"] is False,
      f"required {twentieth['required_now']} after 20 candidates")
check("...explaining that the best of N noisy results is high by construction",
      "high by construction" in twentieth["why"])
check("...and advising more data rather than more candidates",
      "more data rather than more candidates" in twentieth["why"])
check("a genuinely large margin still clears after many candidates",
      lw.multiplicity_guard(0.30, 20, 0.05)["established"] is True)

# --- held-out data is spent, not borrowed ---------------------------------
promoted = lw.promote_to_heldout(cand, "myocyte_boundary_recall", True)
check("a candidate that won on development data may spend one held-out run",
      promoted["tested_on_heldout"] is True and promoted["stage"] == "promoted")
check("...and is told there is no second run", "no second run" in promoted["note"])

try:
    lw.promote_to_heldout(promoted, "myocyte_boundary_recall", True)
    check("a second held-out run on the same candidate is refused", False)
except lw.WatchError as exc:
    check("a second held-out run on the same candidate is refused", True)
    check("...naming that it turns held-out data into training data",
          "becomes a training set" in str(exc))

try:
    lw.promote_to_heldout(cand, "myocyte_boundary_recall", False)
    check("a candidate that lost on development data is refused held-out data",
          False)
except lw.WatchError as exc:
    check("a candidate that lost on development data is refused held-out data",
          True)
    check("...saying held-out data is spent, not borrowed",
          "spent, not borrowed" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("LITERATURE_WATCH_PASS")
