"""A saved review session that does not fit must never end the tool.

THE TRAP, found in use on 7 Aug 2026 and present in TWO tools line for line:

    except Exception as exc:
        messagebox.showerror("Resume failed", str(exc)); return

Starting fresh was always available and the tool knew it, so a mismatch ended
the sitting instead of costing one file. Anyone who hits that concludes the
tool is broken and works around it silently - which is why this is pinned
rather than left to review.

THE CHECK ITSELF STAYS STRICT, and these tests exist partly to stop anyone
loosening it later. `states` is POSITIONAL: one entry per frame, indexed by
frame number. Applying a 500-entry array to a 520-frame stack does not fail,
it silently misaligns every corrected spine, and the output looks like data.
That is worse than any refusal.
"""
from pathlib import Path
import json
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

import tracker_review_session as trs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


class FakeTracker:
    def __init__(self, frames):
        self.T = frames
        self.state = [{"needs_help": 0, "provenance": "measured"}
                      for _ in range(frames)]
        self.len_ref = None
        self.area_ref = None


SOURCE = {"recording_key": "vid_01", "first_frame": "a.tif",
          "last_frame": "z.tif", "frame_count": 500}


def write_session(folder, frames, corrections=0, tool="single_worm_tracker"):
    tracker = FakeTracker(frames)
    for i in range(corrections):
        tracker.state[i]["provenance"] = "manual"
    # A DISTINCT NAME PER SESSION. Writing them all to one path let a later
    # fixture silently overwrite the one under test, and two checks failed
    # against a file that was no longer the file they were written for.
    path = Path(folder) / f"session_{frames}_{corrections}_{tool}.json"
    trs.save_tracker_session(path, tracker, tool=tool, source=SOURCE)
    return path


with tempfile.TemporaryDirectory() as folder:

    print("\n--- the strict check, which must stay strict ------------------")

    path = write_session(folder, 500, corrections=37)
    ok = trs.load_tracker_session(path, FakeTracker(500),
                                  tool="single_worm_tracker", source=SOURCE)
    check("a session matching the frame count loads", bool(ok))

    raised = ""
    try:
        trs.load_tracker_session(path, FakeTracker(520),
                                 tool="single_worm_tracker", source=SOURCE)
    except ValueError as exc:
        raised = str(exc)
    check("500 states are REFUSED for a 520-frame stack",
          "frame count" in raised,
          "positional states silently misalign otherwise - never loosen this")

    raised = ""
    try:
        trs.load_tracker_session(path, FakeTracker(500),
                                 tool="neuron_tracker", source=SOURCE)
    except ValueError as exc:
        raised = str(exc)
    check("another tool's session is refused", "different tool" in raised)

    print("\n--- the offer names what discarding it would cost -------------")

    facts = trs.describe(path)
    check("describe reads a session it could not load",
          facts["frame_count"] == 500 and facts["corrections"] == 37,
          f"{facts['corrections']} hand-corrected frames")
    check("...counts only MANUAL frames as corrections",
          trs.describe(write_session(folder, 100, corrections=0))
          ["corrections"] == 0,
          "needs_help is the tracker's flag, not a person's work")
    check("...and records when it was saved", bool(facts["saved_utc"]))
    check("describe returns None for an unreadable file",
          trs.describe(Path(folder) / "nope.json") is None)

    text = trs.summarise(path)
    check("the summary names frames and corrections",
          "500" in text and "37" in text, text[:78])
    check("one correction is not pluralised",
          "1 hand-corrected frame," in trs.summarise(
              write_session(folder, 60, corrections=1)))

    print("\n--- a mismatch costs the file, never the sitting --------------")

    asked = []

    def yes(title, message):
        asked.append((title, message))
        return True

    def no(title, message):
        asked.append((title, message))
        return False

    def inform(title, message):
        asked.append((title, message))

    asked.clear()
    resumed = trs.resume_or_start_fresh(
        path, FakeTracker(520), tool="single_worm_tracker", source=SOURCE,
        confirm=yes, inform=inform)
    check("a session that does not fit returns False, not an exception",
          resumed is False,
          "this is the whole fix - the tool continues and tracks fresh")
    check("...and the offer explains the mismatch",
          any("does not fit" in title for title, _ in asked))
    check("...naming the frames and corrections at stake",
          any("hand-corrected" in message for _, message in asked))
    check("...and saying the file is not overwritten",
          any("not overwritten" in message for _, message in asked))

    asked.clear()
    resumed = trs.resume_or_start_fresh(
        path, FakeTracker(500), tool="single_worm_tracker", source=SOURCE,
        confirm=yes, inform=inform)
    check("a session that DOES fit still resumes", resumed is True)

    asked.clear()
    resumed = trs.resume_or_start_fresh(
        path, FakeTracker(500), tool="single_worm_tracker", source=SOURCE,
        confirm=no, inform=inform)
    check("declining to resume starts fresh rather than failing",
          resumed is False)

    check("no saved session at all is simply a fresh start",
          trs.resume_or_start_fresh(
              Path(folder) / "absent.json", FakeTracker(10),
              tool="single_worm_tracker", source=SOURCE,
              confirm=yes, inform=inform) is False)

    # Declining the fresh start is the ONLY exit, and it is the user's choice
    # rather than the tool's.
    exited = False
    try:
        trs.resume_or_start_fresh(
            path, FakeTracker(520), tool="single_worm_tracker", source=SOURCE,
            confirm=no if len(asked) else no, inform=inform)
    except SystemExit:
        exited = True
    check("declining BOTH resume and fresh start does not exit",
          not exited,
          "declining to resume is a fresh start, not a refusal to continue")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("TRACKER_REVIEW_SESSION_PASS")
