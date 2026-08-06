"""Montage frame selection: context on both sides, and honesty when there isn't.

A montage exists so a person can judge a flagged span by eye. Frames from
inside the span show what was flagged; frames from either side show what it is
being judged against. A span at the very start or end of a recording has no
context on one side - and silently dropping that side would let a reader think
they had compared both.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "batch_inspection"))

import montage as mo   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("montage - regression\n")

N = 500
mid = mo.sample_frames({"start_frame": 100, "end_frame": 120}, N)

check("frames are drawn from inside the flagged span",
      all(100 <= f <= 120 for f in mid["inside"]) and len(mid["inside"]) == 4)
check("...spanning it end to end, not clustered",
      min(mid["inside"]) == 100 and max(mid["inside"]) == 120)
check("context frames come from BOTH sides",
      mid["before"] == [98, 99] and mid["after"] == [121, 122],
      "the span is judged against what surrounds it")
check("...and neither side is flagged missing",
      mid["no_before"] is False and mid["no_after"] is False)

end = mo.sample_frames({"start_frame": 480, "end_frame": 499}, N)
check("a span at the end of the recording has no 'after'",
      end["after"] == [])
check("...and SAYS so rather than dropping it silently",
      end["no_after"] is True,
      "otherwise a reader thinks they compared both sides")
check("...while still giving the 'before' side", end["before"] == [478, 479])

start = mo.sample_frames({"start_frame": 0, "end_frame": 10}, N)
check("a span at the start has no 'before', and says so",
      start["before"] == [] and start["no_before"] is True)
check("...while still giving the 'after' side", start["after"] == [11, 12])

one = mo.sample_frames({"start_frame": 50, "end_frame": 50}, N)
check("a single-frame span still yields one inside frame",
      one["inside"] == [50],
      "a span of one is exactly the case worth looking at by eye")

wide = mo.sample_frames({"start_frame": 10, "end_frame": 400}, N, inside=6)
check("the number of inside frames is controllable",
      len(wide["inside"]) == 6)
check("...and they still span the whole flagged region",
      min(wide["inside"]) == 10 and max(wide["inside"]) == 400)

deep = mo.sample_frames({"start_frame": 100, "end_frame": 120}, N, outside=4)
check("more context can be asked for on both sides",
      len(deep["before"]) == 4 and len(deep["after"]) == 4)

check("frame indices never go negative",
      all(f >= 0 for f in start["after"] + start["inside"]))
check("frame indices never exceed the recording",
      all(f < N for f in end["before"] + end["inside"] + end["after"]))

check("the module states why both sides matter",
      "would let a reader think they had compared both"
      in mo.sample_frames.__doc__)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("MONTAGE_PASS")
