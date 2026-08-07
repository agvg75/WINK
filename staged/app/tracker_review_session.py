"""Versioned, resumable review state for single-animal transmitted-light tools.

A SAVED SESSION THAT DOES NOT FIT IS A REASON TO IGNORE IT, NOT TO QUIT.
Both tools that resume through here used to do this:

    except Exception as exc:
        messagebox.showerror("Resume failed", str(exc)); return

which ends the tool. Starting fresh was always available and the tool knew
it, so anyone hitting that concludes the tool is broken and works around it
silently. `resume_or_start_fresh` below exists so the safe behaviour is the
easy one and a third tool cannot reintroduce the trap.
"""
from __future__ import annotations

import datetime as _datetime
import json
from pathlib import Path

import numpy as np


SCHEMA_VERSION = 1
ARRAY_KEYS = {"pts", "path", "curv", "seg_widths", "raw_pts", "raw_path"}


def _jsonable(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.floating, np.integer, np.bool_)):
        return value.item()
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def save_tracker_session(path, tracker, *, tool, source):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "schema_version": SCHEMA_VERSION,
        "tool": str(tool),
        "source": _jsonable(source),
        "saved_utc": _datetime.datetime.now(_datetime.timezone.utc).isoformat(),
        "frame_count": int(tracker.T),
        "reference": {
            "length_px": _jsonable(getattr(tracker, "len_ref", None)),
            "area_px": _jsonable(getattr(tracker, "area_ref", None)),
            "manual_identity_reference": _jsonable(
                getattr(tracker, "manual_identity_reference", False)),
            "soma_nose_arc_px": _jsonable(getattr(tracker, "soma_nose_arc", None)),
            "soma_profile": _jsonable(getattr(tracker, "soma_profile", None)),
        },
        "states": _jsonable(tracker.state),
    }
    temporary = path.with_suffix(path.suffix+".tmp")
    temporary.write_text(json.dumps(document, indent=2, allow_nan=True), encoding="utf-8")
    temporary.replace(path)
    return path


def load_tracker_session(path, tracker, *, tool, source):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if int(document.get("schema_version", -1)) != SCHEMA_VERSION:
        raise ValueError("Unsupported tracker review-session version.")
    if document.get("tool") != str(tool):
        raise ValueError("This review session belongs to a different tool.")
    # DO NOT LOOSEN THIS TO MAKE A MISMATCH GO AWAY. `states` is POSITIONAL -
    # one entry per frame, indexed by frame number. Applying a 500-entry state
    # array to a 520-frame stack does not fail; it silently misaligns every
    # corrected spine, and the result looks like data. Corruption that looks
    # like data is the failure class this project keeps turning up, and it is
    # far worse than a refusal.
    #
    # The right response to a mismatch is to DISCARD the saved session and
    # start fresh - see resume_or_start_fresh - never to relax the comparison.
    if int(document.get("frame_count", -1)) != int(tracker.T):
        raise ValueError("The review session does not match this recording's frame count.")
    saved_source = document.get("source", {})
    for key in ("recording_key", "first_frame", "last_frame"):
        if saved_source.get(key) != source.get(key):
            raise ValueError(f"The review session source differs at {key}.")
    states = document.get("states", [])
    if len(states) != tracker.T:
        raise ValueError("The review session contains an incomplete state sequence.")
    for state in states:
        if state is None:
            continue
        for key in ARRAY_KEYS:
            if state.get(key) is not None:
                state[key] = np.asarray(state[key], float)
        for key in ("head", "tail", "centroid", "soma", "nose"):
            if state.get(key) is not None:
                state[key] = tuple(state[key])
    tracker.state = states
    reference = document.get("reference", {})
    tracker.len_ref = reference.get("length_px", tracker.len_ref)
    tracker.area_ref = reference.get("area_px", tracker.area_ref)
    if hasattr(tracker, "manual_identity_reference"):
        tracker.manual_identity_reference = bool(
            reference.get("manual_identity_reference",
                          tracker.manual_identity_reference))
    if hasattr(tracker, "soma_nose_arc"):
        tracker.soma_nose_arc = reference.get("soma_nose_arc_px", tracker.soma_nose_arc)
    if hasattr(tracker, "soma_profile"):
        tracker.soma_profile = reference.get("soma_profile", tracker.soma_profile)
    if hasattr(tracker, "suggested_manual_anchors"):
        tracker.suggested_manual_anchors = [
            i for i, state in enumerate(states)
            if state and state.get("suggested_manual_anchor")]
    return document


def describe(path):
    """What a saved session holds, WITHOUT validating that it fits.

    Deliberately separate from `load_tracker_session`: this is what a person
    needs in order to decide whether discarding the file costs them two
    minutes or an hour, and they need it precisely when the session does NOT
    fit and so cannot be loaded.

    Returns None if the file is missing or unreadable, because a session that
    cannot even be described is not one anybody will mourn.
    """
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    states = document.get("states") or []
    # `provenance` is set to "manual" only where a person fixed that frame by
    # hand. `needs_help` is the tracker's own flag and is not a correction.
    corrections = sum(1 for state in states
                      if state and state.get("provenance") == "manual")
    return {
        "frame_count": int(document.get("frame_count", len(states))),
        "corrections": corrections,
        "needs_help": sum(1 for state in states
                          if state and state.get("needs_help")),
        "saved_utc": document.get("saved_utc", ""),
        "tool": document.get("tool", ""),
    }


def summarise(path):
    """One human sentence naming what discarding this session would cost."""
    facts = describe(path)
    if not facts:
        return "The saved session could not be read."
    when = (facts["saved_utc"] or "")[:16].replace("T", " ")
    return (f"The saved session covers {facts['frame_count']:,} frames and "
            f"holds {facts['corrections']:,} hand-corrected frame"
            f"{'' if facts['corrections'] == 1 else 's'}"
            + (f", saved {when} UTC." if when else "."))


def resume_or_start_fresh(path, tracker, *, tool, source, confirm, inform):
    """Try to resume; on any mismatch offer a fresh start. NEVER a dead end.

    `confirm(title, message) -> bool` and `inform(title, message)` are passed
    in so this module stays free of any UI toolkit.

    Returns True if the saved session was resumed, False if the caller should
    track from scratch. IT DOES NOT RAISE for a session that does not fit -
    that is the whole point. The strict frame-count check in
    `load_tracker_session` stays exactly as strict; what changes is that a
    refusal now costs the saved file rather than the whole sitting.
    """
    path = Path(path)
    if not path.exists():
        return False
    if not confirm("Resume review?",
                   f"A saved review session exists for this recording.\n\n"
                   f"{summarise(path)}\n\n"
                   "Resume the corrected spines and continue reviewing?"):
        return False
    try:
        load_tracker_session(path, tracker, tool=tool, source=source)
        return True
    except Exception as exc:                              # noqa: BLE001
        if confirm("Saved session does not fit",
                   f"{exc}\n\n{summarise(path)}\n\n"
                   "This usually means the analysis interval differs from the "
                   "one the session was saved with. The saved corrections are "
                   "stored per frame, so they cannot be applied to a "
                   "different number of frames without misaligning them.\n\n"
                   "Start fresh instead? The saved session is left on disk "
                   "and is not overwritten until you save again."):
            return False
        inform("Review cancelled",
               "Nothing was changed. Re-open the tracker and choose the same "
               "analysis interval the session was saved with to resume it.")
        raise SystemExit(0)
