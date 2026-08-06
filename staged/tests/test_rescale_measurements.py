"""Correcting measurements written at the wrong scale.

Backlog #17: a 904 px confocal bar printed "49.2 um" was read as 1.0 mm,
giving 1.10619 um/px instead of 0.05442 - a factor of 20.3.

The property under test is that each column scales by ITS OWN power and an
unrecognised column is left alone. Scaling an area by the length factor, or
guessing at a column whose units are unclear, produces a corrected file that
is worse than the original and looks authoritative.
"""
from pathlib import Path
import csv
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import rescale_measurements as rs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("rescale measurements - regression\n")

K = rs.RIGHT_UM_PX / rs.WRONG_UM_PX

# --- the powers --------------------------------------------------------------
check("a length scales by k", rs.power_for("feret_um") == 1)
check("an area scales by k squared", rs.power_for("area_um2") == 2)
check("a per-length density scales by 1/k",
      rs.power_for("serial_density_per_um") == -1)
check("a per-area density scales by 1/k squared",
      rs.power_for("sarc_density_per_um2") == -2)
check("'_per_um2' is not mistaken for '_um2'",
      rs.power_for("sarc_density_per_um2") == -2,
      "the longest suffix must be tested first")
check("pixel columns do not change", rs.power_for("area_px2") == 0
      and rs.power_for("feret_px") == 0,
      "pixel geometry does not depend on the scale - which is why no "
      "re-measurement is needed")
check("ratios do not change",
      all(rs.power_for(c) == 0 for c in
          ("aspect_ratio", "circularity", "solidity", "anisotropy")))
check("counts do not change", rs.power_for("sarc_number") == 0)
check("angles do not change", rs.power_for("feret_angle_deg") == 0,
      "scaling an angle would silently rotate the result")
check("the scale column is replaced, not multiplied",
      rs.power_for("um_px") == "scale")
check("an unfamiliar column is NOT guessed at",
      rs.power_for("mystery_value") is None)

# --- the plan ----------------------------------------------------------------
cols = ["myocyte_id", "um_px", "area_px2", "feret_px", "area_um2", "feret_um",
        "aspect_ratio", "sarc_density_per_um2", "serial_density_per_um",
        "feret_angle_deg", "sarc_number", "mystery_value"]
p = rs.plan(cols)
check("the factor is the ratio of the scales",
      abs(p["factor"] - K) < 1e-12, f"{p['factor']:.5f}")
check("...and it says the originals were 20x too large",
      "20.3x too large" in p["why"], p["why"][-30:])
check("areas get the squared factor",
      abs(p["scaled"]["area_um2"] - K ** 2) < 1e-15)
check("densities get the inverse factor",
      abs(p["scaled"]["sarc_density_per_um2"] - K ** -2) < 1e-9)
check("unknown columns are listed for a human",
      p["unknown"] == ["mystery_value"])
check("...and the note says they are copied unchanged",
      "COPIED UNCHANGED" in p["unknown_note"])
check("...naming that guessing makes it worse than the original",
      "worse than the original" in p["unknown_note"])

# --- a real file --------------------------------------------------------------
tmp = Path(tempfile.mkdtemp())
src = tmp / "myocytes.csv"
with src.open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=cols)
    w.writeheader()
    for i in (1, 2):
        w.writerow({"myocyte_id": i, "um_px": rs.WRONG_UM_PX,
                    "area_px2": 40000, "feret_px": 300,
                    "area_um2": 40000 * rs.WRONG_UM_PX ** 2,
                    "feret_um": 300 * rs.WRONG_UM_PX,
                    "aspect_ratio": 3.2, "sarc_density_per_um2": 0.004,
                    "serial_density_per_um": 0.5, "feret_angle_deg": 41.0,
                    "sarc_number": 12, "mystery_value": 7})

dry = rs.rescale_csv(src, dry_run=True)
check("a dry run writes nothing",
      not Path(dry["dest"]).exists() and dry["dry_run"] is True)

res = rs.rescale_csv(src, dry_run=False, note="backlog #17")
out = list(csv.DictReader(Path(res["dest"]).open(encoding="utf-8-sig")))

check("the original file is untouched",
      list(csv.DictReader(src.open(encoding="utf-8-sig")))[0]["feret_um"]
      == str(300 * rs.WRONG_UM_PX))
check("a corrected copy is written alongside", Path(res["dest"]).exists())

row = out[0]
check("length is now the pixel value times the CORRECT scale",
      abs(float(row["feret_um"]) - 300 * rs.RIGHT_UM_PX) < 1e-6,
      f"{row['feret_um']} vs {300 * rs.RIGHT_UM_PX:.6g}")
check("area is now the pixel area times the correct scale SQUARED",
      abs(float(row["area_um2"]) - 40000 * rs.RIGHT_UM_PX ** 2) < 1e-6,
      "this is the one that goes wrong if every column gets the same factor")
check("pixel geometry is unchanged",
      float(row["area_px2"]) == 40000 and float(row["feret_px"]) == 300,
      "the outlines somebody drew are still exactly right")
check("ratios are unchanged", float(row["aspect_ratio"]) == 3.2)
check("counts are unchanged", float(row["sarc_number"]) == 12)
check("angles are unchanged", float(row["feret_angle_deg"]) == 41.0)
check("the recorded scale is replaced with the correct one",
      abs(float(row["um_px"]) - rs.RIGHT_UM_PX) < 1e-12)
check("an unrecognised column is copied verbatim",
      row["mystery_value"] == "7")
check("the correction is stamped into the DATA, not only a sidecar",
      row["rescaled_from_um_px"].startswith("1.10619") and
      abs(float(row["rescaled_to_um_px"]) - rs.RIGHT_UM_PX) < 1e-12,
      "a corrected file that loses provenance is mistaken for an original")
check("...including the note", row.get("rescaled_note") == "backlog #17")

# --- round trip ---------------------------------------------------------------
back = rs.rescale_csv(res["dest"], tmp / "back.csv", dry_run=False,
                      wrong_um_px=rs.RIGHT_UM_PX, right_um_px=rs.WRONG_UM_PX)
r2 = list(csv.DictReader(Path(back["dest"]).open(encoding="utf-8-sig")))[0]
check("correcting back recovers the original numbers",
      abs(float(r2["area_um2"]) - 40000 * rs.WRONG_UM_PX ** 2) < 1e-6,
      "the transform is exactly invertible, so a mistaken direction is fixable")

# --- screening: a scale ALONE cannot diagnose this ---------------------------
# I first screened against the morphometry's 0.8-6.0 band, assuming it was a
# band for the scale. It is not - that band applies to sarcomere LENGTH, and
# the bad value 1.10619 um/px sits comfortably inside it. Screening scales
# that way would have passed the very error this module corrects.
alone = rs.looks_miscalibrated(1.10619)
check("the bad scale alone is NOT diagnosable",
      alone["suspicious"] is False and alone["basis"] == "indeterminate",
      "1.1 um/px is an ordinary plate calibration")
check("...and it says why rather than passing silently",
      "nothing about the number distinguishes those" in alone["why"])

as_confocal = rs.looks_miscalibrated(1.10619, "confocal")
check("the same scale IS wrong for confocal imaging",
      as_confocal["suspicious"] is True and
      as_confocal["basis"] == "modality_mismatch")
check("...naming the um-read-as-mm mechanism",
      "read as mm" in as_confocal["why"])
check("the same scale is fine for a plate rig",
      rs.looks_miscalibrated(1.10619, "plate")["suspicious"] is False,
      "which is exactly why the number alone is not evidence")
check("a correct confocal scale passes",
      rs.looks_miscalibrated(0.05442, "confocal")["suspicious"] is False)

by_biology = rs.looks_miscalibrated(1.10619, sarcomere_um=38.0)
check("a sarcomere length outside its biological range IS diagnostic",
      by_biology["suspicious"] is True and
      by_biology["basis"] == "sarcomere_length",
      "this is what actually caught the original error")
check("...and says a measurement beats a plausible-looking scale",
      "plausible-looking scale is not" in by_biology["why"])
check("a normal sarcomere length raises nothing",
      rs.looks_miscalibrated(0.05442, sarcomere_um=1.6)["suspicious"] is False)

check("a non-numeric scale is suspicious rather than crashing",
      rs.looks_miscalibrated("n/a")["suspicious"] is True)
try:
    rs.looks_miscalibrated(1.0, "electron_microscope")
    check("an unknown modality is refused", False)
except rs.RescaleError as exc:
    check("an unknown modality is refused", True)
    check("...naming that the band decides error versus routine",
          "an error or routine" in str(exc))

# --- refusals -----------------------------------------------------------------
try:
    rs.plan(cols, wrong_um_px=0, right_um_px=1)
    check("a missing scale is refused", False)
except rs.RescaleError as exc:
    check("a missing scale is refused", True)
    check("...naming that guessing produces false precision",
          "look precise and are not" in str(exc))
empty = tmp / "empty.csv"
empty.write_text("a,b\n", encoding="utf-8")
try:
    rs.rescale_csv(empty, dry_run=False)
    check("an empty file is refused", False)
except rs.RescaleError as exc:
    check("an empty file is refused", True)
    check("...naming that it would look like a successful correction",
          "correction of nothing" in str(exc))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("RESCALE_MEASUREMENTS_PASS")
