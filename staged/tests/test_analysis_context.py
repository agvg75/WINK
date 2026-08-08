"""The analysis context: what one tool tells another about what is analysed.

Fix "A". Two live defects came from callers reconstructing a fact they already
held - the GCaMP handoff forgot the frame range, the tracker's `g` key sent a
directory derived from where a session file sat instead of the recording as
loaded. So the tests care about exactly those two fields and about refusing
rather than repairing anything doubtful.
"""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

from analysis_context import (                     # noqa: E402
    AnalysisContext, ContextError, SCHEMA, add_argument, from_arguments)

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def refuses(make):
    try:
        make()
    except ContextError as exc:
        return str(exc)
    return ""


print("analysis context - what travels between tools\n")

tmp = Path(tempfile.mkdtemp(prefix="wink_ctx_"))

# ----------------------------------------------------------- the essentials
ctx = AnalysisContext(source=r"D:\rec\worm1", tool="single_worm_tracker",
                      frame_start=1, frame_end=234, fps=30.0)
check("a context carries the recording as loaded", ctx.source == r"D:\rec\worm1")
check("and the frame range, both ends", ctx.has_range)
check("the range counts inclusively, the way a person reads frame numbers",
      ctx.frame_count() == 234, ctx.frame_count())
check("and describes itself in the caller's numbers",
      ctx.describe_range() == "frames 1-234 (234 frames)", ctx.describe_range())

whole = AnalysisContext(source="x")
check("no range means the whole recording, said plainly rather than as a "
      "silent None", whole.describe_range() == "the whole recording")
check("and frame_count is None, not zero - unknown is not a quantity",
      whole.frame_count() is None)

# --------------------------------------------------------------- refusals
message = refuses(lambda: AnalysisContext(source=""))
check("a context with NO SOURCE is refused - this is the `g` key defect, "
      "where a derived directory stood in for the recording", bool(message))
check("and the refusal explains what a source must be, not merely that one "
      "is missing", "AS LOADED" in message, message[:80])

check("a source of only whitespace is refused too",
      bool(refuses(lambda: AnalysisContext(source="   "))))

message = refuses(lambda: AnalysisContext(source="x", frame_start=5))
check("HALF A RANGE IS REFUSED - the receiver would have to invent the other "
      "end and would analyse a span nobody assessed", bool(message))
check("and so is the other half",
      bool(refuses(lambda: AnalysisContext(source="x", frame_end=5))))
check("a backwards range is refused",
      bool(refuses(lambda: AnalysisContext(source="x", frame_start=9,
                                           frame_end=2))))
check("a zero or negative start is refused, because frames are 1-based here "
      "and an off-by-one in a handoff is invisible",
      bool(refuses(lambda: AnalysisContext(source="x", frame_start=0,
                                           frame_end=5))))

# ---------------------------------------------------------- unknown is None
bare = AnalysisContext(source="x")
check("an unknown frame rate is None, never a plausible default - a filled-in "
      "30 fps would be indistinguishable from a measured one",
      bare.fps is None and bare.um_per_px is None)

# --------------------------------------------------------- round trip
path = ctx.write(tmp / "ctx.json")
again = AnalysisContext.read(path)
check("a context survives a write and read unchanged",
      again.to_dict() == ctx.to_dict())
check("the file records its schema, so a future reader knows what it holds",
      json.loads(path.read_text(encoding="utf-8"))["schema"] == SCHEMA)

temp_path = ctx.write_temp()
check("a temp context can be written for a single subprocess call",
      Path(temp_path).is_file())
check("and the command arguments name it",
      ctx.command_arguments(temp_path) == ["--context", str(temp_path)])
Path(temp_path).unlink()

# ------------------------------------------------------- schema discipline
future = json.loads(path.read_text(encoding="utf-8"))
future["schema"] = SCHEMA + 1
future["some_new_field"] = "which this version cannot interpret"
(tmp / "future.json").write_text(json.dumps(future), encoding="utf-8")
message = refuses(lambda: AnalysisContext.read(tmp / "future.json"))
check("A NEWER SCHEMA FAILS LOUDLY. Reading the fields we recognise and "
      "ignoring the rest is precisely how a frame range goes missing - the "
      "defect this module exists to fix, one layer down", bool(message))
check("and the refusal names both versions so the reader knows which end is "
      "stale", str(SCHEMA + 1) in message and str(SCHEMA) in message,
      message[:90])

older = json.loads(path.read_text(encoding="utf-8"))
older["schema"] = SCHEMA
older["unknown_extra"] = 1
(tmp / "older.json").write_text(json.dumps(older), encoding="utf-8")
check("an unexpected field at the CURRENT schema is tolerated - only a newer "
      "schema is a refusal",
      AnalysisContext.read(tmp / "older.json").source == ctx.source)

(tmp / "broken.json").write_text("{not json", encoding="utf-8")
check("a corrupt context is refused with a readable reason, not a traceback",
      "JSON" in refuses(lambda: AnalysisContext.read(tmp / "broken.json")))
check("a missing context file is refused rather than treated as empty",
      bool(refuses(lambda: AnalysisContext.read(tmp / "absent.json"))))

# ------------------------------------------------------- sampling a span
from analysis_context import sample_indices                  # noqa: E402

everything = sample_indices(9000, 30)
check("with no context the sample spans the whole recording",
      everything[0] == 0 and everything[-1] == 8999, (everything[0], everything[-1]))

ranged = sample_indices(9000, 30, AnalysisContext(
    source="x", frame_start=1, frame_end=234))
check("WITH a range the sample stays inside it - sampling 30 frames across "
      "8,999 when only 234 were assessed once produced an 18-fold apparent "
      "swing that was just the animal being absent",
      ranged[0] == 0 and ranged[-1] == 233, (ranged[0], ranged[-1]))
check("and the sample is spread across the range, not bunched at one end",
      len(ranged) == 30 and len(set(ranged)) == 30, len(ranged))

mid = sample_indices(9000, 5, AnalysisContext(
    source="x", frame_start=500, frame_end=600))
check("a range that does not start at frame 1 is honoured at both ends",
      mid[0] == 499 and mid[-1] == 599, (mid[0], mid[-1]))

short = sample_indices(9000, 50, AnalysisContext(
    source="x", frame_start=10, frame_end=12))
check("a range shorter than the sample limit yields every frame in it once, "
      "not a padded or repeated list", short == [9, 10, 11], short)

message = refuses(lambda: sample_indices(100, 10, AnalysisContext(
    source="x", frame_start=1, frame_end=234)))
check("A RANGE THAT DOES NOT FIT IS REFUSED, NOT CLAMPED. Trimming would "
      "measure a different span and report it under the caller's numbers",
      bool(message))
check("and the refusal states both the request and what is there",
      "234" in message and "100" in message, message[:100])
check("an empty recording is refused rather than sampled",
      bool(refuses(lambda: sample_indices(0, 10))))

# ------------------------------------------------------------ command line
import argparse                                              # noqa: E402
parser = argparse.ArgumentParser()
add_argument(parser)
args = parser.parse_args(["--context", str(path)])
check("a receiving tool gets --context in one line",
      from_arguments(args).source == ctx.source)
check("and no context is None rather than an error, so a tool opened directly "
      "still works", from_arguments(parser.parse_args([])) is None)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ANALYSIS_CONTEXT_PASS")
