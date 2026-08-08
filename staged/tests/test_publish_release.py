"""The publish command's refusals and its failure reporting.

WHY THIS SUITE EXISTS AT ALL. publish_release.py gates every release the lab
ever sees, and until now nothing checked it. The specific defect that prompted
the file: a check suite died on an uncaught FileNotFoundError, and the refusal
printed

    FAIL  test_magnet_dependency_guard.py    PASS  and pins it to 5.x

because the reason was taken from the last STDOUT line - the final passing
check - while the traceback sat on STDERR, which `stdout or stderr` stops
reading the moment stdout is non-empty.

A failure notice that reads "PASS" is worse than none. It invites the reader
to treat a real failure as a display quirk and re-run until it goes away.
"""
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "publish"))

import publish_release as pr                      # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def fake(stdout="", stderr="", returncode=1):
    return types.SimpleNamespace(stdout=stdout, stderr=stderr,
                                 returncode=returncode)


print("publish release - refusals and failure reporting\n")

# ------------------------------------------- the defect that prompted this
TRACEBACK = (
    'Traceback (most recent call last):\n'
    '  File "C:\\staged\\tests\\test_magnet_dependency_guard.py", line 130, '
    'in <module>\n'
    '    release = (ROOT / "app" / "release_info.json").read_text()\n'
    "FileNotFoundError: [Errno 2] No such file or directory: "
    "'C:\\\\staged\\\\app\\\\release_info.json'")
STDOUT = ("  PASS  magpylib is importable\n"
          "  PASS  and pins it to 5.x, so a fresh install cannot pick up v4")

why = pr.why_failed(fake(stdout=STDOUT, stderr=TRACEBACK), STDOUT.splitlines()[-1])
check("a suite that died on an exception is reported by its EXCEPTION, not by "
      "the last line it managed to print", "FileNotFoundError" in why, why[:70])
check("and the reported reason does not read as a pass", "PASS" not in why)
check("the innermost frame is carried too, so the reason names who asked for "
      "the missing thing", "test_magnet_dependency_guard.py" in why)

# ----------------------------------------------- a suite that fails cleanly
# No traceback: the suite ran to completion, counted its own failures and
# exited 1. The reason must come from its own verdict line, not the summary
# line that follows it.
SELF = ("  PASS  something fine\n"
        "  FAIL  the thing that broke\n"
        "3 of 4 checks passed\n"
        "   FAILED: the thing that broke")
why = pr.why_failed(fake(stdout=SELF), SELF.splitlines()[-1])
check("a suite that reports its own failure is quoted on that failure",
      "the thing that broke" in why, why)

# ------------------------------------------------------- nothing to go on
why = pr.why_failed(fake(stdout=""), "(no output)")
check("a silent failure says so rather than inventing a reason",
      why == "(no output)", why)

# ------------------------------------------------------ stderr wins on tie
# A suite can print to both. The exception is the more specific fact.
why = pr.why_failed(fake(stdout="all good\n", stderr="ValueError: bad"), "all good")
check("stderr is preferred over stdout, which is the whole bug",
      "ValueError" in why, why)

# ------------------------------------------------------- the stale stamp
# The refusal that deleted release_info.json from staged in the first place.
# If this constant drifts, the test above (which now reads MIN_RUNTIME_VERSION
# out of this module) is measuring nothing.
check("MIN_RUNTIME_VERSION is declared and is not the unbumped default",
      isinstance(pr.MIN_RUNTIME_VERSION, str)
      and pr.MIN_RUNTIME_VERSION != "1.0.0", pr.MIN_RUNTIME_VERSION)
check("staged carries NO release_info.json - a stamp there makes a Hub run "
      "from staged display someone else's version number",
      not (ROOT / "app" / "release_info.json").exists())
check("a per-test timeout exists, so one blocked GUI suite cannot hang the "
      "release indefinitely",
      isinstance(pr.TEST_TIMEOUT_S, (int, float)) and pr.TEST_TIMEOUT_S > 0,
      f"{pr.TEST_TIMEOUT_S}s")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("PUBLISH_RELEASE_PASS")
