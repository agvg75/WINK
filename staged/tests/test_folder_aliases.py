"""Nicknames for folders without renaming them.

Measured on this system rather than assumed: directory symlinks are fully
transparent to Python; shortcuts are not; junctions fail on the lab drive.
The properties under test are that the catalogue is the shared truth, the view
tree is disposable, and nothing here can delete real data through a link.
"""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import folder_aliases as fa   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("folder aliases - regression\n")

tmp = Path(tempfile.mkdtemp())
data = tmp / "data"
views = tmp / "views"
for n in ("w6", "OF 1350"):
    (data / n).mkdir(parents=True)
    (data / n / "frame.tif").write_bytes(b"x" * 10)

sheet = tmp / "names.csv"
sheet.write_text(
    "path,new_name,group,note\n"
    f"{data / 'w6'},2024-03-11_N2_swim_worm6,swimming,first pass\n"
    f"{data / 'OF 1350'},2024-05-02_VC40699_crawl,crawling,\n"
    f"{data / 'w6'},,unnamed,\n", encoding="utf-8")

entries = fa.read_names_csv(sheet)
check("unnamed rows are skipped", len(entries) == 2)
check("groups and notes are read",
      entries[0]["group"] == "swimming" and entries[0]["note"] == "first pass")

ok, probs = fa.check_names(entries)
check("a clean sheet validates", len(ok) == 2 and probs == [])

bad = [{"row": 2, "real_path": str(data / "w6"), "alias": "a/b", "group": ""},
       {"row": 3, "real_path": str(data / "w6"), "alias": "trail ", "group": ""},
       {"row": 4, "real_path": str(tmp / "gone"), "alias": "x", "group": ""},
       {"row": 5, "real_path": str(data / "w6"), "alias": "dup", "group": "g"},
       {"row": 6, "real_path": str(data / "OF 1350"), "alias": "DUP",
        "group": "g"}]
_, bp = fa.check_names(bad)
kinds = {p["kind"] for p in bp}
check("illegal characters are caught", "illegal_characters" in kinds)
check("trailing spaces are caught", "trailing_space_or_dot" in kinds)
check("a missing target is caught", "target_missing" in kinds)
check("...naming that a dead link looks like a live one until opened",
      any("until it is opened" in p["why"] for p in bp))
check("duplicate aliases within a group collide", "duplicate_alias" in kinds)
check("...but the same alias in a different group is fine",
      len(fa.check_names([
          {"row": 2, "real_path": str(data / "w6"), "alias": "same",
           "group": "a"},
          {"row": 3, "real_path": str(data / "OF 1350"), "alias": "same",
           "group": "b"}])[0]) == 2,
      "one folder may appear in several groupings")

# --- the catalogue ------------------------------------------------------------
cat = fa.catalogue_from_names(ok)
check("the catalogue records the assignments", len(cat["entries"]) == 2)
again = fa.catalogue_from_names(ok, cat)
check("folding the same sheet twice adds nothing",
      len(again["entries"]) == 2, "regenerating must be idempotent")
multi = fa.catalogue_from_names(
    [{"row": 9, "real_path": str(data / "w6"), "alias": "another name",
      "group": "by_strain", "note": ""}], cat)
check("one folder may carry several nicknames",
      len(multi["entries"]) == 3,
      "which a rename cannot do")

cpath = tmp / "catalogue.json"
fa.save_catalogue(multi, cpath)
check("the catalogue round-trips",
      len(fa.load_catalogue(cpath)["entries"]) == 3)
(tmp / "bad.json").write_text("{half", encoding="utf-8")
try:
    fa.load_catalogue(tmp / "bad.json")
    check("a corrupt catalogue is refused", False)
except fa.AliasError as exc:
    check("a corrupt catalogue is refused", True)
    check("...naming that it is the one thing not reproducible from the drive",
          "not reproducible from the drive itself" in str(exc))

# --- building the view tree ---------------------------------------------------
dry = fa.build_views(multi, views)
check("nothing is created by default",
      dry["dry_run"] is True and not views.exists())
check("...but it reports what it would make", dry["n_made"] == 3)

real = fa.build_views(multi, views, dry_run=False)
check("symlinks are created", real["n_made"] == 3 and real["n_failed"] == 0,
      str(real.get("failed"))[:100])

link = views / "swimming" / "2024-03-11_N2_swim_worm6"
check("the link exists and is a symlink",
      link.is_symlink() and link.exists())
check("...and is TRANSPARENT: it lists as a directory",
      link.is_dir() and len(os.listdir(link)) == 1,
      "this is what shortcuts cannot do")
check("...and a file can be read straight through it",
      (link / "frame.tif").read_bytes() == b"x" * 10)
check("groups become folders", (views / "crawling").is_dir())
check("the real folder still has its real name",
      (data / "w6").exists() and not (data / "w6").is_symlink(),
      "nothing was renamed, so no stored path broke")

second = fa.build_views(multi, views, dry_run=False)
check("re-running skips what exists rather than failing",
      second["n_made"] == 0 and second["n_skipped"] == 3)

# --- a view tree inside the data is refused -----------------------------------
try:
    fa.build_views(multi, data, dry_run=False)
    check("building views inside the data is refused", False)
except fa.AliasError as exc:
    check("building views inside the data is refused", True)
    check("...naming both hazards",
          "surveyed as if they were" in str(exc) and
          "recursive delete" in str(exc),
          "links analysed as data, and deletes reaching the real folders")

# --- verification -------------------------------------------------------------
v = fa.verify_views(views)
check("live links are counted", v["n_live"] == 3 and v["n_dead"] == 0)
os.rename(data / "OF 1350", data / "OF 1350 moved")
v2 = fa.verify_views(views)
check("a broken link is detected", v2["n_dead"] == 1)
check("...but a disconnected drive is not assumed to be a move",
      "look identical" in v2["warning"],
      "a dead link and an unmounted share are indistinguishable")
os.rename(data / "OF 1350 moved", data / "OF 1350")

# --- removal is never recursive -----------------------------------------------
rm_dry = fa.remove_views(views, dry_run=True)
check("removal is dry by default",
      rm_dry["dry_run"] is True and link.is_symlink())
rm = fa.remove_views(views, dry_run=False)
check("links are removed", rm["n_removed"] == 3 and not link.is_symlink())
check("...and the REAL data survives untouched",
      (data / "w6" / "frame.tif").exists(),
      "a recursive delete through a symlink would have destroyed it")
check("...which is stated, not left implicit",
      "can destroy the real data" in rm["safety"])

# --- finding things by the names you gave them --------------------------------
found = fa.find(multi, "swim")
check("aliases are searchable", len(found) >= 1)
check("...and so are notes and groups",
      len(fa.find(multi, "by_strain")) == 1 and
      len(fa.find(multi, "first pass")) == 1,
      "which is the whole point of naming them")

# --- the view tree need not resemble the drive at all -----------------------
# Andres: the way the data is organised on L: may not be the best way to look
# at it. Fill structured fields in ONCE, then any arrangement is a
# regeneration rather than a re-edit.
for n in ("a1", "a2", "a3"):
    (data / n).mkdir(exist_ok=True)
rich = {"entries": [
    {"real_path": str(data / "a1"), "alias": "swim_N2_run1",
     "assay": "swimming", "strain": "N2", "year": "2024", "person": "Ella"},
    {"real_path": str(data / "a2"), "alias": "swim_VC40699_run1",
     "assay": "swimming", "strain": "VC40699", "year": "2025",
     "person": "Danny"},
    {"real_path": str(data / "a3"), "alias": "crawl_N2_run1",
     "assay": "crawling", "strain": "N2", "year": "2024", "person": "Ella"},
]}

t1 = tmp / "by_assay"
r1 = fa.build_tree(rich, t1, by=("assay", "year"), dry_run=False)
check("a tree can be grouped by assay then year", r1["n_made"] == 3)
check("...nesting in the order given",
      (t1 / "swimming" / "2024" / "swim_N2_run1").is_symlink() and
      (t1 / "crawling" / "2024" / "crawl_N2_run1").is_symlink())

t2 = tmp / "by_strain"
r2 = fa.build_tree(rich, t2, by=("strain",), dry_run=False)
check("the SAME data can carry a second, different tree at once",
      (t2 / "N2" / "swim_N2_run1").is_symlink() and
      (t2 / "VC40699" / "swim_VC40699_run1").is_symlink())
check("...and both trees are live simultaneously",
      (t1 / "swimming" / "2024" / "swim_N2_run1").exists() and
      (t2 / "N2" / "swim_N2_run1").exists(),
      "one folder, two arrangements, nothing duplicated")

t3 = tmp / "by_person"
fa.build_tree(rich, t3, by=("person", "assay"), dry_run=False)
check("a third arrangement costs a regeneration, not a re-edit",
      (t3 / "Ella" / "swimming" / "swim_N2_run1").is_symlink() and
      (t3 / "Danny" / "swimming" / "swim_VC40699_run1").is_symlink())
check("the real drive is untouched by any of it",
      (data / "a1").exists() and not (data / "a1").is_symlink())

# --- unlabelled rows are visible, not dropped --------------------------------
gappy = {"entries": rich["entries"] + [
    {"real_path": str(data / "w6"), "alias": "unlabelled_one", "assay": ""}]}
t4 = tmp / "gappy"
r4 = fa.build_tree(gappy, t4, by=("assay",), dry_run=False)
check("a row missing its grouping field still appears",
      (t4 / "_unspecified" / "unlabelled_one").is_symlink())
check("...and is counted", r4["n_incomplete"] == 1)
check("...naming that a silently-complete view is the danger",
      "looks complete and is not" in r4["incomplete_note"],
      "the unlabelled rows are the ones most in need of finding")
t5 = tmp / "strict"
r5 = fa.build_tree(gappy, t5, by=("assay",), dry_run=False, require_all=True)
check("excluding them is possible but must be asked for",
      r5["n_made"] == 3 and not (t5 / "_unspecified").exists())

# --- a field value that looks like a path does not invent nesting ------------
odd = {"entries": [{"real_path": str(data / "a1"), "alias": "x",
                    "assay": "swim/crawl mix"}]}
t6 = tmp / "odd"
fa.build_tree(odd, t6, by=("assay",), dry_run=False)
check("a slash inside a field value becomes one folder, not two",
      (t6 / "swim-crawl mix" / "x").is_symlink(),
      "otherwise a stray character silently restructures the tree")

# --- extra spreadsheet columns are carried through ---------------------------
sheet2 = tmp / "rich.csv"
sheet2.write_text(
    "path,new_name,assay,strain,year\n"
    f"{data / 'a1'},run_one,swimming,N2,2024\n", encoding="utf-8")
e2 = fa.read_names_csv(sheet2)
check("columns the module has never heard of are kept",
      e2[0]["assay"] == "swimming" and e2[0]["strain"] == "N2",
      "so the sheet can grow fields without changing the code")

print()
failed = [n for n, ok_, _ in results if not ok_]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("FOLDER_ALIASES_PASS")
