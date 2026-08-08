"""What frame types a recording folder actually contains. Measured, not assumed.

    from frame_census import census, require_homogeneous
    record = census(folder)             # for the navigator identity record
    require_homogeneous(folder)         # before treating it as one series

THE INCIDENT, 8 Aug 2026 — AND IT IS THE SECOND FROM THE SAME DIRECTORY.
`Carlees Worms\\AVG6` holds 1,262 files that every tool had treated as one
recording. It is two: **1,154 grayscale (768, 1024) uint16 planes and 108 RGB
(768, 1024, 3) planes.** Loading it as a series raised numpy's

    ValueError: all input arrays must have the same shape

which names neither how many planes differ, nor which, nor in what way. The
first lesson from this same folder was the AVG6 name collision (navigator spec
§6.1); a directory that has now taught two different lessons about identity is
worth taking seriously as a type.

**MIXED FOLDERS SURFACE THE SPLIT. THEY ARE NEVER COERCED.** Silently keeping
the majority and dropping 108 planes would be a measurement decision made by a
loader — and one nobody would see, because the result looks like an ordinary
recording that happens to be 108 frames shorter.

**HOMOGENEITY IS VERIFIED BY MEASUREMENT, not inferred from the folder.** The
frames are read; the extension, the naming convention and the folder's tidy
appearance say nothing about dtype or channel count.

The record produced here **joins the navigator identity record** — a
recording's identity is not its folder name (§6.1), and it is not its file
count either. Frame type is part of what distinguishes one recording from
another.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

FRAME_EXTENSIONS = {".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp", ".pgm"}


class MixedFramesError(ValueError):
    """A folder holding more than one frame type, where one was required."""


def _describe(shape, dtype):
    channels = shape[2] if len(shape) == 3 else 1
    return {"shape": tuple(shape), "dtype": str(dtype), "channels": channels,
            "height": shape[0], "width": shape[1]}


def census(folder, limit=None):
    """Frame-type census for a recording folder.

    Returns a record with `types` (each with its count), `homogeneous`,
    `dominant`, and `n_frames`. Reading every plane is the point; a sample
    would answer a different question, so `limit` exists only for very large
    folders and is recorded when used.
    """
    folder = Path(folder)
    files = sorted(p for p in folder.iterdir()
                   if p.is_file() and p.suffix.lower() in FRAME_EXTENSIONS)
    if limit:
        files = files[:limit]
    if not files:
        return {"folder": str(folder), "n_frames": 0, "types": [],
                "homogeneous": None, "dominant": None,
                "note": "no frame files found"}

    import tifffile
    seen = Counter()
    unreadable = 0
    for path in files:
        try:
            if path.suffix.lower() in (".tif", ".tiff"):
                with tifffile.TiffFile(str(path)) as handle:
                    page = handle.pages[0]
                    shape, dtype = tuple(page.shape), page.dtype
            else:
                import numpy as np
                from PIL import Image
                with Image.open(path) as image:
                    array = np.asarray(image)
                shape, dtype = array.shape, array.dtype
        except Exception:                                    # noqa: BLE001
            unreadable += 1
            continue
        seen[(tuple(shape), str(dtype))] += 1

    types = [dict(_describe(shape, dtype), count=count)
             for (shape, dtype), count in seen.most_common()]
    record = {
        "folder": str(folder),
        "n_frames": len(files),
        "n_unreadable": unreadable,
        "types": types,
        "homogeneous": len(seen) == 1,
        "dominant": types[0] if types else None,
    }
    if limit:
        record["sampled"] = limit
    return record


def describe(record):
    """One line per frame type, for a person."""
    if not record["types"]:
        return f"{record['folder']}: no readable frames"
    if record["homogeneous"]:
        only = record["types"][0]
        return (f"{record['n_frames']:,} frames, all {only['shape']} "
                f"{only['dtype']}")
    parts = [f"{t['count']:,} x {t['shape']} {t['dtype']}"
             for t in record["types"]]
    return (f"{record['n_frames']:,} frames of {len(record['types'])} TYPES: "
            + "; ".join(parts))


def require_homogeneous(folder, record=None):
    """Refuse to treat a mixed folder as one series. Returns the record.

    Called by a loader BEFORE series treatment. The refusal names the split,
    because "all input arrays must have the same shape" tells the reader
    nothing they can act on.
    """
    record = record or census(folder)
    if record["homogeneous"]:
        return record
    if not record["types"]:
        raise MixedFramesError(f"{folder}: no readable frames to treat.")
    raise MixedFramesError(
        f"This folder holds more than one kind of frame, so it is not one "
        f"recording:\n  {describe(record)}\n\n"
        f"Nothing was loaded. Coercing it - keeping the majority and "
        f"dropping the rest - would silently shorten the recording and "
        f"choose which frames count. Split the folder, or name the type to "
        f"read.")
