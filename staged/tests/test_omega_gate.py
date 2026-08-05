"""The omega gate: unchecked by default, but the default is recorded as such.

The property that matters is the distinction between what the box SAYS and
whether anyone LOOKED. Both are recorded, because only one of them is evidence.
"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "batch_inspection"))

import omega_gate as og   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("omega gate - regression\n")
tmp = Path(tempfile.mkdtemp())


def rec(name):
    p = tmp / name
    p.write_text("x", encoding="utf-8")
    return p

# --- the default ---------------------------------------------------------
a = rec("a.csv")
check("the checkbox is unchecked by default", og.DEFAULT_CONTAINS_OMEGAS is False)
g = og.may_autocorrect(a)
check("an unasked RGBCaMP recording may be corrected automatically",
      g["allowed"] is True, "which is the workflow: crawling and reversing only")
check("...but it is marked as coming from the DEFAULT, not an assertion",
      g["from_default"] is True and g["confirmed"] is False)

# --- the same default is WRONG for data that has omegas ------------------
g2 = og.may_autocorrect(a, default_contains=True)
check("a tool whose data DOES contain omegas flips the default",
      g2["allowed"] is False,
      "the default belongs to the acquisition, not to the software")
check("...and says what would go wrong", "silently reversed" in g2["why"])
check("...offering the duration test instead",
      "one undulation period" in g2["fallback"])

# --- an answered recording ------------------------------------------------
b = rec("b.csv")
og.record(b, "contains_omegas", by="andres", frames_viewed=140)
gb = og.may_autocorrect(b)
check("a recording answered 'contains omegas' refuses auto-correction",
      gb["allowed"] is False and gb["asked"] is True)
check("...and the answer survives the default being permissive",
      og.may_autocorrect(b, default_contains=False)["allowed"] is False,
      "an assertion outranks a default in both directions")

c = rec("c.csv")
og.record(c, "no_omegas", by="mackenzie", frames_viewed=88)
gc = og.may_autocorrect(c)
check("a confirmed 'no omegas' allows correction and says who",
      gc["allowed"] and gc["confirmed"] and og.load(c)["answered_by"] == "mackenzie")
check("...recording how many frames were actually viewed",
      og.load(c)["frames_viewed"] == 88,
      "scrubbing to frame 3 and answering is not the same as scrubbing to 88")

# --- confirmed vs left at default ----------------------------------------
d = rec("d.csv")
og.record(d, "no_omegas", confirmed=False)
check("a default-derived answer is flagged as unconfirmed",
      og.load(d)["confirmed"] is False)
check("...and says the value is an assumption, not evidence",
      "nobody asserted this" in og.load(d)["confirmation_note"])
check("a deliberately-set answer says so",
      "set this deliberately" in og.load(c)["confirmation_note"])

# --- the floor ------------------------------------------------------------
check("the biological floor is one undulation period",
      og.biological_floor(5.0, 0.2) == 25.0, "25 frames at 5 fps, 0.2 Hz")
check("...and it scales with frame rate",
      og.biological_floor(30.0, 0.2) == 150.0)
try:
    og.biological_floor(None)
    check("guessing the frame rate is refused", False)
except og.OmegaGateError as exc:
    check("guessing the frame rate is refused", True)
    check("...naming that it sets the biology threshold",
          "whether an event is biology" in str(exc))

# --- refusals -------------------------------------------------------------
try:
    og.record(rec("e.csv"), "probably not")
    check("an invented answer is refused", False)
except og.OmegaGateError as exc:
    check("an invented answer is refused", True)
    check("...naming the silent reversal it would permit",
          "silently reverses real reorientations" in str(exc))

f = rec("f.csv")
og.gate_path(f).write_text("{broken", encoding="utf-8")
try:
    og.load(f)
    check("an unreadable gate file is refused", False)
except og.OmegaGateError as exc:
    check("an unreadable gate file is refused", True)
    check("...rather than being treated as an answer",
          "nobody vouched for" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("OMEGA_GATE_PASS")
