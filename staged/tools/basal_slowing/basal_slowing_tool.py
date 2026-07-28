"""Student-facing GUI for population basal-slowing analysis."""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
import numpy as np
import pandas as pd

from basal_slowing import analyze, list_frames, read_gray
from track_review import review_tracks, save_track_review
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))
from roi_editor import draw_roi, draw_rois as draw_multiple_rois
from process_ui import CockpitApp


class App(CockpitApp):
    def __init__(self):
        super().__init__("Population Basal Slowing", geometry="1180x760",
                         process_title="Basal slowing")
        self.folder = tk.StringVar()
        self.fps = tk.StringVar(value="7.5")
        self.scale = tk.StringVar(value="15.0")
        self.min_area = tk.StringVar(value="40")
        self.max_area = tk.StringVar(value="2500")
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

    def review_tracking(self, events, tracks, out):
        files = list_frames(self.folder.get())
        decisions = review_tracks(
            files, tracks, events, self.start_roi, self.lawn_rois,
            float(self.fps.get()))
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
        fig, ax = plt.subplots(figsize=(11, 8))
        for _, lawn in enumerate(self.lawn_rois, 1):
            p = np.asarray(lawn + [lawn[0]])
            ax.plot(p[:, 0], p[:, 1], color="#990000", lw=1.5)
        start = np.asarray(self.start_roi + [self.start_roi[0]])
        ax.plot(start[:, 0], start[:, 1], color="#00a6a6", lw=1.5)
        for _, group in tracks.groupby("track_id"):
            ax.plot(group.x, group.y, color="#777777", lw=.7, alpha=.6)
        artists = {}
        for _, event in events.iterrows():
            event_id = int(event.event_id)
            color = "green" if accepted[event_id] else "orange"
            artist, = ax.plot(
                event.entry_x, event.entry_y, "o", color=color,
                markersize=8, picker=7)
            artists[artist] = event_id
        ax.invert_yaxis()
        ax.set_aspect("equal")
        ax.set_title(
            "Paired lawn entries: click markers to accept/reject; "
            "close to save\nGreen = accepted, orange/red = rejected or flagged")

        def picked(event):
            event_id = artists[event.artist]
            accepted[event_id] = not accepted[event_id]
            event.artist.set_color(
                "green" if accepted[event_id] else "red")
            fig.canvas.draw_idle()

        fig.canvas.mpl_connect("pick_event", picked)
        plt.show()
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
