"""Orthogonal slice viewer for marking neurites - Tkinter, no Qt, no GPU.

This is the ANNOTATION half of the split described in tools/neurite_annotation.
It produces a sidecar of marked points and nothing else. Tracing, measuring
and export are separate and headless, so they run on any station.

WHY TKINTER RATHER THAN NAPARI
-------------------------------
Napari would render this stack faster, but it drags Qt onto every machine
that ever opens a confocal file. Since the marking work is judged slice by
slice - "is the neurite in THIS plane or the next one" - a volume renderer
buys little, and the two things that actually decide usability are handled
here explicitly rather than hoped for:

1. REDRAW COST. One XY plane of the lab's Leica stack is 8,153,184 pixels.
   Two defences: everything is drawn from a decimated DisplayTexture (16x
   fewer pixels per redraw on that stack), and redraws are BLITTED - the
   axes, frames and labels are rendered once and cached, so moving the
   crosshair repaints only the crosshair. Clicks map back to full-resolution
   voxels, so the display gets cheaper without the data getting coarser.

2. XZ / YZ ASPECT. Measured on the real stack: at true physical proportions
   a z plane is 0.35 screen pixels tall. Not "thin" - unclickable. So z is
   stretched for display by a factor computed from how thick a plane must be
   to hit (about 12x here), and every stretched panel carries a caption
   saying so. Position may be judged from those panels; shape may not.

LAYOUT
------
XY on top, and the two depth views as strips beneath it rather than the
usual XZ-below / YZ-right arrangement. Both strips are then (Z, lateral),
so they share one stretch factor and one click convention - the arrangement
that removes the classic ortho-viewer bug where the YZ panel is transposed
relative to the others and clicking it moves the wrong axis.
"""
from __future__ import annotations

from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

_HERE = Path(__file__).resolve().parent
for _p in (str(_HERE), str(_HERE.parent / "app")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import confocal_loader as cl               # noqa: E402
import neurite_annotation as na            # noqa: E402
import neurite_viewer_core as vc           # noqa: E402
from process_ui import CockpitApp          # noqa: E402

NOMINAL_PANEL_PX = 760          # used to size the z stretch before first draw
NEAR_Z_PLANES = 1               # how far a marked point still counts as "here"
LOW_PERCENTILE = 2.0
# Deliberately close to the top: see the note on the upper contrast slider.
HIGH_PERCENTILE = 99.9


class NeuriteViewer(CockpitApp):
    """Mark start, end and correction anchors on a confocal stack."""

    def __init__(self):
        super().__init__("WINK - Neurite Annotation Viewer",
                         geometry="1240x900",
                         controls_label="Stack and marking",
                         hood_label="Hood: process and notes")
        self.stack = None
        self.series = []
        self.series_index = 0
        self.channel = 0
        self.texture = None
        self.aspect = None
        self.volume = None
        self.point = (0, 0, 0)              # crosshair, FULL-resolution (z,y,x)
        self.current_points = []            # points of the neurite being marked
        self.annotations = []               # finished NeuriteAnnotation objects
        self._display_range = (0.0, 1.0)
        self._static_bg = None
        self._slice_bg = None
        self._in_scale_callback = False     # Windows Tk fires Scale re-entrantly
        self._build_controls()
        self._build_canvas()
        self._set_help_for("start")
        self.set_status("Open a confocal stack to begin.")

    # ------------------------------------------------------------------ UI
    def _build_controls(self):
        c = self.controls
        ttk.Button(c, text="Open stack...", command=self._open).pack(
            fill="x", pady=(0, 6))

        ttk.Label(c, text="series").pack(anchor="w")
        self.series_var = tk.StringVar()
        self.series_box = ttk.Combobox(c, textvariable=self.series_var,
                                       state="readonly", width=30)
        self.series_box.pack(fill="x")
        self.series_box.bind("<<ComboboxSelected>>", lambda _e: self._load_series())

        ttk.Label(c, text="channel").pack(anchor="w", pady=(6, 0))
        self.channel_var = tk.StringVar()
        self.channel_box = ttk.Combobox(c, textvariable=self.channel_var,
                                        state="readonly", width=10)
        self.channel_box.pack(fill="x")
        self.channel_box.bind("<<ComboboxSelected>>", lambda _e: self._set_channel())

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=8)

        # z stays open - it is the control in constant use. Brightness folds
        # away, so the marking buttons stay reachable without scrolling.
        nav = self.add_control_section("View")
        ttk.Label(nav, text="z plane").pack(anchor="w")
        self.z_var = tk.IntVar(value=0)
        self.z_scale = ttk.Scale(nav, from_=0, to=0, orient="horizontal",
                                 command=self._on_z_scale)
        self.z_scale.pack(fill="x")
        self.z_label = ttk.Label(nav, text="-")
        self.z_label.pack(anchor="w")
        ttk.Label(nav, wraplength=210, justify="left", foreground="#555555",
                  text="Scroll over the XY panel to zoom; the depth strips "
                       "follow it. Left/Right arrows step one plane.").pack(
            fill="x", pady=(4, 0))

        c2 = self.add_control_section("Brightness/contrast", collapsed=True)
        ttk.Label(c2, text="display range (percentile)").pack(anchor="w")
        self.lo_var = tk.DoubleVar(value=LOW_PERCENTILE)
        self.hi_var = tk.DoubleVar(value=HIGH_PERCENTILE)
        self.lo_scale = ttk.Scale(c2, from_=0, to=20, orient="horizontal",
                                  variable=self.lo_var,
                                  command=lambda _v: self._on_contrast())
        self.lo_scale.pack(fill="x")
        # The upper slider spans 99-100, not 80-100. A neurite is a thin
        # bright thread in a large dark volume: it can be well under 0.3% of
        # the voxels, so a 99.7% ceiling sits inside the background noise and
        # the structure washes out. The useful range is all in the last
        # percent, and a coarse slider cannot reach it.
        self.hi_scale = ttk.Scale(c2, from_=99.0, to=100.0, orient="horizontal",
                                  variable=self.hi_var,
                                  command=lambda _v: self._on_contrast())
        self.hi_scale.pack(fill="x")
        self.contrast_label = ttk.Label(c2, text="-", wraplength=210)
        self.contrast_label.pack(anchor="w")

        ttk.Label(c, text="neurite id").pack(anchor="w")
        self.id_var = tk.StringVar(value="n1")
        ttk.Entry(c, textvariable=self.id_var, width=16).pack(fill="x")
        ttk.Label(c, text="label (optional)").pack(anchor="w", pady=(4, 0))
        self.label_var = tk.StringVar(value="")
        ttk.Entry(c, textvariable=self.label_var, width=16).pack(fill="x")
        ttk.Label(c, text="annotator").pack(anchor="w", pady=(4, 0))
        self.annotator_var = tk.StringVar(value="")
        ttk.Entry(c, textvariable=self.annotator_var, width=16).pack(fill="x")

        ttk.Button(c, text="add point at crosshair  (a)",
                   command=self._add_point).pack(fill="x", pady=(8, 2))
        ttk.Button(c, text="undo last point  (z)",
                   command=self._undo_point).pack(fill="x", pady=2)
        ttk.Button(c, text="finish this neurite",
                   command=self._finish_neurite).pack(fill="x", pady=2)
        self.points_label = ttk.Label(c, text="0 points", wraplength=240)
        self.points_label.pack(anchor="w", pady=(4, 0))

        ttk.Separator(c, orient="horizontal").pack(fill="x", pady=8)
        ttk.Button(c, text="save annotation sidecar",
                   command=self._save).pack(fill="x", pady=2)
        ttk.Button(c, text="trace now (headless check)",
                   command=self._trace_now).pack(fill="x", pady=2)
        self.saved_label = ttk.Label(c, text="0 neurites marked", wraplength=240)
        self.saved_label.pack(anchor="w", pady=(4, 0))

        self.bind("<a>", lambda _e: self._add_point())
        self.bind("<A>", lambda _e: self._add_point())
        self.bind("<z>", lambda _e: self._undo_point())
        self.bind("<Z>", lambda _e: self._undo_point())
        self.bind("<Left>", lambda _e: self._step_z(-1))
        self.bind("<Right>", lambda _e: self._step_z(1))

    def _build_canvas(self):
        self.fig = Figure(figsize=(8.6, 8.4), dpi=100)
        self._make_axes()
        self.canvas = FigureCanvasTkAgg(self.fig, master=self.center)
        self.canvas.get_tk_widget().pack(fill="both", expand=True)
        self.canvas.mpl_connect("draw_event", self._on_draw)
        self.canvas.mpl_connect("button_press_event", self._on_click)
        self.canvas.mpl_connect("scroll_event", self._on_scroll)
        self._images = {}
        self._overlays = {}

    def _make_axes(self, ratios=(4, 1, 1)):
        """Lay the three panels out, sized to the images they will hold.

        The row heights have to come from the data: a fixed split leaves the
        XY panel floating in an oversized box while the depth strips - the
        ones that were already hard to click - get squeezed. Every panel is
        drawn at the same lateral scale, so the heights follow directly.
        """
        self.fig.clear()
        gs = self.fig.add_gridspec(3, 1, height_ratios=list(ratios), hspace=0.32,
                                   left=0.04, right=0.99, top=0.95, bottom=0.03)
        self.ax_xy = self.fig.add_subplot(gs[0])
        self.ax_xz = self.fig.add_subplot(gs[1])
        self.ax_yz = self.fig.add_subplot(gs[2])
        for ax, name in ((self.ax_xy, "XY"), (self.ax_xz, "XZ (depth vs x)"),
                         (self.ax_yz, "YZ (depth vs y)")):
            ax.set_title(name, fontsize=9)
            ax.set_xticks([])
            ax.set_yticks([])

    def _panel_height_ratios(self):
        """How tall each panel needs to be, in units of one shared width.

        All three are measured against the SAME width (the XY panel's), which
        is what keeps a feature the same size in x across panels instead of
        each row silently rescaling itself.
        """
        n_z, n_disp_y, n_disp_x = self.texture.shape
        width = float(n_disp_x)
        return (max(0.12, n_disp_y / width),
                max(0.06, n_z * self.aspect.aspect / width),
                max(0.06, n_z * self.aspect_yz.aspect / width))

    # -------------------------------------------------------------- loading
    def _open(self):
        # parent=self, the toplevel - without it the dialog opens BEHIND the
        # cockpit on Windows. (Parenting to an embedded frame is the thing to
        # avoid: that grabs focus and never gives it back.)
        path = filedialog.askopenfilename(
            parent=self, title="Open a confocal stack",
            filetypes=[("Confocal stacks", "*.lif *.czi *.nd2 *.tif *.tiff"),
                       ("All files", "*.*")])
        if not path:
            return
        self.load_path(path)

    def load_path(self, path):
        """Open a stack by path. Separate from the file dialog so the whole
        load-and-draw path can be exercised without a dialog in the way."""
        self.path = Path(path)
        with self.process_log.timed("List series", self.path.name):
            self.series = cl.list_series(self.path)
        self.series_box["values"] = [s.describe() for s in self.series]
        self.series_box.current(0)
        self.refresh_hood()
        self._load_series()

    def _load_series(self):
        idx = max(0, self.series_box.current())
        info = self.series[idx]
        self.series_index = info.index
        with self.process_log.timed("Load stack", info.name):
            self.stack = cl.load_stack(self.path, series=info.index,
                                       require_calibration=False)
        for note in self.stack.preflight_warnings():
            self.log("Preflight", note, status="warn")
        if self.stack.voxel_size_um is None:
            self.log("Uncalibrated", "No voxel size in the file. Marks can "
                     "still be made, but nothing traced from them will have a "
                     "physical length.", status="warn")
        self.channel_box["values"] = [str(i) for i in range(self.stack.n_channels)]
        self.channel_box.current(0)
        self._set_channel()

    def _set_channel(self):
        self.channel = max(0, self.channel_box.current())
        self.volume = self.stack.channel(self.channel)
        with self.process_log.timed("Build display texture"):
            self.texture = vc.DisplayTexture(self.volume)
        self.log("Display texture", self.texture.describe())

        vox = self.stack.voxel_size_um or (1.0, 1.0, 1.0)
        dz, dy, dx = vox
        # Aspect is computed in DISPLAY units: one drawn column spans
        # `step` full-resolution voxels, so the lateral size seen by the
        # panel is dx * step, not dx.
        n_z, n_disp_y, n_disp_x = self.texture.shape
        lat_x = dx * self.texture.step
        lat_y = dy * self.texture.step
        # ONE stretch for both depth strips, taken from whichever needs more.
        # The panels are shown together and read against each other, so two
        # different z scales would mean a feature that looks deeper in one
        # panel than the other - the two disagreeing about the same axis.
        stretch = max(
            vc.auto_z_stretch(n_z, dz, lat_x, n_disp_x, NOMINAL_PANEL_PX),
            vc.auto_z_stretch(n_z, dz, lat_y, n_disp_y, NOMINAL_PANEL_PX))
        self.aspect = vc.ortho_aspect(n_z, dz, lat_x, n_disp_x,
                                      NOMINAL_PANEL_PX, z_stretch=stretch)
        self.aspect_yz = vc.ortho_aspect(n_z, dz, lat_y, n_disp_y,
                                         NOMINAL_PANEL_PX, z_stretch=stretch)
        if not self.aspect.physically_true:
            self.log("Depth panels stretched",
                     f"z x{stretch:.1f} on BOTH strips so a plane is "
                     f"{vc.MIN_SCREEN_PX_PER_PLANE:.0f} screen px and can be "
                     f"clicked. Judge position from those panels, not shape.",
                     status="warn")

        self.z_scale.configure(from_=0, to=max(0, n_z - 1))
        self.point = (n_z // 2, self.volume.shape[1] // 2, self.volume.shape[2] // 2)
        self.z_var.set(self.point[0])
        self.z_scale.set(self.point[0])
        self.z_label.configure(text=f"z {self.point[0]} of {n_z - 1}")
        self.current_points = []
        self.annotations = []
        self._recompute_contrast()
        self._build_artists()
        self._set_help_for("mark")
        self.set_status(
            f"{self.path.name} series {self.series_index} channel {self.channel} - "
            f"click to move the crosshair, 'a' to add a point.")

    def _recompute_contrast(self):
        lo_p = float(self.lo_var.get())
        hi_p = float(self.hi_var.get())
        if hi_p <= lo_p:
            hi_p = min(100.0, lo_p + 0.5)
        # Percentiles come from the DECIMATED texture, not the full volume:
        # on an 8-megapixel-per-plane stack the full percentile is slow enough
        # to stall the slider, and the decimated sample gives the same answer
        # to well within a display level.
        sample = self.texture._small
        lo, hi = np.percentile(sample, [lo_p, hi_p])
        if hi <= lo:
            hi = lo + 1.0
        self._display_range = (float(lo), float(hi))
        # Show the ceiling against the brightest voxel in the stack. On sparse
        # data those two numbers are far apart, and seeing that is what tells
        # a student the structure is being clipped away rather than absent.
        peak = float(sample.max())
        self.contrast_label.configure(
            text=f"{lo_p:.1f}-{hi_p:.2f}%  ->  {lo:.0f}-{hi:.0f}"
                 f"   (brightest voxel {peak:.0f})")

    # ------------------------------------------------------------- drawing
    def _build_artists(self):
        """Create the artists once. Everything after this is set_data + blit."""
        self._make_axes(self._panel_height_ratios())
        z, y, x = self.point
        lo, hi = self._display_range

        self._images["xy"] = self.ax_xy.imshow(
            self.texture.xy_slice(z), cmap="gray", vmin=lo, vmax=hi,
            interpolation="nearest", animated=True)
        self._images["xz"] = self.ax_xz.imshow(
            self.texture.xz_slice(y), cmap="gray", vmin=lo, vmax=hi,
            interpolation="nearest", aspect=self.aspect.aspect, animated=True)
        self._images["yz"] = self.ax_yz.imshow(
            self.texture.yz_slice(x), cmap="gray", vmin=lo, vmax=hi,
            interpolation="nearest", aspect=self.aspect_yz.aspect, animated=True)

        self.ax_xy.set_title("XY", fontsize=9)
        # The caption is mandatory, not decorative: a stretched panel that
        # does not say so invites shape to be read off a distorted picture.
        self.ax_xz.set_title(f"XZ (depth vs x)   -   {self.aspect.label()}",
                             fontsize=9)
        self.ax_yz.set_title(f"YZ (depth vs y)   -   {self.aspect_yz.label()}",
                             fontsize=9)

        self._overlays = {}
        for key, ax in (("xy", self.ax_xy), ("xz", self.ax_xz), ("yz", self.ax_yz)):
            vline = ax.axvline(0, color="#4fc3f7", lw=0.8, animated=True)
            hline = ax.axhline(0, color="#4fc3f7", lw=0.8, animated=True)
            marked, = ax.plot([], [], "o", ms=5, mfc="none", mec="#ffb300",
                              mew=1.2, animated=True)
            near, = ax.plot([], [], "o", ms=6, mfc="#ff5252", mec="white",
                            mew=0.8, animated=True)
            done, = ax.plot([], [], "-", color="#69f0ae", lw=1.0, alpha=0.8,
                            animated=True)
            self._overlays[key] = (vline, hline, marked, near, done)

        self._static_bg = None
        self._slice_bg = None
        self.canvas.draw()

    def _on_draw(self, _event):
        """Re-cache the static background whenever matplotlib does a full draw.

        Animated artists are skipped by canvas.draw(), so what gets cached
        here is exactly the expensive-but-unchanging part: frames, titles and
        the caption. Everything else is blitted on top.
        """
        if not self._images:
            return
        self._static_bg = self.canvas.copy_from_bbox(self.fig.bbox)
        self._slice_bg = None
        self._blit_slices()

    def _blit_slices(self):
        """Slice indices changed -> repaint the three images, then cache them."""
        if self._static_bg is None or not self._images:
            return
        z, y, x = self.point
        self._images["xy"].set_data(self.texture.xy_slice(z))
        self._images["xz"].set_data(self.texture.xz_slice(y))
        self._images["yz"].set_data(self.texture.yz_slice(x))
        lo, hi = self._display_range
        for im in self._images.values():
            im.set_clim(lo, hi)
        self.canvas.restore_region(self._static_bg)
        for key, ax in (("xy", self.ax_xy), ("xz", self.ax_xz), ("yz", self.ax_yz)):
            ax.draw_artist(self._images[key])
        self.canvas.blit(self.fig.bbox)
        # Cache the result WITH the images in it, so a crosshair move that
        # does not change any slice repaints only the crosshair.
        self._slice_bg = self.canvas.copy_from_bbox(self.fig.bbox)
        self._blit_overlays()

    def _blit_overlays(self):
        """Only the crosshair or the marked points moved - cheapest path."""
        if self._slice_bg is None:
            self._blit_slices()
            return
        z, y, x = self.point
        pos = vc.crosshair_positions(self.point, self.texture)
        self.canvas.restore_region(self._slice_bg)
        for key, ax in (("xy", self.ax_xy), ("xz", self.ax_xz), ("yz", self.ax_yz)):
            vline, hline, marked, near, done = self._overlays[key]
            col, row = pos[key]
            vline.set_xdata([col, col])
            hline.set_ydata([row, row])
            mx, my, nx_, ny_ = self._point_markers(key)
            marked.set_data(mx, my)
            near.set_data(nx_, ny_)
            dx_, dy_ = self._finished_paths(key)
            done.set_data(dx_, dy_)
            for artist in (self._images[key], vline, hline, marked, near, done):
                ax.draw_artist(artist)
        self.canvas.blit(self.fig.bbox)

    def _point_markers(self, panel):
        """Points of the neurite being marked, split into near and far.

        A point two planes away is drawn hollow: in a stack this anisotropic
        it is genuinely somewhere else, and drawing it solid would suggest the
        neurite passes through the plane on screen when it does not.
        """
        far_x, far_y, near_x, near_y = [], [], [], []
        z_now = self.point[0]
        for (pz, py, px) in self.current_points:
            dy_, dx_ = self.texture.to_display(py, px)
            if panel == "xy":
                cx, cy = dx_, dy_
                is_near = abs(pz - z_now) <= NEAR_Z_PLANES
            elif panel == "xz":
                cx, cy = dx_, pz
                is_near = abs(py - self.point[1]) <= self.texture.step
            else:
                cx, cy = dy_, pz
                is_near = abs(px - self.point[2]) <= self.texture.step
            (near_x if is_near else far_x).append(cx)
            (near_y if is_near else far_y).append(cy)
        return far_x, far_y, near_x, near_y

    def _finished_paths(self, panel):
        """Already-finished neurites, drawn as connected polylines."""
        xs, ys = [], []
        for ann in self.annotations:
            for (pz, py, px) in ann.points_zyx:
                dy_, dx_ = self.texture.to_display(py, px)
                if panel == "xy":
                    xs.append(dx_); ys.append(dy_)
                elif panel == "xz":
                    xs.append(dx_); ys.append(pz)
                else:
                    xs.append(dy_); ys.append(pz)
            xs.append(np.nan); ys.append(np.nan)      # break between neurites
        return xs, ys

    # ---------------------------------------------------------- interaction
    def _on_z_scale(self, value):
        # Windows Tk can re-enter a Scale command from inside its own handler;
        # without this guard a drag turns into a feedback loop of redraws.
        if self._in_scale_callback or self.texture is None:
            return
        self._in_scale_callback = True
        try:
            z = int(round(float(value)))
            z = int(np.clip(z, 0, self.texture.full_shape[0] - 1))
            if z != self.point[0]:
                self.point = (z, self.point[1], self.point[2])
                self.z_var.set(z)
                self.z_label.configure(
                    text=f"z {z} of {self.texture.full_shape[0] - 1}")
                self._blit_slices()
        finally:
            self._in_scale_callback = False

    def _step_z(self, delta):
        if self.texture is None:
            return
        self.z_scale.set(int(np.clip(self.point[0] + delta, 0,
                                     self.texture.full_shape[0] - 1)))

    def _on_contrast(self):
        if self._in_scale_callback or self.texture is None:
            return
        self._in_scale_callback = True
        try:
            self._recompute_contrast()
            self._blit_slices()
        finally:
            self._in_scale_callback = False

    def _on_click(self, event):
        if self.texture is None or event.inaxes is None:
            return
        if event.xdata is None or event.ydata is None:
            return
        panel = {self.ax_xy: "xy", self.ax_xz: "xz",
                 self.ax_yz: "yz"}.get(event.inaxes)
        if panel is None:
            return
        if event.button == 3:
            self._undo_point()
            return
        moved = vc.panel_click_to_full(panel, event.xdata, event.ydata,
                                       self.point, self.texture)
        z_changed = moved[0] != self.point[0]
        self.point = moved
        if z_changed:
            self.z_scale.set(moved[0])
        self.z_label.configure(
            text=f"z {moved[0]} of {self.texture.full_shape[0] - 1}")
        self.set_status(f"crosshair  z={moved[0]}  y={moved[1]}  x={moved[2]} "
                        f"(full-resolution voxels)")
        self._blit_slices()

    def _on_scroll(self, event):
        """Zoom the XY panel about the cursor; the depth strips follow it."""
        if event.inaxes is not self.ax_xy or self.texture is None:
            return
        factor = 0.8 if event.button == "up" else 1.25
        x0, x1 = self.ax_xy.get_xlim()
        y0, y1 = self.ax_xy.get_ylim()
        cx = event.xdata if event.xdata is not None else (x0 + x1) / 2
        cy = event.ydata if event.ydata is not None else (y0 + y1) / 2
        self.ax_xy.set_xlim(cx + (x0 - cx) * factor, cx + (x1 - cx) * factor)
        self.ax_xy.set_ylim(cy + (y0 - cy) * factor, cy + (y1 - cy) * factor)
        # Keep the strips showing the same span as the panel above them.
        self.ax_xz.set_xlim(*self.ax_xy.get_xlim())
        self.ax_yz.set_xlim(*sorted(self.ax_xy.get_ylim()))
        self.canvas.draw()          # a zoom invalidates the cached background

    # -------------------------------------------------------------- marking
    def _add_point(self):
        if self.texture is None:
            return
        self.current_points.append(tuple(int(v) for v in self.point))
        self._update_point_label()
        self._blit_overlays()

    def _undo_point(self):
        if not self.current_points:
            return
        self.current_points.pop()
        self._update_point_label()
        self._blit_overlays()

    def _update_point_label(self):
        n = len(self.current_points)
        if n == 0:
            text = "0 points - click to position, then 'a'"
        elif n == 1:
            text = "1 point (the start). Add at least an end."
        else:
            text = (f"{n} points: start, {n - 2} anchor(s), end"
                    if n > 2 else "2 points: start and end, no anchors")
        self.points_label.configure(text=text)

    def _finish_neurite(self):
        if len(self.current_points) < 2:
            messagebox.showwarning(
                "Not enough points",
                "A neurite needs at least a start and an end.\n\n"
                "Click to position the crosshair, then press 'a' to add it.", parent=self)
            return
        neurite_id = self.id_var.get().strip() or f"n{len(self.annotations) + 1}"
        if any(a.neurite_id == neurite_id for a in self.annotations):
            messagebox.showwarning(
                "Duplicate id",
                f"'{neurite_id}' is already used in this session. Give this "
                f"neurite a different id so the two can be told apart later.", parent=self)
            return
        ann = na.NeuriteAnnotation(
            neurite_id=neurite_id, points_zyx=list(self.current_points),
            label=self.label_var.get().strip(), channel=self.channel,
            annotator=self.annotator_var.get().strip())
        self.annotations.append(ann)
        self.log("Neurite marked",
                 f"{neurite_id}: {len(ann.points_zyx)} points, "
                 f"{len(ann.anchors_zyx)} anchor(s)")
        self.current_points = []
        self._update_point_label()
        self.saved_label.configure(
            text=f"{len(self.annotations)} neurite(s) marked, not yet saved")
        self.id_var.set(f"n{len(self.annotations) + 1}")
        self._set_help_for("save")
        self._blit_overlays()

    def _identity(self):
        return na.stack_identity(self.path, self.series_index,
                                 self.stack.array.shape,
                                 self.stack.voxel_size_um)

    def _save(self):
        if not self.annotations:
            messagebox.showwarning(
                "Nothing to save",
                "No neurite has been finished yet. Mark the points, then "
                "press 'finish this neurite'.", parent=self)
            return
        path = na.sidecar_path(self.path, self.series_index)
        if path.exists():
            if not messagebox.askyesno(
                    "Sidecar already exists",
                    f"{path.name} already exists and will be replaced.\n\n"
                    f"The annotations in it will be lost. Continue?", parent=self):
                return
        na.save_annotations(path, self._identity(), self.annotations)
        self.log("Saved sidecar", str(path), status="ok")
        self.saved_label.configure(text=f"saved: {path.name}")
        self.set_status(f"Saved {len(self.annotations)} neurite(s) to {path.name}")
        messagebox.showinfo(
            "Saved",
            f"{len(self.annotations)} neurite(s) written to:\n{path}\n\n"
            f"Tracing, measuring and export need no viewer - they run on any "
            f"station from this file.", parent=self)

    def _trace_now(self):
        """Run the headless half here, as a check that the marks are usable."""
        if not self.annotations:
            messagebox.showwarning("Nothing to trace",
                                   "Finish at least one neurite first.", parent=self)
            return
        if self.stack.voxel_size_um is None:
            messagebox.showwarning(
                "Uncalibrated stack",
                "This stack has no voxel size, so a traced length would have "
                "no physical meaning. The marks can still be saved.", parent=self)
            return
        radius_um = float(self.stack.voxel_size_um[1]) * 3.0
        with self.process_log.timed("Trace from marks",
                                    f"{len(self.annotations)} neurite(s)"):
            results = na.trace_annotations(self.stack, self.annotations,
                                           radius_um=radius_um)
        for r in results:
            self.log(f"  {r['neurite_id']}",
                     f"{r['length_um']:.2f} um "
                     f"(raw {r['raw_length_um']:.2f}), "
                     f"{r['n_anchors']} anchor(s)")
        self.set_status("Traced. These same numbers come out of the sidecar on "
                        "any station, with no viewer installed.")

    # ----------------------------------------------------------------- help
    def _set_help_for(self, stage):
        if stage == "start":
            self.set_help(
                "Open a stack",
                "This viewer only records WHERE a neurite runs. It does no "
                "tracing and no measuring - those read the file you save here "
                "and run on any station, so nobody needs this viewer to get "
                "numbers out of your work.",
                ["Open stack... and choose the file.",
                 "Pick the series and the channel the neurite is in.",
                 "If the file has no voxel size the hood will say so; marks "
                 "are still valid, but lengths from them would not be."])
        elif stage == "mark":
            self.set_help(
                "Mark a neurite",
                "Click any panel to move the crosshair, then press 'a' to "
                "record that spot. The first point is the start and the last "
                "is the end; anything in between is a correction anchor - put "
                "one wherever you can see the automatic path would go wrong. "
                "The depth strips are stretched vertically so a plane is thick "
                "enough to hit. Use them to judge WHERE in depth something "
                "sits, never how thick it is.",
                ["Scroll to zoom the XY panel; the strips follow it.",
                 "Left/Right arrows or the z slider step through planes.",
                 "'a' adds a point, 'z' or right-click removes the last.",
                 "Hollow circles are points on other planes; solid ones are "
                 "on the plane you are looking at.",
                 "Press 'finish this neurite' when start and end are set."])
        else:
            self.set_help(
                "Save and hand off",
                "Saving writes a small JSON sidecar next to the stack holding "
                "only your points and who made them - no image data. It "
                "records which stack it was made against and refuses to load "
                "onto a different one, so a sidecar can never be quietly "
                "applied to the wrong series.",
                ["'save annotation sidecar' writes the file.",
                 "'trace now' runs the headless half here as a check.",
                 "Re-tracing later with different settings costs no "
                 "re-marking - the points are already on disk."])


def main():
    NeuriteViewer().mainloop()


if __name__ == "__main__":
    main()
