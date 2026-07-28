"""Small, shared helpers for WINK decision-audit exports.

The goal is not to make detectors sound more certain than they are.  The goal is
to make every assistive decision inspectable: what the program proposed, which
rules/cues supported that proposal, where the human review lives, and what
should still be treated as provisional.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json


WINK_DECISION_PRINCIPLE = (
    "WINK separates automatic suggestions from human-reviewed conclusions. "
    "Automatic candidates are assistance, not truth; final measurements should "
    "come from reviewed/accepted records when the module offers review."
)


def vote_policy_summary(cues, required_votes=None, required_contrast_votes=None,
                        vetoes=None, human_review=True):
    """Return a reusable, JSON-safe description of a transparent vote detector.

    Several WINK tools now use the same human-in-the-loop pattern: the program
    proposes objects/events when multiple independent cues agree, records the
    cue names, and lets the reviewer accept/reject/correct them.  This helper
    keeps that "hood off" language consistent across modules.
    """
    return {
        "decision_style": "transparent_multi_cue_vote",
        "cues": [str(c) for c in (cues or [])],
        "required_votes": required_votes,
        "required_contrast_votes": required_contrast_votes,
        "vetoes": [str(v) for v in (vetoes or [])],
        "human_review_required_for_final_count": bool(human_review),
        "interpretation": (
            "A proposed object/event is a hypothesis supported by the listed cues. "
            "It becomes a final measurement only after human review when review is offered."
        ),
    }


def _plain(value):
    """Convert common numpy/pandas/path values into JSON-safe Python objects."""
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    try:
        # numpy scalar support without importing numpy into this tiny helper.
        if hasattr(value, "item"):
            return value.item()
    except Exception:
        pass
    return value


def write_decision_manifest(
    output_dir,
    tool_name,
    *,
    method_note="",
    summary=None,
    decision_files=None,
    fields=None,
    color_legend=None,
    caveats=None,
    filename="decision_transparency.json",
):
    """Write a plain-language JSON manifest describing detector decisions."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tool": str(tool_name),
        "principle": WINK_DECISION_PRINCIPLE,
        "method_note": str(method_note or ""),
        "summary": _plain(summary or {}),
        "decision_files": _plain(decision_files or {}),
        "fields": _plain(fields or {}),
        "color_legend": _plain(color_legend or {}),
        "caveats": _plain(caveats or []),
    }
    path = out / filename
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return path
