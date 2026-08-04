"""An error report must name OUR line, not the library that raised.

This exists because of a real cost. The population tracking tool reported

    TypeError: ufunc 'isfinite' not supported ... [arraylike.py:402 in array_ufunc]

and arraylike.py is inside pandas. The report named the messenger, not the
caller, so most of an afternoon went into guessing which of our lines was
responsible - and two fixes were shipped against the wrong theory before the
reporting itself was recognised as the problem.
"""
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))

import tkinter as tk           # noqa: E402
import process_ui              # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("error reporting - regression\n")

root = tk.Tk()
root.withdraw()
captured = []
process_ui.install_error_reporting(root, status=captured.append)


def broken_action():
    """Exactly the reported failure: np.isfinite on a pandas string column."""
    series = pd.Series(["1.0", "none", "3.0"])
    return np.isfinite(series)


root.after(1, broken_action)
root.after(400, root.quit)
root.mainloop()
root.destroy()

check("the failure was reported at all", bool(captured))
text = captured[0] if captured else ""
print(f"\n  report:\n    {text}\n")

check("the report names the exception", "TypeError" in text)
check("the report names OUR file, not just the library",
      "test_error_reporting.py" in text)
check("...and the function in our code that called it",
      "broken_action" in text)
check("...and shows the offending source line",
      "np.isfinite" in text)
# Which library frame is deepest varies with the pandas/numpy version - the
# reported one was arraylike.py, here it is numpy_.py - so assert that A
# library frame is carried as context rather than naming one.
check("the library frame is kept as context, not discarded",
      "raised inside" in text and ".py:" in text.split("raised inside")[-1])

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ERROR_REPORTING_PASS")
