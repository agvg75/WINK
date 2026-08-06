"""Persisted session marks for single-channel GCaMP recordings.

WHAT A SESSION MARK IS. One folder is often not one recording. The protocol
is: find a worm under transmitted light, zoom in, switch the transmitted light
off, film under blue light, move to the next worm. So a folder holds
alternating BRIGHT search sequences and DIM fluorescence takes, several worms
deep. A session mark says which source frames are one take.

WHY THIS EXISTS SEPARATELY. `gcamp.detect_episodes` finds those boundaries
automatically from frame means, and the tool can already act on one - but only
in memory, as a tuple that dies with the window. A judgement about which
frames are the real take is the expensive part of the work, and it was being
thrown away every time the tool closed. This writes it down.

THE KEY NAMES ARE NOT NEW. `frame_start`, `frame_end` and `kind` are what
`gcamp_tool` already converts detected episodes into, in SOURCE frame numbers.
Inventing parallel names for the same quantity is how two representations of
one idea start drifting.

WHY NOT `segmentation_review`. It has a versioned, validated, JSON-persisted
frame-range schema that fits this shape exactly, and it names
`single_channel_gcamp` in `PHOTOMETRY_EXCLUSIONS`. That module may define
object extent only and must never be used for fluorescence photometry, so the
structural fit is a trap rather than an invitation.

`origin` DISTINGUISHES A JUDGEMENT FROM A DETECTION. A range the detector
proposed and a range a person drew are not equally good evidence, and once
both are in the same file nothing else can tell them apart.
"""
from __future__ import annotations

import datetime as _datetime
import json
from pathlib import Path

SCHEMA_VERSION = 1
TOOL = "single_channel_gcamp"
DEFAULT_NAME = "gcamp_session_marks.json"
ORIGINS = {"manual", "detected", "detected_edited"}


class SessionMarkError(ValueError):
    """Refusals that name the consequence."""


def make_mark(frame_start, frame_end, *, kind="", origin="manual", note=""):
    """One validated mark, in SOURCE frame numbers, ends inclusive."""
    try:
        a, b = int(frame_start), int(frame_end)
    except (TypeError, ValueError):
        raise SessionMarkError(
            f"Frame numbers must be whole numbers, got "
            f"{frame_start!r} and {frame_end!r}.")
    if a < 0:
        raise SessionMarkError(
            f"A mark cannot start before frame 0 (got {a}). These are source "
            f"frame numbers, not offsets into a selection.")
    if b < a:
        raise SessionMarkError(
            f"A mark must end at or after it starts (got {a} to {b}). A "
            f"reversed range silently analyses nothing.")
    if origin not in ORIGINS:
        raise SessionMarkError(
            f"Unknown origin {origin!r}. Known: {sorted(ORIGINS)}. The origin "
            f"is what separates a judgement from a detection.")
    return {"frame_start": a, "frame_end": b, "kind": str(kind),
            "origin": str(origin), "note": str(note)}


def marks_from_ranges(ranges, *, kind="", origin="manual"):
    """Marks from the (start, end) pairs `frame_range_selector` returns."""
    return [make_mark(a, b, kind=kind, origin=origin) for a, b in ranges]


def validate(marks, *, frame_count=None):
    """Sorted marks, or a refusal that says what would have gone wrong."""
    checked = [make_mark(**{k: m[k] for k in
                            ("frame_start", "frame_end", "kind", "origin",
                             "note") if k in m})
               for m in marks]
    if not checked:
        raise SessionMarkError(
            "A session file with no marks in it says nothing. Either mark a "
            "range or do not save one.")
    checked.sort(key=lambda m: (m["frame_start"], m["frame_end"]))
    for previous, current in zip(checked, checked[1:]):
        if current["frame_start"] <= previous["frame_end"]:
            raise SessionMarkError(
                f"Marks {previous['frame_start']}-{previous['frame_end']} and "
                f"{current['frame_start']}-{current['frame_end']} overlap. "
                f"Overlapping takes would contribute the same frames to two "
                f"baselines, and a dF/F0 computed twice from one frame is not "
                f"two measurements.")
    if frame_count is not None:
        last = checked[-1]["frame_end"]
        if last >= int(frame_count):
            raise SessionMarkError(
                f"A mark ends at frame {last} but the recording has "
                f"{int(frame_count)} frames (0-{int(frame_count) - 1}). Marks "
                f"are source frame numbers; this one is off the end.")
    return checked


def save_marks(path, marks, *, source, frame_count=None, note=""):
    """Write the marks, refusing anything that could not be analysed."""
    checked = validate(marks, frame_count=frame_count)
    document = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "source": str(source),
        "saved_utc": _datetime.datetime.now(
            _datetime.timezone.utc).isoformat(timespec="seconds"),
        "frame_count": int(frame_count) if frame_count is not None else None,
        "frame_numbering": "source frames, 0-based, ends inclusive",
        "note": str(note),
        "marks": checked,
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2), encoding="utf-8")
    return document


def load_marks(path, *, source=None):
    """Read a session file back, refusing one written for something else."""
    path = Path(path)
    try:
        document = json.loads(path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError as exc:
        raise SessionMarkError(
            f"{path.name} is not readable as JSON ({exc}). A session file is "
            f"written by this tool; it is not meant to be edited by hand.")
    version = document.get("schema_version")
    if version != SCHEMA_VERSION:
        raise SessionMarkError(
            f"{path.name} is schema version {version!r}, and this build "
            f"reads version {SCHEMA_VERSION}. Refusing rather than guessing "
            f"what a field meant in another version.")
    if document.get("tool") != TOOL:
        raise SessionMarkError(
            f"{path.name} was written by {document.get('tool')!r}, not "
            f"{TOOL!r}. Frame ranges from another tool may be numbered "
            f"against a different selection.")
    if source is not None and document.get("source") != str(source):
        raise SessionMarkError(
            f"{path.name} was marked against {document.get('source')!r}, but "
            f"the loaded recording is {str(source)!r}. Source frame numbers "
            f"mean nothing against a different recording.")
    document["marks"] = validate(document.get("marks", []),
                                 frame_count=document.get("frame_count"))
    return document


def span(marks):
    """The single (start, end) the tool's `episode_range` holds.

    The tool analyses one contiguous span. Several marks collapse to their
    outer bounds, which INCLUDES whatever sits between them - so this reports
    the gap rather than hiding it.
    """
    checked = validate(marks)
    a = checked[0]["frame_start"]
    b = checked[-1]["frame_end"]
    covered = sum(m["frame_end"] - m["frame_start"] + 1 for m in checked)
    return (a, b), (b - a + 1) - covered
