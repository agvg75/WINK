"""Standalone Scale & magnification calculator.

Opens the shared scale-calibration dialog so a student can work out
micrometres-per-pixel from the scope + zoom + camera, or by drawing a scale bar
on a frame, independently of any single analysis module.  The resulting value
can be copied into whichever tool needs it.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "movie"))

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


def _load_frame(path):
    """Best-effort first frame as a numpy image, or None."""
    try:
        from movie_reader import open_movie
        mov = open_movie(path)
        try:
            frame = mov.get_frame(0)
        finally:
            try:
                mov.close()
            except Exception:
                pass
        import numpy as np
        return np.asarray(frame)
    except Exception:
        try:
            from PIL import Image
            import numpy as np
            return np.asarray(Image.open(path))
        except Exception:
            return None


def _show_result(root, result):
    win = tk.Toplevel(root)
    win.title("Scale result")
    frm = ttk.Frame(win, padding=14)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="Micrometres per pixel (copy into your module):",
              font=("Segoe UI", 10, "bold")).pack(anchor="w")
    var = tk.StringVar(value=f"{result['um_per_px']:.5f}")
    ent = ttk.Entry(frm, textvariable=var, width=20, font=("Consolas", 12))
    ent.pack(fill="x", pady=6)
    ent.select_range(0, "end")
    ent.focus_set()
    ttk.Label(frm, text=f"source: {result.get('source','')}\n"
                        f"{result.get('details','')}",
              foreground="#555555", wraplength=360, justify="left").pack(anchor="w")
    ttk.Button(frm, text="Close", command=root.destroy).pack(anchor="e", pady=(8, 0))
    win.protocol("WM_DELETE_WINDOW", root.destroy)


def main():
    root = tk.Tk()
    try:                      # error reporting
        from process_ui import install_error_reporting
        install_error_reporting(root)
    except Exception as _e:   # never break the tool for this
        print('error reporting unavailable:', _e)
    root.withdraw()
    path = filedialog.askopenfilename(
        title="Choose an image or movie for the scale bar (Cancel to skip)",
        filetypes=[("Images and movies",
                    "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.avi *.mp4 *.mov *.mkv"),
                   ("All files", "*.*")])
    frame = _load_frame(path) if path else None
    if path and frame is None:
        messagebox.showwarning(
            "Scale calculator",
            "Could not read that file for the scale bar; the optical estimate "
            "and manual entry are still available.")
    from scale_calibration_ui import ask_scale
    result = ask_scale(root, frame=frame,
                       title="Scale & magnification calculator")
    if result is None:
        root.destroy()
        return
    _show_result(root, result)
    root.deiconify(); root.withdraw()
    root.mainloop()


if __name__ == "__main__":
    main()
