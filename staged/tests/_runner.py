"""Run assert-style test functions without pytest.

Several suites here were written as bare `def test_*(...)` functions with no
main block. Run as a script they defined those functions, called none of
them, and exited 0 - a green tick for zero executed checks. Run under pytest
they would work, but pytest is not installed and should not be: this venv is
what Setup_Lab_Tools.bat builds on every lab machine, and a test framework
has no business in a student runtime.

So each of those files ends with:

    if __name__ == "__main__":
        from _runner import run_module_tests
        raise SystemExit(run_module_tests(globals(), "suite name"))

The assertions themselves are left exactly as they were. The point is to
execute them, not to restate them - rewriting assertions in code that has
never actually run is how you change what is being checked while believing
you are only changing how it is reported.

Supported fixtures: `tmp_path`, the only one these suites use. Anything else
is reported as unrunnable rather than skipped quietly, because a test that
cannot run is not a test that passed.
"""
from __future__ import annotations

import inspect
from pathlib import Path
import shutil
import tempfile
import traceback

SUPPORTED_FIXTURES = {"tmp_path"}


def run_module_tests(namespace, title=None, verbose=True):
    """Execute every test_* callable in `namespace`. Returns an exit code."""
    title = title or namespace.get("__name__", "tests")
    functions = [
        (name, obj) for name, obj in sorted(namespace.items())
        if name.startswith("test") and callable(obj)
        and not inspect.isclass(obj)
        and getattr(obj, "__module__", None) == namespace.get("__name__")
    ]
    if not functions:
        print(f"{title}: no test functions found - nothing ran.")
        return 1

    print(f"{title}\n")
    temp_dirs = []
    passed, failures = 0, []
    for name, func in functions:
        try:
            params = inspect.signature(func).parameters
        except (TypeError, ValueError):
            params = {}
        unsupported = [p for p in params if p not in SUPPORTED_FIXTURES]
        if unsupported:
            failures.append((name, f"needs fixture(s) {', '.join(unsupported)}, "
                                   f"which this runner does not provide"))
            print(f"  UNRUNNABLE  {name}  [{', '.join(unsupported)}]")
            continue
        kwargs = {}
        if "tmp_path" in params:
            path = Path(tempfile.mkdtemp())
            temp_dirs.append(path)
            kwargs["tmp_path"] = path
        try:
            func(**kwargs)
        except Exception as error:                       # noqa: BLE001
            failures.append((name, f"{type(error).__name__}: {error}"))
            print(f"  FAIL  {name}")
            if verbose:
                for line in traceback.format_exc().splitlines()[-4:]:
                    print(f"        {line}")
        else:
            passed += 1
            print(f"  PASS  {name}")

    for path in temp_dirs:
        shutil.rmtree(path, ignore_errors=True)

    print()
    print(f"{passed} of {len(functions)} tests passed")
    for name, why in failures:
        print(f"   FAILED: {name}  -  {why}")
    return 1 if failures else 0
