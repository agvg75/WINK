"""Interactive tool wrapper for myocyte_morphometry.py.

Mirrors Myocyte_Morphometry.ijm's per-myocyte workflow: draw the cell
boundary, accept (or redraw) the proposed across-band sampling line,
review the automatic sarcomere detection (accept / edit ticks / manual /
skip), then save one CSV row. Everything happens on the cockpit's own
embedded canvas via direct click handling - no separate popup windows for
drawing or clicking, matching the rest of this cockpit's tools and this
lab's own stated preference for fewer popup windows.

Every EDITED, MANUAL, or MANUAL_RECOUNT sarcomere count is written to the
correction log (app/morphometry_corrections.py) alongside the CSV row -
see that module's docstring for what this can and cannot be used for.
"""
from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

import numpy as np
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE), str(ROOT / "app"), str(ROOT / "tools" / "movie")]

from movie_reader import open_movie
from process_ui import CockpitApp
import myocyte_morphometry as mm
import morphometry_corrections as corr

TOOL_NAME = "Myocyte morphometry"
TOOL_VERSION = "0.1.0"

CSV_COLUMNS = [
    "myocyte_id", "worm_id", "genotype", "day", "region", "myocyte_number",
    "um_px", "area_um2", "perimeter_um", "feret_um", "minferet_um",
    "major_um", "minor_um", "aspect_ratio", "circularity", "solidity",
    "anisotropy", "sarc_number", "sarc_length_um", "sarc_sd_um", "sarc_cv",
    "sarc_mode", "sarc_quality", "calib_flag", "sarc_density_per_um2",
    "serial_density_per_um", "filament_length_um", "sarc_parallel_proxy",
    "sarc_series_proxy", "contractile_content_proxy", "feret_angle_deg",
    "roi_name", "blind", "timestamp", "image_title", "linked_myocyte_id",
    "wave_n_fibers", "wave_n_affected", "wave_n_lowconf",
    "wave_width_fraction", "wave_length_frac_mean", "wave_length_frac_max",
    "wave_n_seeded", "wave_n_manual", "wave_n_relabelled", "wave_link_um",
]

REGIONS = ["anterior", "midbody", "posterior", "other"]
MYO_NUMBER_CHOICES = ["unknown"] + [str(i) for i in range(1, 25)] + ["other"]
SCHEMATIC_FILENAMES = ("myocyte schematic.jpg", "myocyte schematic.jpeg",
                       "myocyte schematic.png", "myocyte schematic.tif")
POINT_PICK_RADIUS_PX = 10  # screen-independent-ish; compares in data coords


def gray(frame):
    values = np.asarray(frame)
    if values.ndim == 2:
        return np.asarray(values, dtype=np.float64)
    return np.add.reduce(
        values[..., :3], axis=2, dtype=np.float64) / np.float64(
            min(3, values.shape[2]))


class App(CockpitApp):
    def __init__(self):
        super().__init__(TOOL_NAME, geometry="1240x820",
                          process_title="Myocyte morphometry")
        self.v = {
            "source": tk.StringVar(value=""),
            "worm_id": tk.StringVar(value=""),
            "genotype": tk.StringVar(value="unknown"),
            "blind": tk.BooleanVar(value=True),
            "day": tk.StringVar(value=""),
            "region": tk.StringVar(value="midbody"),
            "myo_number": tk.StringVar(value="unknown"),
            "student_id": tk.StringVar(value=""),
        }
        self.status = tk.StringVar(
            value="Choose a source image, set session info, then draw a boundary.")
        self.last_myo_number = None   # for auto-suggesting the next number
        self.image = None
        self.scale = None            # um/px
        # Display-only brightness/contrast (min/max display range, same idea
        # as ImageJ's own Brightness/Contrast dialog). This NEVER touches
        # self.image - only what imshow's vmin/vmax show on screen. Every
        # measurement function reads self.image directly, so a dark/low-
        # contrast fluorescence frame can be stretched for the person
        # drawing/checking things without changing a single measured pixel.
        self.display_vmin = tk.DoubleVar(value=0.0)
        self.display_vmax = tk.DoubleVar(value=255.0)
        self._display_job = None
        self.myo_counter = 0
        # The id THIS myocyte will get when saved. Fixed once at the start of
        # each myocyte (see _reset_myocyte) so the correction log write in
        # finish_editing() and the CSV row write in save_myocyte() - which
        # happen at different times - always agree on the same myocyte_id
        # and stay joinable, matching the macro's own single-myoCounter-value
        # guarantee (it increments myoCounter only once, at the very end).
        self.pending_myocyte_id = 1
        self.csv_path = None

        self.boundary = None         # (N,2) array once drawn
        self.normal_angle = None
        self.line = None             # (ax1, ay1, ax2, ay2)
        self.profile = None
        self.est_period_px = None
        self.min_spacing_px = None
        self.auto_ticks_px = None    # peak positions, px along the line
        self.final_ticks_px = None
        self.sarc_mode = "none"

        self.last_myocyte = None     # cached context for blind recount
        # Fiber/wave state for the myocyte in progress. Computed at REVIEW
        # time (not save time) so the traces can be seen and corrected
        # before anything is written - see _compute_waves_and_review().
        self.waves = None
        self.wave_link_um = mm.WAVE_LINK_UM
        self.manual_fiber_class = tk.StringVar(value="straight")
        self._fiber_cid = None
        self._cut_cid = None
        self._extend_cid = None
        self._extend_target = None   # (fiber index, extending-the-start?)
        self._manual_fiber_cid = None
        self._manual_fiber_pts = []

        self._boundary_pts = []
        self._boundary_cid = None
        self._edit_points_img = []   # [(x,y)] in image coords, during edit/manual
        self._edit_cids = []
        self._edit_drag_index = None
        self._edit_kind = None       # "EDITED" or "MANUAL"

        # Small artists added incrementally during clicking/dragging (points,
        # in-progress polyline) instead of a full clear()+imshow() per event -
        # that full rebuild on every single click/drag is what made drawing
        # feel laggy on multi-thousand-pixel confocal frames. Cleared and
        # reset to [] every time a full _redraw() runs (its clear() already
        # destroys them).
        self._live_artists = []
        # Whether the user has manually zoomed - if so, a full _redraw()
        # preserves the current view instead of snapping back to full-image
        # fit, which would otherwise happen on every stage transition.
        self._zoom_active = False
        self._scroll_cid = None
        # Completed myocytes THIS SESSION (persists across the per-myocyte
        # _reset_myocyte() calls, cleared only when a new image is chosen or
        # a session is resumed) so a student can see everything they've
        # already measured on the image, matching the macro's own persistent
        # per-cell overlay.
        self.completed_myocytes = []  # [{"boundary": [[x,y],...], "label": str}]

        self._build_controls()
        self._build_center()
        self.status.trace_add("write", lambda *_: self.set_status(self.status.get()))
        self.set_status(self.status.get())

    # -- controls --------------------------------------------------------
    def _build_controls(self):
        c = self.controls

        src = ttk.Frame(c); src.pack(fill="x", pady=2)
        ttk.Label(src, text="Source image", width=14).pack(side="left")
        ttk.Entry(src, textvariable=self.v["source"]).pack(side="right", fill="x", expand=True)
        ttk.Button(c, text="Choose image...", command=self._choose).pack(fill="x", pady=(0, 6))
        ttk.Button(c, text="Resume session...", command=self._resume_session).pack(fill="x", pady=(0, 6))

        # View and brightness fold away by default. Both are reference and
        # adjustment panels, and between them they cost enough height to push
        # the fiber-review buttons off the bottom of the window. The controls
        # column scrolls now, but the buttons a student needs every myocyte
        # should be visible without scrolling at all.
        view = self.add_control_section("View", collapsed=True)
        ttk.Label(view, wraplength=205, justify="left", foreground="#555555",
                  text="Scroll the mouse wheel over the image to zoom in/out "
                       "(zooms on the cursor, like Fiji) - useful for placing "
                       "ticks precisely on individual fibers.").pack(
            fill="x", padx=4, pady=(2, 2))
        ttk.Button(view, text="Reset zoom", command=self._reset_zoom).pack(
            fill="x", padx=4, pady=(0, 4))
        ttk.Label(view, wraplength=205, justify="left", foreground="#555555",
                  text="After a save, fiber traces are overlaid: "
                       "blue=straight, red=wavy, yellow=low-confidence "
                       "(likely a split/branch, not a confident call). "
                       "View only - there is no way yet to click a fiber "
                       "and correct its color.").pack(fill="x", padx=4, pady=(0, 4))

        display = self.add_control_section(
            "Brightness/contrast (view only)", collapsed=True)
        self.vmin_label = ttk.Label(display, text="Min: 0")
        self.vmin_label.pack(anchor="w", padx=4)
        self.vmin_scale = ttk.Scale(
            display, variable=self.display_vmin, from_=0, to=255,
            orient="horizontal", command=lambda _v: self._on_display_range_move())
        self.vmin_scale.pack(fill="x", padx=4, pady=(0, 4))
        self.vmax_label = ttk.Label(display, text="Max: 255")
        self.vmax_label.pack(anchor="w", padx=4)
        self.vmax_scale = ttk.Scale(
            display, variable=self.display_vmax, from_=0, to=255,
            orient="horizontal", command=lambda _v: self._on_display_range_move())
        self.vmax_scale.pack(fill="x", padx=4, pady=(0, 4))
        btn_row = ttk.Frame(display); btn_row.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Button(btn_row, text="Auto", width=8,
                   command=self._auto_display_range).pack(side="left")
        ttk.Button(btn_row, text="Reset", width=8,
                   command=self._reset_display_range).pack(side="right")

        # Session stays open: these are inputs the measurement needs, not
        # adjustments, so hiding them would hide required work.
        session = self.add_control_section("Session")

        def field(label, key, master=session):
            row = ttk.Frame(master); row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=14).pack(side="left")
            ttk.Entry(row, textvariable=self.v[key]).pack(side="right", fill="x", expand=True)

        field("Worm ID", "worm_id")
        field("Genotype", "genotype")
        ttk.Checkbutton(session, text="Blind (hide genotype in CSV/output)",
                         variable=self.v["blind"]).pack(anchor="w", pady=2)
        field("Day", "day")
        region_row = ttk.Frame(session); region_row.pack(fill="x", pady=2)
        ttk.Label(region_row, text="Region", width=14).pack(side="left")
        ttk.Combobox(region_row, textvariable=self.v["region"], values=REGIONS,
                     state="readonly").pack(side="right", fill="x", expand=True)
        myo_row = ttk.Frame(session); myo_row.pack(fill="x", pady=2)
        ttk.Label(myo_row, text="Myocyte number", width=14).pack(side="left")
        ttk.Combobox(myo_row, textvariable=self.v["myo_number"],
                     values=MYO_NUMBER_CHOICES, state="readonly").pack(
            side="right", fill="x", expand=True)
        ttk.Button(session, text="Show myocyte numbering schematic",
                   command=self._show_schematic).pack(fill="x", pady=(2, 2))
        field("Student ID (log)", "student_id")

        self.add_scale_button(
            lambda: self.image, self._apply_scale,
            initial=lambda: self.scale,
            text="Calibrate scale (um/px)...").pack(fill="x", pady=(4, 2))
        self.scale_status_label = ttk.Label(
            c, text="Scale: NOT calibrated - Save will not work until this "
                    "is set.", foreground="#a00000")
        self.scale_status_label.pack(anchor="w", pady=(0, 6))

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        self._actions = ttk.Frame(c); self._actions.pack(fill="x")
        self._show_stage_boundary()

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(c, text="Blind recount of last myocyte",
                   command=self.start_blind_recount).pack(fill="x", pady=2)
        self.counter_label = ttk.Label(c, text="0 myocytes saved this session.",
                                        foreground="#555555")
        self.counter_label.pack(anchor="w", pady=(6, 0))

    def _build_center(self):
        ttk.Label(self.center, text="Myocyte morphometry",
                  font=("Segoe UI", 12, "bold")).pack(anchor="w", padx=6, pady=(6, 2))
        self.center_fig = Figure(figsize=(6.2, 5.2), dpi=100)
        self.center_ax = self.center_fig.add_subplot(111)
        self.center_ax.set_axis_off()
        # Fill the WHOLE figure - matplotlib's default subplot margins waste
        # real space around the image even with the axis off, which was a
        # real (separate) part of "lots of white space around" alongside
        # the resize lag below.
        self.center_ax.set_position([0, 0, 1, 1])
        self.center_canvas = FigureCanvasTkAgg(self.center_fig, master=self.center)
        canvas_widget = self.center_canvas.get_tk_widget()
        canvas_widget.pack(fill="both", expand=True, padx=6, pady=(0, 4))
        self.center_ax.text(0.5, 0.5, "Choose a source image; it appears here.",
                            ha="center", va="center", fontsize=10, color="#888888")
        self.center_canvas.draw()
        self._scroll_cid = self.center_canvas.mpl_connect("scroll_event", self._on_scroll)
        # NOTE: do not bind <Configure> on canvas_widget here. FigureCanvasTk
        # (the actual base class behind FigureCanvasTkAgg) already binds
        # "<Configure>" on this exact widget (get_tk_widget() returns its own
        # _tkcanvas) to its own self.resize, which correctly keeps the figure
        # in sync with the widget's real size. An earlier version of this
        # code added a second, competing bind() here without add="+", which
        # in Tkinter REPLACES a widget's existing binding for that event
        # rather than adding to it - it silently deleted matplotlib's own
        # resize handling and replaced it with an incomplete substitute,
        # and the window stopped resizing at all. imshow keeps aspect='equal'
        # (the default, unchanged) so proportions stay correct regardless -
        # a fiber's true shape matters for placing ticks accurately.
        ttk.Label(self.center, textvariable=self.status, wraplength=620,
                  justify="left").pack(anchor="w", padx=6, pady=(0, 6))
        self.result_label = ttk.Label(self.center, text="", wraplength=620,
                                       justify="left", foreground="#1a4e8a")
        self.result_label.pack(anchor="w", padx=6, pady=(0, 6))

    # -- action-panel stages ----------------------------------------------
    def _clear_actions(self):
        for child in self._actions.winfo_children():
            child.destroy()

    def _show_stage_boundary(self):
        self._clear_actions()
        self.set_help(
            "Step 1 - draw the cell boundary",
            "Everything about this cell is measured from the outline you draw, so "
            "trace the myocyte itself and not the bright fibres inside it. Area, "
            "perimeter, Feret and the sarcomere sampling line are all derived from "
            "this polygon.",
            ["Set Worm ID, Day and Region first - they go into every row.",
             "Calibrate the scale if you have not: enter the length PRINTED on the "
             "image, then apply it. A wrong scale makes every result wrong by the "
             "same factor.",
             "Press Start boundary, then left-click around the cell.",
             "Right-click to close it (3 or more points).",
             "Scroll to zoom in if the edge is hard to see."])
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="1. Draw the cell boundary: left-click vertices on the "
                       "image, right-click to close (3+ vertices).").pack(
            fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Start boundary",
                   command=self.start_boundary).pack(fill="x", pady=2)

    def _show_stage_line(self):
        self._clear_actions()
        self.set_help(
            "Step 2 - the across-band sampling line",
            "Sarcomere LENGTH is read across the striations, not along them. The "
            "cyan line is placed at the cell's widest point, square to the bands "
            "the image itself shows, so edge sarcomeres are not missed. Accept it "
            "if it crosses the bands squarely.",
            ["Accept the proposed line if it cuts across the bands.",
             "Draw your own if the automatic angle is wrong - click the two ends.",
             "Skip sarcomeres to record this cell's shape only."])
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text=(f"Proposed across-band sampling line (auto-oriented "
                        f"{np.degrees(self.normal_angle):.0f} deg). Accept it, "
                        "draw your own, or skip sarcomeres for this cell.")
                  ).pack(fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Accept proposed line",
                   command=self.accept_line).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Draw my own line",
                   command=self.start_own_line).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Skip sarcomeres",
                   command=self.skip_sarcomeres).pack(fill="x", pady=2)

    def _show_stage_review(self):
        self._clear_actions()
        self.set_help(
            "Step 3 - check the sarcomere ticks",
            "Each red tick is one detected band. Spacing between ticks is the "
            "sarcomere length, and the tick count is the sarcomere number. Zoom in "
            "and check they sit on real bands before accepting - a tick on noise "
            "changes both numbers.",
            ["Accept if every tick is on a band and none are missing.",
             "Edit ticks to drag, add or delete individual marks.",
             "Manual to count from scratch, ignoring the automatic pass.",
             "Expect roughly 1.4-1.9 um; CHECK_CALIBRATION means the scale is "
             "probably wrong, not the biology."])
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="Review the automatic sarcomere detection (red ticks)."
                  ).pack(fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Accept auto detection",
                   command=self.accept_auto).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Edit ticks: fix, add, remove",
                   command=self.start_edit_ticks).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Manual: count from scratch",
                   command=self.start_manual_ticks).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Skip sarcomeres",
                   command=self.skip_sarcomeres).pack(fill="x", pady=2)

    def _show_stage_editing(self, kind):
        self._clear_actions()
        verb = "Drag a point to move it, click empty space to add, " \
               "right-click a point to delete." if kind == "EDITED" else \
               "Click each band in order to add a point; right-click a " \
               "point to remove it."
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text=verb).pack(fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Done editing",
                   command=self.finish_editing).pack(fill="x", pady=2)

    def _show_stage_waves(self):
        self._clear_actions()
        self.set_help(
            "Step 4 - check the fibres",
            "Each line is one traced actin fibre: blue straight, red wavy, yellow "
            "low-confidence (likely a split or branch). Waviness is a comparative "
            "damage proxy, so it is only meaningful if the traces really follow "
            "single fibres. Correct them here - nothing is written until you save.",
            ["Click a fibre to relabel it; right-click deletes one.",
             "Delete a trace that zigzags between two different fibres - that is "
             "the tracer hopping, not a real wave.",
             "Cut a fibre that covers a straight stretch AND a wavy one.",
             "Extend one the tracer stopped short on.",
             "Draw a fibre it missed entirely.",
             "Retry tracing with a smaller link distance if it keeps hopping."])
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="Review the fiber traces on the image: blue=straight, "
                       "red=wavy, yellow=low-confidence. Correct anything "
                       "wrong BEFORE saving.").pack(fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Relabel / delete a fiber (click it)",
                   command=self.start_fiber_relabel).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Cut a fiber in two",
                   command=self.start_fiber_cut).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Extend a fiber",
                   command=self.start_fiber_extend).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Draw a missed fiber by hand",
                   command=self.start_manual_fiber).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Retry tracing (change link distance)",
                   command=self.retry_wave_detection).pack(fill="x", pady=2)
        ttk.Separator(self._actions, orient="horizontal").pack(fill="x", pady=4)
        ttk.Button(self._actions, text="Accept fibers, go to save",
                   command=self.accept_waves).pack(fill="x", pady=2)

    def _show_stage_fiber_edit(self):
        self._clear_actions()
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="Left-click a fiber to cycle its label "
                       "(straight -> wavy -> low-confidence). Right-click a "
                       "fiber to delete it - use that for a trace that "
                       "jumped between two different real fibers.").pack(
            fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Done relabelling",
                   command=self.finish_fiber_relabel).pack(fill="x", pady=2)

    def _show_stage_fiber_cut(self):
        self._clear_actions()
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="Click a fiber at the point where it should be cut in "
                       "two. Use this when one trace covers a genuinely "
                       "straight stretch and a wavy one, so each half can be "
                       "labelled separately.").pack(fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Done cutting",
                   command=self.finish_fiber_cut).pack(fill="x", pady=2)

    def _show_stage_fiber_extend(self):
        self._clear_actions()
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="Click near the END of a fiber to pick it, then click "
                       "along where it really continues. Right-click to "
                       "finish. Use this where the tracer stopped early.").pack(
            fill="x", pady=(0, 4))
        ttk.Button(self._actions, text="Done extending",
                   command=self.finish_fiber_extend).pack(fill="x", pady=2)

    def _show_stage_manual_fiber(self):
        self._clear_actions()
        ttk.Label(self._actions, wraplength=205, justify="left", foreground="#555555",
                  text="Left-click along the fiber from one end to the "
                       "other (several points). Right-click to finish it. "
                       "The tracer only ever seeds from detected bands, so "
                       "a fiber it missed can only be added this way.").pack(
            fill="x", pady=(0, 4))
        row = ttk.Frame(self._actions); row.pack(fill="x", pady=2)
        ttk.Label(row, text="Label", width=8).pack(side="left")
        ttk.Combobox(row, textvariable=self.manual_fiber_class,
                     values=["straight", "wavy", "low-confidence"],
                     state="readonly").pack(side="right", fill="x", expand=True)
        ttk.Button(self._actions, text="Cancel this fiber",
                   command=self.cancel_manual_fiber).pack(fill="x", pady=2)

    def _show_stage_save(self):
        self._clear_actions()
        self.set_help(
            "Step 5 - save this myocyte",
            "Saving appends one row to the CSV next to your image and updates the "
            "session file, so nothing is lost if you close the tool. The cell stays "
            "outlined on the image so you can see what is already done.",
            ["Set the Myocyte number if you can identify the cell on the schematic.",
             "Save myocyte writes the row immediately.",
             "Discard throws this cell away without writing anything.",
             "Then draw the next boundary - the number advances for you."])
        ttk.Button(self._actions, text="4. Save myocyte",
                   command=self.save_myocyte).pack(fill="x", pady=2)
        if self.waves:
            ttk.Button(self._actions, text="Back to fiber review",
                       command=lambda: (self._show_stage_waves(), self._redraw())
                       ).pack(fill="x", pady=2)
        ttk.Button(self._actions, text="Discard this myocyte / start over",
                   command=self._reset_myocyte).pack(fill="x", pady=2)

    # -- source / calibration ----------------------------------------------
    def _choose(self):
        path = filedialog.askopenfilename(
            parent=self, title="Choose a myocyte image",
            filetypes=[("Images", "*.tif *.tiff *.png *.jpg *.jpeg *.bmp"),
                       ("All files", "*.*")])
        if not path:
            return
        self.v["source"].set(path)
        try:
            movie = open_movie(path)
            self.image = gray(movie.get_frame(0))
            movie.close()
        except Exception as exc:
            self.status.set(f"Could not load image: {exc}")
            return
        self.completed_myocytes = []  # overlays are per-image; a new image
                                       # starts with none, even mid-session
                                       # (csv_path/myo_counter deliberately
                                       # NOT reset - see _save_myocyte_
                                       # unguarded's docstring note on the
                                       # macro's own session-spans-multiple-
                                       # images behavior)
        self._zoom_active = False
        self._reset_myocyte(keep_image=True)
        lo, hi = float(self.image.min()), float(self.image.max())
        self.vmin_scale.configure(from_=lo, to=hi)
        self.vmax_scale.configure(from_=lo, to=hi)
        self._auto_display_range()  # also redraws
        self.status.set("Image loaded. Draw the cell boundary.")

    # -- session save / resume ----------------------------------------------
    def _session_path(self):
        if self.csv_path is None:
            return None
        return self.csv_path.with_name(self.csv_path.stem + "_session.json")

    def _save_session_state(self):
        """Called after every successful save, so closing the tool (or it
        crashing) never loses more than the myocyte in progress - everything
        already saved is durable in the CSV, and where to pick back up
        (which image, session metadata, what's already been measured on it)
        is durable here."""
        path = self._session_path()
        if path is None:
            return
        state = {
            "source": self.v["source"].get(),
            "worm_id": self.v["worm_id"].get(),
            "genotype": self.v["genotype"].get(),
            "blind": bool(self.v["blind"].get()),
            "day": self.v["day"].get(),
            "region": self.v["region"].get(),
            "student_id": self.v["student_id"].get(),
            "scale": self.scale,
            "myo_counter": self.myo_counter,
            "last_myo_number": self.last_myo_number,
            "csv_path": str(self.csv_path),
            "completed_myocytes": self.completed_myocytes,
        }
        try:
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as exc:
            self.status.set(f"Myocyte was saved to the CSV, but the resume "
                            f"file could not be written: {exc}")

    def _resume_session(self):
        path = filedialog.askopenfilename(
            parent=self, title="Resume a saved session",
            filetypes=[("Session files", "*_session.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            state = json.loads(Path(path).read_text(encoding="utf-8"))
            movie = open_movie(state["source"])
            self.image = gray(movie.get_frame(0))
            movie.close()
        except Exception as exc:
            self.status.set(f"Could not resume session: {exc}")
            return
        self.v["source"].set(state.get("source", ""))
        self.v["worm_id"].set(state.get("worm_id", ""))
        self.v["genotype"].set(state.get("genotype", "unknown"))
        self.v["blind"].set(bool(state.get("blind", True)))
        self.v["day"].set(state.get("day", ""))
        self.v["region"].set(state.get("region", "midbody"))
        self.v["student_id"].set(state.get("student_id", ""))
        self.scale = state.get("scale")
        self.myo_counter = int(state.get("myo_counter", 0))
        self.last_myo_number = state.get("last_myo_number")
        self.csv_path = Path(state["csv_path"]) if state.get("csv_path") else None
        self.completed_myocytes = state.get("completed_myocytes", [])
        self._zoom_active = False
        self._reset_myocyte(keep_image=True)  # also applies the next-number suggestion
        lo, hi = float(self.image.min()), float(self.image.max())
        self.vmin_scale.configure(from_=lo, to=hi)
        self.vmax_scale.configure(from_=lo, to=hi)
        self._auto_display_range()  # also redraws
        self.counter_label.configure(
            text=f"{self.myo_counter} myocyte row(s) saved this session.")
        self.status.set(
            f"Resumed: {len(self.completed_myocytes)} myocyte(s) already "
            "measured on this image (shown in green). Draw the next boundary.")
        self.log("Session resumed", str(path), status="edit")

    def _apply_scale(self, res):
        self.scale = float(res["um_per_px"])
        self.status.set(f"Scale set: {self.scale:.5f} um/pixel.")
        self.log("Scale calibrated", f"{self.scale:.5f} um/px", status="edit")
        self.scale_status_label.configure(
            text=f"Scale: {self.scale:.5f} um/px", foreground="#1a6e1a")

    # -- myocyte identity (body-wall numbering schematic) -------------------
    def _show_schematic(self):
        """Show the body-wall numbering schematic in its own window, so a
        student can check which numbered myocyte (Myo01-24) they are looking
        at against the working image - same purpose as the macro's own
        showSchematic().

        The diagram is GENERATED by app/myocyte_schematic.py from the same
        muscle-size profile the segmentation uses, so the numbering a student
        checks against cannot drift from the numbering the tools measure
        with. It was previously a stored image that had to be located on
        disk, and when it was not found the student was sent looking for it
        through a file dialog - which is how a figure from someone's
        Downloads folder could end up standing in for the reference.
        """
        try:
            import myocyte_schematic as msch
        except Exception as exc:
            self.status.set(
                f"Schematic generator unavailable ({exc}); "
                f"falling back to a stored image.")
            return self._show_schematic_file()

        win = tk.Toplevel(self)
        win.title("Myocyte numbering - Myo01 to Myo24")
        fig = Figure(figsize=(13.0, 2.9), dpi=100)
        ax = fig.add_subplot(111)
        msch.draw(ax)
        fig.subplots_adjust(left=0.01, right=0.99, top=0.99, bottom=0.01)
        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        ttk.Label(
            win, wraplength=1180, justify="left", foreground="#555555",
            text="Numbering runs head (1) to tail (24). The two bands are "
                 "opposing muscle quadrants - neither is labelled dorsal or "
                 "ventral, because orientation is only known when a vulva "
                 "seed was given, and the vulva is drawn as an X across the "
                 "full width for the same reason.").pack(
            anchor="w", padx=10, pady=(2, 8))
        win.transient(self)
        win.lift()
        self.status.set("Opened numbering schematic (generated).")

    def _show_schematic_file(self):
        """Fallback: open a stored schematic image, as this tool used to."""
        path = None
        for name in SCHEMATIC_FILENAMES:
            candidate = HERE / name
            if candidate.exists():
                path = candidate
                break
        if path is None:
            chosen = filedialog.askopenfilename(
                parent=self, title="Choose the myocyte numbering schematic",
                filetypes=[("Images", "*.jpg *.jpeg *.png *.tif *.tiff"),
                           ("All files", "*.*")])
            if not chosen:
                self.status.set("No schematic selected.")
                return
            path = Path(chosen)
        try:
            os.startfile(str(path))
        except Exception:
            try:
                subprocess.Popen(["explorer", str(path)])
            except Exception as exc:
                self.status.set(f"Could not open the schematic: {exc}")
                return
        self.status.set(f"Opened numbering schematic: {path.name}")

    # -- display brightness/contrast (view only, never measured) -----------
    def _on_display_range_move(self):
        self.vmin_label.configure(text=f"Min: {self.display_vmin.get():.1f}")
        self.vmax_label.configure(text=f"Max: {self.display_vmax.get():.1f}")
        if self._display_job is not None:
            try:
                self.after_cancel(self._display_job)
            except Exception:
                pass
        self._display_job = self.after(80, self._redraw)

    def _auto_display_range(self):
        if self.image is None:
            return
        lo, hi = np.percentile(self.image, [0.5, 99.5])
        if hi <= lo:
            lo, hi = float(self.image.min()), float(self.image.max())
        self.display_vmin.set(float(lo))
        self.display_vmax.set(float(hi))
        self._on_display_range_move()

    def _reset_display_range(self):
        if self.image is None:
            return
        self.display_vmin.set(float(self.image.min()))
        self.display_vmax.set(float(self.image.max()))
        self._on_display_range_move()

    # -- zoom (scroll wheel, like Fiji - never consumes left/right click, -
    # -- so it coexists with the boundary/tick click handlers) -------------
    def _on_scroll(self, event):
        if self.image is None or event.inaxes != self.center_ax:
            return
        if event.xdata is None or event.ydata is None:
            return
        scale = 0.8 if event.button == "up" else 1.25 if event.button == "down" else None
        if scale is None:
            return
        x0, x1 = self.center_ax.get_xlim()
        y0, y1 = self.center_ax.get_ylim()
        new_w = (x1 - x0) * scale
        new_h = (y1 - y0) * scale
        # keep the point under the cursor fixed while the view scales
        relx = (x1 - event.xdata) / (x1 - x0) if x1 != x0 else 0.5
        rely = (y1 - event.ydata) / (y1 - y0) if y1 != y0 else 0.5
        self.center_ax.set_xlim(event.xdata - new_w * (1 - relx), event.xdata + new_w * relx)
        self.center_ax.set_ylim(event.ydata - new_h * (1 - rely), event.ydata + new_h * rely)
        self._zoom_active = True
        # Synchronous draw, not draw_idle(): a fast scroll wheel/trackpad
        # fires many events in quick succession, each computed from the
        # CURRENT axes limits (correct regardless of render timing - the
        # limit state updates immediately, independent of when pixels hit
        # the screen). But draw_idle() defers the actual on-screen update,
        # so a person scrolling based on what they SEE can end up several
        # events ahead of what's rendered, which reads as the zoom center
        # drifting away from the cursor even though each individual
        # computation was centered correctly. Keeping the screen in sync
        # with each event closes that feedback-loop lag.
        self.center_canvas.draw()

    def _reset_zoom(self):
        if self.image is None:
            return
        h, w = self.image.shape
        self.center_ax.set_xlim(-0.5, w - 0.5)
        self.center_ax.set_ylim(h - 0.5, -0.5)  # image y-axis: top row first
        self._zoom_active = False
        self.center_canvas.draw_idle()

    def _pick_radius(self):
        """Click/drag tolerance for finding an existing edit point, in DATA
        (image-pixel) units - but sized from a fixed SCREEN-pixel tolerance
        at the CURRENT zoom level, not a fraction of the line's own length.

        A fixed data-pixel radius looks reasonable in the abstract but is
        wrong on these images: a multi-thousand-pixel confocal frame shown
        zoomed-out in a modest canvas compresses many image pixels into one
        screen pixel, so a "15 image-px" tolerance can be a fraction of a
        single screen pixel - effectively impossible to click. Deriving the
        radius from the actual data-per-screen-pixel ratio means the
        tolerance is always about the same number of screen pixels,
        regardless of zoom, which is what "close enough to drag" should mean
        to a person looking at the screen.
        """
        try:
            xlim = self.center_ax.get_xlim()
            bbox = self.center_ax.get_window_extent()
            data_per_px = abs(xlim[1] - xlim[0]) / max(bbox.width, 1)
            return max(2.0, 10.0 * data_per_px)
        except Exception:
            ax1, ay1, ax2, ay2 = self.line
            length = float(np.hypot(ax2 - ax1, ay2 - ay1))
            return max(4.0, 0.03 * length)

    # -- boundary drawing ----------------------------------------------
    def start_boundary(self):
        if self.image is None:
            self.status.set("Choose a source image first.")
            return
        self._reset_myocyte(keep_image=True)
        self._boundary_pts = []
        self._boundary_cid = self.center_canvas.mpl_connect(
            "button_press_event", self._boundary_click)
        self._redraw()
        self.status.set("Draw the cell boundary: left-click vertices, "
                         "right-click to close (3+ vertices).")

    def _boundary_click(self, event):
        if event.inaxes != self.center_ax:
            return
        if event.button == 3:
            self._finish_boundary()
            return
        if event.xdata is None:
            return
        self._boundary_pts.append((float(event.xdata), float(event.ydata)))
        self._draw_live_boundary()

    # -- incremental (fast) drawing during clicking/dragging ---------------
    # Adds small artists directly instead of the full clear()+imshow()
    # _redraw() does - that full rebuild on every single mouse event is what
    # made drawing feel laggy on multi-thousand-pixel confocal frames (a
    # point wouldn't visibly appear until the whole sequence finished and
    # something else forced a redraw). Same pattern nonstriated_morphology_
    # tool.py already uses for its own ROI clicking, which is why THAT tool
    # doesn't have this problem.
    def _clear_live_artists(self):
        for artist in self._live_artists:
            try:
                artist.remove()
            except Exception:
                pass
        self._live_artists = []

    def _add_live_boundary_artist(self):
        """Add the in-progress boundary polyline as a TRACKED artist (append
        to self._live_artists) without triggering a canvas redraw - the
        caller does that. This is the only place that ever draws
        _boundary_pts, used by both the full _redraw() and the incremental
        per-click path, so _live_artists is always a complete, accurate
        record of what's on screen for it - see _add_live_edit_artist for
        why that invariant matters."""
        if self._boundary_pts:
            pts = np.array(self._boundary_pts)
            line, = self.center_ax.plot(pts[:, 0], pts[:, 1], "o-",
                                        color="#ffcc00", ms=5, lw=1.5)
            self._live_artists.append(line)

    def _add_live_edit_artist(self):
        """Add the in-progress edit/manual tick markers as a TRACKED artist.
        Same single-path discipline as _add_live_boundary_artist, and for
        the same reason: a real bug shipped here once already. _redraw()
        used to draw these points with its OWN separate ax.plot() call,
        untracked by _live_artists. The first incremental edit after that
        (e.g. deleting one point) would clear only what _live_artists knew
        about - empty - draw a fresh, correct marker, and leave the
        original untracked one orphaned on the canvas forever: added points
        appeared to work, but nothing ever visually disappeared. Every
        artist for these points must be created through this one method so
        _clear_live_artists() can always find and remove all of them."""
        if self._edit_points_img:
            pts = np.array(self._edit_points_img)
            marker, = self.center_ax.plot(
                pts[:, 0], pts[:, 1], "s", color="#ff4fd8", ms=8, mew=1.8,
                markerfacecolor="none")
            self._live_artists.append(marker)

    def _draw_live_boundary(self):
        self._clear_live_artists()
        self._add_live_boundary_artist()
        self.center_canvas.draw_idle()

    def _draw_live_edit_points(self):
        self._clear_live_artists()
        self._add_live_edit_artist()
        self.center_canvas.draw_idle()

    def _finish_boundary(self):
        if self._boundary_cid is not None:
            try:
                self.center_canvas.mpl_disconnect(self._boundary_cid)
            except Exception:
                pass
            self._boundary_cid = None
        if len(self._boundary_pts) < 3:
            self.status.set("Need at least 3 vertices; keep clicking, "
                             "then right-click to close.")
            return
        self.boundary = np.array(self._boundary_pts, dtype=float)
        self.log("Boundary drawn", f"{len(self.boundary)}-vertex polygon",
                  status="edit")
        self._propose_line()

    # -- sampling line ----------------------------------------------
    def _propose_line(self):
        if self.image is None or self.boundary is None:
            return
        try:
            self.normal_angle = mm.band_normal_angle(self.image, self.boundary)
            self.line = mm.widest_point_line(self.boundary, self.normal_angle)
        except Exception as exc:
            self.status.set(f"Could not propose a sampling line: {exc}")
            self.line = None
        if self.line is None:
            self.status.set("No usable sampling line found; draw your own or skip.")
        self._show_stage_line()
        self._redraw()

    def start_own_line(self):
        self._own_line_pts = []
        self._own_line_cid = self.center_canvas.mpl_connect(
            "button_press_event", self._own_line_click)
        self.status.set("Draw across-band line: click the two endpoints.")

    def _own_line_click(self, event):
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        self._own_line_pts.append((float(event.xdata), float(event.ydata)))
        if len(self._own_line_pts) >= 2:
            try:
                self.center_canvas.mpl_disconnect(self._own_line_cid)
            except Exception:
                pass
            (x1, y1), (x2, y2) = self._own_line_pts[:2]
            self.line = (x1, y1, x2, y2)
            self.log("Sampling line drawn manually", status="edit")
            self.accept_line()

    def accept_line(self):
        if self.line is None:
            self.status.set("No line to accept.")
            return
        self._detect_sarcomeres()

    def skip_sarcomeres(self):
        self.sarc_mode = "none"
        self.profile = None
        self.auto_ticks_px = None
        self.final_ticks_px = None
        self.waves = None
        self.result_label.configure(text="Sarcomeres skipped for this cell.")
        self._show_stage_save()
        self._redraw()

    # -- fiber / wave review (runs BEFORE saving, like the macro) -----------
    def _compute_waves_and_review(self):
        """Trace and classify fibers now, so they can be SEEN and corrected
        before the row is written.

        This used to run inside save_myocyte(), which meant fiber traces
        only ever appeared after the myocyte was already committed - no
        preview, no way to relabel a wrong call, no way to add a fiber the
        tracer missed. The macro ran detectWaves() during measurement with
        an Accept / Correct / Retry dialog for exactly this reason.
        """
        self.waves = None
        if (self.line is None or self.final_ticks_px is None
                or len(self.final_ticks_px) < 2 or not self.scale):
            self._show_stage_save()
            self._redraw()
            return
        try:
            self.waves = self._run_wave_detection()
        except Exception as exc:
            self.log("Wave detection failed for this myocyte",
                    f"{type(exc).__name__}: {exc} - geometry and sarcomere "
                    "data are unaffected; wave_* columns will be 0.",
                    status="error")
            self.status.set(f"Wave detection failed: {exc}. You can still "
                            "save; wave columns will be zero.")
            self._show_stage_save()
            self._redraw()
            return
        # Report the fibers actually TRACED (and therefore visible and
        # correctable), not the number of bands seeded.
        #
        # This is a deliberate, documented divergence from the macro.
        # detect_waves() sets n_fibers = len(zpos) - every detected band
        # seeds a fiber - but a seed whose trace comes out shorter than 20
        # points is skipped and never produces a fiber. The macro counted
        # those skipped seeds in wave_width_fraction's denominator anyway.
        # That was defensible when nothing was reviewable; now that a person
        # sees the traces and can delete a bad one or hand-draw a missed
        # one, a denominator including invisible, uncorrectable fibers would
        # make the on-screen picture disagree with the saved number. The
        # seeded count is kept as wave_n_seeded for provenance.
        self.waves["n_seeded"] = self.waves.get("n_fibers", 0)
        self._recount_wave_summary()
        self._show_stage_waves()
        self._redraw()
        self._update_wave_label()

    def _run_wave_detection(self):
        ax1, ay1, ax2, ay2 = self.line
        length_line = float(np.hypot(ax2 - ax1, ay2 - ay1))
        nux = (ax2 - ax1) / max(length_line, 1e-9)
        nuy = (ay2 - ay1) / max(length_line, 1e-9)
        mux, muy = -nuy, nux
        geo = mm.boundary_measurements(self.boundary)
        feret_um = geo["feret_px"] * self.scale
        path_contains = _boundary_path(self.boundary)
        return mm.detect_waves(
            self.image, path_contains, self.final_ticks_px,
            ax1, ay1, mux, muy, nux, nuy, feret_um, self.scale,
            wave_link_um=self.wave_link_um)

    def _recount_wave_summary(self):
        """Recompute the aggregate damage fractions from the CURRENT (possibly
        hand-corrected, possibly hand-drawn) fiber classes, so the saved row
        reflects what the person actually confirmed rather than the automatic
        first pass."""
        if not self.waves:
            return
        fibers = self.waves.get("fibers", [])
        n_fibers = len(fibers)
        affected = [f for f in fibers if f["class"] == 1]
        lowconf = [f for f in fibers if f["class"] == 2]
        self.waves["n_fibers"] = n_fibers
        self.waves["n_affected"] = len(affected)
        self.waves["n_lowconf"] = len(lowconf)
        self.waves["width_fraction"] = (len(affected) / n_fibers) if n_fibers else 0.0
        fracs = [f.get("length_fraction", 0.0) for f in affected]
        self.waves["length_frac_mean"] = float(np.mean(fracs)) if fracs else 0.0
        self.waves["length_frac_max"] = float(np.max(fracs)) if fracs else 0.0

    def accept_waves(self):
        self._recount_wave_summary()
        self._update_wave_label()
        self._show_stage_save()
        self._redraw()

    def retry_wave_detection(self):
        """Re-trace with a different link distance. The tracer's search
        radius is the main knob that decides whether it follows one fiber or
        hops onto its neighbour, and the right value depends on how close
        this myocyte's fibers actually are - so it is exposed rather than
        fixed, same as the macro's own adjustable WAVE_LINK_UM."""
        current = self.wave_link_um
        answer = simpledialog.askfloat(
            "Retry fiber tracing",
            "Link distance (um) - how far sideways the tracer may look for "
            "the fiber's continuation at each step.\n\n"
            "Smaller keeps it on one fiber but may lose a genuinely wavy "
            "one; larger follows waves but risks hopping onto a neighbour. "
            "It is additionally capped at 35% of the real gap between this "
            "cell's own detected bands.\n\n"
            f"Current: {current}",
            parent=self, initialvalue=current, minvalue=0.05, maxvalue=20.0)
        if answer is None:
            return
        self.wave_link_um = float(answer)
        try:
            self.waves = self._run_wave_detection()
        except Exception as exc:
            self.status.set(f"Retry failed: {exc}")
            return
        self.log("Fiber tracing retried", f"link distance {self.wave_link_um} um",
                 status="edit")
        self.status.set(f"Re-traced with link distance {self.wave_link_um} um. "
                        "Nothing is written until you save.")
        self._update_wave_label()
        self._redraw()

    # -- relabel / delete an existing fiber ---------------------------------
    def start_fiber_relabel(self):
        if not self.waves or not self.waves.get("fibers"):
            self.status.set("No fibers to relabel.")
            return
        self._fiber_cid = self.center_canvas.mpl_connect(
            "button_press_event", self._fiber_click)
        self._show_stage_fiber_edit()
        self.status.set("Left-click a fiber to cycle its label; right-click "
                        "to delete it.")

    def _nearest_fiber_index(self, x, y):
        best_i, best_d = None, None
        for i, fiber in enumerate(self.waves.get("fibers", [])):
            fx = np.asarray(fiber["x"], dtype=float)
            fy = np.asarray(fiber["y"], dtype=float)
            if fx.size == 0:
                continue
            d = float(np.min(np.hypot(fx - x, fy - y)))
            if best_d is None or d < best_d:
                best_i, best_d = i, d
        if best_i is None or best_d > self._pick_radius() * 3:
            return None
        return best_i

    def _fiber_click(self, event):
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        i = self._nearest_fiber_index(float(event.xdata), float(event.ydata))
        if i is None:
            self.status.set("No fiber near that click - try closer to a traced line.")
            return
        fiber = self.waves["fibers"][i]
        if event.button == 3:
            self.waves["fibers"].pop(i)
            self._recount_wave_summary()
            self.status.set(f"Fiber deleted ({len(self.waves['fibers'])} left). "
                            "Nothing is written until you save.")
        else:
            fiber["class"] = (fiber["class"] + 1) % 3
            fiber["corrected"] = True
            if fiber["class"] != 1:
                fiber["length_fraction"] = 0.0
            self._recount_wave_summary()
            self.status.set(
                f"Fiber relabelled to "
                f"{['straight', 'wavy', 'low-confidence'][fiber['class']]}.")
        self._update_wave_label()
        self._redraw()

    def finish_fiber_relabel(self):
        if self._fiber_cid is not None:
            try:
                self.center_canvas.mpl_disconnect(self._fiber_cid)
            except Exception:
                pass
            self._fiber_cid = None
        self._recount_wave_summary()
        self._update_wave_label()
        self._show_stage_waves()
        self._redraw()

    # -- cut / extend an existing fiber -------------------------------------
    # Between them, relabel, delete, cut, extend and hand-draw give a fiber
    # the same editing power the population tracker gives an animal track -
    # split, trim, delete, add missing points - except applied to one
    # frame's traced fiber rather than a trajectory over time.
    def _nearest_fiber_and_point(self, x, y):
        """(fiber_index, point_index) of the closest traced point to (x, y),
        or None when the click is not near any fiber."""
        best = None
        for i, fiber in enumerate(self.waves.get("fibers", [])):
            fx = np.asarray(fiber["x"], dtype=float)
            fy = np.asarray(fiber["y"], dtype=float)
            if fx.size == 0:
                continue
            d = np.hypot(fx - x, fy - y)
            j = int(np.argmin(d))
            if best is None or d[j] < best[2]:
                best = (i, j, float(d[j]))
        if best is None or best[2] > self._pick_radius() * 3:
            return None
        return best[0], best[1]

    def _fiber_arc_length_px(self, fx, fy):
        fx = np.asarray(fx, dtype=float); fy = np.asarray(fy, dtype=float)
        if fx.size < 2:
            return 0.0
        return float(np.hypot(np.diff(fx), np.diff(fy)).sum())

    def _refresh_length_fraction(self, fiber):
        """Keep a wavy fiber's length fraction consistent with its CURRENT
        extent after a cut or extend. The automatic value came from the
        classifier's wavy-window count on the original trace; once a person
        changes the trace's extent that number no longer describes it, so it
        is re-derived from the fiber's own arc length against the cell's
        Feret - the same basis used for a hand-drawn fiber."""
        if fiber.get("class") != 1:
            fiber["length_fraction"] = 0.0
            return
        try:
            geo = mm.boundary_measurements(self.boundary)
            feret_um = geo["feret_px"] * self.scale
            arc_um = self._fiber_arc_length_px(fiber["x"], fiber["y"]) * self.scale
            fiber["length_fraction"] = float(arc_um / feret_um) if feret_um > 0 else 0.0
        except Exception:
            pass

    def start_fiber_cut(self):
        if not self.waves or not self.waves.get("fibers"):
            self.status.set("No fibers to cut.")
            return
        self._cut_cid = self.center_canvas.mpl_connect(
            "button_press_event", self._fiber_cut_click)
        self._show_stage_fiber_cut()
        self.status.set("Click a fiber where it should be cut in two.")

    def _fiber_cut_click(self, event):
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        hit = self._nearest_fiber_and_point(float(event.xdata), float(event.ydata))
        if hit is None:
            self.status.set("No fiber near that click - try closer to a traced line.")
            return
        i, j = hit
        fiber = self.waves["fibers"][i]
        fx = list(fiber["x"]); fy = list(fiber["y"])
        # Both halves must survive classify_fiber_wavy's own 10-point floor,
        # otherwise a "cut" would silently produce a stub too short to mean
        # anything.
        if j < 10 or (len(fx) - j) < 10:
            self.status.set(
                "That cut would leave a stub shorter than 10 points, which is "
                "too short to classify - cut nearer the middle, or delete the "
                "fiber instead.")
            return
        head = dict(fiber); tail = dict(fiber)
        head["x"] = fx[:j]; head["y"] = fy[:j]
        tail["x"] = fx[j:]; tail["y"] = fy[j:]
        for part in (head, tail):
            part["corrected"] = True
            part["source"] = fiber.get("source", "auto")
            self._refresh_length_fraction(part)
        self.waves["fibers"][i:i + 1] = [head, tail]
        self._recount_wave_summary()
        self.status.set(
            f"Fiber cut into two ({len(head['x'])} and {len(tail['x'])} points; "
            f"{self.waves['n_fibers']} fibers total). Relabel either half if "
            "the cut separated a straight stretch from a wavy one.")
        self._update_wave_label()
        self._redraw()

    def finish_fiber_cut(self):
        if self._cut_cid is not None:
            try:
                self.center_canvas.mpl_disconnect(self._cut_cid)
            except Exception:
                pass
            self._cut_cid = None
        self._recount_wave_summary()
        self._update_wave_label()
        self._show_stage_waves()
        self._redraw()

    def start_fiber_extend(self):
        if not self.waves or not self.waves.get("fibers"):
            self.status.set("No fibers to extend.")
            return
        self._extend_target = None
        self._extend_cid = self.center_canvas.mpl_connect(
            "button_press_event", self._fiber_extend_click)
        self._show_stage_fiber_extend()
        self.status.set("Click near the END of the fiber you want to extend.")

    def _fiber_extend_click(self, event):
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        x, y = float(event.xdata), float(event.ydata)
        if event.button == 3:
            self.finish_fiber_extend()
            return
        if self._extend_target is None:
            hit = self._nearest_fiber_and_point(x, y)
            if hit is None:
                self.status.set("No fiber near that click - click near the end "
                                "of the fiber you want to extend.")
                return
            i, j = hit
            fiber = self.waves["fibers"][i]
            # Extend whichever end the click was closer to.
            at_start = j < (len(fiber["x"]) - 1 - j)
            self._extend_target = (i, at_start)
            self.status.set(
                f"Extending the {'start' if at_start else 'end'} of this fiber. "
                "Click along where it continues; right-click when done.")
            self._redraw()
            return
        i, at_start = self._extend_target
        fiber = self.waves["fibers"][i]
        fx = list(fiber["x"]); fy = list(fiber["y"])
        anchor = (fx[0], fy[0]) if at_start else (fx[-1], fy[-1])
        # Fill in ~2 px steps so an extended stretch has the same point
        # spacing as the traced part - classify_fiber_wavy counts POINTS, so
        # a sparsely clicked extension would otherwise be weighted wrongly
        # against the rest of the fiber.
        seg = float(np.hypot(x - anchor[0], y - anchor[1]))
        n = max(1, int(round(seg / 2.0)))
        xs = list(np.linspace(anchor[0], x, n + 1)[1:])
        ys = list(np.linspace(anchor[1], y, n + 1)[1:])
        if at_start:
            fiber["x"] = list(reversed(xs)) + fx
            fiber["y"] = list(reversed(ys)) + fy
        else:
            fiber["x"] = fx + xs
            fiber["y"] = fy + ys
        fiber["corrected"] = True
        self._refresh_length_fraction(fiber)
        self._recount_wave_summary()
        self.status.set(
            f"Extended to {len(fiber['x'])} points. Keep clicking, or "
            "right-click to finish.")
        self._update_wave_label()
        self._redraw()

    def finish_fiber_extend(self):
        if self._extend_cid is not None:
            try:
                self.center_canvas.mpl_disconnect(self._extend_cid)
            except Exception:
                pass
            self._extend_cid = None
        self._extend_target = None
        self._recount_wave_summary()
        self._update_wave_label()
        self._show_stage_waves()
        self._redraw()

    # -- draw a fiber the tracer missed entirely ----------------------------
    def start_manual_fiber(self):
        if self.waves is None:
            self.status.set("Detect sarcomeres first.")
            return
        self._manual_fiber_pts = []
        self._manual_fiber_cid = self.center_canvas.mpl_connect(
            "button_press_event", self._manual_fiber_click)
        self._show_stage_manual_fiber()
        self.status.set("Click along the missed fiber; right-click to finish.")

    def _manual_fiber_click(self, event):
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        if event.button == 3:
            self._finish_manual_fiber()
            return
        self._manual_fiber_pts.append((float(event.xdata), float(event.ydata)))
        self._clear_live_artists()
        pts = np.array(self._manual_fiber_pts)
        artist, = self.center_ax.plot(pts[:, 0], pts[:, 1], "o-",
                                       color="#00e0ff", ms=4, lw=1.5)
        self._live_artists.append(artist)
        self.center_canvas.draw_idle()

    def _finish_manual_fiber(self):
        if self._manual_fiber_cid is not None:
            try:
                self.center_canvas.mpl_disconnect(self._manual_fiber_cid)
            except Exception:
                pass
            self._manual_fiber_cid = None
        pts = self._manual_fiber_pts
        self._manual_fiber_pts = []
        self._clear_live_artists()
        if len(pts) < 2:
            self.status.set("A fiber needs at least 2 points - nothing added.")
            self._show_stage_waves(); self._redraw()
            return
        # Resample the clicked polyline so a hand-drawn fiber has comparable
        # point spacing to a traced one - its wavy length fraction is
        # measured the same way, and that measure counts POINTS.
        pts = np.asarray(pts, dtype=float)
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        total = float(seg.sum())
        n_steps = max(2, int(round(total / 2.0)))   # ~2 px spacing, as traced
        t = np.concatenate([[0.0], np.cumsum(seg)])
        even = np.linspace(0.0, total, n_steps)
        fx = np.interp(even, t, pts[:, 0])
        fy = np.interp(even, t, pts[:, 1])
        cls = {"straight": 0, "wavy": 1,
               "low-confidence": 2}[self.manual_fiber_class.get()]
        geo = mm.boundary_measurements(self.boundary)
        feret_um = geo["feret_px"] * self.scale
        length_fraction = 0.0
        if cls == 1 and feret_um > 0:
            length_fraction = float(total * self.scale / feret_um)
        self.waves.setdefault("fibers", []).append({
            "x": fx.tolist(), "y": fy.tolist(), "class": cls,
            "length_fraction": length_fraction, "ambiguous_fraction": 0.0,
            "source": "manual",
        })
        self._recount_wave_summary()
        self.log("Fiber drawn by hand",
                 f"{len(fx)} points, labelled {self.manual_fiber_class.get()}",
                 status="edit")
        self.status.set(
            f"Hand-drawn fiber added as {self.manual_fiber_class.get()} "
            f"({self.waves['n_fibers']} fibers total). Nothing is written "
            "until you save.")
        self._update_wave_label()
        self._show_stage_waves()
        self._redraw()

    def cancel_manual_fiber(self):
        if self._manual_fiber_cid is not None:
            try:
                self.center_canvas.mpl_disconnect(self._manual_fiber_cid)
            except Exception:
                pass
            self._manual_fiber_cid = None
        self._manual_fiber_pts = []
        self._clear_live_artists()
        self._show_stage_waves()
        self._redraw()

    def _update_wave_label(self):
        if not self.waves:
            self.result_label.configure(text="")
            return
        w = self.waves
        n_manual = sum(1 for f in w.get("fibers", []) if f.get("source") == "manual")
        n_corrected = sum(1 for f in w.get("fibers", []) if f.get("corrected"))
        extra = ""
        if n_manual:
            extra += f"   {n_manual} hand-drawn"
        if n_corrected:
            extra += f"   {n_corrected} relabelled"
        self.result_label.configure(
            text=(f"Fibers: {w['n_fibers']}   wavy {w['n_affected']}   "
                  f"low-confidence {w['n_lowconf']}   straight "
                  f"{w['n_fibers'] - w['n_affected'] - w['n_lowconf']}   "
                  f"(width fraction {w['width_fraction']:.0%}){extra}"))

    # -- sarcomere detection ----------------------------------------------
    def _detect_sarcomeres(self):
        ax1, ay1, ax2, ay2 = self.line
        self.profile = mm.get_profile_band(self.image, ax1, ay1, ax2, ay2)
        if len(self.profile) < mm.MIN_PROFILE_N:
            self.status.set(
                f"Profile too short ({len(self.profile)} samples, need "
                f"{mm.MIN_PROFILE_N}+) - draw your own line or skip.")
            self.auto_ticks_px = np.array([])
            self._show_stage_line()
            self._redraw()
            return
        um_px = self.scale or 0.1
        peaks, period = mm.detect_band_peaks(self.profile, um_px=um_px)
        self.auto_ticks_px = peaks
        self.est_period_px = period
        self.min_spacing_px = max(2, round(0.6 * period))
        self.final_ticks_px = peaks.copy()
        self.sarc_mode = "AUTO"
        self._update_result_label()
        self._show_stage_review()
        self._redraw()
        # A detection that found no usable bands must SAY so. Previously this
        # went straight to the review panel ("review the automatic detection
        # (red ticks)") with no ticks drawn and no explanation, and Accept
        # would then happily save a sarc_mode=AUTO row with sarc_number=0 -
        # which reads in the CSV like a real measurement of zero sarcomeres
        # rather than a failed detection. Reported from real use as "the
        # second myocyte does not even show tick marks".
        if len(peaks) < 2:
            self.status.set(
                f"No usable sarcomere bands found on this line "
                f"({len(peaks)} peak(s) - at least 2 are needed for a "
                "spacing). This is a detection failure, not a measurement "
                "of zero: draw a different across-band line, count the "
                "bands manually, or skip sarcomeres for this cell.")
            messagebox.showwarning(
                "No sarcomere bands detected",
                f"The automatic detector found {len(peaks)} band(s) on this "
                "sampling line - not enough to measure a spacing.\n\n"
                "This usually means the line does not cross the striations "
                "squarely, or this part of the cell has no resolvable "
                "banding.\n\nUse 'Draw my own line', 'Manual: count from "
                "scratch', or 'Skip sarcomeres' rather than accepting this "
                "as a result.", parent=self)

    def _sarc_stats_from_ticks(self, ticks_px):
        um_px = self.scale or 0.1
        n, mean, sd, cv = mm.interval_stats(ticks_px, um_px)
        quality = mm.sarcomere_quality(n, cv) if n else "none"
        flag = mm.calibration_flag(mean)
        return {"n": len(ticks_px), "n_intervals": n, "mean": mean,
                "sd": sd, "cv": cv, "quality": quality, "calib_flag": flag}

    def _update_result_label(self):
        if self.final_ticks_px is None:
            self.result_label.configure(text="")
            return
        s = self._sarc_stats_from_ticks(self.final_ticks_px)
        self.result_label.configure(
            text=(f"Sarcomere number (bands): {s['n']}   length: "
                  f"{s['mean']:.3f} um ({s['n_intervals']} intervals)   "
                  f"sd {s['sd']:.3f}   cv {s['cv']:.3f}   "
                  f"quality {s['quality']}   calibration {s['calib_flag']}"))

    def accept_auto(self):
        self.final_ticks_px = self.auto_ticks_px.copy()
        self.sarc_mode = "AUTO"
        self._update_result_label()
        self._compute_waves_and_review()

    # -- edit / manual tick entry ----------------------------------------
    def _ticks_to_img_points(self, ticks_px):
        ax1, ay1, ax2, ay2 = self.line
        length = float(np.hypot(ax2 - ax1, ay2 - ay1))
        ux, uy = (ax2 - ax1) / max(length, 1e-9), (ay2 - ay1) / max(length, 1e-9)
        return [(ax1 + t * ux, ay1 + t * uy) for t in ticks_px]

    def _perpendicular_tick_segments(self, ticks_px, half_len=8.0):
        """(x1,y1,x2,y2) for a short segment through each tick position,
        perpendicular to the sampling line - in DATA coordinates, computed
        from the line's own direction, so it stays correctly perpendicular
        regardless of the line's angle in the image (matches the macro's
        own tx1,ty1,tx2,ty2 convention: tick length is a fixed pixel count,
        not scaled to zoom - use the mouse-wheel zoom to see it more
        precisely on a very zoomed-out view)."""
        ax1, ay1, ax2, ay2 = self.line
        length = float(np.hypot(ax2 - ax1, ay2 - ay1))
        ux, uy = (ax2 - ax1) / max(length, 1e-9), (ay2 - ay1) / max(length, 1e-9)
        perp_x, perp_y = -uy, ux
        segments = []
        for px, py in self._ticks_to_img_points(ticks_px):
            segments.append((px - half_len * perp_x, py - half_len * perp_y,
                             px + half_len * perp_x, py + half_len * perp_y))
        return segments

    def _img_points_to_ticks(self, points):
        ax1, ay1, ax2, ay2 = self.line
        length = float(np.hypot(ax2 - ax1, ay2 - ay1))
        ux, uy = (ax2 - ax1) / max(length, 1e-9), (ay2 - ay1) / max(length, 1e-9)
        ticks = [(px - ax1) * ux + (py - ay1) * uy for px, py in points]
        return np.array(sorted(ticks))

    def start_edit_ticks(self):
        self._edit_kind = "EDITED"
        self._edit_points_img = self._ticks_to_img_points(
            self.auto_ticks_px if self.auto_ticks_px is not None else [])
        self._start_point_editor()

    def start_manual_ticks(self, kind="MANUAL"):
        self._edit_kind = kind
        self._edit_points_img = []
        self._start_point_editor()

    def _start_point_editor(self):
        self._edit_drag_index = None
        self._edit_cids = [
            self.center_canvas.mpl_connect("button_press_event", self._edit_press),
            self.center_canvas.mpl_connect("motion_notify_event", self._edit_motion),
            self.center_canvas.mpl_connect("button_release_event", self._edit_release),
        ]
        self._show_stage_editing(self._edit_kind)
        self._redraw()
        self.status.set("Editing sarcomere ticks on the image below.")

    def _nearest_point_index(self, x, y, max_dist=None):
        if not self._edit_points_img:
            return None
        pts = np.array(self._edit_points_img)
        d = np.hypot(pts[:, 0] - x, pts[:, 1] - y)
        j = int(np.argmin(d))
        if max_dist is not None and d[j] > max_dist:
            return None
        return j

    def _edit_press(self, event):
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        x, y = float(event.xdata), float(event.ydata)
        radius = self._pick_radius()
        j = self._nearest_point_index(x, y, max_dist=radius)
        if event.button == 3:
            if j is not None:
                self._edit_points_img.pop(j)
                self._draw_live_edit_points()
            return
        if j is not None:
            self._edit_drag_index = j
        else:
            self._edit_points_img.append((x, y))
            self._draw_live_edit_points()

    def _edit_motion(self, event):
        if self._edit_drag_index is None:
            return
        if event.inaxes != self.center_ax or event.xdata is None:
            return
        self._edit_points_img[self._edit_drag_index] = (
            float(event.xdata), float(event.ydata))
        self._draw_live_edit_points()

    def _edit_release(self, event):
        self._edit_drag_index = None

    def finish_editing(self):
        for cid in self._edit_cids:
            try:
                self.center_canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._edit_cids = []
        self.final_ticks_px = self._img_points_to_ticks(self._edit_points_img)
        self.sarc_mode = self._edit_kind
        self._write_correction_log(self._edit_kind)
        self._update_result_label()
        if self._edit_kind == "MANUAL_RECOUNT":
            # A blind recount deliberately re-measures the SAME line for
            # validation; the macro does not run wave detection on those
            # rows either, so there is nothing to review here.
            self._show_stage_save()
            self._redraw()
        else:
            self._compute_waves_and_review()

    def _write_correction_log(self, correction_type):
        if self.profile is None or self.line is None:
            return
        try:
            log = corr.CorrectionLog()
            detector = corr.DetectorOutput(
                peak_positions_px=(self.auto_ticks_px
                                    if self.auto_ticks_px is not None else []),
                estimated_period_px=self.est_period_px or 0.0,
                min_spacing_px=self.min_spacing_px or 0.0,
                relative_bounds=(0.6 * (self.est_period_px or 0.0),
                                  1.5 * (self.est_period_px or 0.0)))
            human = corr.HumanCorrection(
                peak_positions_px=self.final_ticks_px, correction_type=correction_type)
            ax1, ay1, ax2, ay2 = self.line
            log.record(
                myocyte_id=self.pending_myocyte_id, worm_id=self.v["worm_id"].get(),
                genotype=self.v["genotype"].get(), day=self.v["day"].get(),
                region=self.v["region"].get(), raw_profile=self.profile,
                line_x1=ax1, line_y1=ay1, line_x2=ax2, line_y2=ay2,
                line_width_px=mm.BAND_WIDTH_PX, um_per_px=self.scale or 0.0,
                detector=detector, human=human,
                student_id=self.v["student_id"].get())
            self.log("Correction logged", correction_type, status="edit")
        except Exception as exc:
            self.status.set(f"Correction log write failed (row will still "
                             f"save): {exc}")

    # -- blind recount ----------------------------------------------
    def start_blind_recount(self):
        if self.last_myocyte is None:
            self.status.set("No previous myocyte to recount yet.")
            return
        self.image = self.last_myocyte["image"]
        self.line = self.last_myocyte["line"]
        self.boundary = self.last_myocyte["boundary"]
        self.profile = mm.get_profile_band(self.image, *self.line)
        um_px = self.scale or 0.1
        self.auto_ticks_px, self.est_period_px = mm.detect_band_peaks(
            self.profile, um_px=um_px)
        self.min_spacing_px = max(2, round(0.6 * self.est_period_px))
        self._blind_recount_active = True
        self.start_manual_ticks(kind="MANUAL_RECOUNT")
        self.status.set("Blind recount: click each band along the SAME line, "
                         "independently - the auto ticks are not shown.")

    # -- save ----------------------------------------------
    def save_myocyte(self):
        if self.image is None or self.boundary is None:
            self.status.set("Draw a boundary first.")
            return
        um_px = self.scale
        if not um_px:
            # A status-line message alone was too easy to miss here - the
            # button stays labeled "Save myocyte" and the panel doesn't
            # change, so clicking Save with no scale set looked exactly
            # like clicking Save did nothing at all (real report: "0
            # myocytes saved, no additional myocyte button in sight" -
            # nothing was wrong with the workflow, the scale was just never
            # calibrated for this session). This can't be missed the same way.
            messagebox.showwarning(
                "Scale not calibrated",
                "This myocyte cannot be saved yet: the scale (um/px) has "
                "not been calibrated for this session.\n\n"
                "Use 'Calibrate scale (um/px)...' in the controls panel, "
                "then Save again. Nothing has been lost - your boundary "
                "and ticks are still here.", parent=self)
            self.status.set("Calibrate the scale (um/px) first.")
            return
        # An AUTO/EDITED row with fewer than 2 bands is a failed detection,
        # not a measurement of zero sarcomeres - make the person say so
        # deliberately rather than letting it land in the CSV looking like
        # real data. "Skip sarcomeres" is the honest way to record a cell
        # whose banding could not be read (it writes sarc_mode="none").
        n_ticks = 0 if self.final_ticks_px is None else len(self.final_ticks_px)
        if self.sarc_mode != "none" and n_ticks < 2:
            proceed = messagebox.askyesno(
                "Save a cell with no measurable sarcomeres?",
                f"This cell has {n_ticks} detected band(s), so no sarcomere "
                f"spacing could be measured, but sarc_mode is "
                f"'{self.sarc_mode}'.\n\nSaving now writes sarc_number=0 and "
                "sarc_length_um=0, which is easy to mistake later for a real "
                "measurement of zero rather than a failed detection.\n\n"
                "Use 'Skip sarcomeres' instead to record this cell's geometry "
                "honestly without a sarcomere claim.\n\nSave anyway?",
                parent=self)
            if not proceed:
                self.status.set(
                    "Save cancelled. Use 'Skip sarcomeres' to record geometry "
                    "only, or count the bands manually.")
                return
        try:
            self._save_myocyte_unguarded(um_px)
        except Exception as exc:
            # Never fail silently mid-save: without this, an exception here
            # (e.g. a wave-detection edge case, a permissions error writing
            # the CSV) stopped execution before _reset_myocyte() ran, and
            # the person was left on the same "Save/Discard" panel with no
            # visible error and, from their side, no obvious way to start
            # the next myocyte - looked exactly like "no option to draw
            # another one." Nothing is lost: the boundary/ticks/state are
            # untouched, so Save can just be tried again after fixing
            # whatever's wrong (or Discard is still available).
            self.status.set(f"Save failed, nothing was written: {exc}. "
                            "Your boundary and ticks are still here - fix "
                            "the issue and try Save again, or Discard.")
            self.log("Save failed", str(exc), status="error")

    def _save_myocyte_unguarded(self, um_px):
        geo = mm.boundary_measurements(self.boundary)
        blind = bool(self.v["blind"].get())
        genotype_txt = "BLINDED" if blind else self.v["genotype"].get()

        is_recount = getattr(self, "_blind_recount_active", False)
        sarc_mode = "MANUAL_RECOUNT" if is_recount else self.sarc_mode
        sarc_quality = "MANUAL_RECOUNT" if is_recount else None

        if self.final_ticks_px is not None and len(self.final_ticks_px) > 0:
            s = self._sarc_stats_from_ticks(self.final_ticks_px)
            sarc_n = s["n"]; sarc_mean = s["mean"]; sarc_sd = s["sd"]
            sarc_cv = s["cv"]; calib_flag = s["calib_flag"]
            if sarc_quality is None:
                sarc_quality = s["quality"]
        else:
            sarc_n = 0; sarc_mean = 0.0; sarc_sd = 0.0; sarc_cv = 0.0
            calib_flag = "n/a"
            if sarc_quality is None:
                sarc_quality = "none"

        area_um2 = geo["area_px2"] * um_px ** 2
        perim_um = geo["perimeter_px"] * um_px
        feret_um = geo["feret_px"] * um_px
        minferet_um = geo["minferet_px"] * um_px
        sdens = sarc_n / area_um2 if area_um2 > 0 else 0.0
        serial = sarc_n / feret_um if feret_um > 0 else 0.0

        filament_length_um = 0.0
        waves = {"n_fibers": 0, "n_affected": 0, "n_lowconf": 0,
                 "width_fraction": 0.0, "length_frac_mean": 0.0,
                 "length_frac_max": 0.0}
        if self.line is not None and sarc_mode != "none" and sarc_n > 0:
            ax1, ay1, ax2, ay2 = self.line
            length_line = float(np.hypot(ax2 - ax1, ay2 - ay1))
            nux, nuy = (ax2 - ax1) / max(length_line, 1e-9), (ay2 - ay1) / max(length_line, 1e-9)
            mux, muy = -nuy, nux
            ccx = float(self.boundary[:, 0].min() + self.boundary[:, 0].max()) / 2
            ccy = float(self.boundary[:, 1].min() + self.boundary[:, 1].max()) / 2
            filament_length_um = _along_axis_extent(
                self.boundary, self.image.shape, ccx, ccy, mux, muy) * um_px
            # Use the fibers the person actually reviewed (and possibly
            # relabelled, deleted, or hand-drew) rather than re-running
            # detection here. Wave detection used to happen at THIS point,
            # which is why fiber traces only ever appeared after a myocyte
            # was already committed - no preview, no correction. It now runs
            # at review time; see _compute_waves_and_review().
            if self.waves is not None:
                waves = self.waves

        sarc_series = filament_length_um / sarc_mean if sarc_mean > 0 else 0.0
        content_proxy = sarc_n * sarc_series

        myocyte_id = self.pending_myocyte_id
        myo_number_sel = self.v["myo_number"].get()
        region = self.v["region"].get()
        label = region
        if myo_number_sel not in ("unknown", "other"):
            n = int(myo_number_sel)
            region = mm.region_from_myo_number(n, self.v["region"].get())
            label = f"Myo{n:02d}"
            self.last_myo_number = n
        roi_name = f"{self.v['worm_id'].get()}_{label}_m{myocyte_id}"
        linked_id = (self.last_myocyte["myocyte_id"]
                     if is_recount and self.last_myocyte else "")

        row = {
            "myocyte_id": myocyte_id, "worm_id": self.v["worm_id"].get(),
            "genotype": genotype_txt, "day": self.v["day"].get(), "region": region,
            "myocyte_number": myo_number_sel, "um_px": round(um_px, 5),
            "area_um2": round(area_um2, 4), "perimeter_um": round(perim_um, 4),
            "feret_um": round(feret_um, 4), "minferet_um": round(minferet_um, 4),
            "major_um": round(geo["major_px"] * um_px, 4),
            "minor_um": round(geo["minor_px"] * um_px, 4),
            "aspect_ratio": round(geo["aspect_ratio"], 4),
            "circularity": round(geo["circularity"], 4),
            "solidity": round(geo["solidity"], 4),
            "anisotropy": round(geo["anisotropy"], 4),
            "sarc_number": sarc_n, "sarc_length_um": round(sarc_mean, 4),
            "sarc_sd_um": round(sarc_sd, 4), "sarc_cv": round(sarc_cv, 4),
            "sarc_mode": sarc_mode, "sarc_quality": sarc_quality,
            "calib_flag": calib_flag,
            "sarc_density_per_um2": round(sdens, 6),
            "serial_density_per_um": round(serial, 6),
            "filament_length_um": round(filament_length_um, 4),
            "sarc_parallel_proxy": sarc_n, "sarc_series_proxy": round(sarc_series, 3),
            "contractile_content_proxy": round(content_proxy, 2),
            "feret_angle_deg": round(geo["feret_angle_deg"], 2),
            "roi_name": roi_name, "blind": blind,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "image_title": Path(self.v["source"].get()).name,
            "linked_myocyte_id": linked_id,
            "wave_n_fibers": waves["n_fibers"], "wave_n_affected": waves["n_affected"],
            "wave_n_lowconf": waves["n_lowconf"],
            "wave_width_fraction": round(waves["width_fraction"], 4),
            "wave_length_frac_mean": round(waves["length_frac_mean"], 4),
            "wave_length_frac_max": round(waves["length_frac_max"], 4),
            # Provenance for the fiber set actually saved: how many bands
            # seeded a trace, how many fibers were hand-drawn, how many had
            # their straight/wavy call corrected by a person, and the link
            # distance the tracing actually used (retry changes it).
            "wave_n_seeded": waves.get("n_seeded", waves["n_fibers"]),
            "wave_n_manual": sum(1 for f in waves.get("fibers", [])
                                 if f.get("source") == "manual"),
            "wave_n_relabelled": sum(1 for f in waves.get("fibers", [])
                                     if f.get("corrected")),
            "wave_link_um": self.wave_link_um,
        }
        self._append_csv_row(row)
        self.myo_counter = myocyte_id

        self.last_myocyte = {
            "myocyte_id": myocyte_id, "image": self.image,
            "line": self.line, "boundary": self.boundary,
        }
        wave_label = (f" wavy={waves['n_affected']}/{waves['n_fibers']}"
                      if waves["n_fibers"] > 0 else "")
        id_label = label if myo_number_sel not in ("unknown", "other") else f"m{myocyte_id}"
        self.completed_myocytes.append({
            "boundary": self.boundary.tolist(),
            "label": f"{id_label} n={sarc_n}{wave_label}",
            # Colored fiber traces (red=wavy, blue=straight, yellow=low-
            # confidence), same convention as the macro's own overlay - see
            # _redraw()'s persistent-overlay loop. This is view-only: there
            # is no way yet to click a fiber and correct its classification
            # (the macro's interactive wave-review dialog is not ported),
            # only to see what the automatic classifier decided.
            "fibers": [{"x": list(f["x"]), "y": list(f["y"]), "class": f["class"]}
                      for f in waves.get("fibers", [])],
        })
        if waves["n_fibers"] > 0:
            self.log("Wave detection",
                    f"{waves['n_fibers']} fibers: {waves['n_affected']} wavy, "
                    f"{waves['n_lowconf']} low-confidence, "
                    f"width fraction {waves['width_fraction']:.0%}",
                    status="ok")
        self._save_session_state()
        self.counter_label.configure(
            text=f"{self.myo_counter} myocyte row(s) saved this session.")
        self.log("Myocyte saved", roi_name, status="ok")
        self.status.set(f"Saved myocyte {myocyte_id} ({sarc_mode}, "
                         f"n={sarc_n}). Draw the next boundary.")
        self._reset_myocyte(keep_image=True)
        self._redraw()

    def _append_csv_row(self, row):
        if self.csv_path is None:
            out_dir = Path(self.v["source"].get()).parent if self.v["source"].get() \
                else Path.cwd()
            fname = (f"myocyte_morphometry_"
                     f"{'BLINDED' if row['blind'] else self.v['genotype'].get()}_"
                     f"day{self.v['day'].get()}_{self.v['region'].get()}_"
                     f"{self.v['worm_id'].get()}_"
                     f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
            self.csv_path = out_dir / fname
        is_new = not self.csv_path.exists()
        with self.csv_path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            if is_new:
                writer.writeheader()
            writer.writerow(row)

    # -- reset / redraw ----------------------------------------------
    def _reset_myocyte(self, keep_image=False):
        self.pending_myocyte_id = self.myo_counter + 1
        self.boundary = None
        self.normal_angle = None
        self.line = None
        self.profile = None
        self.auto_ticks_px = None
        self.final_ticks_px = None
        self.sarc_mode = "none"
        self._boundary_pts = []
        self._edit_points_img = []
        self._blind_recount_active = False
        self.waves = None
        self._manual_fiber_pts = []
        self._extend_target = None
        for _cid_attr in ("_fiber_cid", "_cut_cid", "_extend_cid", "_manual_fiber_cid"):
            _cid = getattr(self, _cid_attr, None)
            if _cid is not None:
                try:
                    self.center_canvas.mpl_disconnect(_cid)
                except Exception:
                    pass
                setattr(self, _cid_attr, None)
        # Real bug: zooming in to place ticks precisely on myocyte N (the
        # exact workflow the zoom feature exists for) left _zoom_active=True
        # with the OLD, zoomed-in xlim/ylim. _redraw() then kept forcing
        # every subsequent view - including myocyte N+1's, drawn at a
        # completely different image location - back to that stale zoomed
        # region. The next myocyte's boundary/line/ticks were set correctly
        # in the data, just rendered entirely off-screen: "ticks showed up"
        # (whatever WAS in the old zoomed view) "but couldn't edit them"
        # (clicks landed nowhere near the real, off-screen ones). Each
        # myocyte starts from a fresh full-image view; zoom back in as
        # needed for that one.
        self._zoom_active = False
        self.result_label.configure(text="")
        # Suggest the next myocyte number along the body wall (matches the
        # macro's own pickMyoNumber() behavior: only auto-advances within
        # 1-23, leaves "unknown"/"other" alone so a skipped/unidentifiable
        # cell doesn't silently drag the count forward).
        if self.last_myo_number is not None and 1 <= self.last_myo_number < 24:
            self.v["myo_number"].set(str(self.last_myo_number + 1))
        self._show_stage_boundary()
        if not keep_image:
            self.image = None

    def _redraw(self):
        # Preserve the current zoom across a full rebuild - clear() resets
        # axis limits, and without this every stage transition (accepting a
        # line, finishing tick edits, saving) would silently snap a zoomed-in
        # view back out to the full image, right when the person is looking
        # closely at a fiber.
        zoom_xlim = self.center_ax.get_xlim() if self._zoom_active else None
        zoom_ylim = self.center_ax.get_ylim() if self._zoom_active else None
        self.center_ax.clear()
        self.center_ax.set_axis_off()
        self._live_artists = []   # clear() already destroyed these artists
        if self.image is None:
            self.center_ax.text(0.5, 0.5, "Choose a source image; it appears here.",
                                ha="center", va="center", fontsize=10, color="#888888")
            self.center_canvas.draw()
            return
        vmin, vmax = self.display_vmin.get(), self.display_vmax.get()
        if vmax <= vmin:
            vmax = vmin + 1.0
        self.center_ax.imshow(self.image, cmap="gray", vmin=vmin, vmax=vmax)
        # Persistent overlay of every myocyte already saved THIS session, so
        # a student can see what they've worked on at a glance - the macro's
        # own ImageJ session kept exactly this kind of running overlay.
        wave_colors = {0: "#3fa8ff", 1: "#ff4444", 2: "#ffcc00"}  # straight/wavy/low-confidence
        for done in self.completed_myocytes:
            poly = np.array(done["boundary"])
            poly = np.vstack([poly, poly[:1]])
            self.center_ax.plot(poly[:, 0], poly[:, 1], "-", color="#33cc33", lw=1.2, alpha=0.85)
            cx, cy = poly[:-1, 0].mean(), poly[:-1, 1].mean()
            self.center_ax.text(cx, cy, done["label"], color="#33cc33",
                                fontsize=8, ha="center", va="center",
                                bbox=dict(boxstyle="round", fc="black", alpha=0.5, ec="none"))
            for fiber in done.get("fibers", []):
                self.center_ax.plot(fiber["x"], fiber["y"], "-",
                                    color=wave_colors.get(fiber["class"], "#888888"),
                                    lw=0.9, alpha=0.8)
        # Fibers for the myocyte IN PROGRESS - drawn thicker than the saved
        # ones above so the cell being reviewed reads as the active one.
        # Hand-drawn fibers get a dashed style so a corrected/added trace is
        # visually distinguishable from an automatic one.
        if self.waves:
            for fiber in self.waves.get("fibers", []):
                self.center_ax.plot(
                    fiber["x"], fiber["y"],
                    "--" if fiber.get("source") == "manual" else "-",
                    color=wave_colors.get(fiber["class"], "#888888"),
                    lw=1.8, alpha=0.95)
        self._add_live_boundary_artist()
        if self.boundary is not None:
            poly = np.vstack([self.boundary, self.boundary[:1]])
            self.center_ax.plot(poly[:, 0], poly[:, 1], "-", color="#00ff66", lw=1.6)
        if self.line is not None:
            ax1, ay1, ax2, ay2 = self.line
            self.center_ax.plot([ax1, ax2], [ay1, ay2], "-", color="cyan", lw=1.5)
        if self._edit_cids:
            self._add_live_edit_artist()
        elif self.final_ticks_px is not None and self.line is not None and len(self.final_ticks_px):
            # Real segments perpendicular to the sampling line in DATA
            # coordinates, not a "|" marker - a marker glyph is always
            # drawn vertical in SCREEN space regardless of the line's
            # actual angle, so on any oblique sampling line the ticks
            # looked crooked relative to it instead of crossing it
            # squarely, making it hard to check placement against the
            # bands (matches the macro's own tx1,ty1,tx2,ty2 perpendicular-
            # segment convention, not a plot marker).
            for tx1, ty1, tx2, ty2 in self._perpendicular_tick_segments(self.final_ticks_px):
                self.center_ax.plot([tx1, tx2], [ty1, ty2], "-", color="red", lw=2)
        if zoom_xlim is not None:
            self.center_ax.set_xlim(zoom_xlim)
            self.center_ax.set_ylim(zoom_ylim)
        self.center_canvas.draw()


def _boundary_path(boundary):
    from matplotlib.path import Path as MplPath
    path = MplPath(np.asarray(boundary, dtype=float))
    return lambda x, y: bool(path.contains_point((x, y)))


def _along_axis_extent(boundary, image_shape, cx, cy, mux, muy):
    """In-cell extent along (mux, muy) through (cx, cy), px. Mirrors the
    macro's filLen march (Roi.contains walk in each direction)."""
    contains = _boundary_path(boundary)
    h, w = image_shape
    max_reach = 3 * max(h, w)
    fr = 0
    while fr < max_reach and contains(cx + fr * mux, cy + fr * muy):
        fr += 1
    fl = 0
    while fl < max_reach and contains(cx - fl * mux, cy - fl * muy):
        fl += 1
    return float(fr + fl)


if __name__ == "__main__":
    App().mainloop()
