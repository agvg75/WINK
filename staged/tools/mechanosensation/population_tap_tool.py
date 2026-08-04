"""Population tap-response / tap-habituation tool.

Piggybacks on the population tracker: run 'Population swimming + modality review'
first to produce a tracks CSV (track_id, frame, x, y), then this tool detects the
plate tap(s) from the global field motion, measures each tap's intensity,
duration, and frequency, splits every worm's centroid track into before/after
windows around each tap, and reports which animals responded (by speed and/or
direction) and the population response fraction per tap.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app"), str(ROOT / "tools" / "movie")]

import population_tap as PT
from process_ui import CockpitApp

# Result tables are read through read_table. Under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it - aborting an analysis with an error that names
# numpy internals rather than the column at fault. The import is guarded
# because these modules are launched several different ways and sys.path is
# not identical in all of them; a hard import would turn a latent dtype
# problem into a tool that will not start.
try:
    from table_io import read_table as _read_table
except Exception:                                    # pragma: no cover
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "app"))
        from table_io import read_table as _read_table
    except Exception:
        _read_table = None


def read_table(path, **kwargs):
    """pandas.read_csv with the pandas-3 dtype trap handled where available."""
    import pandas as _pd
    if _read_table is not None:
        return _read_table(path, **kwargs)
    return _pd.read_csv(path, **kwargs)



def _motion_signal_streaming(movie):
    """Per-frame global motion (mean abs frame-to-frame diff), streamed so a long
    movie never lives in RAM all at once."""
    import movie_reader
    m = movie_reader.open_movie(movie)
    try:
        n = int(m.n_frames)
        sig = np.zeros(max(n, 1), dtype=float)
        prev = None
        for i in range(n):
            a = np.asarray(m.get_frame(i), dtype=np.float32)
            if a.ndim == 3:
                a = a[..., :3].mean(axis=2)
            if prev is not None:
                sig[i] = float(np.mean(np.abs(a - prev)))
            prev = a
        if n > 1:
            sig[0] = sig[1]
        return sig, n
    finally:
        try:
            m.close()
        except Exception:
            pass


class App(CockpitApp):
    def __init__(self):
        super().__init__("Population tap response / habituation",
                         geometry="1120x680", process_title="Population tap response")
        self.v = {k: tk.StringVar(value=d) for k, d in {
            "tracks": "", "movie": "", "fps": "10", "scale": "1.0",
            "speed_change_frac": "0.30", "direction_change_deg": "45",
            "before_s": "3", "after_s": "3"}.items()}
        self.status = tk.StringVar(
            value="Run Population swimming first to get a tracks CSV, then "
                  "choose it and the movie here.")
        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    def _build_controls(self):
        c = self.controls
        fields = [
            ("Population tracks CSV (track_id, frame, x, y)", "tracks", True),
            ("Movie / stack / image folder (tap signal)", "movie", True),
            ("FPS", "fps", False), ("Scale (units/pixel)", "scale", False),
            ("Speed-change threshold (fraction of baseline)", "speed_change_frac", False),
            ("Direction-change threshold (degrees)", "direction_change_deg", False),
            ("Before window (s)", "before_s", False),
            ("After window (s)", "after_s", False),
        ]
        for label, key, browse in fields:
            row = ttk.Frame(c); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=28, wraplength=195, justify="left").pack(side="left")
            ttk.Entry(row, textvariable=self.v[key]).pack(side="right", fill="x", expand=True)
            if browse:
                ttk.Button(c, text=f"Choose {key}...",
                           command=lambda k=key: self._choose(k)).pack(fill="x", pady=(0, 2))
        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(c, text="Detect taps and analyze responses",
                   command=self.run).pack(fill="x", pady=2)

    def _build_center(self):
        ttk.Label(self.center, text="Population tap response / habituation",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        ttk.Label(self.center, wraplength=620, justify="left", foreground="#444444",
                  text=("Run 'Population swimming + modality review' first to produce a tracks "
                        "CSV (track_id, frame, x, y). This tool detects the plate tap(s) from the "
                        "global field motion, measures each tap's intensity, duration, and "
                        "frequency, splits every worm's centroid track into before/after windows "
                        "around each tap, and reports which animals responded (by speed and/or "
                        "direction) and the population response fraction per tap.")).pack(
            anchor="w", padx=6, pady=4)
        ttk.Separator(self.center, orient="horizontal").pack(fill="x", padx=6, pady=6)
        ttk.Label(self.center, textvariable=self.status, wraplength=620,
                  justify="left").pack(anchor="w", padx=6, pady=4)

    def _choose(self, key):
        if key == "tracks":
            p = filedialog.askopenfilename(
                title="Population tracks CSV", filetypes=[("CSV", "*.csv")])
        else:
            p = filedialog.askopenfilename(
                title="Movie, stack, or one image of a sequence",
                filetypes=[("Movies, stacks and images",
                            "*.avi *.mp4 *.mov *.mkv *.tif *.tiff *.jpg *.jpeg "
                            "*.png"), ("All files", "*.*")])
        if p:
            self.v[key].set(p)

    def run(self):
        try:
            tracks_path = Path(self.v["tracks"].get())
            if not tracks_path.exists():
                raise ValueError("Choose a population tracks CSV.")
            movie = self.v["movie"].get()
            if not movie:
                raise ValueError("Choose the movie for the tap signal.")
            fps = float(self.v["fps"].get())
            scale = float(self.v["scale"].get())
            if not (fps > 0):
                raise ValueError("FPS must be greater than zero.")
            tracks = read_table(tracks_path)
            need = {"track_id", "frame", "x", "y"}
            missing = sorted(need - set(tracks.columns))
            if missing:
                raise ValueError(
                    "The tracks CSV is missing columns: " + ", ".join(missing) +
                    ". Use the export from Population swimming.")
            self.status.set("Measuring global field motion for tap detection...")
            self.update_idletasks()
            motion, n = _motion_signal_streaming(movie)
            times = np.arange(n) / fps
            taps = PT.detect_taps(motion, times)
            if not taps:
                messagebox.showinfo(
                    "No tap detected",
                    "No global motion tap was detected. Check FPS, or that the "
                    "movie contains the plate tap.", parent=self)
                self.status.set("No tap detected.")
                return
            rt = PT.tap_response_table(
                tracks, taps, fps, scale=scale,
                before_s=float(self.v["before_s"].get()),
                after_s=float(self.v["after_s"].get()),
                speed_change_frac=float(self.v["speed_change_frac"].get()),
                direction_change_deg=float(self.v["direction_change_deg"].get()))
            summary = PT.population_summary(rt)
            out = tracks_path.parent / (tracks_path.stem + "_tap_response")
            out.mkdir(parents=True, exist_ok=True)
            pd.DataFrame([{k: v for k, v in t.items()} for t in taps]).to_csv(
                out / "taps.csv", index=False)
            rt.to_csv(out / "per_worm_tap_response.csv", index=False)
            (out / "population_tap_summary.json").write_text(
                json.dumps({"fps": fps, "scale": scale,
                            "n_taps": len(taps), "per_tap": summary}, indent=2),
                encoding="utf-8")
            frac = summary[0]["fraction_responding"] if summary else None
            self.status.set(
                f"{len(taps)} tap(s); first-tap responders: "
                f"{'' if frac is None else f'{frac*100:.0f}%'}. Saved: {out}")
            messagebox.showinfo(
                "Population tap response",
                f"Detected {len(taps)} tap(s).\n"
                f"Per-tap response fractions: "
                + ", ".join(f"tap {s['tap_number']}: "
                            f"{(s['fraction_responding'] or 0)*100:.0f}%"
                            for s in summary)
                + f"\n\nSaved to:\n{out}", parent=self)
        except Exception as exc:
            messagebox.showerror("Population tap response", str(exc), parent=self)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
