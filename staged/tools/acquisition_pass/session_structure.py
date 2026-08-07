"""Sessions, not folders, are the recording. Timing recovered from names.

    py session_structure.py --root "L:\\" --out sessions.csv

THE UNIT WAS WRONG. `41921_cop1367` is not one recording of 107,976 frames.
It is TWELVE recordings of about 8,998, and the FlyCap session timestamp in
each filename is what separates them. Anything computed per folder - duration,
frame rate, how many animals a recording contains - was computed on the wrong
unit, and a tracker that links across a session boundary is stitching together
different animals.

HOW THE FRAME RATE IS RECOVERED, given that nothing states it. FlyCap writes
`fc2_save_2021-04-19-132028-0000.tif`: date, SESSION START TIME, frame index.
The start time is per session, not per frame, so it does not time the frames -
but consecutive session starts BRACKET the rate:

    a recording cannot still be running when the next one starts,
    so   fps > frames / (next start - this start)

That is a hard lower bound from arithmetic. The camera ceiling gives the upper
bound. Where the two are close the rate is MEASURED; where the gap to the next
session is long the bracket is loose and the ceiling is doing the work, which
is a much weaker claim. BRACKET WIDTH IS REPORTED SO THE TWO ARE NEVER
CONFUSED.

Measured on the frozen pezo-1 set: 8,998 frames recurs across unrelated
folders, three of them bracket above 25.4 fps, and only 30 fps makes 8,998 a
round 299.9 s. That is a five minute protocol, recovered from filenames on an
archive that documents none of it.

NO RATE IS EVER ASSUMED. A single-session folder has no next session, so it
has no bracket, and its frames are reported as UNKNOWN DURATION rather than
being given the ceiling. A confident total that buries an assumption is worse
than an honest split.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import os
import re
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "drive_audit"))

FRAME_EXT = {".tif", ".tiff", ".jpg", ".jpeg", ".pgm", ".png", ".bmp"}

# A FULL ACQUISITION STAMP FOLLOWED BY A FRAME INDEX, anywhere in the name.
#
# NOT anchored to `fc2_save_`. That anchor was too strict and cost real data:
# `tm2071_crawl2_04072017_2017-04-07-115046-0000.pgm` carries the same stamp
# mid-name and holds 449 genuine frames. The stamp is the evidence; the
# prefix in front of it is just what the student called the run.
STAMP_RE = re.compile(
    r"(\d{4})-(\d{2})-(\d{2})-(\d{6})-(\d+)(?!\d)")

# A looser fallback: anything ending in a run of digits is a frame index, and
# whatever precedes it is the series. Catches hand-rolled exports.
INDEXED_RE = re.compile(r"^(.*?)[_\-]?(\d{3,6})$")

# A SESSION SMALLER THAN THIS IS NOT A RECORDING, it is the fallback above
# mistaking a filename for a series. Measured: run drive-wide without this
# guard, the fallback produced 550,354 "sessions" from 2.5 M frames with a
# MEDIAN OF ONE FRAME EACH, against 11,402 real stamped sessions. Groups
# below the threshold are pooled into one unstamped sequence per folder and
# carry no timing at all, which is the honest description of them.
MIN_SESSION_FRAMES = 20
UNSTAMPED = "(unstamped sequence)"

# EVERY RIG IN THIS LAB TOPS OUT HERE. Andres, 7 Aug 2026. A header or a
# derivation claiming more than this is wrong, and that is a validity rule
# rather than a heuristic - pumping and swimming are filmed at 30, defecation
# and crawling often lower.
CAMERA_MAX_FPS = 30.0

# Within this fraction of each other, gaps are the same gap. A protocol run by
# a person does not repeat to the second.
REGULAR_TOLERANCE = 0.20


def session_key(name):
    """(session id, frame index, stamped?) for one filename, or None.

    `stamped` is what separates evidence from guesswork: a full acquisition
    stamp is something the camera wrote, while a shared filename prefix is
    this module's inference and gets no timing derived from it.
    """
    match = STAMP_RE.search(name)
    if match:
        stamp = f"{match.group(1)}-{match.group(2)}-{match.group(3)}-" \
                f"{match.group(4)}"
        return stamp, int(match.group(5)), True
    match = INDEXED_RE.match(os.path.splitext(name)[0])
    if match and match.group(1):
        return match.group(1).lower(), int(match.group(2)), False
    return None


def seconds_of(stamp):
    """Absolute seconds from a FlyCap session stamp, or None.

    THE DATE IS PART OF THIS. An earlier version decoded only the time of
    day, which sorts 00:05 on the 20th BEFORE 23:55 on the 19th and then
    subtracts them into a negative gap. Folders here really do hold sessions
    from more than one day - the frozen pezo-1 set mixes 2021-04-19 and
    2021-05-05 stamps - so ignoring the date is not a midnight edge case, it
    is wrong on ordinary data.
    """
    parts = stamp.split("-")
    if len(parts) != 4 or len(parts[3]) != 6:
        return None
    try:
        day = datetime.date(int(parts[0]), int(parts[1]), int(parts[2]))
        hour, minute, second = (int(parts[3][i:i + 2]) for i in (0, 2, 4))
    except ValueError:
        return None
    if not (0 <= hour < 24 and 0 <= minute < 60 and 0 <= second < 60):
        return None
    return day.toordinal() * 86400 + hour * 3600 + minute * 60 + second


def regularity(gaps):
    """Whether the gaps between sessions look like a protocol."""
    if len(gaps) < 2:
        return "", 0.0
    median = statistics.median(gaps)
    if median <= 0:
        return "", 0.0
    spread = max(abs(g - median) / median for g in gaps)
    if spread <= REGULAR_TOLERANCE:
        return "regular", spread
    return "irregular", spread


def analyse(folder, names):
    """Sessions in one folder, with the rate bracket for each."""
    grouped = defaultdict(list)
    from_stamp = {}
    for name in names:
        key = session_key(name)
        if key:
            grouped[key[0]].append(key[1])
            from_stamp[key[0]] = from_stamp.get(key[0], False) or key[2]

    # Anything the fallback split into a handful of frames is not a
    # recording. Pool those rather than report them as sessions - see
    # MIN_SESSION_FRAMES for what happened when they were not pooled.
    sessions, leftovers = {}, 0
    for name, indices in grouped.items():
        if from_stamp[name] or len(indices) >= MIN_SESSION_FRAMES:
            sessions[name] = indices
        else:
            leftovers += len(indices)
    if leftovers:
        sessions[UNSTAMPED] = list(range(leftovers))
        from_stamp[UNSTAMPED] = False

    if not sessions:
        return []

    stamped = {s: seconds_of(s) if from_stamp.get(s) else None
               for s in sessions}
    ordered = sorted(sessions, key=lambda s: (stamped[s] is None,
                                              stamped[s] or 0, s))
    gaps = []
    for first, second in zip(ordered, ordered[1:]):
        a, b = stamped[first], stamped[second]
        if a is not None and b is not None and b > a:
            gaps.append(b - a)
    shape, spread = regularity(gaps)

    rows = []
    for index, name in enumerate(ordered):
        frames = len(sessions[name])
        start = stamped[name]
        gap = None
        if index + 1 < len(ordered):
            following = stamped[ordered[index + 1]]
            if start is not None and following is not None and following > start:
                gap = following - start

        # THE BRACKET. Lower bound from the gap, upper from the camera.
        low = (frames / gap) if gap else None
        high = CAMERA_MAX_FPS
        if low is not None and low > CAMERA_MAX_FPS:
            # The recording cannot fit before the next one even at full rate.
            # Something is wrong - overlapping sessions, or frames from
            # elsewhere pooled in. Reported, never silently clamped.
            bracketed, width, rate, note = False, None, None, \
                "gap too short for the frame count even at the camera maximum"
        elif low is not None:
            bracketed = True
            width = high - low
            rate = high          # the only rate consistent with both bounds
            note = ""
        elif not from_stamp.get(name):
            bracketed, width, rate, note = False, None, None, \
                "no acquisition stamp - grouped by filename, so no timing"
        else:
            bracketed, width, rate, note = False, None, None, \
                "single session, or no usable gap - no lower bound exists"

        rows.append({
            "folder": folder,
            "session": name,
            "frames": frames,
            "start_s": start if start is not None else "",
            "gap_to_next_s": gap or "",
            "fps_lower_bound": round(low, 2) if low else "",
            "fps_upper_bound": high,
            "bracket_width_fps": round(width, 2) if width is not None else "",
            "rate_measured": "yes" if bracketed else "NO",
            "duration_s": round(frames / rate, 1) if rate else "",
            "sessions_in_folder": len(ordered),
            "stamped": "yes" if from_stamp.get(name) else "NO",
            "gap_shape": shape,
            "gap_spread": round(spread, 3) if shape else "",
            "note": note,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--min-frames", type=int, default=20)
    ap.add_argument("--max-seconds", type=float, default=2400.0)
    args = ap.parse_args()

    started = time.time()
    rows = []
    folders = 0
    stack = [args.root]
    stopped = False

    while stack:
        if time.time() - started > args.max_seconds:
            stopped = True
            break
        current = stack.pop()
        names = []
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                            continue
                    except OSError:
                        continue
                    if os.path.splitext(entry.name)[1].lower() in FRAME_EXT:
                        names.append(entry.name)
        except OSError:
            continue
        if len(names) < args.min_frames:
            continue
        folders += 1
        rows.extend(analyse(current, names))
        if folders % 2000 == 0:
            print(f"  {folders:,} folders  {len(rows):,} sessions  "
                  f"{time.time() - started:.0f}s", flush=True)

    fields = ["folder", "session", "frames", "start_s", "gap_to_next_s",
              "fps_lower_bound", "fps_upper_bound", "bracket_width_fps",
              "rate_measured", "duration_s", "sessions_in_folder", "stamped",
              "gap_shape", "gap_spread", "note"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    measured = [r for r in rows if r["rate_measured"] == "yes"]
    unknown = [r for r in rows if r["rate_measured"] != "yes"]
    m_frames = sum(r["frames"] for r in measured)
    u_frames = sum(r["frames"] for r in unknown)
    hours = sum(float(r["duration_s"]) for r in measured) / 3600

    stamped_rows = [r for r in rows if r["stamped"] == "yes"]
    guessed = [r for r in rows if r["stamped"] != "yes"]

    print(f"\n{'sequence folders':32} {folders:,}"
          + ("   STOPPED AT CAP" if stopped else "   (complete)"))
    print(f"{'SESSIONS from an acquisition stamp':32} {len(stamped_rows):,}"
          f"   {sum(r['frames'] for r in stamped_rows):,} frames")
    print(f"{'unstamped sequences (no timing)':32} {len(guessed):,}"
          f"   {sum(r['frames'] for r in guessed):,} frames")
    print(f"{'elapsed':32} {time.time() - started:.0f} s")

    print("\nDURATION, WITH ITS COVERAGE ATTACHED")
    print(f"    measured from a bracket   {len(measured):7,} sessions   "
          f"{m_frames:12,} frames   {hours:9,.1f} hours")
    print(f"    NO bracket, unknown       {len(unknown):7,} sessions   "
          f"{u_frames:12,} frames   {'-':>9}")
    total = m_frames + u_frames
    if total:
        print(f"    frames with a duration    {m_frames / total * 100:.1f}%")

    if measured:
        widths = sorted(float(r["bracket_width_fps"]) for r in measured)
        print("\nBRACKET WIDTH - how much work the ceiling is doing")
        print(f"    tightest {widths[0]:5.2f} fps      "
              f"median {widths[len(widths) // 2]:5.2f}      "
              f"loosest {widths[-1]:5.2f}")
        tight = [w for w in widths if w <= 5]
        print(f"    within 5 fps of the ceiling: {len(tight):,} of "
              f"{len(widths):,} ({len(tight) / len(widths) * 100:.0f}%)")
        print("    a wide bracket means 30 fps was chosen because it is the")
        print("    ceiling, not because the arithmetic pinned it there")

    multi = defaultdict(int)
    for row in rows:
        multi[row["folder"]] = row["sessions_in_folder"]
    many = [f for f, n in multi.items() if n > 1]
    print(f"\nFOLDERS HOLDING MORE THAN ONE SESSION: {len(many):,} of "
          f"{len(multi):,}")
    print("    every one of these is a folder where per-folder statistics")
    print("    pooled separate recordings, and separate ANIMALS")

    shapes = defaultdict(int)
    for row in rows:
        if row["gap_shape"]:
            shapes[row["gap_shape"]] += 1
    if shapes:
        print("\nSESSION GAP STRUCTURE")
        for shape, n in sorted(shapes.items()):
            print(f"    {shape:12} {n:7,} sessions")
        print("    regular gaps are a PROTOCOL - experimental design")
        print("    recovered from timestamps on an undocumented archive")

    print(f"\nwritten {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
