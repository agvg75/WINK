"""Startup dependency probe for the preview. Run by the .bat before the GUI.

Separate from preview_build.install so it can run under python.exe with a
visible console: pythonw.exe discards stdout, and a failure the student
cannot see is the failure mode this exists to prevent.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preview_build   # noqa: E402

ok, message = preview_build.probe_dependencies()
print()
print(f"  {preview_build.version_string()}")
print()
print(f"  {message}")
print()
if not ok:
    print("  The viewer was NOT started.")
    print()
raise SystemExit(0 if ok else 1)
