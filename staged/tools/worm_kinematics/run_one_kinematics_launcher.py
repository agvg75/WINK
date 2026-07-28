"""
run_one_kinematics_launcher.py
==============================
GUI entry point for run_one_kinematics.py, no command line, no typed filenames.

Double-clicking Analyze_One_Worm_Kinematics.bat runs this with the pinned
venv's pythonw.exe (no console window). It:
  1. shows a file picker for the exported transmitted-light recording CSV
  2. runs the kinematics-only analysis (run_one_kinematics.analyse_one_kinematics)
  3. opens the output folder when done, or shows an error dialog

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
import run_one_kinematics


def main():
    root = tk.Tk()
    root.withdraw()

    csv_path = filedialog.askopenfilename(
        title="Choose a transmitted-light worm recording CSV",
        filetypes=[("Worm recording CSV", "*.csv"), ("All files", "*.*")],
    )
    if not csv_path:
        return   # cancelled, exit quietly

    try:
        result = run_one_kinematics.analyse_one_kinematics(csv_path)
    except Exception:
        tb = traceback.format_exc()
        messagebox.showerror(
            "Kinematics analysis failed",
            f"Could not analyse:\n{csv_path}\n\n{tb[-1500:]}")
        return

    messagebox.showinfo("Kinematics analysis complete",
                        f"Wrote tables and figures to:\n{result.out_dir}")
    os.startfile(str(result.out_dir))


if __name__ == "__main__":
    main()
