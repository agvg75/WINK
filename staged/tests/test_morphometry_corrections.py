"""Regression tests for app/morphometry_corrections.py."""
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import morphometry_corrections as mc

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("morphometry_corrections - regression\n")

# ---------------------------------------------------------------------------
# agreement_summary: matched / missed / spurious, by construction (known
# ground truth built into the fixture, not asserted against itself).
# ---------------------------------------------------------------------------
# auto found peaks at 10, 40, 90 (90 is a false positive); human found
# 10, 40, 65 (65 is a real band the detector missed). Tolerance 3px.
auto = [10, 40, 90]
human = [10, 40, 65]
summary = mc.agreement_summary(auto, human, tolerance_px=3)
check("agreement_summary: matched counts the two peaks both agree on",
      summary["matched"] == 2, summary)
check("agreement_summary: missed counts the human peak the detector skipped",
      summary["missed"] == 1, summary)
check("agreement_summary: spurious counts the auto peak with no human match",
      summary["spurious"] == 1, summary)
check("agreement_summary: n_auto_peaks/n_human_peaks reflect the raw counts",
      summary["n_auto_peaks"] == 3 and summary["n_human_peaks"] == 3, summary)

perfect = mc.agreement_summary([5, 15, 25], [5.5, 14.8, 25.2], tolerance_px=1)
check("agreement_summary: near-exact agreement within tolerance is all matched",
      perfect["matched"] == 3 and perfect["missed"] == 0
      and perfect["spurious"] == 0, perfect)

empty_auto = mc.agreement_summary([], [10, 20], tolerance_px=3)
check("agreement_summary: no auto peaks means every human peak is missed",
      empty_auto["missed"] == 2 and empty_auto["matched"] == 0, empty_auto)

# a tie: two auto peaks close to the same single human peak should match
# only one of them (greedy nearest, no double-counting a human peak)
tie = mc.agreement_summary([10, 11], [10.5], tolerance_px=3)
check("agreement_summary: one human peak cannot be matched twice",
      tie["matched"] == 1 and tie["spurious"] == 1, tie)

# ---------------------------------------------------------------------------
# HumanCorrection.validate: rejects an unknown correction_type
# ---------------------------------------------------------------------------
try:
    mc.HumanCorrection(peak_positions_px=[1, 2], correction_type="BOGUS").validate()
    check("HumanCorrection.validate rejects an unrecognized correction_type",
          False)
except ValueError:
    check("HumanCorrection.validate rejects an unrecognized correction_type",
          True)
check("HumanCorrection.validate accepts a real correction_type",
      mc.HumanCorrection(peak_positions_px=[1], correction_type="EDITED")
      .validate().correction_type == "EDITED")

# ---------------------------------------------------------------------------
# CorrectionLog: record() writes a well-formed JSONL entry; read_all()
# round-trips it; the record is joinable back to a results-CSV row via
# myocyte_id, and the raw profile stored is exactly what was passed in
# (not the auto-detected simplification of it).
# ---------------------------------------------------------------------------
tmp_dir = Path(tempfile.mkdtemp())
try:
    log = mc.CorrectionLog(root=tmp_dir)
    detector = mc.DetectorOutput(
        peak_positions_px=[10, 40, 90], estimated_period_px=30.0,
        min_spacing_px=18.0, relative_bounds=(18.0, 45.0))
    human = mc.HumanCorrection(peak_positions_px=[10, 40, 65],
                                correction_type="EDITED")
    raw_profile = [float(i % 7) for i in range(50)]
    path = log.record(
        myocyte_id=3, worm_id="42", genotype="dys-1(eg33)", day=5,
        region="midbody", raw_profile=raw_profile,
        line_x1=100.0, line_y1=200.0, line_x2=140.0, line_y2=200.0,
        line_width_px=15, um_per_px=0.05319, detector=detector, human=human,
        student_id="test_student", note="unit test")
    check("CorrectionLog.record writes a file", path.exists())

    rows = log.read_all()
    check("CorrectionLog.read_all returns exactly the one record written",
          len(rows) == 1, len(rows))
    row = rows[0]
    check("record: myocyte_id round-trips (joinable to the results CSV row)",
          row["myocyte_id"] == 3, row["myocyte_id"])
    check("record: raw_profile is stored exactly, not the auto-detected "
          "simplification of it",
          row["raw_profile"] == raw_profile)
    check("record: auto peak positions round-trip",
          row["auto"]["peak_positions_px"] == [10.0, 40.0, 90.0])
    check("record: human correction_type round-trips",
          row["human"]["correction_type"] == "EDITED")
    check("record: agreement summary was computed and stored",
          row["agreement"]["matched"] == 2 and row["agreement"]["missed"] == 1
          and row["agreement"]["spurious"] == 1, row["agreement"])
    check("record: line endpoints and calibration are stored for traceability",
          row["line_endpoints_px"]["x1"] == 100.0
          and row["um_per_px"] == 0.05319)

    # a second record on the same day appends to the SAME file rather than
    # overwriting - append-only, one object per line
    detector2 = mc.DetectorOutput(
        peak_positions_px=[5, 15], estimated_period_px=10.0,
        min_spacing_px=6.0, relative_bounds=(6.0, 15.0))
    human2 = mc.HumanCorrection(peak_positions_px=[5, 15, 25],
                                 correction_type="MANUAL_RECOUNT")
    log.record(
        myocyte_id=4, worm_id="42", genotype="dys-1(eg33)", day=5,
        region="midbody", raw_profile=[1.0, 2.0, 3.0],
        line_x1=0, line_y1=0, line_x2=30, line_y2=0, line_width_px=15,
        um_per_px=0.05319, detector=detector2, human=human2)
    rows2 = log.read_all()
    check("a second same-day record is appended, not overwritten",
          len(rows2) == 2, len(rows2))
finally:
    shutil.rmtree(tmp_dir, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MORPHOMETRY_CORRECTIONS_REGRESSION_PASS")
