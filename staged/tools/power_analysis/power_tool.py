"""Launcher for the WINK sample planner ("how many more?" power analysis).

Replaces the earlier tk power workbench.  It opens the interactive HTML planner
in the default browser.  The planner runs entirely offline (no server, no
network) and can either take pasted values or load a module's plate-level CSV
export directly, then runs the distribution checks (outliers, Shapiro-Wilk,
Levene), forks to the honest test (Welch's t / Mann-Whitney / Welch ANOVA /
Kruskal-Wallis), and shows the standardized effect, current power, and how many
more replicates are needed - with the plate (not the worm) as the unit.
"""
from __future__ import annotations

import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
PLANNER = HERE / "nike_sample_planner.html"


def main():
    if not PLANNER.exists():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "Power analysis / sample planner",
                f"The planner page was not found:\n\n{PLANNER}\n\n"
                "Re-run the Lab Tools update, or reinstall.")
            root.destroy()
        except Exception:
            print("Planner not found:", PLANNER)
        return
    webbrowser.open(PLANNER.as_uri())


if __name__ == "__main__":
    main()
