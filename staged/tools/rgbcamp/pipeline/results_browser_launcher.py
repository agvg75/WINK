"""
results_browser_launcher.py
=============================
GUI entry point for results_browser.py -- no command line, no typed filenames.

Double-clicking Browse_Recording_Results.bat (at the RGBCaMP_Tracker root)
runs this with the pinned venv's pythonw.exe (no console window). It:
  1. shows a file picker for the exported recording CSV
  2. opens the Single Recording Results Browser window

Silent-failure guard: ANY startup or import error is written to a log file
beside this script AND shown as a message box (if tkinter itself is usable)
-- never a blank flash with no operator-visible feedback.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "results_browser_launcher.log"


def _log_and_show(title: str, message: str):
    try:
        LOG_PATH.write_text(message, encoding="utf-8")
    except Exception:
        pass
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        shown = message if len(message) <= 1800 else message[:1800] + f"\n\n(full log: {LOG_PATH})"
        messagebox.showerror(title, shown)
        root.destroy()
    except Exception:
        pass  # tkinter itself unusable -- the log file is the only remaining signal


def main():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tkinter as tk
        from tkinter import filedialog
        import results_browser as rb
    except Exception:
        _log_and_show("RGBCaMP Results Browser -- startup failed",
                      f"Could not start:\n\n{traceback.format_exc()}")
        return

    try:
        picker_root = tk.Tk()
        picker_root.withdraw()
        csv_path = filedialog.askopenfilename(
            title="Choose an exported RGBCaMP recording CSV",
            filetypes=[("RGBCaMP recording CSV", "*.csv"), ("All files", "*.*")],
        )
        picker_root.destroy()
        if not csv_path:
            return  # operator cancelled -- exit quietly, no terminal ever shown

        app = rb.ResultsBrowser(csv_path)
        app.mainloop()
    except Exception:
        _log_and_show("RGBCaMP Results Browser -- error",
                      f"Could not open the results browser:\n\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
