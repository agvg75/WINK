"""The segmentation channel is a gate, not a warning, and it is never silent.

SPEC 1 of the cultured cell population spec. The question it settles is
whether the cells MEASURED are a fair sample of the cells PRESENT, and every
between-cell comparison rests on it. A warning can be read past; a withheld
result cannot.

THE BIAS THAT MAKES THIS MATTER. If cells are found by thresholding the
calcium channel, dim cells are missed and the sample skews towards high
calcium - and the skew need not be equal between groups. A knockdown that
raises resting calcium also makes its own cells easier to find, inflating the
very difference being measured. That is not a small effect on the margin; it
manufactures the result.

WHY IT IS NOT SIMPLY BLOCKED WHEN THE PROBE CHANNEL IS USED (spec 1.3): a
single-channel acquisition has no other option, and refusing it would stop
the students working. The condition is stated instead, and it travels with
EXPORTED results rather than living only in the UI - the caveat has to reach
whoever reads the CSV, not only whoever clicked the button.

THE ONE-CHANNEL CASE. Requiring someone to type a channel name when there is
exactly one channel to choose is a gate that teaches people to click past
gates. It is pre-filled and confirmed in one click: recorded and confirmed
always, silent never.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

import cell_calcium as cc   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def design(seg):
    return cc.check_two_channel_design(
        signal_channel="_ch00", marker_channel="_ch01",
        segmentation_channel=seg)


print("\n--- undeclared withholds, and says what it withheld ------------")

undeclared = design(None)
check("population measures are BLOCKED when nothing is declared",
      undeclared["blocked_measures"],
      f"{len(undeclared['blocked_measures'])} withheld")
check("...including the three named in the spec",
      all(m in undeclared["blocked_measures"]
          for m in ("resting", "soce", "responding_fraction")))
check("...and the declaration is recorded as absent",
      undeclared["segmentation_declared"] is False)
check("...with a warning that says why it matters",
      any("fair sample" in w for w in undeclared["warnings"]))

print("\n--- an independent channel releases them ----------------------")

good = design("_ch02")
check("nothing is blocked", good["blocked_measures"] == [])
check("...the declaration is recorded", good["segmentation_declared"])
check("...no bias note is attached", good["bias_note"] == "")
check("...and it says why this arrangement is the right one",
      any("untransfected cells act as controls" in n for n in good["notes"]))

print("\n--- probe-channel segmentation: allowed, never unlabelled -----")

probe = design("_ch00")
check("it is NOT blocked", probe["blocked_measures"] == [],
      "a single-channel acquisition has no other option")
check("...but a bias note exists", bool(probe["bias_note"]))
check("...naming loading as the confound",
      "LOADING" in probe["bias_note"].upper())
check("...and saying within-cell time courses survive",
      "within-cell" in probe["bias_note"].lower(),
      "the caveat is about BETWEEN-cell comparison only")

marker = design("_ch01")
check("marker-channel segmentation still warns about the lost control",
      any("internal control" in w for w in marker["warnings"]))

print("\n--- one channel: pre-filled, confirmed, never silent -----------")

channel, why = cc.single_channel_default(["_ch00"])
check("a single channel is offered", channel == "_ch00")
check("...with a reason to confirm against",
      "only have come from it" in why)
check("...that names the consequence before the click",
      "loading-bias" in why or "loading" in why.lower(),
      "accepting routes to the 1.3 path, and says so first")

none_offered, why_not = cc.single_channel_default(["_ch00", "_ch01"])
check("two channels are NOT pre-filled", none_offered is None,
      "with a choice to make, the person makes it")
check("...and it says why it is asking", "2 channels" in why_not)
check("zero channels are not pre-filled",
      cc.single_channel_default([])[0] is None)
check("blank names do not count as a channel",
      cc.single_channel_default(["_ch00", "  "])[0] == "_ch00",
      "an empty string is not a second channel")

print("\n--- accepting the single channel lands on the 1.3 path ---------")

accepted = design(cc.single_channel_default(["_ch00"])[0])
check("confirming the one channel produces the bias note",
      bool(accepted["bias_note"]))
check("...and does not block the students from working",
      accepted["blocked_measures"] == [])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("SEGMENTATION_GATE_PASS")
