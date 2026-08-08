"""Per-user launch history, outcomes, pins, and the revert default.

The field that matters is OUTCOME, because it decides what "revert" offers.
Two ways it can lie, and both are tested here:

  a crash recorded as clean   the crash handler writes first and the atexit
                              hook writes after it, so last-write-wins would
                              record every crashed session as clean
  silence recorded as clean   a launch that never reported back was killed or
                              hung; counting it as success hands the student
                              the build that hung
"""
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import launch_history as lh                        # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("launch history - outcomes, pins, revert default\n")

tmp = Path(tempfile.mkdtemp(prefix="wink_launch_"))
store = lh.LaunchHistory(tmp)

# ------------------------------------------------------------- round trip
one = store.record_launch("Egg counter", "11.130")
store.record_outcome(one, lh.CLEAN)
two = store.record_launch("Egg counter", "11.138")
store.record_outcome(two, lh.CRASH, "ValueError: no frames")
three = store.record_launch("Egg counter", "11.136")     # no outcome at all

sessions = store.sessions("Egg counter")
check("every launch is recorded", len(sessions) == 3, len(sessions))
by_version = {version: outcome for _m, version, _w, outcome in sessions}
check("a clean session is clean", by_version["11.130"] == lh.CLEAN)
check("a crashed session is a crash", by_version["11.138"] == lh.CRASH)
check("a launch that never reported back is UNKNOWN, never clean - it was "
      "killed or it hung, and calling that success hands the student the "
      "build that hung", by_version["11.136"] == lh.UNKNOWN)

# --------------------------------------------------------- id collisions
# THIS SUITE FOUND THE BUG BY ACCIDENT. The first id was pid + timestamp, so
# the three launches above - same process, same second - shared one id and
# their outcomes overwrote each other. A student double-clicking, or opening
# two tools in a row, would have had one tool's crash recorded against the
# other. Named explicitly so it cannot come back silently.
burst = [store.record_launch("Burst", "11.138") for _ in range(20)]
check("ids are unique per LAUNCH, not per second - two tools started from the "
      "same Hub inside one second must not share an outcome",
      len(set(burst)) == 20, f"{len(set(burst))} distinct of 20")

# ------------------------------------------- a crash outranks a later clean
# Exactly what the atexit hook would do in a crashing process.
four = store.record_launch("Tracker", "11.138")
store.record_outcome(four, lh.CRASH, "boom")
store.record_outcome(four, lh.CLEAN)
outcome = {v: o for _m, v, _w, o in store.sessions("Tracker")}["11.138"]
check("a crash followed by a clean exit for the SAME launch stays a crash; "
      "last-write-wins here would invert the field revert depends on",
      outcome == lh.CRASH, outcome)

# ------------------------------------------------------- another module
store.record_launch("Tracker", "11.130")
check("sessions filter by module", len(store.sessions("Egg counter")) == 3,
      len(store.sessions("Egg counter")))

# ------------------------------------------------------ the revert default
offered = ["11.138", "11.136", "11.130"]
default = store.revert_default("Egg counter", offered, current="11.138")
check("revert defaults to the most recent version with a CLEAN session for "
      "THIS user, not to the previous number - 11.136 is the previous number "
      "and this user never got a clean session on it",
      default == "11.130", default)

empty = lh.LaunchHistory(tmp / "someone_else")
check("a user with no history gets no recommendation rather than an invented "
      "one; the picker must ask",
      empty.revert_default("Egg counter", offered, "11.138") is None)

# -------------------------------------------------------------- annotation
notes = store.annotate("Egg counter", offered, current="11.138")
check("the current version is marked current", notes["11.138"] == "current")
check("a version with a clean session says when",
      notes["11.130"].startswith("last clean session"), notes["11.130"])
check("a version used without a clean session says so rather than looking "
      "equivalent to one that worked",
      "no clean session" in notes["11.136"], notes["11.136"])
notes = store.annotate("Egg counter", ["11.96"], current="11.138")
check("a version this user never ran says so", notes["11.96"] == "never used by you")

# -------------------------------------------------------------------- pins
check("no pin by default", store.pinned("Egg counter") is None)
store.pin("Egg counter", "11.130")
check("a pin is readable back", store.pinned("Egg counter") == "11.130")
check("PINS ARE PER TOOL - pinning one tool leaves the others alone, which is "
      "what makes reverting cheap enough to do without asking",
      store.pinned("Tracker") is None)
check("pins are per user - another user's store is unaffected",
      lh.LaunchHistory(tmp / "someone_else").pinned("Egg counter") is None)
store.unpin("Egg counter")
check("a pin can be removed", store.pinned("Egg counter") is None)

# ------------------------------------------------------- child environment
env = lh.launch_environment("Egg counter", "11.138", "abc", base={})
check("the child is told its launch id, module and version, since the parent "
      "cannot observe the child's fate",
      env[lh.ENV_LAUNCH] == "abc" and env[lh.ENV_MODULE] == "Egg counter"
      and env[lh.ENV_VERSION] == "11.138", sorted(env))

# ------------------------------------------------------------- robustness
with open(store.log, "a", encoding="utf-8") as handle:
    handle.write('{"event": "launch", "id": "torn"')          # killed mid-write
check("a torn final line from a killed process does not lose the history "
      "above it", len(store.sessions("Egg counter")) == 3,
      len(store.sessions("Egg counter")))

unwritable = lh.LaunchHistory(Path(tmp) / "a" / "b" / "c")
check("recording never raises - a student's analysis must not die because a "
      "history file was locked",
      unwritable.record_launch("X", "1") is not None)

check("history is JSON lines, one record per line, appended",
      all(json.loads(line) for line in
          store.log.read_text(encoding="utf-8").splitlines()[:-1] if line))

# -------------------------------------------------- across a real process
# THE ONE THING UNIT TESTS CANNOT SHOW. The outcome loop spans a process
# boundary: the Hub records the launch, the CHILD records its fate through an
# atexit hook, and the Hub is not waiting to see it. Every part above can pass
# while the loop stays open in practice - a missing env var, an atexit hook
# that never fires under pythonw, a child that writes to a different store.
import os as _os                                             # noqa: E402
import subprocess                                            # noqa: E402
import textwrap                                              # noqa: E402

e2e = Path(tempfile.mkdtemp(prefix="wink_e2e_"))
parent = lh.LaunchHistory(e2e)
child_id = parent.record_launch("Child tool", "11.138")

child_script = e2e / "child.py"
child_script.write_text(textwrap.dedent(f"""
    import sys
    sys.path.insert(0, r"{ROOT / 'app'}")
    import launch_history
    launch_history.LaunchHistory.__init__.__defaults__ = (r"{e2e}",)
    launch_history.arrive(launch_history.LaunchHistory(r"{e2e}"))
    print("child ran")
"""), encoding="utf-8")

env = lh.launch_environment("Child tool", "11.138", child_id,
                            base=dict(_os.environ))
done = subprocess.run([sys.executable, str(child_script)], env=env,
                      capture_output=True, text=True, timeout=60)
outcome = {i: o for _m, v, _w, o in parent.sessions("Child tool")
           for i in [v]}.get("11.138")
check("a child process that exits normally records its OWN clean exit, which "
      "the parent then reads - the loop the Hub depends on and cannot observe "
      "itself", outcome == lh.CLEAN,
      f"{outcome}; child said {done.stdout.strip()!r} {done.stderr.strip()[:80]}")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("LAUNCH_HISTORY_PASS")
