"""Versioned, resumable review state for single-animal transmitted-light tools."""
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
