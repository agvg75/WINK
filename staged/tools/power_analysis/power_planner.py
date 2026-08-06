"""Launch the WINK sample planner ("how many more replicates?") in the browser.

Replaces the older power_tool with the interactive planner: paste group values
OR load a module export CSV, and it checks the data (outliers, normality, equal
variance), picks the honest test, and shows current power and how many more
replicate units are needed. Plate/well/worm replicate unit is explicit, so it
refuses worm-level power for population assays (pseudoreplication).
"""
import sys
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
HTML = HERE / "wink_sample_planner.html"


def main():
    if not HTML.exists():
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            try:                      # error reporting
                from process_ui import install_error_reporting
                install_error_reporting(root)
            except Exception as _e:   # never break the tool for this
                print('error reporting unavailable:', _e)
            root.withdraw()
            messagebox.showerror(
                "Power analysis / sample planner",
                f"The planner page was not found:\n{HTML}\n\n"
                "Reinstall or update WINK Lab Tools.")
            root.destroy()
        except Exception:
            print(f"Planner not found: {HTML}", file=sys.stderr)
        return
    webbrowser.open(HTML.as_uri())


if __name__ == "__main__":
    main()
