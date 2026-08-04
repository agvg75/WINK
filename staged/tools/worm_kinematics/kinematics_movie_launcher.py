"""
kinematics_movie_launcher.py
============================
GUI entry point for kinematics_movie.py -- no command line, no typed filenames.

  1. pick the kinematics CSV the tracker exported
  2. pick the image stack or folder it was tracked on (or skip it)
  3. choose smoothing and how many frames to keep
  4. preview four frames, or render

Silent-failure guard: ANY startup or import error is written to a log beside
this script AND shown as a message box -- never a blank flash with no
operator-visible feedback. Same convention as results_browser_launcher.py.

Nothing here measures anything, so re-rendering with different settings is
cheap and safe.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "kinematics_movie_launcher.log"


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
        shown = (message if len(message) <= 1800
                 else message[:1800] + f"\n\n(full log: {LOG_PATH})")
        messagebox.showerror(title, shown)
        root.destroy()
    except Exception:
        pass


def main():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import kinematics_movie as km
    except Exception:
        _log_and_show("Kinematics Results Movie -- startup failed",
                      f"Could not start:\n\n{traceback.format_exc()}")
        return

    try:
        root = tk.Tk()
        root.withdraw()
        csv_path = filedialog.askopenfilename(
            parent=root, title="Choose the kinematics CSV the tracker exported",
            filetypes=[("Kinematics CSV", "*.csv"), ("All files", "*.*")])
        if not csv_path:
            root.destroy()
            return

        image_path = filedialog.askopenfilename(
            parent=root,
            title="Choose the image stack it was tracked on "
                  "(Cancel to pick a folder or skip)",
            filetypes=[("Image stack", "*.tif *.tiff"), ("All files", "*.*")])
        if not image_path:
            image_path = filedialog.askdirectory(
                parent=root,
                title="Choose the image FOLDER (Cancel to render without frames)")

        try:
            rec = km.load(csv_path, image_path=image_path or None)
        except km.MovieInputError as exc:
            messagebox.showwarning("Cannot render this recording", str(exc),
                                   parent=root)
            root.destroy()
            return

        suggested = km.suggested_decimation(rec)

        root.deiconify()
        root.title("Kinematics results movie")
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=Path(csv_path).name,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")

        quality = rec.quality_summary()
        flagged = quality.get("frames_flagged", 0)
        summary = (f"{rec.n_frames} frames  |  {rec.n_seg} segments  |  "
                   f"{rec.fps:g} fps declared  |  "
                   f"{len(rec.images) if rec.images else 0} images\n"
                   f"velocity column: {rec.velocity_column or 'none found'}")
        if not rec.um_per_px:
            summary += ("\nScale is not calibrated, so speed is reported in "
                        "px/s and labelled as such.")
        if flagged:
            summary += (f"\n{flagged} of {rec.n_frames} frames "
                        f"({100.0*flagged/max(rec.n_frames,1):.1f}%) are "
                        f"flagged needs_help and are ticked on every trace.")
        ttk.Label(frm, foreground="#5E6E76", justify="left",
                  text=summary).pack(anchor="w", pady=(2, 10))

        smooth = tk.DoubleVar(value=0.5)
        row = ttk.Frame(frm); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Smoothing (s)", width=16).pack(side="left")
        ttk.Spinbox(row, from_=0.0, to=5.0, increment=0.1, width=6,
                    textvariable=smooth).pack(side="left")
        ttk.Label(row, foreground="#5E6E76",
                  text="  0 = none. The raw trace stays visible underneath."
                  ).pack(side="left")

        dec = tk.IntVar(value=suggested)
        row2 = ttk.Frame(frm); row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Every Nth frame", width=16).pack(side="left")
        ttk.Spinbox(row2, from_=1, to=50, width=6,
                    textvariable=dec).pack(side="left")
        ttk.Label(row2, foreground="#5E6E76",
                  text=f"  suggested {suggested} for this recording"
                  ).pack(side="left")

        ttk.Label(frm, wraplength=560, justify="left", foreground="#5E6E76",
                  text=("The movie always plays at REAL TIME: keeping every "
                        "frame gives smoother playback and a longer render, "
                        "while a larger N renders faster and plays choppier. "
                        "Neither speeds the animal up.")
                  ).pack(anchor="w", pady=(6, 8))

        status = tk.StringVar(value="Ready.")
        ttk.Label(frm, textvariable=status,
                  foreground="#3E4F58").pack(anchor="w", pady=(4, 4))
        bar = ttk.Progressbar(frm, mode="determinate", length=460)
        bar.pack(fill="x", pady=(0, 8))
        buttons = ttk.Frame(frm); buttons.pack(fill="x")

        def _run(preview_only):
            for child in buttons.winfo_children():
                child.state(["disabled"])

            def work():
                try:
                    out_dir = Path(csv_path).parent
                    if preview_only:
                        p = km.preview(rec,
                                       out_dir / f"{rec.base}_movie_preview.png",
                                       smooth_s=smooth.get())
                        status.set(f"Preview written: {p.name}")
                    else:
                        def prog(n, total):
                            bar["value"] = 100.0 * n / max(total, 1)
                            status.set(f"Rendering frame {n} of {total}...")
                        p, prov = km.render(
                            rec, out_dir / f"{rec.base}_kinematics_movie.mp4",
                            smooth_s=smooth.get(), decimate=dec.get(),
                            progress=prog)
                        bar["value"] = 100
                        status.set(
                            f"Written: {p.name}  ({prov['output_fps']:.1f} fps, "
                            f"{prov['playback_speed_x']:.2f}x real time)")
                    try:
                        os.startfile(str(out_dir))
                    except Exception:
                        pass
                except Exception:
                    status.set("Failed - see the message box.")
                    _log_and_show("Kinematics Results Movie -- render failed",
                                  traceback.format_exc())
                finally:
                    for child in buttons.winfo_children():
                        child.state(["!disabled"])

            threading.Thread(target=work, daemon=True).start()

        ttk.Button(buttons, text="Preview 4 frames",
                   command=lambda: _run(True)).pack(side="left", padx=(0, 8))
        ttk.Button(buttons, text="Render movie",
                   command=lambda: _run(False)).pack(side="left")
        ttk.Button(buttons, text="Close",
                   command=root.destroy).pack(side="right")

        root.mainloop()
    except Exception:
        _log_and_show("Kinematics Results Movie -- error",
                      f"Could not open the kinematics movie tool:\n\n"
                      f"{traceback.format_exc()}")


if __name__ == "__main__":
    main()
