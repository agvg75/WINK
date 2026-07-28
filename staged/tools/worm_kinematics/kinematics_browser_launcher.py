"""
kinematics_browser_launcher.py
==============================
GUI entry point for kinematics_browser.py, no command line, no typed filenames.

Double-clicking Browse_Worm_Kinematics.bat runs this with the pinned venv's
pythonw.exe (no console window). It:
  1. shows a file picker for the exported transmitted-light recording CSV
  2. opens the Worm Kinematics Results Browser window

Silent-failure guard: ANY startup or import error is written to a log file
beside this script AND shown as a message box, never a blank flash.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "kinematics_browser_launcher.log"


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
        pass


def main():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import tkinter as tk
        from tkinter import filedialog
        import kinematics_browser as kb
    except Exception:
        _log_and_show("Worm Kinematics Browser: startup failed",
                      f"Could not start:\n\n{traceback.format_exc()}")
        return

    try:
        picker_root = tk.Tk()
        picker_root.withdraw()
        csv_path = filedialog.askopenfilename(
            title="Choose a transmitted-light worm recording CSV",
            filetypes=[("Worm recording CSV", "*.csv"), ("All files", "*.*")],
        )
        picker_root.destroy()
        if not csv_path:
            return

        app = kb.KinematicsBrowser(csv_path)
        app.mainloop()
    except Exception:
        _log_and_show("Worm Kinematics Browser: error",
                      f"Could not open the kinematics browser:\n\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
