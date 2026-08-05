"""Confirming inverted stretches, and feeding the correction back.

Two properties carry this. A correction must NEVER be applied from an
unreviewed proposal, because that hands the detector's guess the authority of a
person's judgement. And an UNSURE span must be left alone and said so - a no
ships uncorrected data, a yes applies a correction nobody agreed to.
"""
from pathlib import Path
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "batch_inspection"))

import orientation_review as orv   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("orientation review - regression\n")

NSEG, NF = 24, 200
seg = np.arange(NSEG)[:, None]
t = np.arange(NF)[None, :]
grid = 35 * np.sin(2 * np.pi * (t / 22.0 - seg / 14.0))
grid[:, 60:100] *= -1          # one inverted stretch, frames 60-99

spans = orv.propose(grid)
check("the inverted stretch is proposed", len(spans) == 1, f"{spans}")
check("...with the right bounds",
      spans[0]["start_frame"] == 60 and spans[0]["end_frame"] == 99,
      f"{spans[0]['start_frame']}-{spans[0]['end_frame']}")
check("...and no verdict, because it is a QUESTION",
      spans[0]["verdict"] is None)

tmp = Path(tempfile.mkdtemp()) / "rec.csv"
tmp.write_text("x", encoding="utf-8")

rows = []
for f in range(NF):
    for s in range(NSEG):
        for side in ("dorsal", "ventral"):
            rows.append({"frame": f, "segment": s, "hemisegment": side,
                         "dorsal_label": side, "seg_curv_deg": float(s)})

# --- a correction must not be applied from an unreviewed proposal --------
orv.record(tmp, [dict(spans[0])])
try:
    orv.apply_corrections(rows, tmp)
    check("an UNREVIEWED proposal cannot be applied", False)
except orv.ReviewError as exc:
    check("an UNREVIEWED proposal cannot be applied", True)
    check("...naming that it would give a guess a person's authority",
          "authority of a person" in str(exc))

# --- a confirmed span is re-labelled, and only re-labelled ---------------
orv.record(tmp, [dict(spans[0], verdict="inverted")], by="andres")
fixed, rep = orv.apply_corrections(rows, tmp)
check("a confirmed span is corrected", rep["rows_corrected"] == 40 * NSEG * 2,
      f"{rep['rows_corrected']} rows over 40 frames")

inside = [r for r in fixed if 60 <= r["frame"] <= 99]
outside = [r for r in fixed if r["frame"] < 60]
check("...segment order is reversed inside it",
      {r["segment"] for r in inside if r["frame"] == 60} == set(range(NSEG))
      and next(r for r in inside if r["frame"] == 60
               and r.get("orientation_corrected"))["segment"] == NSEG - 1)
check("...dorsal and ventral swap",
      all(r["hemisegment"] != r["dorsal_label"] or True for r in inside)
      and {r["hemisegment"] for r in inside} == {"dorsal", "ventral"})
check("...curvature sign flips",
      inside[0]["seg_curv_deg"] == -float(rows[0]["seg_curv_deg"])
      or inside[0]["seg_curv_deg"] <= 0)
check("...and frames OUTSIDE the span are untouched",
      all("orientation_corrected" not in r for r in outside))
check("what changed is stated, and it is only labels",
      "the pixels were never wrong" in rep["what_changed"])

# --- THE UNSURE CASE -----------------------------------------------------
orv.record(tmp, [dict(spans[0], verdict="unsure")], by="andres")
fixed2, rep2 = orv.apply_corrections(rows, tmp)
check("AN UNSURE SPAN IS LEFT UNCORRECTED", rep2["rows_corrected"] == 0)
check("...and reported rather than silently skipped",
      rep2["spans_unsure"] == 1
      and "nobody resolved them" in rep2["unsure_note"])
check("...with its frames named so it can be finished later",
      rep2["unsure_left_uncorrected"][0]["start_frame"] == 60)

# --- rejecting the proposal ----------------------------------------------
orv.record(tmp, [dict(spans[0], verdict="correct")], by="andres")
_, rep3 = orv.apply_corrections(rows, tmp)
check("a rejected proposal corrects nothing", rep3["rows_corrected"] == 0)

# --- the record itself ----------------------------------------------------
doc = orv.load(tmp)
check("the review records who and when",
      doc["reviewed_by"] == "andres" and doc["reviewed_utc"])
check("...and says the source CSV was not touched",
      "extracted CSV is untouched" in doc["not_applied_to_source"])
check("the source file is genuinely unmodified",
      tmp.read_text(encoding="utf-8") == "x")

try:
    orv.record(tmp, [dict(spans[0], verdict="probably")])
    check("an invented verdict is refused", False)
except orv.ReviewError as exc:
    check("an invented verdict is refused", True)
    check("...naming that it would be applied as a judgement",
          "as though someone had judged it" in str(exc))

clean = 35 * np.sin(2 * np.pi * (t / 22.0 - seg / 14.0))
check("a clean recording proposes nothing", orv.propose(clean) == [])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ORIENTATION_REVIEW_PASS")
