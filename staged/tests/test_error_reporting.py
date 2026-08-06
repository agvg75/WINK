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

# --- the cockpit path used to differ, and was wrong ------------------------
# CockpitApp sets report_callback_exception in __init__, so 15 tools HAD error
# reporting - but it reported frames[-1], which is the library that raised.
# Same capability, opposite outcome, and the audit could not see the difference.
src = (ROOT / "app" / "process_ui.py").read_text(encoding="utf-8")
check("both paths share one helper",
      src.count("describe_exception(exc_type, value, tb)") >= 2)
check("...and the cockpit no longer reports frames[-1] itself",
      "last = frames[-1]" not in src,
      "that pointed every cockpit tool at the wrong file")


def only_ours():
    raise RuntimeError("boom")


try:
    only_ours()
except Exception:
    d2 = process_ui.describe_exception(*sys.exc_info())
check("a failure with no library involved still names the line",
      "only_ours" in d2 and "RuntimeError: boom" in d2)
check("...without inventing a library aside",
      "raised inside" not in d2,
      "the parenthetical is only meaningful when the frames differ")

# --- the tools patched in this pass ----------------------------------------
PATCHED = [
    "tools/population_orientation/aggregate_plates_tool.py",
    "tools/worm_kinematics/kinematics_browser.py",
    "tools/afd_neuron/run_neuron_tracker.py",
    "tools/scale_tools/scale_calculator.py",
    "tools/segmentation_review_tool.py",
    "tools/worm_kinematics/dic_tracker/run_dic_kinematics.py",
    "tools/movie/convert_gui.py",
    "tools/movie/movie_probe_gui.py",
    "tools/power_analysis/power_planner.py",
]
texts = {p: (ROOT / p).read_text(encoding="utf-8") for p in PATCHED}
check("every patched tool installs reporting",
      not [p for p in PATCHED if "install_error_reporting" not in texts[p]])
check("...guarded, so a sys.path problem cannot break a working tool",
      not [p for p in PATCHED if "error reporting unavailable" not in texts[p]],
      "breaking a tool to add diagnostics would be a bad trade")

import py_compile   # noqa: E402
bad = []
for p in PATCHED:
    try:
        py_compile.compile(str(ROOT / p), doraise=True)
    except Exception as exc:
        bad.append(f"{p}: {exc}")
check("every patched tool still compiles", not bad, str(bad))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("ERROR_REPORTING_PASS")
