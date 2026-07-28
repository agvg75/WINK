"""Student-facing T12 pharynx template placement, review, and export."""
from __future__ import annotations

from datetime import datetime
import json
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
from capability_gate import (
    MetricRequirement, RecordingProxies, evaluate_metric)
from failure_library import FailureLibrary
from movie_reader import open_movie
from pharynx import analyze_pharynx, centerline_from_landmarks, template_mask,compartment_masks
from run_feedback import RunFeedbackStore, prompt_post_run_feedback
from process_ui import CockpitApp

TOOL_NAME = "Pharynx deformable-template morphometry"
TOOL_VERSION = "0.1.0"


def gray(frame):
    array = np.asarray(frame)
    return array.astype(float) if array.ndim == 2 else np.mean(array, axis=2)


class App(CockpitApp):
    def __init__(self):
        super().__init__(TOOL_NAME, geometry="1160x760", process_title="Pharynx morphometry")
        self.source = tk.StringVar()
        self.frame_index = tk.StringVar(value="0")
        self.calibration_um = tk.StringVar(value="100")
        self.bit_depth = tk.StringVar(value="16")
        self.channel = tk.StringVar(value="pharyngeal fluorescence")
        self.status = tk.StringVar(
            value="Choose an image, TIFF stack, movie, or frame folder.")
        self.image = None
        self.um_per_px = None
        self.anterior = None
        self.posterior = None
        self.bends = []
        self.width_px = None
        self.grinder_mask = None
        self.output_dir = None
        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    def _build_controls(self):
        c = self.controls

        def field(label, var):
            row = ttk.Frame(c); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=22, wraplength=160, justify="left").pack(side="left")
            ttk.Entry(row, textvariable=var).pack(side="right", fill="x", expand=True)

        srow = ttk.Frame(c); srow.pack(fill="x", pady=2)
        ttk.Label(srow, text="Source", width=22).pack(side="left")
        ttk.Entry(srow, textvariable=self.source).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose file / folder...", command=self._choose_and_show).pack(fill="x", pady=(0, 4))
        field("Frame index", self.frame_index)
        field("Calibration distance (um)", self.calibration_um)
        field("Bit depth", self.bit_depth)
        field("Channel identity", self.channel)
        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        for label, command in [
                ("1. Calibrate scale", self.calibrate),
                ("2. Place anchors and optional bends", self.place_template),
                ("3. Set width", self.set_width),
                ("4. Mark terminal-bulb grinder (optional)", self.mark_grinder),
                ("5. Preview and review template", self.preview),
                ("6. Analyze and export", self.run)]:
            ttk.Button(c, text=label, command=command).pack(fill="x", pady=2)

    def _choose_and_show(self):
        self.choose()
        if self.source.get():
            self._show_first_frame()

    def _build_center(self):
        ttk.Label(self.center, text="Pharynx deformable-template morphometry",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        self.center_fig = Figure(figsize=(5.6, 4.0), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111); self.center_ax.set_axis_off()
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        self.center_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.center_ax.text(0.5, 0.5, "Choose a source; the frame appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        ttk.Label(self.center, textvariable=self.status, wraplength=560,
                  justify="left").pack(anchor="w", padx=6, pady=(0, 2))
        ttk.Label(self.center, text="No composite damage score is emitted without calibrated "
                                    "undamaged/damaged reference ranges.",
                  foreground="#8a3b00", wraplength=560).pack(anchor="w", padx=6, pady=(0, 6))

    def _show_first_frame(self):
        try:
            im = self.load()
        except Exception as exc:
            self.status.set(f"Could not load frame: {exc}"); return
        self.center_ax.clear(); self.center_ax.imshow(im, cmap="gray")
        self.center_ax.set_axis_off(); self.center_ax.set_title(f"Frame {self.frame_index.get()}", fontsize=9)
        self.center_canvas.draw()

    def choose(self):
        path = filedialog.askopenfilename(
            filetypes=[("Images and movies",
                        "*.tif *.tiff *.png *.jpg *.jpeg *.avi *.mp4 *.mov"),
                       ("All files", "*.*")])
        if not path:
            path = filedialog.askdirectory(title="Choose a frame folder")
        if path:
            self.source.set(path)
            self.image = None

    def load(self):
        if self.image is None:
            movie = open_movie(self.source.get())
            self.image = gray(movie.get_frame(int(self.frame_index.get())))
            movie.close()
        return self.image

    def calibrate(self):
        try:
            image = self.load()
            fig, axis = plt.subplots()
            axis.imshow(image, cmap="gray")
            axis.set_title(
                "Click both ends of the declared calibration distance")
            points = plt.ginput(2, timeout=0)
            plt.close(fig)
            if len(points) != 2:
                return
            pixels = float(np.linalg.norm(np.subtract(points[1], points[0])))
            if pixels <= 0:
                raise ValueError("Calibration clicks must be distinct.")
            self.um_per_px = float(self.calibration_um.get()) / pixels
            self.status.set(f"Scale calibrated: {self.um_per_px:.4f} µm/pixel")
        except Exception as exc:
            messagebox.showerror("Calibration", str(exc), parent=self)

    def place_template(self):
        try:
            image = self.load()
            fig, axis = plt.subplots()
            axis.imshow(image, cmap="gray")
            axis.set_title(
                "Click mouth, optional 1–4 bend landmarks, then terminal-bulb "
                "posterior end; press Enter")
            points = plt.ginput(-1, timeout=0)
            plt.close(fig)
            if len(points) < 2 or len(points) > 6:
                raise ValueError(
                    "Place 2–6 points: anterior, up to four bends, posterior.")
            self.anterior = points[0]
            self.posterior = points[-1]
            self.bends = points[1:-1]
            self.status.set(
                f"Template anchors saved with {len(self.bends)} bend landmark(s).")
        except Exception as exc:
            messagebox.showerror("Template anchors", str(exc), parent=self)

    def set_width(self):
        try:
            image = self.load()
            fig, axis = plt.subplots()
            axis.imshow(image, cmap="gray")
            axis.set_title("Click across the full pharynx width")
            points = plt.ginput(2, timeout=0)
            plt.close(fig)
            if len(points) != 2:
                return
            self.width_px = float(np.linalg.norm(
                np.subtract(points[1], points[0])))
            self.status.set(f"Template width: {self.width_px:.1f} pixels")
        except Exception as exc:
            messagebox.showerror("Template width", str(exc), parent=self)

    def mark_grinder(self):
        try:
            image = self.load()
            fig, axis = plt.subplots()
            axis.imshow(image, cmap="gray")
            axis.set_title(
                "Click around the terminal-bulb grinder; press Enter")
            points = plt.ginput(-1, timeout=0)
            plt.close(fig)
            if len(points) < 3:
                self.grinder_mask = None
                self.status.set("No grinder ROI saved.")
                return
            from matplotlib.path import Path as MplPath
            yy, xx = np.indices(image.shape)
            self.grinder_mask = MplPath(points).contains_points(
                np.c_[xx.ravel(), yy.ravel()]).reshape(image.shape)
            self.status.set("Grinder ROI saved.")
        except Exception as exc:
            messagebox.showerror("Grinder ROI", str(exc), parent=self)

    def _require_template(self):
        if self.um_per_px is None:
            raise ValueError("Calibrate scale first.")
        if self.anterior is None or self.posterior is None:
            raise ValueError("Place anterior and posterior anchors first.")
        if self.width_px is None or self.width_px <= 0:
            raise ValueError("Set the width scale first.")

    def preview(self):
        try:
            self._require_template()
            image = self.load()
            line = centerline_from_landmarks(
                self.anterior, self.posterior, self.bends)
            masks=compartment_masks(image.shape,line,self.width_px)
            fig, axis = plt.subplots()
            axis.imshow(image, cmap="gray")
            colors={"procorpus":"cyan","metacorpus":"lime","isthmus":"orange","terminal_bulb":"magenta"}
            for name,mask in masks.items():
                axis.contour(mask,levels=[.5],colors=[colors[name]])
                yy,xx=np.where(mask);axis.text(float(np.mean(xx)),float(np.mean(yy)),name.replace("_"," "),color=colors[name],fontsize=8,ha="center")
            axis.plot(line[:, 0], line[:, 1], color="cyan", linewidth=1)
            axis.scatter(
                [self.anterior[0], self.posterior[0]],
                [self.anterior[1], self.posterior[1]], c=["yellow", "red"])
            if self.grinder_mask is not None:
                axis.contour(
                    self.grinder_mask, levels=[0.5], colors=["magenta"])
            axis.set_title(
                "Review four connected territories: cyan procorpus, green metacorpus, orange isthmus, magenta terminal bulb")
            plt.show()
            accepted = messagebox.askyesno(
                "Accept template?",
                "Does the template follow the pharynx and contain the intended "
                "compartments? Choose No to reposition it.",
                parent=self)
            self.status.set(
                "Template accepted for analysis." if accepted else
                "Template not accepted; reposition anchors or width.")
            return accepted
        except Exception as exc:
            messagebox.showerror("Template preview", str(exc), parent=self)
            return False

    def run(self):
        try:
            self._require_template()
            if not self.preview():
                return
            image = self.load()
            proxies = RecordingProxies(
                worm_length_px=float(np.linalg.norm(np.subtract(
                    self.posterior, self.anterior))),
                worm_width_px=self.width_px, fps=None,
                contrast_ratio=float(
                    np.percentile(image, 90) /
                    max(np.percentile(image, 10), 1e-9)),
                saturation_fraction=float(np.mean(image >= np.max(image))),
                bit_depth=int(self.bit_depth.get()),
                focus_score=float(np.var(np.gradient(image)[0])),
                occluded_fraction=0, compression_artifact_score=None)
            gate = evaluate_metric(
                proxies, MetricRequirement(
                    "pharynx_compartment_morphometry",
                    min_length_px=100, min_width_px=8,
                    min_contrast_ratio=1.15, min_bit_depth=8))
            if gate.status == "red":
                messagebox.showerror(
                    "Capability Gate",
                    "Do not attempt this image:\n" + "\n".join(gate.unmet),
                    parent=self)
                return
            result = analyze_pharynx(
                image, anterior_xy=self.anterior,
                posterior_xy=self.posterior, width_px=self.width_px,
                um_per_px=self.um_per_px, bend_landmarks=self.bends,
                grinder_roi_mask=self.grinder_mask)
            source = Path(self.source.get())
            output = source.parent / (
                source.stem + "_pharynx_morphometry")
            output.mkdir(parents=True, exist_ok=True)
            acquisition = AcquisitionMetadata(
                None, "not_applicable", self.um_per_px,
                "two_point_calibration", None, "not_applicable",
                bit_depth=int(self.bit_depth.get()), compression="unknown",
                channel_identity=self.channel.get(),
                anatomical_orientation="declared_landmarks")
            payload = {
                **acquisition.stamped(TOOL_NAME, TOOL_VERSION),
                "capability_gate": gate.as_dict(), **result}
            result_path = output / "pharynx_morphometry.json"
            result_path.write_text(
                json.dumps(payload, indent=2), encoding="utf-8")
            self.output_dir = output
            self.status.set(f"Reviewed result saved: {result_path}")
            messagebox.showinfo(
                "Pharynx analysis complete",
                f"Reviewed compartment metrics saved to:\n{result_path}\n\n"
                "No uncalibrated composite damage score was emitted.",
                parent=self)
            prompt_post_run_feedback(
                tool_name=TOOL_NAME, tool_version=TOOL_VERSION,
                run_id=output.name, acquisition=acquisition,
                parameters={
                    "frame_index": int(self.frame_index.get()),
                    "width_px": self.width_px,
                    "bend_landmark_count": len(self.bends)},
                parent=self, evidence_paths=[result_path],
                roi_coordinates={
                    "anterior": self.anterior, "posterior": self.posterior,
                    "bends": self.bends})
        except Exception as exc:
            messagebox.showerror("Pharynx analysis", str(exc), parent=self)


if __name__ == "__main__":
    App().mainloop()
