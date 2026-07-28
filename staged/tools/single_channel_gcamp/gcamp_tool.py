"""Student-facing T13 feasibility-first single-channel GCaMP workflow."""
from __future__ import annotations

import json
import os
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
from movie_reader import open_movie
from run_feedback import prompt_post_run_feedback
from gcamp import extract_trace, feasibility_pass
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
        self.status = tk.StringVar(
            value="Choose a blue-only movie, stack, or frame folder.")
        self.frames = None
        self.seed = None
        self.feasibility = None
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

        srow = ttk.Frame(c); srow.pack(fill="x", pady=2)
        ttk.Label(srow, text="Recording", width=24).pack(side="left")
        ttk.Entry(srow, textvariable=self.v["source"]).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose file / folder...", command=self._choose_and_show).pack(fill="x", pady=(0, 4))
        for label, key in [
                ("Declared FPS", "fps"), ("Scale (um/pixel)", "scale"),
                ("Exposure (ms)", "exposure"), ("Bit depth", "bit_depth"),
                ("Channel identity", "channel"), ("Feasibility sample frames", "sample_frames"),
                ("Neuron radius (pixels)", "neuron_radius"),
                ("Local search radius (pixels)", "search_radius")]:
            field(label, key)
        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=6)
        ttk.Button(c, text="1. Run feasibility pass", command=self.run_feasibility).pack(fill="x", pady=2)
        ttk.Button(c, text="2. Extract, relink flagged frames, and review",
                   command=self.run_extractor).pack(fill="x", pady=2)

    def _choose_and_show(self):
        self.choose()
        if self.v["source"].get():
            self._show_first_frame()

    def _build_center(self):
        ttk.Label(self.center, text="Single-channel GCaMP feasibility and extractor",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        self.center_fig = Figure(figsize=(5.6, 4.0), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111); self.center_ax.set_axis_off()
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        self.center_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.center_ax.text(0.5, 0.5, "Choose a source; the first frame appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        ttk.Label(self.center, textvariable=self.status, wraplength=560,
                  justify="left").pack(anchor="w", padx=6, pady=(0, 2))
        ttk.Label(self.center, text="The tracker searches only near the predicted neuron. It "
                                    "does not jump to the brightest object elsewhere in the worm.",
                  foreground="#8a3b00", wraplength=560).pack(anchor="w", padx=6, pady=(0, 6))

    def _show_first_frame(self):
        try:
            m = open_movie(self.v["source"].get()); im = gray(m.get_frame(0)); m.close()
        except Exception as exc:
            self.status.set(f"Could not load frame: {exc}"); return
        self.center_ax.clear(); self.center_ax.imshow(im, cmap="gray")
        self.center_ax.set_axis_off(); self.center_ax.set_title("First frame", fontsize=9)
        self.center_canvas.draw()

    def choose(self):
        path = filedialog.askopenfilename(
            filetypes=[("Movies and stacks",
                        "*.tif *.tiff *.avi *.mp4 *.mov *.mkv *.webm"),
                       ("All files", "*.*")])
        if not path:
            path = filedialog.askdirectory(title="Choose a frame folder")
        if path:
            self.v["source"].set(path)
            self.frames = None
            self.feasibility = None

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
        self.frames=np.empty((count,y1-y0,x1-x0),dtype=np.float32)
        def cropped_gray(frame):return gray(frame)[y0:y1,x0:x1]
        if getattr(movie, "source_kind", "") == "image_sequence":
            workers = min(6, max(2, (os.cpu_count() or 2) // 2))
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for index, frame in enumerate(pool.map(
                        lambda i: cropped_gray(movie.get_frame(i)), range(count))):
                    self.frames[index] = frame
        else:
            for index, frame in enumerate(movie.frames()):
                self.frames[index] = cropped_gray(frame)
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
        """Read only the transparent feasibility subsample, never the full movie."""
        movie = open_movie(self.v["source"].get())
        count = int(movie.n_frames)
        if count < 2:
            movie.close()
            raise ValueError("A multi-frame recording is required.")
        sample_count = max(
            2, min(int(self.v["sample_frames"].get()), count))
        indices = np.unique(np.linspace(
            0, count - 1, sample_count).round().astype(int))
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


if __name__ == "__main__":
    App().mainloop()
