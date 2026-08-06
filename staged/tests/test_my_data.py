"""Each person sees their own data; the lab lead sees all of it.

The property that matters is the failure mode: when nobody has signed in, this
must show NOTHING rather than everything. Showing one student another's
folders because a field was blank is the error worth engineering against.
"""
from pathlib import Path
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

tmp = Path(tempfile.mkdtemp())
os.environ["WINK_OPERATOR"] = str(tmp / "operator.json")

import my_data as md            # noqa: E402
import operator_identity as oi  # noqa: E402
oi.STORE = tmp / "operator.json"

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("my data - regression\n")

CAT = {"entries": [
    {"real_path": "L:/a", "alias": "swim_run1", "person": "Ella",
     "assay": "swimming", "year": "2024"},
    {"real_path": "L:/b", "alias": "crawl_run1", "person": "Ella",
     "assay": "crawling", "year": "2025"},
    {"real_path": "L:/c", "alias": "mtx_run1", "person": "Danny",
     "assay": "magnetotaxis", "year": "2024"},
    {"real_path": "L:/d", "alias": "orphan", "person": "",
     "assay": "", "year": ""},
]}

# --- nobody signed in --------------------------------------------------------
oi.clear()
nobody = md.current_person()
shown, scope = md.entries_for(CAT, nobody)
check("with nobody signed in, NOTHING is shown", shown == [])
check("...and it says why rather than failing silently",
      scope["shown"] == "nothing")
check("...naming that showing the wrong person's data is the worse error",
      "worse than showing nothing" in scope["why"])

# --- a student sees their own ------------------------------------------------
oi.save("EK", "Ella Kim")
ella = md.current_person()
mine, scope2 = md.entries_for(CAT, ella)
check("a student sees only their own folders",
      {e["alias"] for e in mine} == {"swim_run1", "crawl_run1"},
      "matched on first name")
check("...and not a colleague's",
      all(e["person"] == "Ella" for e in mine))
check("...and unattributed folders are counted, not shown",
      scope2["unattributed"] == 1,
      "an orphan folder belongs to nobody until somebody claims it")

# --- the lab lead sees everything --------------------------------------------
oi.save("AVG", "Andres Vidal-Gadea")
lead = md.current_person()
allrows, scope3 = md.entries_for(CAT, lead)
check("the lab lead sees the whole lab", len(allrows) == 4)
check("...including the unattributed folders",
      any(e["alias"] == "orphan" for e in allrows),
      "somebody has to be able to see what nobody claimed")
check("...and it says so", scope3["shown"] == "everything")
check("who sees everything is a SETTING, not a hard-coded name",
      md.sees_everything({"initials": "ZZ"}, lead_initials=("ZZ",)) is True and
      md.sees_everything({"initials": "ZZ"}) is False,
      "a name in the code stops working the day somebody else runs the lab")

# --- the arrangement is personal --------------------------------------------
by_assay = md.arrange(allrows, by=("assay",))
check("data can be arranged by assay",
      "swimming" in by_assay and "magnetotaxis" in by_assay)
by_year = md.arrange(allrows, by=("year", "assay"))
check("...or by year then assay, from the same rows",
      "2024" in by_year and "swimming" in by_year["2024"],
      "two people can arrange the same experiments differently at once")
check("unlabelled rows get a visible bucket, not silent omission",
      "(unlabelled)" in md.arrange(allrows, by=("assay",)))
check("arranging moves nothing on disk",
      allrows[0]["real_path"] == "L:/a",
      "it is purely a view")

# --- the summary a person reads at a glance ----------------------------------
s = md.summarise(allrows)
check("the summary counts folders, assays and people",
      s["n"] == 4 and s["n_people"] == 2)
check("...and says how many are still unlabelled", s["n_unlabelled"] == 1)
check("an empty catalogue says so plainly",
      md.summarise([])["text"] == "Nothing catalogued yet.")

# --- opening a folder --------------------------------------------------------
try:
    md.open_in_explorer(tmp / "not_there")
    check("opening a missing folder is refused", False)
except md.MyDataError as exc:
    check("opening a missing folder is refused", True)
    check("...naming that a disconnected drive looks identical",
          "drive is disconnected" in str(exc),
          "check the drive before concluding anything is lost")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MY_DATA_PASS")
