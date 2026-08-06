"""Who ran this, recorded so it still resolves to a person years later.

The property under test is that a MISSING attribution stays visibly missing.
Anything that quietly fills the gap - a default, an empty string treated as a
value, a confirmed flag on an uninspected file - names an innocent person as
the source of a number, which is worse than an honest hole.
"""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

tmp = Path(tempfile.mkdtemp())
os.environ["WINK_OPERATOR"] = str(tmp / "operator.json")

import operator_identity as oi   # noqa: E402
oi.STORE = tmp / "operator.json"

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("operator identity - regression\n")

# --- the name is not the stdlib module ------------------------------------
import operator as stdlib_operator   # noqa: E402
check("importing 'operator' gets the standard library",
      hasattr(stdlib_operator, "itemgetter"))
# That check alone is weak: `operator` is usually already in sys.modules by the
# time app/ reaches sys.path, so a shadowing file passes it and then breaks
# somewhere else depending on import order. Assert on the file instead - an
# intermittent import bug is worse than a reproducible one.
check("no app/operator.py exists to shadow it",
      not (ROOT / "app" / "operator.py").exists(),
      "the module is named operator_identity.py for exactly this reason")

# --- unset is visibly unset ------------------------------------------------
check("nobody is set to begin with", oi.load()["set"] is False)
rec = oi.stamp({"measurement": 12.0}, tool="pboc")
check("an unattributed run still records", rec["operator"]["set"] is False)
check("...with the initials as None, not an empty string",
      rec["operator"]["initials"] is None,
      "an empty string reads as a value and looks attributed")
check("...and says plainly that nobody owns it",
      "no owner" in rec["operator_unset"])
check("...naming why guessing would be worse",
      "names an innocent person" in rec["operator_unset"])
check("the status line says so too", "not set" in oi.describe())

# --- setting an operator ---------------------------------------------------
oi.save("mj", "Mackenzie Jones")
op = oi.load()
check("initials are normalised to upper case", op["initials"] == "MJ")
check("the full name is kept alongside", op["full_name"] == "Mackenzie Jones")
check("the machine is recorded", bool(op["machine"]))
check("the status line names the person", "Mackenzie Jones" in oi.describe())

# --- the stamp -------------------------------------------------------------
rec = oi.stamp({"measurement": 12.0}, tool="pboc")
check("a run is stamped with the initials", rec["operator"]["initials"] == "MJ")
check("...and the full name, which is what survives ambiguity",
      rec["operator"]["full_name"] == "Mackenzie Jones")
check("...and the date, so date+initials assign an owner",
      len(rec["run_date"]) == 10 and rec["run_date"][4] == "-")
check("...and the tool", rec["tool"] == "pboc")
check("no unset warning once somebody is set", "operator_unset" not in rec)

src = {"measurement": 12.0}
oi.stamp(src)
check("stamping does not mutate the record it is given", src == {"measurement": 12.0},
      "otherwise measured fields and added ones become indistinguishable")

# --- refusals --------------------------------------------------------------
try:
    oi.save("", "Someone")
    check("empty initials are refused", False)
except oi.OperatorError as exc:
    check("empty initials are refused", True)
    check("...naming that it would look attributed when it is not",
          "look attributed" in str(exc))

try:
    oi.save("AV", "")
    check("initials without a full name are refused", False)
except oi.OperatorError as exc:
    check("initials without a full name are refused", True)
    check("...because initials alone stop being unambiguous",
          "second person shares them" in str(exc))

# --- handing over the station ---------------------------------------------
oi.clear()
check("clearing leaves nobody set, not the last person",
      oi.load()["set"] is False and oi.initials() == "")
check("...and a run made afterwards is marked unattributed",
      "operator_unset" in oi.stamp({}))

# --- an unreadable store is not silently an empty one ----------------------
oi.STORE.write_text("{broken", encoding="utf-8")
try:
    oi.load()
    check("an unreadable store is refused", False)
except oi.OperatorError as exc:
    check("an unreadable store is refused", True)
    check("...rather than quietly attributing everything to nobody",
          "would not be visible" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("OPERATOR_IDENTITY_PASS")
