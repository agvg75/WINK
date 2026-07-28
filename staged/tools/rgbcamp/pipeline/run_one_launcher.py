"""
run_one_launcher.py
====================
GUI entry point for run_one.py -- no command line, no typed filenames.

Double-clicking Analyze_One_Recording.bat (at the RGBCaMP_Tracker root) runs
this script with the pinned venv's pythonw.exe (no console window). It:
  1. shows a file picker for the exported recording CSV
  2. runs the single-recording analysis (run_one.analyse_one)
  3. opens the output folder in Explorer when done, or shows an error dialog

The operator never sees a terminal: cancelling the picker exits quietly,
success opens the output folder, failure shows a message box with the error.
"""
from __future__ import annotations

import os
import sys
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import run_one


def main():
    root = tk.Tk()
    root.withdraw()   # no blank window -- just the dialogs

    csv_path = filedialog.askopenfilename(
        title="Choose an exported RGBCaMP recording CSV",
        filetypes=[("RGBCaMP recording CSV", "*.csv"), ("All files", "*.*")],
    )
    if not csv_path:
        return   # operator cancelled -- exit quietly, no terminal ever shown

    try:
        result = run_one.analyse_one(csv_path)
    except Exception:
        tb = traceback.format_exc()
        messagebox.showerror(
            "RGBCaMP analysis failed",
            f"Could not analyse:\n{csv_path}\n\n{tb[-1500:]}")
        return

    messagebox.showinfo("RGBCaMP analysis complete",
                        f"Wrote tables and figures to:\n{result.out_dir}")
    os.startfile(str(result.out_dir))


if __name__ == "__main__":
    main()
