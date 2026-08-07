"""The frame range crosses the module boundary instead of being re-asked.

FOUND IN USE, 7 Aug 2026. The GCaMP tool assessed a committed frame range,
reported it usable, and offered "analyze kinematics using single worm
tracker". Clicking that opened the tracker, which asked for the frame range
again - from a slider. A slider cannot reliably land on an exact frame, the
review state is stored PER FRAME, and the near-miss then read as a frame
count mismatch that ended the tool.

The handoff existed and dropped the range: it passed the recording path
alone. Worse, there was nothing to pass it TO - the tracker's CLI took only
`source` and `--ignore-border-objects`. Unwired at both ends.

The exactness requirement is legitimate, so the fix is to TRANSMIT the range,
not to loosen the check. This pins the transmission, the 0-based to 1-based
conversion across the boundary, and the refusal to clamp a range that does
not fit.
"""
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"),
                str(ROOT / "tools" / "worm_kinematics" / "dic_tracker")]

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


# Imported by source rather than executed: run_dic_kinematics pulls in the
# whole tracker stack at import time and this needs one pure function.
SOURCE = (ROOT / "tools" / "worm_kinematics" / "dic_tracker"
          / "run_dic_kinematics.py").read_text(encoding="utf-8")
start = SOURCE.index("def _inherited_interval")
end = SOURCE.index("def _choose_analysis_interval")
module = types.ModuleType("inherited")
exec(compile(SOURCE[start:end], "run_dic_kinematics.py", "exec"),
     module.__dict__)
_inherited_interval = module._inherited_interval


def args(first=None, last=None):
    return types.SimpleNamespace(frame_start=first, frame_end=last)


print("\n--- a range given is a range used ------------------------------")

check("no range means the slider still runs",
      _inherited_interval(args(), 500) is None,
      "launching the tracker directly must be unaffected")

check("1-based in, 0-based inclusive out",
      _inherited_interval(args(101, 400), 500) == (100, 399),
      "the tool stores 0-based; the tracker shows 1-based to the user")

check("the whole recording round-trips",
      _inherited_interval(args(1, 500), 500) == (0, 499))

check("a single-frame-short range is still honoured exactly",
      _inherited_interval(args(1, 499), 500) == (0, 498),
      "off by one here is the entire bug being fixed")

print("\n--- a range that does not fit is REFUSED, never clamped --------")

for first, last, why in ((1, 501, "end past the recording"),
                         (0, 100, "start below frame 1"),
                         (400, 100, "end before start"),
                         (501, 502, "wholly outside")):
    raised = False
    try:
        _inherited_interval(args(first, last), 500)
    except SystemExit:
        raised = True
    check(f"{why} is refused", raised, f"{first}-{last} of 500")

check("...and the refusal explains why nothing was analysed",
      "not trimmed to fit" in SOURCE,
      "analysing a different span than was assessed reports the wrong "
      "frames under the right label")

raised = False
try:
    _inherited_interval(args(10, 11), 500)
except SystemExit:
    raised = True
check("a range under 3 frames is refused", raised, "too short to track")

print("\n--- half a range is not a range --------------------------------")

for first, last in ((100, None), (None, 400)):
    raised = False
    try:
        _inherited_interval(args(first, last), 500)
    except SystemExit:
        raised = True
    check(f"start={first} end={last} is refused", raised,
          "a half specified range cannot be inherited")

print("\n--- the caller actually sends it -------------------------------")

TOOL = (ROOT / "tools" / "single_channel_gcamp"
        / "gcamp_tool.py").read_text(encoding="utf-8")
handoff = TOOL[TOOL.index("def _handoff_to_tracker"):]
handoff = handoff[:handoff.index("\n    def ")] if "\n    def " in handoff \
    else handoff

check("the handoff passes --frame-start and --frame-end",
      "--frame-start" in handoff and "--frame-end" in handoff,
      "it used to pass the recording path alone")
check("...converting 0-based to 1-based",
      "first + 1" in handoff and "last + 1" in handoff)
check("...from the committed episode_range",
      "episode_range" in handoff)
check("...and still works when nothing was committed",
      "if episode:" in handoff,
      "an uncommitted range must not crash the handoff")

print("\n--- the tracker advertises the flags ---------------------------")

check("--frame-start is a real CLI argument", '"--frame-start"' in SOURCE)
check("--frame-end is a real CLI argument", '"--frame-end"' in SOURCE)
check("the interval chooser is skipped when a range is inherited",
      "if inherited is not None:" in SOURCE)
check("...and the note records that it was inherited",
      "inherited from the calling tool" in SOURCE,
      "so the CSV says which frames were analysed and why")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("TRACKER_HANDOFF_PASS")
