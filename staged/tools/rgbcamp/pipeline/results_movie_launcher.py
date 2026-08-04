"""
results_movie_launcher.py
=========================
GUI entry point for results_movie.py -- no command line, no typed filenames.

  1. pick the exported recording CSV
  2. pick the image folder for the worm panel (or skip it)
  3. choose normalisation, decimation and preview-vs-render
  4. watch progress; the movie lands beside the CSV

Silent-failure guard: ANY startup or import error is written to a log beside
this script AND shown as a message box (if tkinter itself is usable) -- never a
blank flash with no operator-visible feedback. Same convention as
results_browser_launcher.py.

Rendering is a render-time choice, never a re-analysis: nothing here measures
anything, so running it again with different settings is cheap and safe.
"""
from __future__ import annotations

import os
import sys
import threading
import traceback
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "results_movie_launcher.log"


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
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import results_movie as rm
    except Exception:
        _log_and_show("RGBCaMP Results Movie -- startup failed",
                      f"Could not start:\n\n{traceback.format_exc()}")
        return

    try:
        root = tk.Tk()
        root.withdraw()
        csv_path = filedialog.askopenfilename(
            parent=root,
            title="Choose an exported RGBCaMP recording CSV",
            filetypes=[("RGBCaMP recording CSV", "*.csv"), ("All files", "*.*")])
        if not csv_path:
            root.destroy()
            return

        image_dir = filedialog.askdirectory(
            parent=root,
            title="Choose the image folder for the worm panel "
                  "(Cancel to render without it)")

        try:
            rec = rm.load(csv_path, image_dir=image_dir or None)
        except rm.MovieInputError as exc:
            # A refusal, not a crash: it names what to do about it.
            messagebox.showwarning("Cannot render this recording", str(exc),
                                   parent=root)
            root.destroy()
            return

        root.deiconify()
        root.title("RGBCaMP results movie")
        frm = ttk.Frame(root, padding=12)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text=Path(csv_path).name,
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        ttk.Label(frm, foreground="#5E6E76", justify="left",
                  text=(f"{rec.n_frames} frames  |  {rec.n_seg} segments per side  |  "
                        f"bands {rec.band_names[0]} / {rec.band_names[1]}\n"
                        f"{len(rec.image_files)} images for the worm panel"
                        + ("" if rec.um_per_px > 0 else
                           "\nScale is not calibrated, so velocity is reported "
                           "in px/s and labelled as such."))
                  ).pack(anchor="w", pady=(2, 10))

        norm = tk.StringVar(value="percentile")
        row = ttk.Frame(frm); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Scaling", width=12).pack(side="left")
        ttk.Combobox(row, textvariable=norm, state="readonly", width=14,
                     values=["percentile", "absolute"]).pack(side="left")
        ttk.Label(row, foreground="#5E6E76",
                  text="  percentile = best contrast, not comparable between "
                       "recordings").pack(side="left")

        dec = tk.IntVar(value=1)
        row2 = ttk.Frame(frm); row2.pack(fill="x", pady=2)
        ttk.Label(row2, text="Every Nth frame", width=12).pack(side="left")
        ttk.Spinbox(row2, from_=1, to=20, textvariable=dec, width=6).pack(side="left")

        status = tk.StringVar(value="Ready.")
        ttk.Label(frm, textvariable=status, foreground="#3E4F58").pack(
            anchor="w", pady=(10, 4))
        bar = ttk.Progressbar(frm, mode="determinate", length=420)
        bar.pack(fill="x", pady=(0, 8))

        buttons = ttk.Frame(frm); buttons.pack(fill="x")

        def _run(preview_only):
            for child in buttons.winfo_children():
                child.state(["disabled"])

            def work():
                try:
                    out_dir = Path(csv_path).parent
                    if preview_only:
                        p = rm.preview(rec, out_dir / f"{rec.base}_movie_preview.png",
                                       normalisation=norm.get())
                        status.set(f"Preview written: {p.name}")
                    else:
                        def prog(n, total):
                            bar["value"] = 100.0 * n / max(total, 1)
                            status.set(f"Rendering frame {n} of {total}...")
                        p, _ = rm.render(
                            rec, out_dir / f"{rec.base}_results_movie.mp4",
                            normalisation=norm.get(), decimate=dec.get(),
                            progress=prog)
                        bar["value"] = 100
                        status.set(f"Written: {p.name}  (+ provenance JSON)")
                    try:
                        os.startfile(str(out_dir))
                    except Exception:
                        pass
                except Exception:
                    status.set("Failed - see the message box.")
                    _log_and_show("RGBCaMP Results Movie -- render failed",
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
        _log_and_show("RGBCaMP Results Movie -- error",
                      f"Could not open the results movie tool:\n\n{traceback.format_exc()}")


if __name__ == "__main__":
    main()
