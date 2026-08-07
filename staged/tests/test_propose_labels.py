"""Proposals carry their evidence, and one fact is not counted 475 times.

Two defects found against real data are pinned here.

FIRST, INHERITED MATCHES. The first pass reported a person for 94% of folders
and it was one observation repeated: a single `L:\\02_Duchenne Muscular
Dystrophy\\Monica` parent is contained in every descendant path, so every
descendant got a proposal. Measured on the real CSV: all 475 hits at depth
index 1, the folder itself named `monica` exactly zero times, one shared
parent. A proposal inherited from an ancestor is ONE fact, must be marked as
such, and must not outrank a match on the folder being labelled.

SECOND, ALIASES. `Kiley` resolves to two authority rows, Hughes K and
Hughes-Wiles K, which the authority Read me sheet documents as ONE person.
Reporting that as "2 people share this surname" contradicts the source.

Also pins the rule that costs the most if it breaks quietly: a bare four or
five digit number is a date, never an allele. On this drive `41921` is
19 April 2021.
"""
from pathlib import Path
import csv
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools" / "drive_audit")]

import propose_labels as pl   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("drive audit proposals\n")

# --- normalisation ------------------------------------------------------------
check("umlauts fold to the ASCII stem the Read me asks for",
      pl.token_key("Gährs") == pl.token_key("Gaehrs") == "gaehrs",
      "citations use umlauts, Windows paths mangle them")
check("...and Staedele likewise",
      pl.token_key("Städele") == pl.token_key("Staedele"))
check("accents are stripped without folding",
      pl.token_key("Mónica") == "monica",
      "an accented given name must still match the folder")

# --- scope: the defect that made 94% coverage meaningless ---------------------
segments = ["02_Duchenne Muscular Dystrophy", "Monica", "dys-1 zw w10 4_27"]
own = pl.scope_of(segments, 2)
inherited = pl.scope_of(segments, 1)
check("a match on the folder itself is scope 0",
      own["match_scope"] == "folder" and own["scope_rank"] == 0)
check("a match on the parent is marked inherited",
      inherited["match_scope"] == "ancestor-1" and
      inherited["scope_rank"] == 1)
check("...and names the ancestor that produced it",
      inherited["evidence_group"].endswith("Monica"),
      "so 475 descendants can be accepted as one decision")
check("inherited matches rank below folder matches",
      inherited["scope_rank"] > own["scope_rank"],
      "an exact hit on a grandparent is weaker evidence about THIS folder "
      "than a fuzzy hit on the folder itself")

# --- a bare number is a date, never an allele --------------------------------
row = {"path": r"L:\05_Proprioception\pezo\41921_cop1367", "folder": "x",
       "area": "05"}
segs = pl.path_segments(row["path"])
years = pl.propose_years(row, segs)
strains = pl.propose_strains(row, segs, [])
check("a bare 5-digit number proposes a YEAR",
      any(p["proposed_value"] == "2021" for p in years),
      "41921 is 19 April 2021")
check("...and never proposes a strain",
      not any(p["matched_token"] == "41921" for p in strains),
      "dates and allele numbers are the same shape")
check("a letter-prefixed designation DOES propose a strain",
      any(p["matched_token"] == "cop1367" for p in strains))
check("bare digits are refused by the strain pattern",
      not pl.STRAIN_RE.match("41921") and bool(pl.STRAIN_RE.match("cop1367")))

# --- the person-shaped folder is filtered ------------------------------------
by_initial = {}
for junk in ("DEFL", "DMSO", "People", "deepcutprotraining"):
    r = {"path": rf"L:\02_Duchenne Muscular Dystrophy\{junk}\w1", "folder": "w1",
         "area": "02"}
    got = pl.propose_given_names(r, pl.path_segments(r["path"]), by_initial)
    check(f"{junk!r} is not proposed as a person", not got,
          "conditions, constructs and software are not students")
r = {"path": r"L:\02_Duchenne Muscular Dystrophy\Danny\w1", "folder": "w1",
     "area": "02"}
check("a real-looking given name still is",
      len(pl.propose_given_names(r, pl.path_segments(r["path"]),
                                 by_initial)) == 1)

# --- aliases collapse, genuine ambiguity does not ----------------------------
hughes = [{"surname": "Hughes", "initials": "K", "first_year": "2018",
           "last_year": "2022", "project_codes": "DMD_WORM"},
          {"surname": "Hughes-Wiles", "initials": "K", "first_year": "2022",
           "last_year": "2025", "project_codes": "PEZO"}]
gomez = [{"surname": "Gomez", "initials": "L", "first_year": "2024",
          "last_year": "2024", "project_codes": "THERMO"},
         {"surname": "Gomez", "initials": "M", "first_year": "2025",
          "last_year": "2025", "project_codes": "DMD_STEROID"}]
p = pl._person_proposal(row, hughes, "kiley", "Kiley", "Kiley",
                        "person_surname_exact", "given name")
check("two spellings of one person collapse to one value",
      "|" not in p["proposed_value"], p["proposed_value"])
check("...and say why", "same person" in p["ambiguity"])
check("...saying it once, not once per alias",
      p["ambiguity"].count("same person") == 1)
p = pl._person_proposal(row, gomez, "gomez", "Gomez", "Gomez",
                        "person_surname_exact", "surname")
check("two genuinely different people do NOT collapse",
      "|" in p["proposed_value"], p["proposed_value"])
check("...and are flagged as unresolved",
      "different people" in p["ambiguity"])

# --- the Owoyemi row must not assert twins -----------------------------------
note = pl.AMBIGUITY_NOTES["owoyemi"]
check("the Owoyemi note records the site's single Taiyelolu",
      "Taiyelolu" in note)
check("...and does NOT assert twins",
      "twin" not in note.lower() and "Kehinde" not in note,
      "that was an inference from two initials, not knowledge")
check("...marking the second row unconfirmed", "UNCONFIRMED" in note)

# --- the input is never written to -------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="wink_props_"))
try:
    labels = tmp / "LABEL_ME.csv"
    fields = ["path", "folder", "parent", "area", "new_name", "assay",
              "strain", "year", "person"]
    with open(labels, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerow({"path": r"L:\02_Duchenne Muscular Dystrophy\Monica"
                                 r"\dys-1 zw w10 4_27_21",
                         "folder": "dys-1 zw w10 4_27_21",
                         "parent": "Monica", "area": "02"})
    before = labels.read_bytes()
    out = tmp / "proposals.csv"
    # Needs a real workbook. Where one is not on this machine the check is
    # SKIPPED rather than asserted as true - a check that cannot run must not
    # report a pass, which is what an earlier draft of this file did.
    authority = next(
        (p for p in (ROOT.parent / "_session_archive" / "lab_name_authority.xlsx",
                     ROOT / "tools" / "drive_audit" / "lab_name_authority.xlsx",
                     Path.home() / "Downloads" / "code files"
                     / "lab_name_authority.xlsx")
         if p.exists()), None)
    if authority is None:
        print("  SKIP  no authority workbook on this machine; the "
              "never-writes-input check needs one")
    else:
        rows, proposals = pl.run(labels, authority, out)
        check("a run produces proposals", len(proposals) > 0,
              f"{len(proposals)} from {len(rows)} folder(s)")
        check("the label CSV is byte-identical after a full run",
              labels.read_bytes() == before,
              "a file that silently acquires 551 guesses is worse than a "
              "blank one")
        check("...and the proposals went to the separate file",
              out.exists() and out.stat().st_size > 0)
        written = list(csv.DictReader(open(out, encoding="utf-8")))
        check("every proposal carries its evidence",
              all(r["matched_token"] and r["source_table"] and r["confidence"]
                  for r in written),
              "token, table and tier on every row")
        check("every proposal declares its scope",
              all(r["match_scope"] for r in written))
        inherited = [r for r in written if r["scope_rank"] != "0"]
        check("the Monica proposal is marked inherited, not a folder match",
              any(r["matched_token"] == "Monica" and
                  r["evidence_group"].endswith("Monica") for r in inherited),
              "one parent, one fact")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- tier order follows the authority, not this parser -----------------------
check("a strain match outranks a project token",
      pl.TIERS["strain_exact"] < pl.TIERS["project_token_exact"])
check("...a project token outranks a person",
      pl.TIERS["project_token_exact"] < pl.TIERS["person_surname_exact"])
check("...and exact outranks fuzzy within each kind",
      pl.TIERS["project_token_exact"] < pl.TIERS["project_token_fuzzy"] and
      pl.TIERS["person_surname_exact"] < pl.TIERS["person_surname_fuzzy"],
      "the Read me sets the person/project/strain order; exact-over-fuzzy "
      "is this parser's")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PROPOSE_LABELS_PASS")
