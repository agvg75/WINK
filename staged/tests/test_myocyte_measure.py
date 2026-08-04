"""Regression tests for per-cell measurement from reviewed boundaries.

Built on a SYNTHETIC field with known cell geometry, so the measurements have
an answer to be checked against rather than merely being self-consistent.
"""
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import myocyte_review_state as mrs      # noqa: E402
import myocyte_measure as mm            # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


UM = 0.1
H, W = 300, 1000                      # 30 x 100 um
tissue = np.zeros((H, W), bool)
tissue[40:260, 20:980] = True         # 22 x 96 um of tissue

# three horizontal boundaries at y = 100, 160, 220 px -> four bands
BOUNDS = (100, 160, 220)


def build(statuses=("accepted",) * 3, accept=True):
    st = mrs.MyocyteReviewState((H, W), UM, "synthetic", "s", "midbody", "t")
    st.add_proposals([(f"seam_{i}", [(0, y), (500, y), (999, y)])
                      for i, y in enumerate(BOUNDS)])
    for i, s in enumerate(statuses):
        if s == "accepted":
            st.apply_intent(mrs.AcceptBoundary(boundary_id=f"seam_{i}"))
        else:
            st.apply_intent(mrs.RejectBoundary(boundary_id=f"seam_{i}",
                                               reason="no_boundary_here"))
    if accept:
        st.apply_intent(mrs.AcceptReview())
    return st


print("myocyte measurement - regression\n")

# --- refuses an unreviewed field ------------------------------------------
st = build(accept=False)
try:
    mm.cells_from_boundaries(st, tissue)
    check("an unaccepted review is refused", False)
except mm.MeasurementError as exc:
    check("an unaccepted review is refused", True)
    check("...and names what would go wrong",
          "nothing distinguishes them from measurements" in str(exc))

# --- cells are the faces between boundaries -------------------------------
st = build()
labels, n, used = mm.cells_from_boundaries(st, tissue)
check("three boundaries across the tissue give four cells", n == 4,
      f"{n} cells from {len(used)} boundaries")

rows = mm.measure_cells(labels, UM)
areas = sorted(r["area_um2"] for r in rows)
# middle bands are 60 px = 6 um tall, 960 px = 96 um wide -> ~576 um2
check("cell area matches the known geometry",
      any(abs(a - 576) < 40 for a in areas),
      f"areas {areas}")
check("cells are elongated along the body axis",
      all(r["orientation_deg"] < 10 or r["orientation_deg"] > 170 for r in rows),
      f"{[r['orientation_deg'] for r in rows]}")
check("length is the long axis, width the short one",
      all(r["length_um"] > r["width_um"] for r in rows))
check("aspect ratio reflects a long thin cell",
      all(r["aspect_ratio"] > 3 for r in rows),
      f"{[r['aspect_ratio'] for r in rows]}")

# --- a REJECTED boundary must not divide anything -------------------------
st2 = build(statuses=("accepted", "rejected", "accepted"))
labels2, n2, used2 = mm.cells_from_boundaries(st2, tissue)
check("a rejected boundary does not create a cell division", n2 == 3,
      f"{n2} cells with the middle boundary rejected")
check("...and it is absent from the boundaries used",
      "seam_1" not in used2)

# --- a missed boundary shows up as a merged cell, and is flagged ----------
rows2 = mm.measure_cells(labels2, UM)
merged = max(rows2, key=lambda r: r["area_um2"])
# Compare against a FULL band, not the smallest cell: the tissue runs y=40-260
# with boundaries at 100/160/220, so the last band is only 40 px tall by
# construction. Using the minimum would compare 120 px against 40 and expect
# the wrong ratio - a fault in the test, not the measurement.
typical = float(np.median([r["area_um2"] for r in rows2]))
check("the merged cell is about twice a full cell's area",
      1.6 < merged["area_um2"] / typical < 2.6,
      f"{merged['area_um2']} vs typical {typical} um2 "
      f"(ratio {merged['area_um2'] / typical:.2f})")
check("an implausible cell is FLAGGED rather than silently reported",
      merged["flags"] != "" or merged["area_um2"] < mm.PLAUSIBLE_AREA_UM2[1],
      merged["flags"] or "within plausible range")

# --- every boundary rejected -> refuse, do not return zero cells ----------
st3 = build(statuses=("rejected",) * 3)
try:
    mm.cells_from_boundaries(st3, tissue)
    check("a field with no surviving boundary is refused", False)
except mm.MeasurementError as exc:
    check("a field with no surviving boundary is refused", True)
    check("...saying every proposal was rejected",
          "Every proposal was rejected" in str(exc))

# --- fibre statistics ------------------------------------------------------
skel = np.zeros((H, W), bool)
skel[130, 100:900] = True             # one 80 um fibre inside the second band
rows3 = mm.measure_cells(labels, UM, fibre_skeleton=skel)
withf = [r for r in rows3 if r.get("fibre_length_um", 0) > 1]
check("fibre length is attributed to the cell containing it",
      len(withf) == 1 and abs(withf[0]["fibre_length_um"] - 80) < 2,
      f"{[round(r.get('fibre_length_um', 0), 1) for r in rows3]}")

# --- fibre angle is reported RELATIVE to the cell axis --------------------
ang = np.full((H, W), 45.0)
coh = np.full((H, W), 0.9)
rows4 = mm.measure_cells(labels, UM, angles=ang, coherence=coh)
check("fibre angle relative to the cell's own axis is reported",
      all("fibre_angle_vs_cell_axis_deg" in r for r in rows4))
check("...and a 45 deg fibre in an axis-aligned cell reads ~45",
      all(abs(r["fibre_angle_vs_cell_axis_deg"] - 45) < 12 for r in rows4),
      f"{[r['fibre_angle_vs_cell_axis_deg'] for r in rows4]}")

# --- the summary carries its own caveat -----------------------------------
s = mm.summarise(rows)
check("summary reports cell count and median area",
      s["n_cells"] == 4 and s["area_um2_median"] > 0)
check("summary states that a missed boundary inflates an area",
      "merges two cells" in s["caveat"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MYOCYTE_MEASURE_PASS")
