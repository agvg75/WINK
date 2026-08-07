"""Sessions are the recording, and no frame rate is ever assumed.

Every filename here is a real one from the frozen pezo-1 set.

THE DEFECT PINNED. `41921_cop1367` was read as one recording of 107,976
frames. It is TWELVE recordings of about 8,998, separated by the FlyCap
session timestamp. Everything computed per folder - duration, rate, how many
animals a recording holds - was computed on the wrong unit, and the 99.4%
single-animal figure drew 60 frames from folders spanning up to 18 animals.

THE RATE DERIVATION. Nothing on this drive states a frame rate. A recording
cannot still be running when the next one starts, so

    fps > frames / (next session start - this session start)

is a hard lower bound from arithmetic alone, and the camera ceiling is the
upper bound. Measured on the real set: the five tightest sessions bound the
rate above 25.1-26.2 fps against a 30 fps ceiling, which genuinely pins it.
The median session only bounds above ~16.7, where the ceiling is doing the
work instead. BRACKET WIDTH IS REPORTED so those two cases cannot be read as
the same claim - an earlier report merged them and overstated the result.
"""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools" / "acquisition_pass")]

import session_structure as ss   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def frames(stamp, n, start=0):
    return [f"fc2_save_{stamp}-{i:04d}.tif" for i in range(start, start + n)]


print("\n--- the session, not the folder, is the recording --------------")

names = frames("2021-04-19-132028", 30) + frames("2021-04-19-132752", 30)
rows = ss.analyse("X", names)
check("two session stamps make two recordings", len(rows) == 2,
      "one folder, twelve stamps, is twelve recordings - not one")
check("frames are attributed to their own session",
      all(r["frames"] == 30 for r in rows))
check("the folder's session count is carried on every row",
      all(r["sessions_in_folder"] == 2 for r in rows))

check("a real FlyCap name parses to (session, index)",
      ss.session_key("fc2_save_2021-04-19-132028-0000.tif")
      == ("2021-04-19-132028", 0))
check("the index is the frame, not part of the session",
      ss.session_key("fc2_save_2021-04-19-132028-8998.tif")[1] == 8998)
check("a name with no index yields nothing",
      ss.session_key("notes.txt") is None)

print("\n--- the bracket, and how much of it the ceiling supplies -------")

# The real tightest session: 8,999 frames, 344 s to the next start.
tight = ss.analyse("X", frames("2021-04-19-153207", 8999)
                   + frames("2021-04-19-153751", 10))
first = tight[0]
check("a short gap bounds the rate from below",
      abs(float(first["fps_lower_bound"]) - 26.16) < 0.02,
      f"8999 frames in 344 s is > {first['fps_lower_bound']} fps")
check("...and the bracket is narrow enough to pin 30",
      float(first["bracket_width_fps"]) < 5,
      f"width {first['bracket_width_fps']} fps")
check("the rate counts as measured", first["rate_measured"] == "yes")
check("duration follows from it",
      abs(float(first["duration_s"]) - 299.97) < 1,
      "8999 at 30 fps is a five minute protocol")

# A long gap leaves the ceiling doing the work. Same frames, 40 minutes.
loose = ss.analyse("X", frames("2021-04-19-132028", 8999)
                   + frames("2021-04-19-140028", 10))[0]
check("a long gap gives a weak lower bound",
      float(loose["fps_lower_bound"]) < 5,
      f"> {loose['fps_lower_bound']} fps says almost nothing")
check("...and the bracket width says so",
      float(loose["bracket_width_fps"]) > 25,
      "wide bracket = 30 was chosen because it is the ceiling")

print("\n--- nothing is assumed where nothing can be derived ------------")

alone = ss.analyse("X", frames("2021-04-19-132028", 8998))[0]
check("a single session has no bracket",
      alone["rate_measured"] == "NO")
check("...so it gets NO duration rather than the ceiling",
      alone["duration_s"] == "",
      "a total that buries an assumption is worse than an honest split")
check("...and says why", "single session" in alone["note"])

# Frames that cannot fit before the next start even at full rate.
impossible = ss.analyse("X", frames("2021-04-19-132028", 9000)
                        + frames("2021-04-19-132128", 10))[0]
check("an impossible gap is reported, never clamped",
      impossible["rate_measured"] == "NO"
      and "camera maximum" in impossible["note"],
      "9000 frames cannot fit in 60 s at 30 fps")

check("the camera ceiling is 30 fps across all rigs",
      ss.CAMERA_MAX_FPS == 30.0,
      "a validity rule, not a heuristic - any claim above it is wrong")

print("\n--- regular gaps are a protocol, irregular ones are not --------")

check("evenly spaced sessions read as a protocol",
      ss.regularity([300, 300, 305, 298])[0] == "regular")
check("...within a human tolerance, not to the second",
      ss.regularity([300, 330, 280])[0] == "regular")
check("scattered gaps read as irregular",
      ss.regularity([300, 900, 320])[0] == "irregular",
      "all 28 gaps in the real pezo-1 set are irregular")
check("one gap is not a pattern", ss.regularity([300])[0] == "")

print("\n--- time of day is read, and midnight is not a negative gap ----")

check("a malformed stamp yields nothing",
      ss.seconds_of("2021-04-19") is None)
check("an impossible clock time yields nothing",
      ss.seconds_of("2021-04-19-256199") is None)

# THE DATE IS PART OF THE STAMP. Decoding only the time of day sorts 00:05 on
# the 20th before 23:55 on the 19th and subtracts them into a negative gap.
# The frozen pezo-1 set really does hold 2021-04-19 and 2021-05-05 stamps in
# one tree, so this is ordinary data, not a midnight edge case.
check("a day boundary is a 600 s gap, not a negative one",
      ss.seconds_of("2021-04-20-000500")
      - ss.seconds_of("2021-04-19-235500") == 600)
midnight = ss.analyse("X", frames("2021-04-19-235500", 100)
                      + frames("2021-04-20-000500", 100))[0]
check("...so a session crossing midnight still brackets",
      midnight["rate_measured"] == "yes"
      and abs(float(midnight["fps_lower_bound"]) - 100 / 600) < 0.01,
      f"> {midnight['fps_lower_bound']} fps")
check("sessions on different days sort by date, not clock",
      [r["session"] for r in
       ss.analyse("X", frames("2021-05-05-090000", 50)
                  + frames("2021-04-19-230000", 50))]
      == ["2021-04-19-230000", "2021-05-05-090000"])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("SESSION_STRUCTURE_PASS")
