"""Closing repro for fix A: does the `g` key hand over the right span?

THE DAY-ONE FOOTAGE, recorded here because it was already lost once - it
lived only in a tracker command line during the provenance diagnostic, and
nothing in the repository named it:

    L:\\02_Duchenne Muscular Dystrophy\\Kiley\\12221_GCaMP2 check\\AVG6
    8,999 frames, dys-1(eg33) I.; Pmyo-3::GCaMP2, failing range 1-234

    py tools\\repro\\fix_a_repro.py ^
       --source "L:\\02_Duchenne Muscular Dystrophy\\Kiley\\12221_GCaMP2 check\\AVG6" ^
       --frame-start 1 --frame-end 234

NOT the only AVG6 on the drive. `Undergraduate Students\\Carlees Worms\\AVG6`
is a different recording of 1,262 frames, and this repro was first run against
it by mistake - a clean PASS about the wrong footage. AVG6 is a STRAIN, so
every person who imaged it made a folder of that name. See
ARCHIVE_NAVIGATOR_SPEC.md §6.1.

THE DEFECT BEING CLOSED. Pressing `g` in the tracker sent
`session_path.parent.parent` - a directory derived from wherever the session
file happened to sit - and no frame range at all. The workbench opened on a
folder with no images and said so, which was true and useless; when it did
open, it sampled the whole recording rather than the span the tracker was
working on.

WHAT THIS CHECKS WITHOUT A HUMAN. It rebuilds the context exactly as
`Reviewer.review_segmentation` does, then opens the recording and computes
the frames the workbench WOULD sample. If the last sampled frame is inside
the requested range, the handoff carried the span. That is the machine half,
and it is the half that can be automated.

WHAT IT CANNOT CHECK. That a window appears, is legible, and shows the right
footage. `--launch` starts the real workbench so a person can look. The
visual step is the item the 168 passing checks prove least - the same reason
the publish spec asks for a two-minute eyeball after each release.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "movie"))

from analysis_context import (                     # noqa: E402
    AnalysisContext, ContextError, sample_indices)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True,
                    help="The recording as the tracker would load it.")
    ap.add_argument("--frame-start", type=int, default=None)
    ap.add_argument("--frame-end", type=int, default=None)
    ap.add_argument("--launch", action="store_true",
                    help="Open the real workbench so a person can look.")
    args = ap.parse_args()

    print(f"source           {args.source}")
    try:
        context = AnalysisContext(
            source=args.source, tool="single_worm_tracker",
            frame_start=args.frame_start, frame_end=args.frame_end,
            note="fix A closing repro")
    except ContextError as exc:
        print(f"\nREFUSED building the context: {exc}")
        return 1
    print(f"handing over     {context.describe_range()}")

    # What the workbench will actually read.
    movie = None
    try:
        from movie_reader import open_movie
        movie = open_movie(args.source)
        count = int(getattr(movie, "n_frames",
                            getattr(movie, "frame_count", 0)))
    except Exception as exc:                                 # noqa: BLE001
        print(f"\nCould not open the recording: {exc}")
        print("This is the ORIGINAL SYMPTOM if the source is wrong - the "
              "workbench opening on something with no readable frames.")
        return 1
    print(f"recording holds  {count:,} frames")

    # THE TOOL'S OWN SAMPLE LIMIT, not a round number of my choosing. The
    # first version hard-coded 30 and reported "would sample 30 frames" while
    # the workbench actually loads 81 - so the repro was describing something
    # the tool does not do. A repro that models the tool loosely can pass
    # while the tool fails, which makes it worse than no repro.
    try:
        read_frame = getattr(movie, "get_frame", None) or movie.read_frame
        import numpy as np
        per_frame = max(int(np.asarray(read_frame(0)).nbytes), 1)
        limit = max(3, min(81, (512 * 1024 ** 2) // per_frame))
    except Exception:                                        # noqa: BLE001
        limit = 81
    print(f"sample limit     {limit} (as the workbench computes it)")

    try:
        indices = sample_indices(count, limit, context)
    except ContextError as exc:
        print(f"\nREFUSED: {exc}")
        return 1
    finally:
        try:
            movie.close()
        except Exception:                                    # noqa: BLE001
            pass

    print(f"would sample     {len(indices)} frames, "
          f"{indices[0] + 1} to {indices[-1] + 1} (1-based)")

    if context.has_range:
        inside = (indices[0] >= context.frame_start - 1
                  and indices[-1] <= context.frame_end - 1)
        print(f"\n{'PASS' if inside else 'FAIL'}  the sample stays inside the "
              f"handed-over range")
        if not inside:
            return 1
    else:
        spans = indices[-1] == count - 1
        print(f"\n{'PASS' if spans else 'FAIL'}  no range was given, so the "
              f"whole recording is sampled")
        if not spans:
            return 1

    if args.launch:
        path = context.write_temp()
        command = [sys.executable,
                   str(ROOT / "tools" / "segmentation_review_tool.py"),
                   args.source, "--tool", "track_one_worm",
                   "--context", str(path)]
        print("\nlaunching the workbench - LOOK AT IT:")
        print("  " + " ".join(f'"{c}"' if " " in c else c for c in command))
        print("\n  Confirm: it opens on this recording, and the frames it "
              "shows are inside the range above.")
        subprocess.run(command, check=False)
        try:
            Path(path).unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
