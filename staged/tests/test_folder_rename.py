"""Renaming a decade of research folders, reversibly.

The property under test is that the LEDGER is trustworthy, not that rename
works - os.rename works. What makes this safe is that every rename is checked
before it happens, recorded as it happens, and reversible from the record
alone; and that a path written down years ago still resolves afterwards.
"""
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import folder_rename as fr   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("folder rename - regression\n")

tmp = Path(tempfile.mkdtemp())
LEDGER = tmp / "ledger.json"
for n in ("w6", "w2", "OF 1350", "keepme"):
    (tmp / n).mkdir()
    (tmp / n / "data.tif").write_bytes(b"x")
(tmp / "w6" / "deep").mkdir()
(tmp / "w6" / "deep" / "inner.csv").write_text("a\n", encoding="utf-8")

sheet = tmp / "plan.csv"
sheet.write_text(
    "path,new_name,note\n"
    f"{tmp / 'w6'},2024-03-11_N2_swim_worm6,first\n"
    f"{tmp / 'w2'},2024-03-11_N2_swim_worm2,\n"
    f"{tmp / 'keepme'},,leave alone\n", encoding="utf-8")

plan = fr.read_plan(sheet)
check("blank new names are skipped quietly", len(plan) == 2,
      "most rows in a 1200-row sheet will be blank")
check("notes are carried through", plan[0]["note"] == "first")

ok, problems = fr.check_plan(plan)
check("a clean plan validates", len(ok) == 2 and problems == [])

# --- everything checkable is checked BEFORE touching the disk ---------------
bad = [
    {"row": 2, "old_path": str(tmp / "w6"), "new_name": "has/slash"},
    {"row": 3, "old_path": str(tmp / "w6"), "new_name": "CON"},
    {"row": 4, "old_path": str(tmp / "w6"), "new_name": "trailing "},
    {"row": 5, "old_path": str(tmp / "nope"), "new_name": "fine"},
    {"row": 6, "old_path": str(tmp / "w2"), "new_name": "keepme"},
]
ok2, probs = fr.check_plan(bad)
kinds = {p["kind"] for p in probs}
check("illegal characters are caught", "illegal_characters" in kinds)
check("reserved device names are caught", "reserved_name" in kinds)
check("trailing spaces are caught", "trailing_space_or_dot" in kinds)
check("...naming that Windows strips them silently",
      any("silently strips" in p["why"] for p in probs),
      "the ledger would then disagree with the disk")
check("a missing source is caught", "source_missing" in kinds)
check("...suggesting the ledger before blaming the sheet",
      any("check the ledger" in p["why"] for p in probs))
check("an occupied target is caught", "target_exists" in kinds)
check("nothing survives validation from a bad plan", ok2 == [])

dupes = [{"row": 2, "old_path": str(tmp / "w6"), "new_name": "same"},
         {"row": 3, "old_path": str(tmp / "w2"), "new_name": "SAME"}]
_, dp = fr.check_plan(dupes)
check("two rows targeting the same name collide",
      any(p["kind"] == "duplicate_target" for p in dp))
check("...case-insensitively, as Windows does",
      any("case-insensitively" in p["why"] for p in dp),
      "'same' and 'SAME' are one folder")

long_plan = [{"row": 2, "old_path": str(tmp / "w6"), "new_name": "x" * 200}]
_, lp = fr.check_plan(long_plan, deepest_child_len=120)
check("a name that would push deep files past MAX_PATH is caught",
      any(p["kind"] == "path_too_long" for p in lp))
check("...naming that the rename appears to work while files become unopenable",
      any("unopenable by ordinary tools" in p["why"] for p in lp))

# --- dry run is the default --------------------------------------------------
dry = fr.apply(ok, LEDGER)
check("apply does nothing by default", dry["dry_run"] is True
      and (tmp / "w6").exists())
check("...but reports exactly what it would do", dry["n_done"] == 2)
check("...and says how to actually do it", "dry_run=False" in dry["note"])
check("a dry run writes no ledger", not LEDGER.exists())

# --- the real thing ----------------------------------------------------------
res = fr.apply(ok, LEDGER, dry_run=False, note="2026 renaming pass")
check("folders are renamed", res["n_done"] == 2 and res["n_failed"] == 0)
check("...and the new names exist",
      (tmp / "2024-03-11_N2_swim_worm6").exists())
check("...and the old ones do not", not (tmp / "w6").exists())
check("each rename is verified after the fact",
      all(r.get("verified") for r in res["done"]))
check("untouched folders are untouched", (tmp / "keepme").exists())
check("the ledger is written", LEDGER.exists())

# --- a path written down years ago still resolves ---------------------------
r1 = fr.resolve(str(tmp / "w6"), LEDGER)
check("an old folder path resolves to its current location",
      r1["moved"] is True and r1["exists_now"] is True)
r2 = fr.resolve(str(tmp / "w6" / "deep" / "inner.csv"), LEDGER)
check("a path INSIDE a renamed folder resolves too",
      r2["current"].endswith("inner.csv") and "2024-03-11" in r2["current"],
      "this is what a stored analysis path looks like")
check("...and the file is really there", Path(r2["current"]).exists())
r3 = fr.resolve(str(tmp / "keepme"), LEDGER)
check("an unrenamed path resolves to itself", r3["moved"] is False)
check("...and says why nothing was found", "never renamed" in r3["why"])

# --- renamed twice ------------------------------------------------------------
second = [{"row": 9, "old_path": str(tmp / "2024-03-11_N2_swim_worm6"),
           "new_name": "FINAL_worm6"}]
ok3, _ = fr.check_plan(second)
fr.apply(ok3, LEDGER, dry_run=False)
r4 = fr.resolve(str(tmp / "w6"), LEDGER)
check("a chain of renames is followed to the end",
      r4["current"].endswith("FINAL_worm6") and len(r4["chain"]) == 2,
      "the original path still finds it after two renames")

# --- undo ---------------------------------------------------------------------
u_dry = fr.undo(LEDGER, dry_run=True)
check("undo is also dry by default",
      u_dry["dry_run"] is True and (tmp / "FINAL_worm6").exists())
u = fr.undo(LEDGER, rows=[9], dry_run=False)
check("a single row can be undone", u["n_reverted"] == 1)
check("...putting the previous name back",
      (tmp / "2024-03-11_N2_swim_worm6").exists())
r5 = fr.resolve(str(tmp / "w6"), LEDGER)
check("the undo is itself recorded, so resolve stays correct",
      r5["current"].endswith("2024-03-11_N2_swim_worm6"),
      "a ledger that forgets its reversals resolves to the wrong folder")

# --- the crosswalk ------------------------------------------------------------
cw = fr.write_crosswalk(LEDGER, tmp / "crosswalk.csv")
text = Path(cw).read_text(encoding="utf-8")
check("a flat crosswalk is exported", "old_path,new_path" in text)
check("...including undos, marked as such", "True" in text)

# --- the ledger is treated as irreplaceable ----------------------------------
(tmp / "broken.json").write_text("{half", encoding="utf-8")
try:
    fr.load_ledger(tmp / "broken.json")
    check("an unreadable ledger is refused", False)
except fr.RenameError as exc:
    check("an unreadable ledger is refused", True)
    check("...naming that it is the ONLY link between old and new",
          "ONLY record" in str(exc) and "no rename" in str(exc),
          "without it a renamed folder cannot be found from a written path")
check("a missing ledger is an empty one, not an error",
      fr.load_ledger(tmp / "nothing.json")["renames"] == [])

try:
    fr.read_plan(sheet, old_col="nope")
    check("a sheet without the path column is refused", False)
except fr.RenameError as exc:
    check("a sheet without the path column is refused", True)
    check("...naming that folder names repeat on this drive",
          "wherever a name repeats" in str(exc),
          "w2 and w6 appear under several people")

print()
failed = [n for n, ok_, _ in results if not ok_]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FOLDER_RENAME_PASS")
