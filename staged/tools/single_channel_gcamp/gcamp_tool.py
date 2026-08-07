"""Student-facing T13 feasibility-first single-channel GCaMP workflow."""
from __future__ import annotations

import csv
import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app"), str(ROOT / "tools" / "movie")]

from acquisition import AcquisitionMetadata
import gcamp_session
from movie_reader import open_movie
from image_sequence import discover_images
from run_feedback import prompt_post_run_feedback
from gcamp import (
    extract_trace, feasibility_pass, body_visibility_pass, extract_oriented_cell)
from process_ui import CockpitApp

TOOL_NAME = "Single-channel GCaMP feasibility and extractor"
TOOL_VERSION = "0.2.0"


def gray(frame):
    values = np.asarray(frame)
    if values.ndim == 2:
        return np.asarray(values, dtype=np.float32)
    return np.add.reduce(
        values[..., :3], axis=2, dtype=np.float32) / np.float32(
            min(3, values.shape[2]))


class App(CockpitApp):
    def __init__(self):
        super().__init__(TOOL_NAME, geometry="1180x760", process_title="Single-channel GCaMP")
        defaults = {
            "source": "", "fps": "30", "scale": "1.0", "exposure": "10",
            "bit_depth": "16", "channel": "blue GCaMP",
            "sample_frames": "8", "neuron_radius": "4",
            "search_radius": "20",
        }
        self.v = {key: tk.StringVar(value=value)
                  for key, value in defaults.items()}
        self.JOBS = {
            "Job 1: body visibility (body-wall GCaMP)": "body",
            "Job 2: track a cell (orientation)": "cell",
            "Job 3: cell + body": "cell_body",
        }
        self.job = tk.StringVar(value="Job 2: track a cell (orientation)")
        self.status = tk.StringVar(
            value="Pick the analysis job, choose a recording, then follow the "
                  "numbered buttons.")
        self.frames = None
        self.seed = None
        self.feasibility = None
        self.cell_soma = None
        self.cell_tip = None
        self.body_result = None
        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    def _build_controls(self):
        c = self.controls

        def field(label, key):
            row = ttk.Frame(c); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=24, wraplength=175, justify="left").pack(side="left")
            ttk.Entry(row, textvariable=self.v[key]).pack(side="right", fill="x", expand=True)

        jrow = ttk.Frame(c); jrow.pack(fill="x", pady=(0, 2))
        ttk.Label(jrow, text="Analysis job", width=24).pack(side="left")
        job_box = ttk.Combobox(jrow, textvariable=self.job, state="readonly",
                               values=list(self.JOBS), width=30)
        job_box.pack(side="right", fill="x", expand=True)
        job_box.bind("<<ComboboxSelected>>", lambda _e: self._rebuild_actions())

        srow = ttk.Frame(c); srow.pack(fill="x", pady=2)
        ttk.Label(srow, text="Recording", width=24).pack(side="left")
        ttk.Entry(srow, textvariable=self.v["source"]).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose file / folder...", command=self._choose_and_show).pack(fill="x", pady=(0, 4))
        self._cell_fields = []
        for label, key in [
                ("Declared FPS", "fps"), ("Scale (um/pixel)", "scale"),
                ("Exposure (ms)", "exposure"), ("Bit depth", "bit_depth"),
                ("Channel identity", "channel"), ("Sample frames", "sample_frames"),
                ("Cell radius (pixels)", "neuron_radius"),
                ("Local search radius (pixels)", "search_radius")]:
            field(label, key)

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        self._actions = ttk.Frame(c); self._actions.pack(fill="x")
        self._rebuild_actions()

    def _current_job(self):
        return self.JOBS.get(self.job.get(), "cell")

    def _rebuild_actions(self):
        for child in self._actions.winfo_children():
            child.destroy()
        job = self._current_job()
        a = self._actions
        if job == "body":
            ttk.Label(a, wraplength=205, justify="left", foreground="#555555",
                      text="Body-wall GCaMP: is the worm separable from the "
                           "background well enough to infer its outline / spine "
                           "even when muscles relax?").pack(fill="x", pady=(0, 4))
            ttk.Button(a, text="1. Assess body visibility",
                       command=self.run_body_visibility).pack(fill="x", pady=2)
            ttk.Button(a, text="2. Track kinematics in the worm tracker",
                       command=self._handoff_to_tracker).pack(fill="x", pady=2)
        elif job == "cell":
            ttk.Label(a, wraplength=205, justify="left", foreground="#555555",
                      text="Track one elongated cell. Mark the soma, then the "
                           "process tip toward the nose - that long axis is the "
                           "orientation (not the direction of travel).").pack(fill="x", pady=(0, 4))
            ttk.Button(a, text="1. Mark cell (soma, then tip)",
                       command=self.mark_cell_axis).pack(fill="x", pady=2)
            ttk.Button(a, text="2. Track cell + orientation, review, export",
                       command=self.run_cell_tracking).pack(fill="x", pady=2)
        else:  # cell_body
            ttk.Label(a, wraplength=205, justify="left", foreground="#555555",
                      text="Track the cell (soma->tip orientation) AND assess "
                           "whether the body is separable enough to also read "
                           "posture / kinematics.").pack(fill="x", pady=(0, 4))
            ttk.Button(a, text="1. Mark cell (soma, then tip)",
                       command=self.mark_cell_axis).pack(fill="x", pady=2)
            ttk.Button(a, text="2. Assess body + track cell, review, export",
                       command=self.run_cell_and_body).pack(fill="x", pady=2)
            ttk.Button(a, text="Track body kinematics in the worm tracker",
                       command=self._handoff_to_tracker).pack(fill="x", pady=(2, 2))

    def _choose_and_show(self):
        self.choose()
        if self.v["source"].get():
            self._show_first_frame()

    def _build_center(self):
        ttk.Label(self.center, text="Single-channel GCaMP: body, cell, and orientation",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        self.center_fig = Figure(figsize=(5.6, 4.0), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111); self.center_ax.set_axis_off()
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        self.center_ax.text(0.5, 0.5, "Choose a source; the first frame appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        # The picture is packed LAST, after every control below, so it takes
        # only the space that is left. Packed first with expand=True it grew
        # into the window and pushed the dial and its buttons off the bottom
        # after a run made the status text longer - the controls vanished and
        # a second recording could not be chosen.
        dial = ttk.LabelFrame(self.center, text="Display brightness / contrast "
                                                "(changes what you SEE, never "
                                                "what is measured)", padding=6)
        dial.pack(side="bottom", fill="x", padx=6, pady=(0, 4))
        self.disp_lo = tk.DoubleVar(value=1.0)
        self.disp_hi = tk.DoubleVar(value=99.5)
        ttk.Label(dial, text="black point (percentile)").grid(row=0, column=0,
                                                              sticky="w")
        ttk.Scale(dial, from_=0.0, to=40.0, variable=self.disp_lo,
                  orient="horizontal", length=170,
                  command=self._rescale_display).grid(row=0, column=1, padx=6)
        ttk.Label(dial, text="white point (percentile)").grid(row=1, column=0,
                                                              sticky="w")
        ttk.Scale(dial, from_=60.0, to=100.0, variable=self.disp_hi,
                  orient="horizontal", length=170,
                  command=self._rescale_display).grid(row=1, column=1, padx=6)
        ttk.Button(dial, text="Auto (1 - 99.5)",
                   command=lambda: (self.disp_lo.set(1.0), self.disp_hi.set(99.5),
                                    self._rescale_display())
                   ).grid(row=0, column=2, rowspan=2, padx=8)
        ttk.Button(dial, text="Find recordings in this folder...",
                   command=self.find_episodes).grid(row=0, column=3, padx=4)
        ttk.Button(dial, text="Choose frames by hand...",
                   command=self.choose_frame_subset).grid(row=1, column=3, padx=4)
        ttk.Button(dial, text="Save session marks...",
                   command=self.save_session_marks).grid(row=0, column=4, padx=4)
        ttk.Button(dial, text="Load session marks...",
                   command=self.load_session_marks).grid(row=1, column=4, padx=4)

        ttk.Label(self.center, textvariable=self.status, wraplength=560,
                  justify="left").pack(side="bottom", anchor="w", padx=6,
                                       pady=(0, 2))
        ttk.Label(self.center, wraplength=560, justify="left", foreground="#8a3b00",
                  text=("Pick a job: (1) body-wall GCaMP - is the worm separable from "
                        "background enough to read its outline/kinematics; (2) a single "
                        "cell - track it and its soma->tip long axis (position, brightness, "
                        "translational and angular velocity); (3) both. Cell tracking "
                        "searches only near the predicted position - it never jumps to the "
                        "brightest object elsewhere.")).pack(side="bottom", anchor="w",
                                                             padx=6, pady=(0, 6))
        # Everything above claimed its space from the bottom up; the canvas now
        # fills whatever remains and can never squeeze the controls out.
        self.center_canvas.get_tk_widget().pack(fill="both", expand=True,
                                                padx=6, pady=(0, 4))

    def find_episodes(self):
        """Split a session folder into separate recordings and let one be chosen.

        A folder is often not one recording. The protocol here is: find a worm
        under transmitted light, zoom, switch to blue light, film, move to the
        next worm - so one folder holds many takes. Analysed whole it shows 88%
        frame-to-frame brightness variation, and a baseline drawn across
        transmitted-light frames would make dF/F0 meaningless.
        """
        import tkinter as tk
        from tkinter import messagebox, ttk as _ttk
        from gcamp import detect_episodes

        try:
            movie = open_movie(self.v["source"].get())
        except Exception as exc:
            messagebox.showerror("Could not open the recording", str(exc))
            return
        n = int(movie.n_frames)
        step = max(1, n // 2500)
        self.status.set(f"Scanning {n} frames for separate recordings...")
        self.update_idletasks()
        try:
            means = np.array([float(np.mean(gray(movie.get_frame(int(i)))))
                              for i in range(0, n, step)])
        finally:
            movie.close()
        eps = detect_episodes(means, min_length=max(8, 40 // step))
        for e in eps:
            e["frame_start"] = e["start"] * step
            e["frame_end"] = min(e["end"] * step + step - 1, n - 1)

        win = tk.Toplevel(self)
        win.title("Recordings found in this folder")
        win.geometry("720x420")
        _ttk.Label(win, padding=8, wraplength=690, justify="left",
                   text=(f"{len(eps)} runs of steady illumination in {n} frames. "
                         f"Dim runs are the likely fluorescence takes; bright "
                         f"ones are probably transmitted-light looks while a "
                         f"worm was found. Choose ONE - measuring across a "
                         f"switch of illumination is not a calcium "
                         f"measurement.")).pack(fill="x")
        body = _ttk.Frame(win)
        body.pack(fill="both", expand=True)
        cols = ("frames", "count", "mean", "steady", "kind")
        tree = _ttk.Treeview(body, columns=cols, show="headings", height=12)
        for c, w in zip(cols, (130, 70, 80, 65, 200)):
            tree.heading(c, text=c)
            tree.column(c, width=w, anchor="w")
        for i, e in enumerate(eps):
            tree.insert("", "end", iid=str(i), values=(
                f"{e['frame_start']} - {e['frame_end']}",
                e["frame_end"] - e["frame_start"] + 1,
                f"{e['mean']:.0f}",
                "yes" if e.get("stable") else "no",
                e["kind"]))
        tree.pack(side="left", fill="both", expand=True, padx=(8, 4), pady=4)

        # PREVIEW. The classifier labels episodes with question marks because it
        # infers illumination from brightness alone - a take filmed at another
        # gain could be misfiled. Asking someone to choose without looking is
        # asking them to trust that guess; showing four frames from the
        # selected episode makes it checkable in a second.
        prev_fig = Figure(figsize=(4.6, 3.6), dpi=100)
        prev_axes = prev_fig.subplots(2, 2).ravel()
        for a in prev_axes:
            a.set_axis_off()
        prev_canvas = FigureCanvasTkAgg(prev_fig, master=body)
        prev_canvas.get_tk_widget().pack(side="left", fill="both", expand=True,
                                         padx=(4, 8), pady=4)

        def preview(_evt=None):
            sel = tree.selection()
            if not sel:
                return
            e = eps[int(sel[0])]
            a, b = e["frame_start"], e["frame_end"]
            picks = np.linspace(a, b, 4).astype(int)
            try:
                mv = open_movie(self.v["source"].get())
                imgs = [gray(mv.get_frame(int(i))) for i in picks]
                mv.close()
            except Exception as exc:
                self.status.set(f"Preview failed: {exc}")
                return
            for ax, im, i in zip(prev_axes, imgs, picks):
                ax.clear(); ax.set_axis_off()
                lo, hi = self._display_limits(im)
                ax.imshow(im, cmap="gray", vmin=lo, vmax=hi)
                ax.set_title(f"frame {i}  mean {np.mean(im):.0f}", fontsize=7)
            prev_fig.suptitle(f"{a}-{b}   {e['kind']}", fontsize=8)
            prev_fig.tight_layout()
            prev_canvas.draw()

        tree.bind("<<TreeviewSelect>>", preview)
        if eps:
            tree.selection_set("0")
            preview()

        def use():
            sel = tree.selection()
            if not sel:
                return
            e = eps[int(sel[0])]
            self.episode_range = (e["frame_start"], e["frame_end"])
            # Recorded as detected rather than manual: a boundary the detector
            # proposed is not the same evidence as one a person drew, and once
            # both are in a session file nothing else can tell them apart.
            self.session_marks = gcamp_session.marks_from_ranges(
                [(e["frame_start"], e["frame_end"])], kind=e.get("kind", ""),
                origin="detected")
            self.frames = None
            self.status.set(
                f"Using frames {e['frame_start']}-{e['frame_end']} "
                f"({e['frame_end'] - e['frame_start'] + 1} frames, {e['kind']}). "
                f"Re-run the feasibility pass.")
            win.destroy()

        bar = _ttk.Frame(win, padding=6)
        bar.pack(fill="x")
        _ttk.Button(bar, text="Use the selected recording", command=use
                    ).pack(side="right")
        _ttk.Button(bar, text="Cancel", command=win.destroy).pack(side="right",
                                                                  padx=6)
        win.transient(self)
        win.grab_set()

    def check_frame_brightness(self):
        """Is frame-to-frame brightness variation biology, or the codec?

        Andres reported that some frames look brighter and suspected an
        encoding bug. That distinction is not cosmetic: this tool measures
        calcium as intensity over time, so a codec that varies frame brightness
        would produce a signal indistinguishable from activity - reproducible,
        plausible, and entirely artefactual.

        A compressed movie encodes occasional key frames and reconstructs the
        rest, and quantisation differs between the two. The signature is
        PERIODICITY at the key-frame interval - a spike every N frames - which
        biology has no reason to produce. Real calcium transients are aperiodic
        and last longer than one frame.
        """
        from tkinter import messagebox
        try:
            movie = open_movie(self.v["source"].get())
        except Exception as exc:
            messagebox.showerror("Could not open the recording", str(exc))
            return
        n = int(movie.n_frames)
        take = min(n, 400)
        idx = np.linspace(0, n - 1, take).astype(int)
        means = []
        try:
            for i in idx:
                means.append(float(np.mean(gray(movie.get_frame(int(i))))))
        finally:
            movie.close()
        means = np.asarray(means, dtype=float)
        if means.size < 16:
            messagebox.showinfo("Too few frames",
                                "Not enough frames to judge periodicity.")
            return

        d = means - np.mean(means)
        rel = float(np.std(means) / max(np.mean(means), 1e-9))
        spec = np.abs(np.fft.rfft(d * np.hanning(d.size)))
        freqs = np.fft.rfftfreq(d.size, d=1.0)
        spec[0] = 0.0
        k = int(np.argmax(spec))
        period = (1.0 / freqs[k]) if freqs[k] > 0 else float("inf")
        peak_ratio = float(spec[k] / max(np.median(spec[1:]), 1e-12))

        # a step change points at auto-exposure or gain, not compression
        jumps = np.abs(np.diff(means))
        big = int((jumps > 5 * np.median(jumps) + 1e-9).sum())

        looks_periodic = peak_ratio > 8 and 1.5 < period < 60
        verdict = (
            "PERIODIC - consistent with a codec key-frame pattern rather than "
            "biology. Intensity measured from this recording would carry that "
            "pattern as if it were signal."
            if looks_periodic else
            "No strong periodicity. The variation looks aperiodic, which is "
            "what real activity looks like - though that is not proof it is.")
        messagebox.showinfo(
            "Frame brightness check",
            f"{take} frames sampled of {n}.\n\n"
            f"Frame-mean variation: {100 * rel:.1f}% of the mean\n"
            f"Strongest periodicity: every {period:.1f} frames "
            f"({peak_ratio:.1f}x the background spectrum)\n"
            f"Abrupt level changes: {big}\n\n"
            f"{verdict}\n\n"
            f"If it is the codec, re-export the recording without inter-frame "
            f"compression - an uncompressed or lossless TIFF stack - before "
            f"measuring anything from it.")

    def _display_limits(self, image):
        """vmin/vmax for DISPLAY ONLY - never for measurement.

        Matplotlib's default autoscale stretches to the full data range, so a
        dim GCaMP frame with a handful of hot pixels renders the worm almost
        black and it looks undetectable when it is plainly there. These
        percentiles change what a human sees and nothing else; every number
        this tool reports comes from the raw frames.
        """
        a = np.asarray(image, dtype=float)
        finite = a[np.isfinite(a)]
        if finite.size == 0:
            return None, None
        lo = float(np.percentile(finite, float(self.disp_lo.get())))
        hi = float(np.percentile(finite, float(self.disp_hi.get())))
        if hi <= lo:
            hi = lo + 1e-6
        return lo, hi

    def _imshow(self, axis, image, **kw):
        lo, hi = self._display_limits(image)
        return axis.imshow(image, cmap="gray", vmin=lo, vmax=hi, **kw)

    def _rescale_display(self, *_):
        if getattr(self, "_last_display_image", None) is None:
            return
        self.center_ax.clear()
        self._imshow(self.center_ax, self._last_display_image)
        self.center_ax.set_axis_off()
        self.center_ax.set_title(getattr(self, "_last_display_title", ""),
                                 fontsize=9)
        self.center_canvas.draw()

    def _show_first_frame(self):
        try:
            m = open_movie(self.v["source"].get())
            n = int(m.n_frames)
            im = gray(m.get_frame(0))
            m.close()
        except Exception as exc:
            self.status.set(f"Could not load frame: {exc}"); return
        # A new source invalidates any previously chosen range - carrying one
        # over would silently analyse frames of a different recording. The
        # marks go with it, for the same reason: they are source frame
        # numbers, and they mean nothing against a different recording.
        self.episode_range = None
        self.session_marks = []
        self.frames = None
        self._last_display_image = im
        self._last_display_title = f"First frame (of {n})"
        self.center_ax.clear(); self._imshow(self.center_ax, im)
        self.center_ax.set_axis_off()
        self.center_ax.set_title(self._last_display_title, fontsize=9)
        self.center_canvas.draw()
        if n > 400:
            self.status.set(
                f"{n} frames. A folder often holds several recordings - use "
                f"'Find recordings in this folder...' to pick one, or 'Choose "
                f"frames...' to set a range by hand. Analysing across a change "
                f"of illumination is not a calcium measurement.")

    def save_session_marks(self):
        """Write the marked range out as structured session data.

        Deciding which frames are the real fluorescence take is the expensive
        part of this work, and until now it lived in a tuple that died with
        the window.
        """
        marks = getattr(self, "session_marks", None)
        if not marks:
            messagebox.showinfo(
                "Session marks",
                "Nothing is marked yet. Use 'Find recordings in this "
                "folder...' or 'Choose frames by hand...' first - there is "
                "no point writing an empty file.", parent=self)
            return
        source = self.v["source"].get()
        path = filedialog.asksaveasfilename(
            parent=self, title="Save session marks",
            defaultextension=".json",
            initialfile=gcamp_session.DEFAULT_NAME,
            initialdir=str(Path(source).parent if source else Path.cwd()),
            filetypes=[("Session marks", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            gcamp_session.save_marks(
                path, marks, source=source,
                frame_count=getattr(self, "_session_frame_count", None))
        except Exception as exc:
            messagebox.showerror("Session marks", str(exc), parent=self)
            return
        self.status.set(f"Session marks saved to {Path(path).name}.")

    def load_session_marks(self):
        """Read marks back and apply them, without re-deciding anything."""
        source = self.v["source"].get()
        path = filedialog.askopenfilename(
            parent=self, title="Load session marks",
            initialdir=str(Path(source).parent if source else Path.cwd()),
            filetypes=[("Session marks", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            document = gcamp_session.load_marks(path, source=source or None)
            (a, b), gap = gcamp_session.span(document["marks"])
        except Exception as exc:
            messagebox.showerror("Session marks", str(exc), parent=self)
            return
        self.session_marks = document["marks"]
        self.episode_range = (int(a), int(b))
        self.frames = None
        if document.get("frame_count"):
            self._session_frame_count = int(document["frame_count"])
        origins = sorted({m["origin"] for m in document["marks"]})
        gap_note = (f" Spans {gap} unmarked frames, which will be analysed "
                    f"too." if gap else "")
        self.status.set(
            f"Loaded {len(document['marks'])} mark(s) from "
            f"{Path(path).name}: frames {a}-{b} ({b - a + 1} frames, "
            f"{'/'.join(origins)}).{gap_note} Re-run the feasibility pass.")

    def choose_frame_subset(self):
        """Pick a frame range by hand, at load time rather than after.

        The frame chooser previously appeared only when a load was already too
        large to fit in memory - so a user with a merely awkward recording had
        no way to say "just this part" until something failed.
        """
        from tkinter import messagebox
        try:
            movie = open_movie(self.v["source"].get())
        except Exception as exc:
            messagebox.showerror("Could not open the recording", str(exc))
            return
        try:
            from frame_range_selector import select_frame_ranges
            ranges = select_frame_ranges(self, movie,
                                         "Choose the frames to analyse")
        except Exception as exc:
            movie.close()
            messagebox.showerror("Frame chooser unavailable", str(exc))
            return
        frame_count = int(movie.n_frames)
        movie.close()
        if not ranges:
            return
        try:
            self.session_marks = gcamp_session.marks_from_ranges(
                ranges, origin="manual")
            (a, b), gap = gcamp_session.span(self.session_marks)
        except gcamp_session.SessionMarkError as exc:
            messagebox.showerror("Frame range", str(exc), parent=self)
            return
        self.episode_range = (int(a), int(b))
        self.frames = None
        self._session_frame_count = frame_count
        # The tool analyses one contiguous span, so disjoint marks collapse to
        # their outer bounds and the frames between them come along. Saying so
        # is the difference between a choice and a surprise.
        gap_note = (f" NOTE: this spans {gap} frames you did not mark, which "
                    f"will be analysed too - the analysis takes one "
                    f"contiguous range." if gap else "")
        self.status.set(f"Using frames {a}-{b} ({b - a + 1} frames)."
                        f"{gap_note} Re-run the feasibility pass.")

    def choose(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Choose a movie, TIFF stack, or one frame of an image sequence",
            filetypes=[("Movies, stacks, and image frames",
                        "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.pgm "
                        "*.avi *.mp4 *.mov *.mkv *.webm"),
                       ("All files", "*.*")])
        if not path:
            path = filedialog.askdirectory(
                parent=self, title="Or choose a folder of numbered frames")
        if not path:
            return
        path = self._resolve_sequence(path)
        if path:
            self.v["source"].set(path)
            self.frames = None
            self.feasibility = None

    def _resolve_sequence(self, path):
        """Accept a folder, a real multi-frame movie/stack, or a single still
        image that belongs to a numbered sequence (offer to load its folder).

        Picking one .tif out of a numbered sequence used to load a single frame
        and fail the multi-frame check; here we detect that and load the folder.
        """
        p = Path(path)
        if p.is_dir():
            return str(p)
        frame_count = None
        movie = None
        try:
            movie = open_movie(str(p))
            frame_count = int(movie.n_frames)
        except Exception:
            frame_count = None
        finally:
            try:
                if movie is not None:
                    movie.close()
            except Exception:
                pass
        if frame_count is not None and frame_count >= 2:
            return str(p)  # genuine movie or multi-page stack
        try:
            sequence = discover_images(p.parent)
        except Exception:
            sequence = []
        if len(sequence) >= 2:
            use_folder = messagebox.askyesno(
                "Load image sequence?",
                f"'{p.name}' is a single frame, but its folder holds "
                f"{len(sequence)} numbered frames.\n\n"
                "Load the whole folder as one recording?",
                parent=self)
            if use_folder:
                return str(p.parent)
        return str(p)

    # Above this the whole-movie load is refused and a frame range must be
    # chosen. Frames are held as float32, so a long recording is far larger in
    # memory than on disk - a 24 GB movie was attempted whole and simply
    # exhausted the machine, with no way offered to take part of it.
    MAX_FRAME_BYTES = 2_000_000_000

    def load_frames(self):
        if self.frames is not None:
            return self.frames
        movie = open_movie(self.v["source"].get())
        count = int(movie.n_frames)
        if count < 2:
            movie.close()
            raise ValueError("A multi-frame recording is required.")
        margin=max(64,int(float(self.v["search_radius"].get())*3),
                   int(float(self.v["neuron_radius"].get())*6))
        centers=np.asarray(getattr(self,"feasibility_centers",[self.seed]),float)
        x0=max(0,int(np.floor(centers[:,0].min()-margin)));x1=min(int(movie.width),int(np.ceil(centers[:,0].max()+margin)))
        y0=max(0,int(np.floor(centers[:,1].min()-margin)));y1=min(int(movie.height),int(np.ceil(centers[:,1].max()+margin)))
        self.analysis_crop=(x0,y0,x1,y1)

        # Which frames? Offer the choice BEFORE allocating anything. The
        # neuron tracker already works this way; this tool did not, and loaded
        # every frame of whatever it was given.
        episode = getattr(self, "episode_range", None)
        if episode:
            indices = list(range(int(episode[0]),
                                 min(int(episode[1]) + 1, count)))
        else:
            indices = list(range(count))
        per_frame = (y1 - y0) * (x1 - x0) * 4
        if per_frame * count > self.MAX_FRAME_BYTES:
            try:
                from frame_range_selector import select_frame_ranges
                ranges = select_frame_ranges(
                    self, movie,
                    "This recording is too large to load whole - choose the "
                    "frames to analyse")
            except Exception:
                ranges = None
            if ranges:
                indices = [i for a, b in ranges for i in range(a, b + 1)]
            if not indices or per_frame * len(indices) > self.MAX_FRAME_BYTES:
                movie.close()
                need = per_frame * max(len(indices), 1) / 1e9
                raise ValueError(
                    f"This selection needs about {need:.1f} GB of memory "
                    f"({len(indices)} frames at {per_frame/1e6:.1f} MB each, "
                    f"held as float32). The limit is "
                    f"{self.MAX_FRAME_BYTES/1e9:.1f} GB.\n\n"
                    f"Choose a shorter range of frames. Loading more than the "
                    f"machine can hold does not fail quickly - it swaps, and "
                    f"the tool appears to hang instead of telling you why.")

        self.frame_indices = indices
        self.frames=np.empty((len(indices),y1-y0,x1-x0),dtype=np.float32)
        def cropped_gray(frame):return gray(frame)[y0:y1,x0:x1]
        if getattr(movie, "source_kind", "") == "image_sequence":
            workers = min(6, max(2, (os.cpu_count() or 2) // 2))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for slot, frame in enumerate(pool.map(
                        lambda i: cropped_gray(movie.get_frame(i)), indices)):
                    self.frames[slot] = frame
        else:
            wanted = set(indices)
            slot = 0
            for index, frame in enumerate(movie.frames()):
                if index in wanted:
                    self.frames[slot] = cropped_gray(frame)
                    slot += 1
                    if slot >= len(indices):
                        break
        movie.close()
        self.seed=(self.seed[0]-x0,self.seed[1]-y0)
        return self.frames

    def acquisition(self, recording_duration_s=None):
        return AcquisitionMetadata(
            float(self.v["fps"].get()), "declared",
            float(self.v["scale"].get()), "declared",
            float(self.v["exposure"].get()), "declared",
            bit_depth=int(self.v["bit_depth"].get()),
            compression="unknown",
            recording_duration_s=recording_duration_s,
            channel_identity=self.v["channel"].get(),
            anatomical_orientation="unknown").validate()

    def load_feasibility_sample(self):
        """Read only the transparent feasibility subsample, never the full movie.

        The sample is drawn from the CHOSEN RANGE, not the whole file. It used
        to span the entire folder regardless, so after picking one recording out
        of a session the feasibility pass still assessed all of it - including
        the transmitted-light stretches between takes - and reported the worm as
        not separable when the chosen episode was fine. The choice had no effect
        on the thing it was made for.
        """
        movie = open_movie(self.v["source"].get())
        count = int(movie.n_frames)
        if count < 2:
            movie.close()
            raise ValueError("A multi-frame recording is required.")
        episode = getattr(self, "episode_range", None)
        lo, hi = (int(episode[0]), min(int(episode[1]), count - 1)) if episode \
            else (0, count - 1)
        if hi - lo < 1:
            movie.close()
            raise ValueError(
                f"The chosen range {lo}-{hi} holds fewer than two frames.")
        sample_count = max(2, min(int(self.v["sample_frames"].get()),
                                  hi - lo + 1))
        indices = np.unique(np.linspace(
            lo, hi, sample_count).round().astype(int))
        frames = np.stack(
            [gray(movie.get_frame(int(index))) for index in indices])
        movie.close()
        return count, indices, frames

    def _seed_on_frame(self, image, title, allow_cancel=False):
        fig, axis = plt.subplots()
        axis.imshow(image, cmap="gray")
        axis.set_title(title)
        points = plt.ginput(1, timeout=0)
        plt.close(fig)
        if len(points) != 1:
            if allow_cancel:
                return None
            raise ValueError("A neuron click is required.")
        return points[0]

    def run_feasibility(self):
        try:
            acquisition = self.acquisition()
            count, indices, sampled_frames = self.load_feasibility_sample()
            centers = []
            last = None
            for sample_position, index in enumerate(indices):
                title = (
                    f"Feasibility frame {index}: click the neuron. "
                    "Use the same target; canceling blocks the pass.")
                last = self._seed_on_frame(
                    sampled_frames[sample_position], title)
                centers.append(last)
            self.seed = centers[0]
            self.feasibility_centers=centers
            structural = messagebox.askyesno(
                "Structural frames",
                "Were transmitted-light or brightfield frames recorded "
                "alongside this fluorescence movie?", parent=self)
            result = feasibility_pass(
                sampled_frames, centers,
                float(self.v["neuron_radius"].get()),
                float(self.v["fps"].get()),
                structural_frames_present=structural)
            result["recording_frame_count"] = count
            result["sampled_frame_indices"] = indices.tolist()
            result["acquisition_constants_validated_before_load"] = True
            self.feasibility = result
            lines = [
                f"Difficulty: {result['difficulty_tier']}",
                f"Median baseline contrast proxy: "
                f"{result['target_contrast_over_local_background_f0']:.3f}",
                f"Below detection: {result['fraction_below_detection']:.1%}",
                f"Expected manual relinking: "
                f"{result['expected_manual_relink_fraction']:.1%}",
                f"Median competing bright objects: "
                f"{result['competing_bright_objects_median']:.1f}",
                f"Motion / neuron radius: "
                f"{result['displacement_per_frame_relative_to_neuron_size']}",
                f"Bleaching slope: "
                f"{result['photobleaching_slope_intensity_per_s']}",
            ]
            text = "\n".join(lines)
            self.status.set(text)
            if result["difficulty_tier"] == "do not attempt":
                messagebox.showerror(
                    "Do not attempt this movie",
                    text + "\n\nThe feasibility pass did not meet the hard "
                    "floor. No calcium trace should be reported.",
                    parent=self)
            else:
                messagebox.showinfo(
                    "Feasibility result", text, parent=self)
        except Exception as exc:
            messagebox.showerror("Feasibility pass", str(exc), parent=self)

    def _manual_relink(self, frames, extraction):
        flagged = [
            row for row in extraction["rows"]
            if row["manual_relink_required"]]
        if not flagged:
            return 0
        review = messagebox.askyesno(
            "Low-signal review",
            f"{len(flagged)} frame(s) need manual relinking. Review them now?",
            parent=self)
        if not review:
            return 0
        corrected = 0
        for row in flagged:
            index = int(row["frame"])
            point = self._seed_on_frame(
                frames[index],
                f"Frame {index}: click neuron, or close to retain prediction",
                allow_cancel=True)
            if point is None:
                continue
            row["x"], row["y"] = float(point[0]), float(point[1])
            row["position_provenance"] = "manual_relink"
            row["manual_relink_required"] = False
            corrected += 1
        return corrected

    def _review_overlay(self, frames, extraction):
        step = max(1, len(frames) // 12)
        fig, axes = plt.subplots(3, 4, figsize=(12, 8))
        axes = axes.ravel()
        for axis, index in zip(axes, range(0, len(frames), step)):
            row = extraction["rows"][index]
            axis.imshow(frames[index], cmap="gray")
            color = "lime" if not row["low_signal"] else "orange"
            axis.scatter([row["x"]], [row["y"]], c=color, s=25)
            axis.set_title(f"Frame {index}: {row['position_provenance']}")
            axis.axis("off")
        for axis in axes:
            if not axis.has_data():
                axis.axis("off")
        fig.suptitle("Review tracked neuron: green detected/manual, orange flagged")
        plt.tight_layout()
        plt.show()
        return messagebox.askyesno(
            "Accept reviewed track?",
            "Does the marker remain on the same neuron? Choose No to refuse "
            "export and revise the track.", parent=self)

    def run_extractor(self):
        try:
            if self.feasibility is None:
                raise ValueError("Run the feasibility pass first.")
            if self.feasibility["difficulty_tier"] == "do not attempt":
                raise ValueError(
                    "This recording was classified do not attempt. "
                    "No trace will be exported.")
            frames = self.load_frames()
            extraction = extract_trace(
                frames, self.seed, float(self.v["neuron_radius"].get()),
                search_radius_px=float(self.v["search_radius"].get()))
            corrected = self._manual_relink(frames, extraction)
            if not self._review_overlay(frames, extraction):
                self.status.set(
                    "Track rejected. No reviewed calcium result was exported.")
                return
            source = Path(self.v["source"].get())
            x0,y0,_,_=self.analysis_crop
            for row in extraction["rows"]:
                row["x"]+=x0;row["y"]+=y0
                row["analysis_crop_x0_px"]=x0;row["analysis_crop_y0_px"]=y0
            output = source.parent / (source.stem + "_single_channel_gcamp")
            output.mkdir(parents=True, exist_ok=True)
            acquisition = self.acquisition(
                recording_duration_s=len(frames) /
                float(self.v["fps"].get()))
            payload = {
                **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
                "feasibility": self.feasibility,
                "manual_relinks": corrected,
                "review_accepted": True,
                "analysis_crop_xyxy":list(self.analysis_crop),
                **extraction}
            result_path = output / "single_channel_gcamp_trace.json"
            result_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8")
            self.status.set(f"Reviewed trace saved: {result_path}")
            messagebox.showinfo(
                "Extraction complete",
                f"Reviewed trace saved:\n{result_path}\n\n"
                f"Manual relinks: {corrected}", parent=self)
            prompt_post_run_feedback(
                tool_name=TOOL_NAME, tool_version=TOOL_VERSION,
                run_id=output.name, acquisition=acquisition,
                parameters={
                    "neuron_radius_px": float(self.v["neuron_radius"].get()),
                    "search_radius_px": float(self.v["search_radius"].get()),
                    "manual_relinks": corrected},
                parent=self, evidence_paths=[result_path])
        except Exception as exc:
            messagebox.showerror("Single-channel GCaMP", str(exc), parent=self)

    # -- 3-job workflows ----------------------------------------------------
    def _pick_points(self, image, n, title):
        fig, axis = plt.subplots()
        axis.imshow(image, cmap="gray")
        axis.set_title(title)
        pts = plt.ginput(n, timeout=0)
        plt.close(fig)
        return pts if len(pts) >= n else None

    def _first_frame_image(self):
        m = open_movie(self.v["source"].get())
        try:
            return gray(m.get_frame(0))
        finally:
            m.close()

    def mark_cell_axis(self):
        if not self.v["source"].get():
            messagebox.showerror("Mark cell", "Choose a recording first.", parent=self)
            return
        try:
            image = self._first_frame_image()
        except Exception as exc:
            messagebox.showerror("Mark cell", f"Could not load a frame: {exc}", parent=self)
            return
        pts = self._pick_points(
            image, 2,
            "Click the SOMA (cell body), then the PROCESS TIP toward the nose.")
        if not pts:
            self.status.set("Cell marking canceled.")
            return
        self.cell_soma = (float(pts[0][0]), float(pts[0][1]))
        self.cell_tip = (float(pts[1][0]), float(pts[1][1]))
        self.center_ax.clear()
        self.center_ax.imshow(image, cmap="gray")
        self.center_ax.set_axis_off()
        self.center_ax.plot([self.cell_soma[0], self.cell_tip[0]],
                            [self.cell_soma[1], self.cell_tip[1]], "-", color="#00e0ff", lw=2)
        self.center_ax.plot(self.cell_soma[0], self.cell_soma[1], "o", color="#00e0ff", ms=7)
        self.center_ax.plot(self.cell_tip[0], self.cell_tip[1], "x", color="#ff4fd8", ms=9, mew=2)
        self.center_ax.set_title("Cell axis: soma (o) -> process tip (x)", fontsize=9)
        self.center_canvas.draw()
        self.status.set("Cell axis set (soma -> tip). Run step 2 to track it.")

    def _track_cell(self):
        """Shared cell tracking: returns (frames, result) in crop coordinates."""
        if self.cell_soma is None or self.cell_tip is None:
            raise ValueError("Mark the cell first (soma, then tip).")
        self.seed = self.cell_soma
        self.feasibility_centers = [self.cell_soma]
        frames = self.load_frames()
        x0, y0, _, _ = self.analysis_crop
        soma = (self.cell_soma[0] - x0, self.cell_soma[1] - y0)
        tip = (self.cell_tip[0] - x0, self.cell_tip[1] - y0)
        result = extract_oriented_cell(
            frames, soma, tip,
            float(self.v["neuron_radius"].get()),
            float(self.v["fps"].get()), float(self.v["scale"].get()),
            search_radius_px=float(self.v["search_radius"].get()))
        return frames, result

    def _review_oriented(self, frames, result):
        rows = result["rows"]
        step = max(1, len(frames) // 12)
        fig, axes = plt.subplots(3, 4, figsize=(12, 8))
        axes = axes.ravel()
        for axis, i in zip(axes, range(0, len(frames), step)):
            row = rows[i]
            axis.imshow(frames[i], cmap="gray")
            color = "orange" if row["low_signal"] else "lime"
            axis.plot(row["x"], row["y"], "o", color=color, ms=5)
            length = 12.0
            axis.plot([row["x"], row["x"] + length * row["orientation_dx"]],
                      [row["y"], row["y"] + length * row["orientation_dy"]],
                      "-", color=color, lw=1.6)
            axis.set_title(f"f{i}: {row['orientation_deg']:.0f} deg", fontsize=7)
            axis.axis("off")
        for axis in axes:
            if not axis.has_data():
                axis.axis("off")
        fig.suptitle("Cell position (dot) and long axis soma->tip (line). "
                     "Orange = low signal (predicted).")
        plt.tight_layout()
        plt.show()
        return messagebox.askyesno(
            "Accept oriented track?",
            "Does the line stay on the cell's long axis (soma toward the nose)? "
            "Choose No to refuse export and revise.", parent=self)

    def _export_cell(self, result, acquisition, body=None):
        source = Path(self.v["source"].get())
        output = source.parent / (source.stem + "_cell_orientation")
        output.mkdir(parents=True, exist_ok=True)
        payload = {
            **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
            "job": self._current_job(),
            "analysis_crop_xyxy": list(self.analysis_crop),
            "body_visibility": body,
            **result}
        (output / "cell_orientation.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8")
        columns = ["frame", "x", "y", "orientation_deg", "orientation_unwrapped_deg",
                   "angular_velocity_deg_s", "translational_speed_px_s",
                   "translational_speed_um_s", "brightness_f", "relative_dff",
                   "elongation", "detection_snr", "low_signal", "position_provenance"]
        with (output / "cell_orientation.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for row in result["rows"]:
                writer.writerow({key: row.get(key) for key in columns})
        self.status.set(f"Saved cell orientation trace: {output}")
        messagebox.showinfo(
            "Export complete",
            f"Cell orientation trace (position, brightness, translational and "
            f"angular velocity) saved:\n{output}", parent=self)

    def run_cell_tracking(self):
        try:
            acquisition = self.acquisition()
            frames, result = self._track_cell()
            if not self._review_oriented(frames, result):
                self.status.set("Track rejected. Nothing exported.")
                return
            x0, y0, _, _ = self.analysis_crop
            for row in result["rows"]:
                row["x"] += x0; row["y"] += y0
            self._export_cell(result, acquisition, body=None)
        except Exception as exc:
            messagebox.showerror("Track cell", str(exc), parent=self)

    def run_body_visibility(self):
        try:
            _count, indices, sample = self.load_feasibility_sample()
            body = body_visibility_pass(sample)
            self.body_result = body
            text = "\n".join([
                f"Body visibility: {body['difficulty_tier']}",
                f"Separable in {body['fraction_frames_body_separable']*100:.0f}% of sampled frames",
                f"Median contrast {body['median_body_background_contrast']:.2f}, "
                f"worst frame {body['worst_frame_contrast']:.2f}",
                ("Outline / spine / kinematics look inferable - hand off to the worm tracker."
                 if body["kinematics_inferable"] else
                 "Body is marginal; relaxed-muscle frames may not be trackable.")])
            self.status.set(text)
            if messagebox.askyesno("Body visibility", text + "\n\nSave this assessment?", parent=self):
                source = Path(self.v["source"].get())
                output = source.parent / (source.stem + "_body_visibility")
                output.mkdir(parents=True, exist_ok=True)
                acquisition = self.acquisition()
                (output / "body_visibility.json").write_text(json.dumps({
                    **acquisition.stamped(TOOL_NAME, TOOL_VERSION), "job": "body",
                    "sampled_frame_indices": indices.tolist(), **body}, indent=2),
                    encoding="utf-8")
                messagebox.showinfo("Saved", f"Body visibility assessment saved:\n{output}", parent=self)
        except Exception as exc:
            messagebox.showerror("Body visibility", str(exc), parent=self)

    def run_cell_and_body(self):
        try:
            _count, indices, sample = self.load_feasibility_sample()
            body = body_visibility_pass(sample)
            self.body_result = body
            acquisition = self.acquisition()
            frames, result = self._track_cell()
            if not self._review_oriented(frames, result):
                self.status.set("Track rejected. Nothing exported.")
                return
            x0, y0, _, _ = self.analysis_crop
            for row in result["rows"]:
                row["x"] += x0; row["y"] += y0
            self._export_cell(result, acquisition, body=body)
            messagebox.showinfo(
                "Cell + body",
                f"Body: {body['difficulty_tier']} (separable in "
                f"{body['fraction_frames_body_separable']*100:.0f}% of frames).\n\n"
                + ("Body kinematics look inferable - use 'Track body kinematics in "
                   "the worm tracker' to read posture alongside the cell brightness."
                   if body["kinematics_inferable"] else
                   "Body may be too dim on some frames for reliable posture."),
                parent=self)
        except Exception as exc:
            messagebox.showerror("Cell + body", str(exc), parent=self)

    def _handoff_to_tracker(self):
        source = self.v["source"].get()
        if not source:
            messagebox.showerror("Worm tracker", "Choose a recording first.", parent=self)
            return
        tracker = ROOT / "tools" / "worm_kinematics" / "dic_tracker" / "run_dic_kinematics.py"
        # HAND OVER THE RANGE THAT WAS ALREADY COMMITTED. This used to pass
        # the recording path alone, so the tracker asked for the interval
        # again with a slider. A slider cannot land on an exact frame, the
        # review state is stored per frame, and the near-miss then read as a
        # frame-count mismatch - a problem created entirely by re-asking a
        # question already answered.
        #
        # episode_range is 0-based with inclusive ends (gcamp_session writes
        # "source frames, 0-based, ends inclusive"); the tracker's flags are
        # 1-based to match the frame numbers it shows the user.
        command = [sys.executable, str(tracker), source]
        episode = getattr(self, "episode_range", None)
        inherited = ""
        if episode:
            first, last = int(episode[0]), int(episode[1])
            command += ["--frame-start", str(first + 1),
                        "--frame-end", str(last + 1)]
            inherited = (f" Carrying over frames {first + 1}-{last + 1} "
                         f"({last - first + 1} frames), so the interval does "
                         f"not have to be chosen again.")
        try:
            subprocess.Popen(command)
            self.status.set("Opened the single-worm tracker on this recording "
                            "(seed the head, review, finalize to get the "
                            "kinematics CSV)." + inherited)
        except Exception as exc:
            messagebox.showerror("Worm tracker", f"Could not start the tracker:\n{exc}", parent=self)


if __name__ == "__main__":
    App().mainloop()
