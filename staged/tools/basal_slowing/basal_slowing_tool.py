"""Student-facing GUI for population basal-slowing analysis."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import cv2
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from basal_slowing import (analyze, list_frames, read_gray,
                           recompute_events_from_tracks)
from track_review import review_tracks, save_track_review
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from roi_editor import draw_roi, draw_rois as draw_multiple_rois
from process_ui import (CockpitApp, ProcessLog, ReviewWorkbench, track_colour,
                        collect_image_points)
import worm_area_probe as wap


class App(CockpitApp):
    def __init__(self):
        super().__init__("Population Basal Slowing", geometry="1180x760",
                         process_title="Basal slowing")
        self.folder = tk.StringVar()
        self.fps = tk.StringVar(value="7.5")
        self.scale = tk.StringVar(value="15.0")
        self.min_area = tk.StringVar(value="40")
        self.max_area = tk.StringVar(value="2500")
        self.max_link_px = tk.StringVar(value="60")
        self.before_s = tk.StringVar(value="10")
        self.after_s = tk.StringVar(value="10")
        self.buffer_px = tk.StringVar(value="10")
        self.window_fraction = tk.StringVar(value="0.70")
        self.entry_fraction = tk.StringVar(value="0.50")
        self.status = tk.StringVar(
            value="Choose a folder, then draw the starting drop and OP50 lawns.")
        self.start_roi = None
        self.lawn_rois = []
        self.start_roi_record = None
        self.lawn_roi_records = []
        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    def _build_controls(self):
        c = self.controls

        def entry_row(label, var):
            row = ttk.Frame(c); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=24, wraplength=170,
                      justify="left").pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="right", fill="x", expand=True)

        frow = ttk.Frame(c); frow.pack(fill="x", pady=2)
        ttk.Label(frow, text="Image folder", width=24).pack(side="left")
        ttk.Entry(frow, textvariable=self.folder).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose folder...", command=self.choose_folder).pack(fill="x", pady=(0, 4))
        entry_row("Declared FPS", self.fps)
        entry_row("Declared scale (um/pixel)", self.scale)
        self.add_scale_button(self._current_frame, self._apply_scale,
                              initial=self._scale_value,
                              text="Calibrate scale (scope / bar)...").pack(fill="x", pady=(0, 4))
        entry_row("Minimum worm area (px)", self.min_area)
        entry_row("Maximum worm area (px)", self.max_area)
        ttk.Label(c, wraplength=300, justify="left", foreground="#5E6E76",
                  text=("Areas are in SOURCE pixels, so the right values depend "
                        "on magnification. The defaults of 40 and 2500 suit a "
                        "modest frame; on a 4K recording the floor is a fraction "
                        "of a percent of an animal, so every speck of debris "
                        "clears it and the tracker fills with noise. Measure one "
                        "animal instead of carrying numbers between rigs.")
                  ).pack(anchor="w", pady=(0, 2))
        ttk.Button(c, text="Measure a worm to set these...",
                   command=self.measure_worm).pack(fill="x", pady=(0, 4))
        entry_row("Max link (px/frame)", self.max_link_px)
        ttk.Label(c, wraplength=300, justify="left", foreground="#5E6E76",
                  text=("How far one animal may travel between frames, in source "
                        "pixels. Too large and the tracker can carry an identity "
                        "across the plate to a different animal. Measured motion on "
                        "a 7.5 fps basal slowing recording was under 4 px per frame "
                        "at the 95th percentile, against this default of 60 - so a "
                        "much smaller value is usually right.")).pack(anchor="w", pady=(0, 4))
        ttk.Button(c, text="Measure motion to set this...",
                   command=self.measure_motion).pack(fill="x", pady=(0, 4))
        entry_row("Before window (s)", self.before_s)
        entry_row("After window inside lawn (s)", self.after_s)
        entry_row("Outside buffer for before (px)", self.buffer_px)
        entry_row("Min usable fraction/window (0-1)", self.window_fraction)
        entry_row("Worm area inside lawn for entry (0-1)", self.entry_fraction)
        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(c, text="1. Draw assay ROIs", command=self.draw_rois).pack(fill="x", pady=2)
        ttk.Button(c, text="Undo last ROI", command=self.undo_last_roi).pack(fill="x", pady=2)
        ttk.Button(c, text="Clear ROIs", command=self.clear_rois).pack(fill="x", pady=2)
        self.roi_label = ttk.Label(c, text="ROIs: none drawn", foreground="#990000")
        self.roi_label.pack(fill="x", pady=2)
        self.go = ttk.Button(c, text="2. Analyze and review", command=self.start)
        self.go.pack(fill="x", pady=2)
        rf = ttk.Frame(c); rf.pack(fill="x", pady=(4, 2))
        ttk.Button(rf, text="Load ROIs", command=self.load_rois).pack(side="left", expand=True, fill="x", padx=2)
        ttk.Button(rf, text="Save ROIs", command=self.save_rois).pack(side="left", expand=True, fill="x", padx=2)

    def _build_center(self):
        ttk.Label(self.center, text="Population basal slowing",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        ttk.Label(self.center, wraplength=560, justify="left", foreground="#444444",
                  text=("Choose the image folder, draw the starting drop and OP50 lawns, then "
                        "Analyze and review. The primary bend measure is a wrMTrck-like body-axis "
                        "oscillation proxy. Every paired lawn entry requires review; entry defaults "
                        "to 50% of segmented worm area inside a lawn, before/after windows to 10 s "
                        "(70% usable). Uncertain evidence is never forced into a class.")).pack(
            anchor="w", padx=6, pady=4)
        self.center_fig = Figure(figsize=(5.6, 4.2), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111); self.center_ax.set_axis_off()
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        self.center_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.center_ax.text(0.5, 0.5, "Choose an image folder; the first frame appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        ttk.Label(self.center, textvariable=self.status, wraplength=560,
                  justify="left").pack(anchor="w", padx=6, pady=(0, 6))

    def _scale_value(self):
        try:
            return float(self.scale.get())
        except (TypeError, ValueError):
            return None

    def _current_frame(self):
        try:
            files = list_frames(self.folder.get()); img = read_gray(files[0])
            try:
                files.close()
            except Exception:
                pass
            return img
        except Exception:
            return None

    def _apply_scale(self, res):
        self.scale.set(f"{float(res['um_per_px']):.5f}")
        self.status.set(f"Scale set: {float(res['um_per_px']):.4f} um/pixel ({res.get('details','')})")

    def _show_first_frame(self):
        im = self._current_frame()
        if im is None:
            return
        self.center_ax.clear(); self.center_ax.imshow(im, cmap="gray")
        self.center_ax.set_axis_off(); self.center_ax.set_title("First frame", fontsize=9)
        self.center_canvas.draw()

    def choose_folder(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.folder.set(folder)
        self._show_first_frame()
        candidates = [
            Path(folder) / "basal_slowing_rois.json",
            Path(folder) / "basal_slowing_results" / "rois.json"]
        existing = next((p for p in candidates if p.exists()), None)
        if existing and messagebox.askyesno(
                "Saved ROIs", f"Reuse saved ROIs from\n{existing}?"):
            self._load_roi_path(existing)

    def draw_rois(self):
        try:
            files = list_frames(self.folder.get())
            image = read_gray(files[0])
        except Exception as exc:
            messagebox.showerror("Recording", str(exc))
            return
        start_record = draw_roi(
            image, "Draw the central starting-drop ROI",
            allow_line=False, default_shape="Oval", frame_count=len(files),
            frame_loader=lambda i: read_gray(files[int(i)]))
        if start_record is None:
            files.close()
            return
        start = start_record["polygon"]
        lawn_records = draw_multiple_rois(
            image, "Draw all OP50 lawns in this one window",
            allow_line=False, default_shape="Oval", label_prefix="Lawn",
            frame_count=len(files),frame_loader=lambda i: read_gray(files[int(i)]))
        files.close()
        if not lawn_records:
            messagebox.showerror("ROIs", "At least one lawn ROI is required.")
            return
        lawns = [record["polygon"] for record in lawn_records]
        self.start_roi, self.lawn_rois = start, lawns
        self.start_roi_record = start_record
        self.lawn_roi_records = lawn_records
        self._update_roi_label()
        self._save_roi_path(Path(self.folder.get()) /
                            "basal_slowing_rois.json", notify=False)

    def _update_roi_label(self):
        if self.start_roi is None:
            text, color = "ROIs: none drawn", "#990000"
        else:
            text = (f"ROIs ready: 1 starting drop and "
                    f"{len(self.lawn_rois)} OP50 lawns")
            color = "#166534" if self.lawn_rois else "#990000"
        self.roi_label.config(
            text=text, foreground=color)

    def undo_last_roi(self):
        if self.lawn_rois:
            self.lawn_rois.pop()
            self.lawn_roi_records.pop()
        elif self.start_roi is not None:
            self.start_roi = None
            self.start_roi_record = None
        else:
            messagebox.showinfo("ROIs", "There is no ROI to undo.")
            return
        self._update_roi_label()

    def clear_rois(self):
        self.start_roi = None
        self.lawn_rois = []
        self.start_roi_record = None
        self.lawn_roi_records = []
        self._update_roi_label()

    def _roi_payload(self):
        return {
            "start_roi": self.start_roi,
            "lawn_rois": self.lawn_rois,
            "shape_metadata": {
                "start": self.start_roi_record,
                "lawns": self.lawn_roi_records}}

    def _save_roi_path(self, path, notify=True):
        if self.start_roi is None or not self.lawn_rois:
            if notify:
                messagebox.showerror("ROIs", "There are no complete ROIs to save.")
            return False
        Path(path).write_text(
            json.dumps(self._roi_payload(), indent=2), encoding="utf-8")
        if notify:
            messagebox.showinfo("ROIs", f"ROIs saved to\n{path}")
        return True

    def save_rois(self):
        initial = (Path(self.folder.get()) / "basal_slowing_rois.json"
                   if self.folder.get() else Path("basal_slowing_rois.json"))
        path = filedialog.asksaveasfilename(
            title="Save reusable ROIs", initialdir=str(initial.parent),
            initialfile=initial.name, defaultextension=".json",
            filetypes=[("ROI JSON", "*.json")])
        if path:
            self._save_roi_path(path)

    def _load_roi_path(self, path):
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.start_roi = data["start_roi"]
            self.lawn_rois = data["lawn_rois"]
            shapes = data.get("shape_metadata", {})
            self.start_roi_record = shapes.get("start") or {
                "shape": "polygon", "polygon": self.start_roi,
                "geometry": {"vertices": self.start_roi}}
            records = shapes.get("lawns") or []
            self.lawn_roi_records = records if len(records) == len(
                self.lawn_rois) else [
                    {"shape": "polygon", "polygon": roi,
                     "geometry": {"vertices": roi}}
                    for roi in self.lawn_rois]
            self._update_roi_label()
            self.status.set(f"Loaded reusable ROIs from {path}")
        except Exception as exc:
            messagebox.showerror("Load ROIs", str(exc))

    def load_rois(self):
        path = filedialog.askopenfilename(
            title="Load saved basal-slowing ROIs",
            initialdir=self.folder.get() or None,
            filetypes=[("ROI JSON", "*.json")])
        if path:
            self._load_roi_path(path)

    def start(self):
        if self.start_roi is None or not self.lawn_rois:
            messagebox.showerror("ROIs", "Draw the assay ROIs first.")
            return
        try:
            kwargs = {
                "folder": self.folder.get(),
                "fps": float(self.fps.get()),
                "um_per_px": float(self.scale.get()),
                "start_roi": self.start_roi,
                "lawn_rois": self.lawn_rois,
                "roi_metadata": {
                    "start": self.start_roi_record,
                    "lawns": self.lawn_roi_records},
                "min_area": int(self.min_area.get()),
                "max_area": int(self.max_area.get()),
                "max_link_px": float(self.max_link_px.get()),
                "before_s": float(self.before_s.get()),
                "after_s": float(self.after_s.get()),
                "outside_buffer_px": float(self.buffer_px.get()),
                "min_window_fraction": float(self.window_fraction.get()),
                "minimum_worm_fraction_inside": float(
                    self.entry_fraction.get()),
            }
        except ValueError:
            messagebox.showerror(
                "Inputs", "FPS, scale, areas, windows, buffer, and fraction "
                          "must be numeric.")
            return
        self.go.state(["disabled"])
        self.status.set("Analyzing frames in the background...")
        threading.Thread(
            target=self._run, args=(kwargs,), daemon=True).start()

    def _run(self, kwargs):
        try:
            events, tracks, out = analyze(
                **kwargs, progress=lambda i, n: self.after(
                    0, self.status.set, f"Processing frame {i} of {n}..."))
            self.after(0, self.review_tracking, events, tracks, out)
        except Exception as exc:
            self.after(0, self.fail, str(exc))

    def measure_worm(self):
        """Click one animal; set the area gates from the detector's own mask.

        Clicking says only WHICH object is an animal - the number comes from
        the thresholded mask, never from a hand-drawn outline, because a traced
        outline is systematically more generous than the mask and it is the
        mask the gates are compared against.

        Shares app/worm_area_probe.py with the rest of WINK rather than growing
        a second copy of the arithmetic. Note that Measure motion depends on
        these gates, so set the areas first or the motion estimate is measured
        over whatever debris the old floor let through.
        """
        folder = self.folder.get().strip()
        if not folder:
            messagebox.showerror("Measure a worm", "Choose a folder first.",
                                 parent=self)
            return
        self.status.set("Sampling frames to measure an animal...")
        self.update_idletasks()
        try:
            files = list_frames(folder)
            idx = wap.sample_indices(len(files))
            samples = [read_gray(files[i]) for i in idx]
            background, chosen = wap.background_and_frame(samples)
            labels, stats = wap.detect_objects(chosen, background)
        except Exception as exc:
            messagebox.showerror("Measure a worm",
                                 f"Could not sample this recording.\n\n{exc}",
                                 parent=self)
            self.status.set("Worm measurement failed.")
            return

        self.status.set("Click on one animal in the frame.")
        points = collect_image_points(
            self, chosen, title="Measure a worm",
            instructions=("Click once on a single animal - the middle of its "
                          "body is best. WINK reads the detected object under "
                          "your click, not the click itself, so precision is "
                          "not required. Avoid two animals that are touching."),
            mode="points", min_points=1, max_points=1,
            process_log=ProcessLog("Measure a worm for the area gates"))
        if not points:
            self.status.set("Worm measurement cancelled.")
            return

        label = wap.object_at(labels, stats, float(points[0][0]),
                              float(points[0][1]))
        described = wap.describe(stats, label, scale=1.0)
        suggested = wap.suggest_gates(described)
        try:
            current = (int(self.min_area.get()), int(self.max_area.get()))
        except ValueError:
            current = (0, 0)
        why = wap.gates_look_wrong_for(described, *current)

        message = (
            f"Detected object under your click:\n\n"
            f"    area          {described['source_area_px']:,.0f} source px\n"
            f"    bounding span {described['span_source_px']:,.0f} px\n\n"
            f"It is larger than {described['percentile_of_objects']:.0f}% of the "
            f"{described['n_objects']} objects found in this frame.\n\n"
            f"Suggested gates ({suggested['min_factor']:g}x to "
            f"{suggested['max_factor']:g}x):\n"
            f"    Minimum worm area   {suggested['min_area']:,}\n"
            f"    Maximum worm area   {suggested['max_area']:,}\n\n"
            f"That would keep {suggested['kept_objects']} of "
            f"{suggested['n_objects']} objects in this frame.\n\n")
        if why:
            message += f"Your current gates {current[0]}/{current[1]}: {why}.\n\n"
        if described["percentile_of_objects"] < 60:
            message = ("NOTE: the object you clicked is smaller than most "
                       "objects in the frame, which usually means a noise blob "
                       "was clicked rather than an animal. Check the numbers "
                       "below before applying.\n\n") + message
        message += "Apply these values?"

        if not messagebox.askyesno("Measure a worm", message, parent=self):
            self.status.set("Measured animal not applied.")
            return
        self.min_area.set(str(suggested["min_area"]))
        self.max_area.set(str(suggested["max_area"]))
        self.log("Area gates measured",
                 f"animal {described['source_area_px']:,.0f} px -> gates "
                 f"{suggested['min_area']}/{suggested['max_area']}", "info")
        self.status.set(
            f"Area gates set from a measured animal: "
            f"{suggested['min_area']}-{suggested['max_area']} px.")

    def measure_motion(self):
        """Measure how far worm-sized objects actually move between frames.

        The link distance is in source pixels, so its correct value depends on
        magnification and frame rate together - a number carried over from
        another rig is usually wrong by a large factor, and an over-large gate
        lets one track jump to a different animal.
        """
        folder = self.folder.get().strip()
        if not folder:
            messagebox.showerror("Measure motion", "Choose a folder first.",
                                 parent=self)
            return
        self.status.set("Sampling frames to measure motion...")
        self.update_idletasks()
        try:
            files = list_frames(folder)
            if len(files) < 10:
                raise ValueError("Need at least ten frames to measure motion.")
            lo, hi = int(self.min_area.get()), int(self.max_area.get())
            idx = np.unique(np.linspace(0, len(files) - 1, 31).astype(int))
            background = np.median(
                np.stack([read_gray(files[i]) for i in idx]), axis=0).astype(np.uint8)
            sample = np.unique(np.linspace(0, len(files) - 1, 120).astype(int))
            previous, steps, per_frame = None, [], []
            for position, i in enumerate(sample):
                frame = read_gray(files[i])
                diff = cv2.GaussianBlur(cv2.absdiff(frame, background), (3, 3), 0)
                _, mask = cv2.threshold(
                    diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                count, _, stats, centroids = cv2.connectedComponentsWithStats(mask)
                points = np.array([centroids[k] for k in range(1, count)
                                   if lo <= stats[k, cv2.CC_STAT_AREA] <= hi], float)
                per_frame.append(len(points))
                if previous is not None and len(points) and len(previous[1]):
                    gap = max(1, i - previous[0])
                    for point in points:
                        steps.append(float(np.min(np.hypot(
                            previous[1][:, 0] - point[0],
                            previous[1][:, 1] - point[1]))) / gap)
                previous = (i, points)
        except Exception as exc:
            messagebox.showerror("Measure motion",
                                 f"Could not sample the recording.\n\n{exc}",
                                 parent=self)
            return
        if len(steps) < 20:
            messagebox.showinfo(
                "Measure motion",
                "Too few worm-sized objects were found to measure motion. "
                "Check the area gates first - they are in source pixels, so the "
                "right values depend on magnification.", parent=self)
            return
        steps = np.array(steps)
        p95 = float(np.percentile(steps, 95))
        suggested = max(8.0, round(p95 * 3))
        current = self.max_link_px.get()
        message = (
            f"Measured over {len(steps):,} object pairs "
            f"({np.mean(per_frame):.1f} objects per frame):\n\n"
            f"    median      {np.percentile(steps, 50):6.2f} px/frame\n"
            f"    p95         {p95:6.2f} px/frame\n"
            f"    p99         {np.percentile(steps, 99):6.2f} px/frame\n\n"
            f"Suggested max link: {suggested:,.0f} px/frame "
            f"(p95 x3, for headroom across missed frames).\n"
            f"Currently {current}.\n\n"
            "Apply the suggestion?")
        self.log("Motion measured",
                 f"median {np.percentile(steps, 50):.2f}, p95 {p95:.2f} px/frame "
                 f"over {len(steps):,} pairs; suggested max link {suggested:,.0f} "
                 f"(currently {current}).", status="done")
        if messagebox.askyesno("Measure motion", message, parent=self):
            self.max_link_px.set(f"{suggested:g}")
            self.status.set(f"Max link set from measured motion: {suggested:g} px/frame.")
        else:
            self.status.set("Measured motion recorded; max link unchanged.")

    def review_tracking(self, events, tracks, out):
        files = list_frames(self.folder.get())
        result = review_tracks(
            files, tracks, events, self.start_roi, self.lawn_rois,
            float(self.fps.get()), return_edits=True)
        decisions = result["decisions"]
        if result["tracks_edited"]:
            # Entry events are derived FROM the trajectories, so an edited
            # track whose events were not rebuilt would describe a trajectory
            # that no longer exists. Rebuild them from the edited tracks.
            tracks = result["tracks"]
            summary = ", ".join(
                f"{e['action']} {e.get('track_id', e.get('kept_track_id', ''))}"
                for e in result["edits"][:6])
            self.log("Tracks edited",
                     f"{len(result['edits'])} edit(s): {summary}"
                     + (" ..." if len(result["edits"]) > 6 else "")
                     + ". Re-deriving entry events from the edited tracks.",
                     status="edit")
            self.status.set("Re-deriving entry events from the edited tracks...")
            self.update_idletasks()
            try:
                events, tracks, out = recompute_events_from_tracks(
                    out, tracks=tracks, fps=float(self.fps.get()),
                    um_per_px=float(self.scale.get()),
                    reason=f"{len(result['edits'])} manual track edit(s) during review")
                (Path(out) / "manual_track_edits.json").write_text(
                    json.dumps(result["edits"], indent=2), encoding="utf-8")
                self.log("Events re-derived",
                         f"{len(events)} entry event(s) from the edited tracks; "
                         f"results in {Path(out).name}. The original run is "
                         "unchanged.", status="done")
            except Exception as exc:
                messagebox.showerror(
                    "Re-derive events",
                    "The tracks were edited but the entry events could not be "
                    f"rebuilt, so they still describe the ORIGINAL tracks:\n\n{exc}",
                    parent=self)
                self.log("Re-derive failed", str(exc), status="failed")
        review_table = save_track_review(decisions, out)
        status = dict(zip(
            review_table.track_id.astype(int),
            review_table.manual_track_status))
        events = events.copy()
        events["manual_track_status"] = (
            events.track_id.astype(int).map(status).fillna("unreviewed"))
        tracks = tracks.copy()
        tracks["manual_track_status"] = (
            tracks.track_id.astype(int).map(status).fillna("unreviewed"))
        tracks.to_csv(
            Path(out) / "detections_and_tracks_reviewed.csv", index=False)
        self.review(events, tracks, out)

    def review(self, events, tracks, out):
        if events.empty:
            self.go.state(["!disabled"])
            self.status.set(
                f"No lawn-entry candidates were found. Results: {out}")
            messagebox.showinfo("Basal slowing", self.status.get())
            return
        accepted = {
            int(row.event_id): bool(
                row.automatic_eligible and
                row.manual_track_status not in {
                    "rejected", "needs_correction"})
            for _, row in events.iterrows()}
        proc = ProcessLog("Paired lawn entries")
        proc.add("Review entries",
                 f"{len(events)} candidate entry event(s) across "
                 f"{events.track_id.nunique()} track(s). Click a marker to accept "
                 "or reject it.", "ready")
        workbench = ReviewWorkbench(self, "Paired lawn entries", proc,
                                    width=1380, height=880)
        fig, ax = workbench.fig, workbench.ax
        # The recording underneath, so a trajectory can be judged against what
        # the animal was actually crossing rather than against blank space.
        background = Path(out) / "background_reference.png"
        if background.exists():
            try:
                image = plt.imread(str(background))
                ax.imshow(image, cmap="gray", zorder=0)
            except Exception:
                pass
        for _, lawn in enumerate(self.lawn_rois, 1):
            p = np.asarray(lawn + [lawn[0]])
            ax.plot(p[:, 0], p[:, 1], color="#ef4444", lw=2.0, zorder=2)
        start = np.asarray(self.start_roi + [self.start_roi[0]])
        ax.plot(start[:, 0], start[:, 1], color="#22d3ee", lw=2.0, zorder=2)
        # One colour per animal: uniform grey at 60% opacity made several
        # trajectories impossible to tell apart, which is most of what this
        # view is for.
        for track_id, group in tracks.groupby("track_id"):
            ax.plot(group.x, group.y, color=track_colour(int(track_id)),
                    lw=1.6, alpha=.9, zorder=3)
        artists = {}
        for _, event in events.iterrows():
            event_id = int(event.event_id)
            color = "green" if accepted[event_id] else "orange"
            artist, = ax.plot(
                event.entry_x, event.entry_y, "o", color=color,
                markersize=13, markeredgecolor="white", markeredgewidth=1.6,
                picker=7, zorder=5)
            artists[artist] = event_id
        if not background.exists():
            ax.invert_yaxis()
        ax.set_aspect("equal")
        ax.set_title(
            "Paired lawn entries: click a marker to accept or reject it.\n"
            "Green = accepted, red = rejected. Each animal has its own colour.")

        def picked(event):
            event_id = artists[event.artist]
            accepted[event_id] = not accepted[event_id]
            event.artist.set_color(
                "#16a34a" if accepted[event_id] else "#dc2626")
            self.log("Entry " + ("accepted" if accepted[event_id] else "rejected"),
                     f"event {event_id}", status="review")
            workbench.draw_idle()

        fig.canvas.mpl_connect("pick_event", picked)
        workbench.add_control_label("Paired lawn entries")
        workbench.add_control_label(
            "Click a marker to accept or reject that entry. Trajectories are "
            "coloured per animal; the red outline is a lawn and the cyan one is "
            "the start region.")
        workbench.add_control_separator()
        workbench.add_control_button("Save and close", workbench.close)
        workbench.add_control_button("Hide controls (c)", workbench.toggle_controls)
        workbench.add_control_button("Hide hood (h)", workbench.toggle_hood)
        workbench.refresh()
        workbench.wait()
        reviewed = events.copy()
        reviewed["accepted"] = reviewed.event_id.map(accepted).fillna(False)
        reviewed["review_status"] = np.where(
            reviewed.accepted, "accepted", "rejected")
        reviewed.to_csv(
            Path(out) / "reviewed_paired_entry_events.csv", index=False)
        used = reviewed[reviewed.accepted]
        summary = {
            "accepted_event_count": int(len(used)),
            "unique_worm_count": int(used.track_id.nunique()),
            "mean_before_speed_um_s": (
                float(used.before_mean_speed_um_s.mean()) if len(used)
                else None),
            "mean_after_speed_um_s": (
                float(used.after_mean_speed_um_s.mean()) if len(used)
                else None),
            "mean_paired_speed_change_um_s": (
                float(used.delta_speed_um_s.mean()) if len(used) else None),
            "mean_before_frequency_hz": (
                float(used.before_body_axis_frequency_proxy_hz.mean())
                if len(used) else None),
            "mean_after_frequency_hz": (
                float(used.after_body_axis_frequency_proxy_hz.mean())
                if len(used) else None),
            "mean_paired_frequency_change_hz": (
                float(used.delta_frequency_hz.mean()) if len(used) else None),
            "mean_post_exit_speed_um_s": (
                float(used.post_exit_mean_speed_um_s.mean())
                if len(used) else None),
            "mean_post_exit_frequency_hz": (
                float(used.post_exit_body_axis_frequency_proxy_hz.mean())
                if len(used) else None),
            "maximum_encounter_number": (
                int(used.encounter_number.max()) if len(used) else 0),
            "inference_note":
                "Use paired events as observations; retain worm ID so repeated "
                "entries by one worm are not treated as independent worms. "
                "Encounter order and elapsed-time columns support longitudinal "
                "or mixed-effects analysis.",
        }
        (Path(out) / "reviewed_summary.json").write_text(
            json.dumps(summary, indent=2), encoding="utf-8")
        self.go.state(["!disabled"])
        self.status.set(
            f"Complete: {len(events)} candidate entries, "
            f"{len(used)} accepted from {used.track_id.nunique()} worms. "
            f"Results: {out}")
        messagebox.showinfo("Basal slowing", self.status.get())

    def fail(self, error):
        self.go.state(["!disabled"])
        self.status.set("Analysis stopped.")
        messagebox.showerror("Population basal slowing", error)


if __name__ == "__main__":
    App().mainloop()
