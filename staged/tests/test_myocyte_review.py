"""Regression tests for the myocyte boundary review state.

The properties that matter are not "does it store points" but the ones that
keep a reviewed result trustworthy: nothing changes state except through an
intent, every change is logged, a review cannot be accepted with proposals
nobody judged, and a hand-drawn boundary stays distinguishable from a corrected
one. Each is asserted on substance, not on structure.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import myocyte_review_state as mrs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def fresh():
    st = mrs.MyocyteReviewState((300, 1200), 0.09, "x.lif", "W1_mid", "midbody")
    st.add_proposals([
        ("seam_0", [(0, 100), (600, 105), (1199, 110)]),
        ("seam_1", [(0, 200), (600, 198), (1199, 195)]),
        ("linked_0", [(200, 150), (500, 152), (800, 149)]),
    ])
    return st


print("myocyte review state - regression\n")

st = fresh()
check("seeding with proposals is NOT logged - proposing is not a decision",
      len(st.correction_log) == 0 and len(st.boundaries) == 3)
check("proposals start unjudged", st.summary()["by_status"]["proposed"] == 3)

# --- every mutation is logged ---------------------------------------------
st.apply_intent(mrs.AcceptBoundary(boundary_id="seam_0"))
st.apply_intent(mrs.MovePoint(boundary_id="seam_1", index=1, x=600, y=210))
check("one log entry per intent", len(st.correction_log) == 2)
check("log entries describe the change in words",
      all(e["description"] for e in st.correction_log))
check("editing a proposal marks it edited, not accepted",
      st.boundaries["seam_1"].status == "edited")

# --- the detector's error is recoverable ----------------------------------
rows = {r["boundary_id"]: r for r in st.measure()}
# One point of three moved by 12 px, so the MEDIAN displacement is legitimately
# zero - two points did not move. The max is what catches a single misplaced
# point, which is why both are reported.
check("a single moved point is caught by the max displacement",
      rows["seam_1"]["displacement_max_um"] is not None
      and abs(rows["seam_1"]["displacement_max_um"] - 12 * 0.09) < 1e-6,
      f"max {rows['seam_1']['displacement_max_um']} um, "
      f"median {rows['seam_1']['displacement_from_proposal_um']} um")
check("...and the median correctly reports that most of it did not move",
      rows["seam_1"]["displacement_from_proposal_um"] == 0)
check("an untouched boundary shows zero displacement on both",
      rows["seam_0"]["displacement_from_proposal_um"] == 0
      and rows["seam_0"]["displacement_max_um"] == 0)
check("length is reported in micrometres, not pixels",
      90 < rows["seam_0"]["length_um"] < 130,
      f"{rows['seam_0']['length_um']} um for a 1199 px span at 0.09 um/px")

# --- refusals --------------------------------------------------------------
try:
    st.apply_intent(mrs.AcceptReview())
    check("a review cannot be accepted while proposals are unjudged", False)
except mrs.ReviewError as exc:
    check("a review cannot be accepted while proposals are unjudged", True)
    check("...and the refusal names the consequence",
          "as though a human had approved" in str(exc))

try:
    st.apply_intent(mrs.RejectBoundary(boundary_id="linked_0",
                                       reason="looked a bit off"))
    check("an off-vocabulary rejection reason is refused", False)
except mrs.ReviewError as exc:
    check("an off-vocabulary rejection reason is refused", True)
    check("...and says why free text cannot be used",
          "cannot be tallied" in str(exc))

try:
    st.apply_intent(mrs.MovePoint(boundary_id="does_not_exist", index=0))
    check("editing a boundary that does not exist is refused", False)
except mrs.ReviewError:
    check("editing a boundary that does not exist is refused", True)

try:
    mrs.intent_from_dict({"kind": "delete_everything"})
    check("an unknown intent is refused", False)
except mrs.ReviewError as exc:
    check("an unknown intent is refused", True)
    check("...naming the risk of a private action",
          "nothing recording how" in str(exc))

# a boundary must not be dissolved by removing its points
st2 = fresh()
st2.apply_intent(mrs.RemovePoint(boundary_id="seam_0", index=0))
try:
    st2.apply_intent(mrs.RemovePoint(boundary_id="seam_0", index=0))
    check("a boundary cannot be reduced below two points", False)
except mrs.ReviewError as exc:
    check("a boundary cannot be reduced below two points", True)
    check("...and points the user at rejection, which records WHY",
          "Reject it instead" in str(exc))

# --- hand-drawn stays distinguishable -------------------------------------
st3 = fresh()
st3.apply_intent(mrs.AddBoundary(boundary_id="hand_0",
                                 points=[(10, 50), (900, 60)]))
check("a hand-drawn boundary is marked as such, not as a proposal",
      st3.boundaries["hand_0"].source == "hand_drawn")
check("...and carries no proposal to be compared against",
      {r["boundary_id"]: r for r in st3.measure()}["hand_0"]
      ["displacement_from_proposal_um"] is None)
try:
    st3.apply_intent(mrs.AddBoundary(boundary_id="seam_0", points=[(0, 0), (1, 1)]))
    check("reusing an existing id is refused", False)
except mrs.ReviewError:
    check("reusing an existing id is refused", True)

# --- a complete review -----------------------------------------------------
st4 = fresh()
for bid in ("seam_0", "seam_1"):
    st4.apply_intent(mrs.AcceptBoundary(boundary_id=bid))
st4.apply_intent(mrs.RejectBoundary(boundary_id="linked_0",
                                    reason="follows_tissue_edge"))
st4.apply_intent(mrs.AcceptReview(note="midbody, W1"))
check("a fully judged review can be accepted", st4.accepted)
check("rejected boundaries are excluded from measurement",
      all(r["boundary_id"] != "linked_0" for r in st4.measure()))
check("rejection reasons are counted, so failure modes can be tallied",
      st4.summary()["reject_reasons"].get("follows_tissue_edge") == 1)

# --- round trip ------------------------------------------------------------
again = mrs.MyocyteReviewState.from_dict(st4.to_dict())
check("state round-trips without changing the measurements",
      again.measure() == st4.measure())
check("the correction log survives the round trip",
      len(again.correction_log) == len(st4.correction_log))
prov = st4.to_provenance()
check("provenance states corrections are tuning data, not ground truth",
      prov["corrections_are_tuning_data_not_ground_truth"] is True
      and "not independent validation" in prov["note"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MYOCYTE_REVIEW_PASS")
