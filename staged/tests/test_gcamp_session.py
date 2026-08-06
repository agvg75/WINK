"""Session marks survive the tool closing, and refuse what cannot be analysed.

The marks reached tool state and drove the analysis already; what they never
reached was a file. Deciding which frames are the real fluorescence take is
the expensive part of the work and it died with the window every time.

Also pins the layout that made the commit control unreachable. The buttons
existed and were correctly wired the whole time - "Accept ranges" was packed
after an expanding preview, so Tk squeezed it to one pixel on any recording
with frames of about 512 px or more. A test that only imports the module and
checks the button exists would have passed throughout.
"""
from pathlib import Path
import json
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

import gcamp_session as gs   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def raises(call, message_fragment=None):
    try:
        call()
    except gs.SessionMarkError as exc:
        return message_fragment is None or message_fragment in str(exc)
    except Exception:
        return False
    return False


print("gcamp session marks\n")

# --- the key names are the tool's, not new ones ------------------------------
m = gs.make_mark(10, 20, kind="dim (fluorescence?)")
check("a mark uses the key names gcamp_tool already produces",
      set(m) >= {"frame_start", "frame_end", "kind"},
      "inventing parallel names for one quantity is how two "
      "representations start drifting")
check("...and records whether a person or the detector drew it",
      m["origin"] == "manual" and
      gs.make_mark(1, 2, origin="detected")["origin"] == "detected")
check("an unknown origin is refused",
      raises(lambda: gs.make_mark(1, 2, origin="guessed"), "judgement"))

# --- refusals that name the consequence --------------------------------------
check("a reversed range is refused",
      raises(lambda: gs.make_mark(50, 10), "silently analyses nothing"))
check("a negative start is refused",
      raises(lambda: gs.make_mark(-1, 10), "not offsets"))
check("a non-numeric frame is refused",
      raises(lambda: gs.make_mark("start", 10)))
check("overlapping marks are refused",
      raises(lambda: gs.validate([gs.make_mark(0, 100), gs.make_mark(50, 200)]),
             "same frames to two baselines"),
      "one frame in two baselines is not two measurements")
check("an empty mark list is refused",
      raises(lambda: gs.validate([]), "says nothing"))
check("a mark past the end of the recording is refused",
      raises(lambda: gs.validate([gs.make_mark(0, 500)], frame_count=100),
             "off the end"))
check("adjacent but non-overlapping marks are fine",
      len(gs.validate([gs.make_mark(0, 99), gs.make_mark(100, 199)])) == 2)
check("marks come back sorted whatever order they went in",
      [x["frame_start"] for x in
       gs.validate([gs.make_mark(300, 400), gs.make_mark(0, 99)])] == [0, 300])

# --- the gap the tool would silently swallow ---------------------------------
(a, b), gap = gs.span([gs.make_mark(0, 99), gs.make_mark(300, 399)])
check("a disjoint selection reports the frames it will also analyse",
      (a, b) == (0, 399) and gap == 200,
      "the analysis takes one contiguous range, so 200 unmarked frames "
      "come along; saying so is the difference between a choice and a "
      "surprise")
check("a contiguous selection reports no gap",
      gs.span([gs.make_mark(0, 99)])[1] == 0)

# --- round trip ---------------------------------------------------------------
tmp = Path(tempfile.mkdtemp(prefix="wink_gcamp_"))
try:
    target = tmp / gs.DEFAULT_NAME
    marks = gs.marks_from_ranges([(120, 640), (900, 1200)], origin="manual")
    gs.save_marks(target, marks, source="D:/rig/worm3", frame_count=9000)
    check("the marks are written to disk", target.exists())

    back = gs.load_marks(target, source="D:/rig/worm3")
    check("...and read back unchanged",
          [(x["frame_start"], x["frame_end"]) for x in back["marks"]]
          == [(120, 640), (900, 1200)])
    check("...carrying the schema version",
          back["schema_version"] == gs.SCHEMA_VERSION)
    check("...and saying what the frame numbers mean",
          "0-based" in back["frame_numbering"]
          and "inclusive" in back["frame_numbering"],
          back["frame_numbering"])

    check("a file marked against another recording is refused",
          raises(lambda: gs.load_marks(target, source="D:/rig/worm7"),
                 "mean nothing against a different recording"))

    other = tmp / "other.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["tool"] = "population_swimming"
    other.write_text(json.dumps(doc), encoding="utf-8")
    check("a file from another tool is refused",
          raises(lambda: gs.load_marks(other), "numbered against a different"))

    future = tmp / "future.json"
    doc = json.loads(target.read_text(encoding="utf-8"))
    doc["schema_version"] = 99
    future.write_text(json.dumps(doc), encoding="utf-8")
    check("a newer schema is refused rather than guessed at",
          raises(lambda: gs.load_marks(future), "Refusing rather than"))

    broken = tmp / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    check("an unreadable file says so plainly",
          raises(lambda: gs.load_marks(broken), "not readable as JSON"))

    check("saving something unanalysable is refused before it reaches disk",
          raises(lambda: gs.save_marks(tmp / "never.json",
                                       [gs.make_mark(0, 10),
                                        gs.make_mark(5, 20)],
                                       source="x"))
          and not (tmp / "never.json").exists())
finally:
    shutil.rmtree(tmp, ignore_errors=True)

# --- the schema this must NOT be -------------------------------------------
import segmentation_review as sr   # noqa: E402
check("segmentation_review still forbids photometry tools",
      "single_channel_gcamp" in sr.PHOTOMETRY_EXCLUSIONS,
      "it has a versioned frame-range schema that fits this shape exactly, "
      "and may define object extent only - the structural fit is a trap")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("GCAMP_SESSION_PASS")
