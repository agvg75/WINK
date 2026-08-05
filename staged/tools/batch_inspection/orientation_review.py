"""Confirm or reject the inverted stretches, and feed the corrections back.

The batch ranking locates spans where the curvature profile inverted - frames
whose anterior-posterior axis, and therefore whose dorsal and ventral labels,
are backwards. Sixteen of twenty-four real recordings carry at least one. This
is the pass where a person says yes or no, and where a yes becomes a correction
the analysis actually applies.

WHY THIS CANNOT BE AUTOMATIC. The detector finds a discontinuity; it cannot
tell a tracking failure from an animal that genuinely reversed and was
re-detected. Both invert the profile. Only someone looking at the frames knows
which happened, which is why the output of the detector is a QUESTION and not
a correction.

WHAT A CONFIRMATION MEANS, precisely. Inside a confirmed span the geometry is
back to front: segment 0 is the tail, so the segment order reverses, and the
sign of curvature flips, so dorsal and ventral swap. `apply_corrections` does
exactly those two things and nothing else - it does not re-track, re-measure or
re-detect, because the pixels were always fine and only their labelling was
wrong.

CORRECTIONS ARE A SIDECAR, NEVER AN EDIT OF THE DATA. The extracted CSV is
what the Fiji plugin or the Python extractor produced and it stays that way.
A correction file sits beside it saying which spans a person judged inverted,
when, and on what basis - so the correction can be re-examined, disagreed with,
or applied differently later. Rewriting the CSV in place would destroy the only
record of what the detector originally said.
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for sub in ("app", "tools", "tools/batch_inspection"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)

VERDICTS = ("inverted", "correct", "unsure")


class ReviewError(Exception):
    """Refusals that name the consequence."""


def correction_path(csv_path):
    return Path(str(csv_path)).with_suffix(".orientation.json")


def load(csv_path):
    try:
        return json.loads(correction_path(csv_path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {"source": str(csv_path), "spans": [], "reviewed": False}
    except json.JSONDecodeError as exc:
        raise ReviewError(
            f"{correction_path(csv_path)} is not valid JSON ({exc}). Review "
            f"decisions would be silently lost if this were ignored.")


def propose(grid, flip_threshold=-0.4):
    """The spans the detector believes are inverted. Questions, not answers."""
    import contact_sheet as cs
    r = cs.wave_continuity(grid)
    n = grid.shape[1]
    idx = [i + 1 for i, v in enumerate(np.nan_to_num(r, nan=1.0))
           if v < flip_threshold]
    spans, state, bounds = [], 0, idx + [n]
    for k in range(len(idx)):
        state ^= 1
        if state:
            spans.append({"start_frame": int(bounds[k]),
                          "end_frame": int(bounds[k + 1]) - 1,
                          "n_frames": int(bounds[k + 1] - bounds[k]),
                          "verdict": None})
    return spans


def record(csv_path, spans, by="", note=""):
    """Save a review pass. Every span carries a verdict or is left open."""
    for s in spans:
        v = s.get("verdict")
        if v is not None and v not in VERDICTS:
            raise ReviewError(
                f"Verdict {v!r} is not one of {VERDICTS}. An invented verdict "
                f"would be applied as though someone had judged it.")
    doc = load(csv_path)
    doc.update({
        "source": str(csv_path),
        "spans": spans,
        "reviewed": any(s.get("verdict") for s in spans),
        "reviewed_by": by,
        "reviewed_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "note": note,
        "n_confirmed": sum(1 for s in spans if s.get("verdict") == "inverted"),
        "n_rejected": sum(1 for s in spans if s.get("verdict") == "correct"),
        "n_unsure": sum(1 for s in spans if s.get("verdict") == "unsure"),
        "not_applied_to_source": (
            "This file records judgements only. The extracted CSV is "
            "untouched, so what the detector originally proposed remains "
            "recoverable and a correction can be disagreed with later."),
    })
    correction_path(csv_path).write_text(json.dumps(doc, indent=2),
                                         encoding="utf-8")
    return doc


def apply_corrections(rows, csv_path, n_seg=24):
    """Re-label the rows inside confirmed spans. Returns (rows, report).

    Two changes and no others: segment order reverses, and the two hemisegment
    labels swap. Nothing is re-measured, because the pixels were never wrong.

    UNSURE SPANS ARE LEFT ALONE and reported. Treating an unresolved question
    as a no would quietly ship the uncorrected data; treating it as a yes would
    apply a correction nobody agreed to.
    """
    doc = load(csv_path)
    confirmed = [s for s in doc.get("spans", [])
                 if s.get("verdict") == "inverted"]
    unsure = [s for s in doc.get("spans", []) if s.get("verdict") == "unsure"]
    if not doc.get("reviewed"):
        raise ReviewError(
            f"{correction_path(csv_path)} has no verdicts. Applying "
            f"corrections from an unreviewed proposal would hand the "
            f"detector's guess the authority of a person's judgement.")

    swap = {"dorsal": "ventral", "ventral": "dorsal",
            "left": "right", "right": "left"}
    out, n_fixed = [], 0
    for r in rows:
        f = r.get("frame")
        inside = any(s["start_frame"] <= f <= s["end_frame"] for s in confirmed)
        if not inside:
            out.append(r)
            continue
        fixed = dict(r)
        if r.get("segment") is not None:
            fixed["segment"] = (n_seg - 1) - int(r["segment"])
        if r.get("hemisegment") in swap:
            fixed["hemisegment"] = swap[r["hemisegment"]]
        if r.get("dorsal_label") in swap:
            fixed["dorsal_label"] = swap[r["dorsal_label"]]
        if r.get("seg_curv_deg") is not None:
            fixed["seg_curv_deg"] = -float(r["seg_curv_deg"])
        fixed["orientation_corrected"] = True
        out.append(fixed)
        n_fixed += 1

    return out, {
        "rows_corrected": n_fixed,
        "spans_confirmed": len(confirmed),
        "spans_unsure": len(unsure),
        "unsure_left_uncorrected": [
            {"start_frame": s["start_frame"], "end_frame": s["end_frame"]}
            for s in unsure],
        "what_changed": (
            "Inside a confirmed span: segment order reversed, hemisegment and "
            "dorsal labels swapped, curvature sign flipped. Nothing was "
            "re-measured - the pixels were never wrong, only their labels."),
        "unsure_note": (
            f"{len(unsure)} span(s) were left uncorrected because nobody "
            f"resolved them. Treating an open question as a no would ship the "
            f"uncorrected data; treating it as a yes would apply a correction "
            f"nobody agreed to."
            if unsure else "No spans were left unresolved."),
    }


def queue(root, source="csv"):
    """Every recording with a proposed inverted span, worst first."""
    import batch_review as br
    res = br.run(root, source=source, progress=None)
    items = []
    for row in res["ranked"]:
        g = res["grids"][row["name"]]
        spans = propose(g)
        if not spans:
            continue
        rec = next((f for f in br.discover_csv(root)
                    if f["name"] == row["name"]), None)
        doc = load(rec["csv"]) if rec else {"reviewed": False}
        items.append({
            "recording": row["name"],
            "csv": rec["csv"] if rec else None,
            "score": row["score"],
            "n_frames": row["n_frames"],
            "spans": spans,
            "inverted_fraction": row.get("inverted_fraction"),
            "ends_inverted": row.get("ends_inverted"),
            "already_reviewed": bool(doc.get("reviewed")),
        })
    return {
        "root": str(root),
        "n_recordings": len(res["ranked"]),
        "n_needing_review": len(items),
        "n_already_reviewed": sum(1 for i in items if i["already_reviewed"]),
        "items": items,
        "grids": res["grids"],
    }
