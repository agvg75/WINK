"""Interactive calibration for gcamp_recoverable's body/signal segmentation.

This is the UI the module docstring in gcamp_recoverable.py anticipated: a
person picks a representative frame, sees the adaptive per-acquisition
bg_sigma default and its confidence, and can nudge it with a MULTIPLIER
dial while watching the resulting body/signal mask update live. The dial
is deliberately not a raw sigma value - see gcamp_recoverable.py's
module-level note on why a raw slider does not transfer between a bright
and a dark acquisition.

This tool only produces a calibration record (chosen bg_sigma, confidence,
the frame it was checked on). It does not track, measure, or classify
anything itself - that happens downstream, using the sigma saved here.
"""
from __future__ import annotations

import json
import sys
import tkinter as tk
from datetime import datetime, timezone
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app"), str(ROOT / "tools" / "movie")]

from movie_reader import open_movie
from image_sequence import discover_images
from process_ui import CockpitApp
import gcamp_recoverable as gr

TOOL_NAME = "GCaMP body/signal segmentation calibration"
TOOL_VERSION = "0.1.0"


def gray(frame):
    values = np.asarray(frame)
    if values.ndim == 2:
        return np.asarray(values, dtype=np.float32)
    return np.add.reduce(
        values[..., :3], axis=2, dtype=np.float32) / np.float32(
            min(3, values.shape[2]))


class App(CockpitApp):
    def __init__(self):
        super().__init__(TOOL_NAME, geometry="1180x780",
                          process_title="GCaMP segmentation calibration")
        self.v = {
            "source": tk.StringVar(value=""),
            "frame": tk.StringVar(value="0"),
            "multiplier": tk.DoubleVar(value=1.0),
            "show_signal": tk.BooleanVar(value=True),
            "boost_contrast": tk.BooleanVar(value=False),
            "enable_coil": tk.BooleanVar(value=False),
        }
        self.status = tk.StringVar(
            value="Choose a recording, then Estimate default on a "
                  "representative frame where the animal is fully visible.")
        self.n_frames = 0
        self.current_gray = None
        self.estimate = None          # last estimate_body_bg_sigma() result
        self.estimate_frame_index = None
        self.straight_mask = None
        self.straight_frame_index = None
        self.straight_sigma = None
        self.coiled_mask = None
        self.coiled_frame_index = None
        self.coiled_sigma = None
        self.coil_validation = None
        self._preview_job = None
        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    # -- controls ------------------------------------------------------
    def _build_controls(self):
        c = self.controls

        src = ttk.Frame(c); src.pack(fill="x", pady=2)
        ttk.Label(src, text="Recording", width=16).pack(side="left")
        ttk.Entry(src, textvariable=self.v["source"]).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose file / folder...", command=self._choose).pack(fill="x", pady=(0, 6))

        nav = ttk.Frame(c); nav.pack(fill="x", pady=2)
        ttk.Label(nav, text="Frame", width=16).pack(side="left")
        frame_entry = ttk.Entry(nav, textvariable=self.v["frame"], width=8)
        frame_entry.pack(side="left")
        frame_entry.bind("<Return>", lambda _e: self._show_frame())
        ttk.Button(nav, text="<", width=3, command=lambda: self._step_frame(-1)).pack(side="left", padx=(4, 0))
        ttk.Button(nav, text=">", width=3, command=lambda: self._step_frame(1)).pack(side="left", padx=(2, 0))
        ttk.Button(c, text="Show frame", command=self._show_frame).pack(fill="x", pady=(2, 6))

        ttk.Checkbutton(c, text="Boost contrast for display only (never measured)",
                         variable=self.v["boost_contrast"],
                         command=self._redraw).pack(anchor="w", pady=(0, 6))

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(c, text="1. Estimate default (this frame)",
                   command=self.run_estimate).pack(fill="x", pady=2)
        self.confidence_label = ttk.Label(
            c, wraplength=205, justify="left", foreground="#555555",
            text="No estimate yet.")
        self.confidence_label.pack(fill="x", pady=(2, 8))

        dial = ttk.LabelFrame(c, text="2. Dial (multiplier on the adaptive default)")
        dial.pack(fill="x", pady=(0, 8))
        row = ttk.Frame(dial); row.pack(fill="x", pady=(4, 0))
        ttk.Label(row, text="x", width=3).pack(side="left")
        self.multiplier_value_label = ttk.Label(row, text="1.00x", width=6)
        self.multiplier_value_label.pack(side="right")
        ttk.Scale(dial, variable=self.v["multiplier"],
                  from_=gr.BG_SIGMA_MULTIPLIER_BOUNDS[0],
                  to=gr.BG_SIGMA_MULTIPLIER_BOUNDS[1],
                  orient="horizontal",
                  command=lambda _v: self._on_multiplier_move()).pack(fill="x", padx=4, pady=(2, 2))
        ttk.Button(dial, text="Reset to 1.0x (trust the estimate)",
                   command=self._reset_multiplier).pack(fill="x", padx=4, pady=(2, 4))
        self.sigma_value_label = ttk.Label(dial, text="Effective bg_sigma: -",
                                            foreground="#555555")
        self.sigma_value_label.pack(anchor="w", padx=4, pady=(0, 4))

        ttk.Checkbutton(c, text="Overlay elevated signal (orange)",
                         variable=self.v["show_signal"],
                         command=self._redraw).pack(anchor="w", pady=(0, 8))

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        self._build_coil_section(c)

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(c, text="4. Save calibration",
                   command=self.save_calibration).pack(fill="x", pady=2)

    def _build_coil_section(self, c):
        ttk.Checkbutton(
            c, text="Enable coil classification for this recording",
            variable=self.v["enable_coil"],
            command=self._toggle_coil_ui).pack(anchor="w", pady=(4, 2))
        ttk.Label(
            c, wraplength=205, justify="left", foreground="#555555",
            text="Coil classification stays off everywhere by default (it "
                 "has never been validated in general). Checking this only "
                 "licenses it for THIS recording, and only after you mark a "
                 "straight and a coiled frame and the check below passes."
        ).pack(fill="x", pady=(0, 4))

        self._coil_actions = ttk.Frame(c)
        ttk.Button(self._coil_actions, text="Mark this frame: straight / extended",
                   command=self.mark_straight).pack(fill="x", pady=2)
        self.straight_label = ttk.Label(
            self._coil_actions, wraplength=205, justify="left",
            text="Not marked yet.", foreground="#555555")
        self.straight_label.pack(fill="x", pady=(0, 4))

        ttk.Button(self._coil_actions, text="Mark this frame: coiled",
                   command=self.mark_coiled).pack(fill="x", pady=2)
        self.coiled_label = ttk.Label(
            self._coil_actions, wraplength=205, justify="left",
            text="Not marked yet.", foreground="#555555")
        self.coiled_label.pack(fill="x", pady=(0, 4))

        ttk.Button(self._coil_actions, text="Check straight/coiled pair",
                   command=self.run_coil_validation).pack(fill="x", pady=2)
        self.coil_result_label = ttk.Label(
            self._coil_actions, wraplength=205, justify="left",
            text="Not checked yet.", foreground="#555555")
        self.coil_result_label.pack(fill="x", pady=(0, 4))
        self._toggle_coil_ui()

    def _toggle_coil_ui(self):
        if self.v["enable_coil"].get():
            self._coil_actions.pack(fill="x", pady=(0, 4))
        else:
            self._coil_actions.pack_forget()

    def _build_center(self):
        ttk.Label(self.center, text="Body / signal segmentation preview",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        self.center_fig = Figure(figsize=(6.0, 5.0), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111)
        self.center_ax.set_axis_off()
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        self.center_canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.center_ax.text(0.5, 0.5, "Choose a recording; a frame appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        ttk.Label(self.center, textvariable=self.status, wraplength=560,
                  justify="left").pack(anchor="w", padx=6, pady=(0, 6))

    # -- source / frame loading ------------------------------------------------
    def _choose(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a movie, TIFF stack, or one frame of an image sequence",
            filetypes=[("Movies, stacks, and image frames",
                        "*.tif *.tiff *.png *.jpg *.jpeg *.bmp *.pgm "
                        "*.avi *.mp4 *.mov *.mkv *.webm"),
                       ("All files", "*.*")])
        if not path:
            path = filedialog.askdirectory(
                parent=self, title="Or choose a folder of numbered frames")
        if not path:
            return
        p = Path(path)
        if not p.is_dir():
            try:
                movie = open_movie(str(p))
                count = int(movie.n_frames)
                movie.close()
            except Exception:
                count = None
            if count is None or count < 2:
                try:
                    sequence = discover_images(p.parent)
                except Exception:
                    sequence = []
                if len(sequence) >= 2 and messagebox.askyesno(
                        "Load image sequence?",
                        f"'{p.name}' is a single frame, but its folder holds "
                        f"{len(sequence)} numbered frames.\n\nLoad the whole "
                        "folder as one recording?", parent=self):
                    p = p.parent
        self.v["source"].set(str(p))
        self.v["frame"].set("0")
        self.estimate = None
        self.estimate_frame_index = None
        self._reset_coil_marks()
        self._show_frame()

    def _reset_coil_marks(self):
        self.straight_mask = None; self.straight_frame_index = None; self.straight_sigma = None
        self.coiled_mask = None; self.coiled_frame_index = None; self.coiled_sigma = None
        self.coil_validation = None
        if hasattr(self, "straight_label"):
            self.straight_label.configure(text="Not marked yet.", foreground="#555555")
            self.coiled_label.configure(text="Not marked yet.", foreground="#555555")
            self.coil_result_label.configure(text="Not checked yet.", foreground="#555555")

    def _step_frame(self, delta):
        try:
            idx = int(self.v["frame"].get()) + delta
        except (TypeError, ValueError):
            idx = 0
        self.v["frame"].set(str(max(0, idx)))
        self._show_frame()

    def _show_frame(self):
        source = self.v["source"].get()
        if not source:
            self.status.set("Choose a recording first.")
            return
        try:
            movie = open_movie(source)
            self.n_frames = int(movie.n_frames)
            idx = max(0, min(int(self.v["frame"].get() or 0), self.n_frames - 1))
            self.v["frame"].set(str(idx))
            self.current_gray = gray(movie.get_frame(idx))
            movie.close()
        except Exception as exc:
            self.status.set(f"Could not load frame: {exc}")
            return
        self.estimate = None
        self.estimate_frame_index = None
        self.confidence_label.configure(
            text="No estimate yet for this frame.", foreground="#555555")
        self._redraw()
        self.status.set(f"Frame {idx} of {self.n_frames}. "
                         "Estimate the default, or adjust the dial by eye.")

    # -- estimate / dial --------------------------------------------------
    def run_estimate(self):
        if self.current_gray is None:
            self.status.set("Show a frame first.")
            return
        self.estimate = gr.estimate_body_bg_sigma(self.current_gray, return_table=True)
        self.estimate_frame_index = int(self.v["frame"].get())
        if self.estimate["abstain"]:
            self.confidence_label.configure(
                text="ABSTAINED: " + self.estimate["abstain_reason"],
                foreground="#a00000")
            self.status.set(
                "The adaptive estimate abstained on this frame - try a "
                "different, more clearly-visible frame, or set the dial "
                "manually and treat the result as unvalidated.")
        else:
            self.confidence_label.configure(
                text=(f"Default bg_sigma = {self.estimate['bg_sigma_default']} "
                      f"(confidence {self.estimate['confidence']:.2f}). "
                      "Dial is a multiplier on this."),
                foreground="#1a6e1a")
            self.status.set("Estimate found. Use the dial to nudge it; "
                             "1.0x trusts the estimate as-is.")
        self._reset_multiplier()

    def _reset_multiplier(self):
        self.v["multiplier"].set(1.0)
        self._on_multiplier_move()

    def _on_multiplier_move(self):
        self.multiplier_value_label.configure(text=f"{self.v['multiplier'].get():.2f}x")
        self._schedule_preview_refresh()

    def _effective_sigma(self):
        base = None
        if self.estimate is not None and not self.estimate["abstain"]:
            base = self.estimate["bg_sigma_default"]
        elif self.estimate is not None and self.estimate["abstain"]:
            base = gr.BODY_BG_SIGMA  # unvalidated fallback, clearly labeled in the UI
        else:
            base = gr.BODY_BG_SIGMA
        return gr.bg_sigma_for_multiplier(base, self.v["multiplier"].get())

    # -- coil branch: mark a straight/coiled pair for THIS recording ---------
    def mark_straight(self):
        self._mark_coil_frame("straight")

    def mark_coiled(self):
        self._mark_coil_frame("coiled")

    def _mark_coil_frame(self, which):
        if self.current_gray is None:
            self.status.set("Show a frame first.")
            return
        sigma = self._effective_sigma()
        body, _signal = gr.segment_body_and_signal(self.current_gray, bg_sigma=sigma)
        if body is None:
            self.status.set(
                f"No plausible body mask at bg_sigma={sigma:.1f} on this frame - "
                "adjust the dial or pick a different frame before marking it.")
            return
        idx = int(self.v["frame"].get())
        if which == "straight":
            self.straight_mask, self.straight_frame_index, self.straight_sigma = body, idx, sigma
            self.straight_label.configure(
                text=f"Straight: frame {idx}, bg_sigma={sigma:.1f}, "
                     f"{int(body.sum()):,} px", foreground="#1a6e1a")
        else:
            self.coiled_mask, self.coiled_frame_index, self.coiled_sigma = body, idx, sigma
            self.coiled_label.configure(
                text=f"Coiled: frame {idx}, bg_sigma={sigma:.1f}, "
                     f"{int(body.sum()):,} px", foreground="#1a6e1a")
        self.coil_validation = None
        self.coil_result_label.configure(text="Not checked yet.", foreground="#555555")
        self.status.set(f"Marked frame {idx} as {which}. "
                         "Mark the other frame, then check the pair.")

    def run_coil_validation(self):
        if self.straight_mask is None or self.coiled_mask is None:
            self.status.set("Mark both a straight and a coiled frame first.")
            return
        if (self.straight_frame_index == self.coiled_frame_index):
            self.status.set("Straight and coiled must be different frames.")
            return
        self.coil_validation = gr.validate_coil_branch(
            self.straight_mask, self.coiled_mask)
        validated = self.coil_validation["validated"]
        reason = self.coil_validation["reason"]
        if abs((self.straight_sigma or 0) - (self.coiled_sigma or 0)) > 0.15 * max(
                self.straight_sigma or 1, self.coiled_sigma or 1):
            reason += (" (note: the straight and coiled frames were marked "
                       f"at different effective sigmas - {self.straight_sigma:.1f} vs "
                       f"{self.coiled_sigma:.1f} - set the dial the same way for both "
                       "before trusting this check.)")
        self.coil_result_label.configure(
            text=("VALIDATED for this recording: " if validated
                  else "NOT validated: ") + reason,
            foreground="#1a6e1a" if validated else "#a00000")
        self.status.set(
            "Coil classification is licensed for this recording (save the "
            "calibration to record it)." if validated else
            "Coil classification did NOT validate for this recording - it "
            "will not be enabled even though the checkbox is on.")

    # -- preview ------------------------------------------------------
    def _schedule_preview_refresh(self):
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(150, self._redraw)

    def _redraw(self):
        self._preview_job = None
        if self.current_gray is None:
            return
        sigma = self._effective_sigma()
        self.sigma_value_label.configure(
            text=f"Effective bg_sigma: {sigma:.1f}"
                 + ("  (unvalidated - no estimate accepted for this frame)"
                    if self.estimate is None or self.estimate["abstain"] else ""))
        body, signal = gr.segment_body_and_signal(self.current_gray, bg_sigma=sigma)
        display = (gr.auto_contrast_preview(self.current_gray)
                   if self.v["boost_contrast"].get() else self.current_gray)
        self.center_ax.clear()
        self.center_ax.imshow(display, cmap="gray")
        self.center_ax.set_axis_off()
        if body is None:
            self.center_ax.set_title(
                f"No plausible body at bg_sigma={sigma:.1f}", fontsize=9, color="#a00000")
        else:
            self.center_ax.imshow(np.ma.masked_where(~body, body),
                                   cmap="Greens", alpha=0.35)
            if signal is not None and self.v["show_signal"].get():
                self.center_ax.imshow(np.ma.masked_where(~signal, signal),
                                       cmap="Oranges", alpha=0.55)
            metrics = gr.mask_plausibility_score(body)
            self.center_ax.set_title(
                f"bg_sigma={sigma:.1f}  area={metrics['area_frac']:.1%}  "
                f"aspect={metrics['aspect']:.1f}"
                if metrics["aspect"] is not None else
                f"bg_sigma={sigma:.1f}  area={metrics['area_frac']:.1%}",
                fontsize=9)
        self.center_canvas.draw()

    # -- save -----------------------------------------------------------
    def save_calibration(self):
        source = self.v["source"].get()
        if not source or self.current_gray is None:
            self.status.set("Choose a recording and show a frame first.")
            return
        sigma = self._effective_sigma()
        body, _signal = gr.segment_body_and_signal(self.current_gray, bg_sigma=sigma)
        metrics = gr.mask_plausibility_score(body) if body is not None else {
            "area_frac": None, "aspect": None, "border_touch_frac": None, "score": None}
        payload = {
            "tool": TOOL_NAME, "tool_version": TOOL_VERSION,
            "generated_utc": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "frame_index_used": int(self.v["frame"].get()),
            "estimate": self.estimate,
            "estimate_frame_index": self.estimate_frame_index,
            "multiplier": float(self.v["multiplier"].get()),
            "bg_sigma_effective": sigma,
            "mask_at_effective_sigma": metrics,
            "manually_overridden": (
                self.estimate is None or self.estimate.get("abstain")
                or abs(self.v["multiplier"].get() - 1.0) > 1e-6),
            "coil": {
                "enabled_by_user": bool(self.v["enable_coil"].get()),
                "straight_frame_index": self.straight_frame_index,
                "coiled_frame_index": self.coiled_frame_index,
                "straight_bg_sigma": self.straight_sigma,
                "coiled_bg_sigma": self.coiled_sigma,
                "validation": self.coil_validation,
                "licensed_for_this_recording": bool(
                    self.v["enable_coil"].get() and self.coil_validation
                    and self.coil_validation.get("validated")),
            },
        }
        src = Path(source)
        out_dir = src.parent / (src.stem + "_gcamp_body_calibration")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / "body_bg_sigma_calibration.json"
        out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        self.log("Segmentation calibration saved",
                  f"bg_sigma={sigma:.1f} (multiplier {self.v['multiplier'].get():.2f}x)",
                  status="edit")
        self.status.set(f"Calibration saved: {out_path}")
        coil_line = ""
        if self.v["enable_coil"].get():
            coil_line = "\n\nCoil classification: " + (
                "LICENSED for this recording."
                if payload["coil"]["licensed_for_this_recording"] else
                "NOT licensed (mark both frames and pass the check to enable it).")
        messagebox.showinfo(
            "Calibration saved",
            f"Saved:\n{out_path}\n\nEffective bg_sigma: {sigma:.1f}\n"
            f"(multiplier {self.v['multiplier'].get():.2f}x on "
            + (f"adaptive default {self.estimate['bg_sigma_default']}"
               if self.estimate and not self.estimate["abstain"]
               else "the unvalidated fixed fallback, since no estimate was accepted")
            + ")" + coil_line, parent=self)


if __name__ == "__main__":
    App().mainloop()
