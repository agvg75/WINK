"""
movie_probe_gui.py
==================
A double-click window for people who do not want a terminal. Pick a movie, a
TIFF stack, or a folder of images, and it tells you in plain language what the
file is and whether it is good enough for calcium or only for behaviour. It
reads through movie_reader, so whatever the reader can open, this can report.

Launch by double-clicking Probe_A_Movie.bat. No typing, no command line. Any
startup error is written to a log beside this script and shown in a dialog.
"""
from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "movie_probe_gui.log"


def _human_report(m) -> tuple[str, str]:
    """Return (plain_text_report, verdict_tone) where tone is 'ok' | 'behaviour'
    | 'warn'. Pure function, testable without a GUI."""
    kind = {"video": "Video file", "tiff_stack": "TIFF stack",
            "image_sequence": "Folder of images", "single_image": "Single image"
            }.get(m.source_kind, m.source_kind)

    if m.n_channels == 1:
        colour = "Grayscale"
    elif m.n_channels == 3:
        colour = "Colour (RGB, 3 channels)"
    else:
        colour = f"{m.n_channels} channels"

    if m.fps:
        rate = f"{m.fps:g} frames per second"
    else:
        rate = "not stored in the file (you enter it manually in the analysis)"

    lines = [
        f"Type:        {kind}",
        f"Frames:      {m.n_frames}",
        f"Size:        {m.width} x {m.height} pixels",
        f"Colour:      {colour}",
        f"Bit depth:   {m.bit_depth}-bit",
        f"Frame rate:  {rate}",
        f"Opened with: {m.backend}",
        "",
    ]

    if m.quantitative_intensity_ok:
        lines.append("Good for behaviour tracking AND for calcium/GCaMP intensity.")
        tone = "ok"
    elif m.lossy:
        lines.append("Good for behaviour tracking (centroids, heading, kinematics).")
        lines.append("NOT reliable for calcium/GCaMP intensity: this file is")
        lines.append("compressed, so brightness values are not trustworthy. Use the")
        lines.append("original 16-bit recording for calcium.")
        tone = "warn"
    else:
        lines.append("Good for behaviour tracking (centroids, heading, kinematics).")
        lines.append(f"Intensity is {m.bit_depth}-bit and low dynamic range: usable")
        lines.append("but prefer a 16-bit recording for quantitative calcium.")
        tone = "behaviour"

    return "\n".join(lines), tone


def _run_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import movie_reader

    TONE_BG = {"ok": "#d1e7dd", "behaviour": "#fff3cd", "warn": "#f8d7da"}
    TONE_FG = {"ok": "#0f5132", "behaviour": "#664d03", "warn": "#58151c"}

    root = tk.Tk()
    root.title("Probe a Movie")
    root.geometry("560x430")

    ttk.Label(root, text="Check what a movie file is",
              font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    ttk.Label(root, text="Pick a video, a TIFF stack, or a folder of images.",
              font=("Segoe UI", 9)).pack(anchor="w", padx=14)

    path_var = tk.StringVar(value="(nothing chosen yet)")
    report = tk.Text(root, height=13, width=64, wrap="word",
                     font=("Consolas", 10), state="disabled", bd=1, relief="solid")

    def _show(path):
        path_var.set(path)
        try:
            m = movie_reader.open_movie(path)
            text, tone = _human_report(m)
            m.close()
        except Exception as e:
            text, tone = (f"Could not open this file.\n\n{e}\n\nIf it is an unusual "
                          "codec, try a different file or tell Andres which camera "
                          "made it."), "warn"
        report.config(state="normal", bg=TONE_BG.get(tone, "#fff"),
                      fg=TONE_FG.get(tone, "#000"))
        report.delete("1.0", "end")
        report.insert("1.0", text)
        report.config(state="disabled")

    def _pick_file():
        p = filedialog.askopenfilename(
            title="Choose a movie or stack",
            filetypes=[("Movies and stacks", "*.avi *.mp4 *.mov *.mkv *.webm *.tif *.tiff"),
                       ("All files", "*.*")])
        if p:
            _show(p)

    def _pick_folder():
        p = filedialog.askdirectory(title="Choose a folder of image frames")
        if p:
            _show(p)

    btns = ttk.Frame(root)
    btns.pack(anchor="w", padx=14, pady=10)
    ttk.Button(btns, text="Choose a movie or stack...", command=_pick_file).pack(side="left")
    ttk.Button(btns, text="Choose an image folder...", command=_pick_folder).pack(side="left", padx=8)

    ttk.Label(root, textvariable=path_var, font=("Segoe UI", 8),
              foreground="#555", wraplength=530).pack(anchor="w", padx=14)
    report.pack(fill="both", expand=True, padx=14, pady=(6, 14))

    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        _show(sys.argv[1])

    root.mainloop()


def main():
    try:
        _run_gui()
    except Exception:
        tb = traceback.format_exc()
        try:
            LOG_PATH.write_text(tb, encoding="utf-8")
        except Exception:
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox
            r = tk.Tk(); r.withdraw()
            messagebox.showerror("Probe a Movie: could not start",
                                 tb[-1500:] + f"\n\n(log: {LOG_PATH})")
            r.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    main()
