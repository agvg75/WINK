"""Tk dialog for :mod:`scale_calibration`.

``ScaleCalibrationDialog`` gives every module one consistent way to set
micrometres-per-pixel: an optical estimate from scope+zoom+camera presets, a
raw scale bar drawn on the image, and a 1.14 mm worm-length sanity check.  It
returns ``{"um_per_px", "source", "details"}`` or ``None`` if cancelled.

The scale-bar and worm-trace steps reuse ``process_ui.collect_image_points`` so
line drawing looks and behaves like the rest of WINK.  A frame (2-D/3-D numpy
image) enables those steps; without one, only the optical estimate and a manual
pixel entry are available.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk, messagebox

import scale_calibration as sc


class ScaleCalibrationDialog:
    def __init__(self, parent, *, frame=None, initial_um_per_px=None,
                 title="Scale & magnification"):
        self.parent = parent
        self.frame = frame
        self.result = None
        self._current = (float(initial_um_per_px)
                         if initial_um_per_px else None)
        self._presets = sc.load_presets()

        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.resizable(False, False)

        self.scope_var = tk.StringVar()
        self.camera_var = tk.StringVar()
        self.objective_var = tk.StringVar()
        self.zoom_var = tk.StringVar(value="1.0")
        self.cmount_var = tk.StringVar(value="0.5")
        self.binning_var = tk.StringVar(value="1")
        self.pixel_var = tk.StringVar(value="")
        self.optical_out = tk.StringVar(value="-")
        self.known_var = tk.StringVar(value="1.0")
        self.unit_var = tk.StringVar(value="mm")
        self.manual_px_var = tk.StringVar(value="")
        self.current_var = tk.StringVar(value="Not set")
        self.worm_out = tk.StringVar(value="")
        self.note_var = tk.StringVar(value="")

        self._build()
        self._refresh_current()
        _raise_modal(self.win, parent)
        parent.wait_window(self.win)

    # -- layout -------------------------------------------------------------
    def _build(self):
        pad = dict(padx=10, pady=4)
        root = ttk.Frame(self.win, padding=12)
        root.pack(fill="both", expand=True)

        # Section 1: optical estimate
        opt = ttk.LabelFrame(root, text="1. Optical estimate (scope + zoom + camera)")
        opt.pack(fill="x", **pad)
        opt.grid_columnconfigure(1, weight=1)
        ttk.Label(opt, text="Scope / body").grid(row=0, column=0, sticky="w", padx=6, pady=3)
        self.scope_cb = ttk.Combobox(opt, textvariable=self.scope_var, state="readonly",
                                     values=list(self._presets["scopes"]), width=30)
        self.scope_cb.grid(row=0, column=1, sticky="ew", padx=6, pady=3)
        self.scope_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_scope())

        ttk.Label(opt, text="Objective").grid(row=1, column=0, sticky="w", padx=6, pady=3)
        self.objective_cb = ttk.Combobox(opt, textvariable=self.objective_var, width=12)
        self.objective_cb.grid(row=1, column=1, sticky="w", padx=6, pady=3)
        self.objective_cb.bind("<<ComboboxSelected>>", lambda _e: self._compute_optical())
        self.objective_cb.bind("<KeyRelease>", lambda _e: self._compute_optical())

        self.zoom_row = ttk.Frame(opt)
        self.zoom_row.grid(row=2, column=0, columnspan=2, sticky="ew")
        ttk.Label(self.zoom_row, text="Zoom factor (0.7-9.0)").pack(side="left", padx=6)
        ze = ttk.Entry(self.zoom_row, textvariable=self.zoom_var, width=8)
        ze.pack(side="left")
        ze.bind("<KeyRelease>", lambda _e: self._compute_optical())
        ttk.Label(self.zoom_row, text="(SZX12 knob 7-90 -> divide by 10)",
                  foreground="#666666").pack(side="left", padx=6)

        ttk.Label(opt, text="C-mount adapter").grid(row=3, column=0, sticky="w", padx=6, pady=3)
        ce = ttk.Entry(opt, textvariable=self.cmount_var, width=8)
        ce.grid(row=3, column=1, sticky="w", padx=6, pady=3)
        ce.bind("<KeyRelease>", lambda _e: self._compute_optical())

        ttk.Label(opt, text="Camera").grid(row=4, column=0, sticky="w", padx=6, pady=3)
        self.camera_cb = ttk.Combobox(opt, textvariable=self.camera_var, state="readonly",
                                      values=list(self._presets["cameras"]), width=30)
        self.camera_cb.grid(row=4, column=1, sticky="ew", padx=6, pady=3)
        self.camera_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_camera())

        prow = ttk.Frame(opt); prow.grid(row=5, column=0, columnspan=2, sticky="ew")
        ttk.Label(prow, text="Pixel pitch (um)").pack(side="left", padx=6)
        pe = ttk.Entry(prow, textvariable=self.pixel_var, width=8); pe.pack(side="left")
        pe.bind("<KeyRelease>", lambda _e: self._compute_optical())
        ttk.Label(prow, text="Binning").pack(side="left", padx=6)
        be = ttk.Entry(prow, textvariable=self.binning_var, width=5); be.pack(side="left")
        be.bind("<KeyRelease>", lambda _e: self._compute_optical())

        ttk.Label(opt, textvariable=self.note_var, foreground="#8a6d00",
                  wraplength=420, justify="left").grid(
            row=6, column=0, columnspan=2, sticky="w", padx=6, pady=(2, 2))
        outrow = ttk.Frame(opt); outrow.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(2, 4))
        ttk.Label(outrow, text="=").pack(side="left", padx=6)
        ttk.Label(outrow, textvariable=self.optical_out, font=("Segoe UI", 10, "bold")).pack(side="left")
        ttk.Button(outrow, text="Use this value", command=self._use_optical).pack(side="right", padx=6)

        # Section 2: scale bar
        bar = ttk.LabelFrame(root, text="2. Raw scale bar (ground truth)")
        bar.pack(fill="x", **pad)
        brow = ttk.Frame(bar); brow.pack(fill="x", padx=6, pady=4)
        ttk.Label(brow, text="Known length").pack(side="left")
        ttk.Entry(brow, textvariable=self.known_var, width=8).pack(side="left", padx=4)
        ttk.Combobox(brow, textvariable=self.unit_var, state="readonly",
                     values=["mm", "um"], width=4).pack(side="left")
        if self.frame is not None:
            ttk.Button(brow, text="Draw line on image",
                       command=self._draw_scale_bar).pack(side="left", padx=8)
        else:
            ttk.Label(brow, text="pixels:").pack(side="left", padx=(8, 2))
            ttk.Entry(brow, textvariable=self.manual_px_var, width=8).pack(side="left")
            ttk.Button(brow, text="Use", command=self._manual_scale_bar).pack(side="left", padx=6)

        # Section 3: current value + worm sanity check
        res = ttk.LabelFrame(root, text="3. Result and 1.14 mm worm check")
        res.pack(fill="x", **pad)
        crow = ttk.Frame(res); crow.pack(fill="x", padx=6, pady=4)
        ttk.Label(crow, text="Current scale:").pack(side="left")
        ttk.Label(crow, textvariable=self.current_var,
                  font=("Segoe UI", 11, "bold")).pack(side="left", padx=6)
        if self.frame is not None:
            ttk.Button(crow, text="Measure a worm",
                       command=self._measure_worm).pack(side="right", padx=6)
        ttk.Label(res, textvariable=self.worm_out, wraplength=420,
                  justify="left").pack(anchor="w", padx=6, pady=(0, 4))

        btns = ttk.Frame(root); btns.pack(fill="x", pady=(8, 0))
        ttk.Button(btns, text="Cancel", command=self._cancel).pack(side="right", padx=4)
        ttk.Button(btns, text="OK (use current)", command=self._ok).pack(side="right", padx=4)

    # -- preset reactions ---------------------------------------------------
    def _on_scope(self):
        spec = self._presets["scopes"].get(self.scope_var.get(), {})
        self.cmount_var.set(str(spec.get("cmount", 1.0)))
        objectives = spec.get("objectives")
        if objectives:
            self.objective_cb.configure(values=[str(o) for o in objectives])
            self.objective_var.set(str(objectives[0]))
        else:
            obj = spec.get("objective", 1.0)
            self.objective_cb.configure(values=[str(obj)])
            self.objective_var.set(str(obj))
        if spec.get("has_zoom"):
            self.zoom_row.grid()
        else:
            self.zoom_var.set("1.0")
            self.zoom_row.grid_remove()
        note = spec.get("note", "")
        if not spec.get("optical", True):
            note = (note + "  This body has no microscope optics - use the "
                    "scale bar.").strip()
        self.note_var.set(note)
        self._compute_optical()

    def _on_camera(self):
        spec = self._presets["cameras"].get(self.camera_var.get(), {})
        self.pixel_var.set(str(spec.get("pixel_um", "")))
        self.binning_var.set(str(spec.get("binning", 1)))
        if spec.get("note"):
            self.note_var.set(spec["note"])
        self._compute_optical()

    def _scope_is_optical(self):
        s = self._presets["scopes"].get(self.scope_var.get(), {})
        c = self._presets["cameras"].get(self.camera_var.get(), {})
        return s.get("optical", True) and c.get("optical", True)

    def _compute_optical(self):
        try:
            if not self._scope_is_optical():
                self.optical_out.set("scale bar only for this rig")
                return None
            pitch = float(self.pixel_var.get())
            objective = float(self.objective_var.get())
            zoom = float(self.zoom_var.get())
            cmount = float(self.cmount_var.get())
            binning = float(self.binning_var.get() or 1)
            umpp = sc.optical_um_per_px(pitch, objective, zoom, cmount, binning)
            mag = sc.total_magnification(objective, zoom, cmount)
            self.optical_out.set(f"{umpp:.4f} um/px   (total {mag:.2f}x)")
            return umpp
        except (ValueError, ZeroDivisionError):
            self.optical_out.set("-")
            return None

    # -- actions ------------------------------------------------------------
    def _use_optical(self):
        umpp = self._compute_optical()
        if umpp is None:
            messagebox.showinfo(
                "Optical estimate",
                "Fill scope, zoom, camera (pixel pitch) for a microscope rig, "
                "or use the scale bar.", parent=self.win)
            return
        self._set_current(umpp, "optical_estimate",
                          f"{self.scope_var.get()} | {self.camera_var.get()} | "
                          f"{self.optical_out.get()}")

    def _draw_scale_bar(self):
        try:
            from process_ui import collect_image_points, ProcessLog
            pts = collect_image_points(
                self.parent, self.frame, title="Draw scale bar",
                instructions="Click the two ends of a feature whose real length "
                             "you know.", mode="polyline", min_points=2,
                max_points=2, process_log=ProcessLog("Scale bar"))
            if not pts or len(pts) < 2:
                return
            length_px = sc.polyline_length_px(pts)
            umpp = sc.scalebar_um_per_px(
                length_px, float(self.known_var.get()), self.unit_var.get())
            self._set_current(
                umpp, "two_point_calibration",
                f"scale bar {float(self.known_var.get())} {self.unit_var.get()} "
                f"/ {length_px:.1f} px")
        except Exception as exc:
            messagebox.showerror("Scale bar", str(exc), parent=self.win)

    def _manual_scale_bar(self):
        try:
            umpp = sc.scalebar_um_per_px(
                float(self.manual_px_var.get()), float(self.known_var.get()),
                self.unit_var.get())
            self._set_current(umpp, "two_point_calibration",
                              f"manual {self.known_var.get()} "
                              f"{self.unit_var.get()} / {self.manual_px_var.get()} px")
        except Exception as exc:
            messagebox.showerror("Scale bar", str(exc), parent=self.win)

    def _measure_worm(self):
        if self._current is None:
            messagebox.showinfo("Worm check", "Set a scale first.", parent=self.win)
            return
        try:
            from process_ui import collect_image_points, ProcessLog
            pts = collect_image_points(
                self.parent, self.frame, title="Measure a worm",
                instructions="Click along an adult worm from tip of head to tip "
                             "of tail, then Finish.", mode="polyline",
                min_points=2, process_log=ProcessLog("Worm length check"))
            if not pts or len(pts) < 2:
                return
            length_px = sc.polyline_length_px(pts)
            mm, ratio, ok = sc.worm_length_check(length_px, self._current)
            verdict = ("looks right" if ok else
                       "OFF - re-check the scale or that this is an adult")
            self.worm_out.set(
                f"Traced worm = {mm:.2f} mm ({length_px:.0f} px) vs expected "
                f"{sc.ADULT_WORM_MM:.2f} mm -> {ratio*100:.0f}% : {verdict}.")
        except Exception as exc:
            messagebox.showerror("Worm check", str(exc), parent=self.win)

    # -- result plumbing ----------------------------------------------------
    def _set_current(self, umpp, source, details):
        self._current = float(umpp)
        self._source = source
        self._details = details
        self._refresh_current()

    def _refresh_current(self):
        if self._current is None:
            self.current_var.set("Not set")
            return
        worm_px = sc.ADULT_WORM_MM * 1000.0 / self._current
        self.current_var.set(
            f"{self._current:.4f} um/px   (1.14 mm worm = {worm_px:.0f} px)")

    def _ok(self):
        if self._current is None:
            messagebox.showinfo(
                "No scale set",
                "Choose an optical estimate or draw a scale bar first.",
                parent=self.win)
            return
        self.result = {
            "um_per_px": float(self._current),
            "source": getattr(self, "_source", "declared"),
            "details": getattr(self, "_details", "")}
        self.win.destroy()

    def _cancel(self):
        self.result = None
        self.win.destroy()


def ask_scale(parent, *, frame=None, initial_um_per_px=None,
              title="Scale & magnification"):
    """Convenience: open the dialog and return its result dict or None."""
    dlg = ScaleCalibrationDialog(parent, frame=frame,
                                 initial_um_per_px=initial_um_per_px, title=title)
    return dlg.result


class ScaleCalibrationPanel:
    """Embeddable, in-window scale calibration.

    Renders the optical estimate + scale-bar + result controls into a provided
    ``container`` frame (e.g. an overlay over a tool's centre pane) instead of a
    Toplevel, and draws the scale bar on the panel's own image canvas -- so
    nothing pops out to a separate window.  Non-blocking: calls
    ``on_done(result_or_None)`` when OK/Cancel is pressed.  ``result`` is
    ``{"um_per_px", "source", "details"}``.
    """

    def __init__(self, container, *, frame=None, initial=None, on_done=None):
        self.container = container
        self.frame = frame
        self.on_done = on_done
        self._current = float(initial) if initial else None
        self._source = None
        self._details = ""
        self._presets = sc.load_presets()
        self._cid = None
        self._collect = None
        self.scope_var = tk.StringVar()
        self.camera_var = tk.StringVar()
        self.objective_var = tk.StringVar()
        self.zoom_var = tk.StringVar(value="1.0")
        self.cmount_var = tk.StringVar(value="0.5")
        self.binning_var = tk.StringVar(value="1")
        self.pixel_var = tk.StringVar(value="")
        self.optical_out = tk.StringVar(value="-")
        self.known_var = tk.StringVar(value="1.0")
        self.unit_var = tk.StringVar(value="mm")
        self.manual_px_var = tk.StringVar(value="")
        self.current_var = tk.StringVar(value="Not set")
        self.note_var = tk.StringVar(value="")
        self._build()
        self._refresh_current()

    def _build(self):
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure
        root = ttk.Frame(self.container, padding=8)
        root.pack(fill="both", expand=True)
        top = ttk.Frame(root); top.pack(fill="x")
        ttk.Label(top, text="Scale & magnification", font=("Segoe UI", 11, "bold")).pack(side="left")
        ttk.Button(top, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(top, text="OK (use current)", command=self._ok).pack(side="right", padx=4)
        body = ttk.Frame(root); body.pack(fill="both", expand=True, pady=(6, 0))
        left = ttk.Frame(body); left.pack(side="left", fill="y")
        right = ttk.Frame(body); right.pack(side="right", fill="both", expand=True, padx=(8, 0))

        opt = ttk.LabelFrame(left, text="1. Optical estimate")
        opt.pack(fill="x")
        opt.grid_columnconfigure(1, weight=1)

        def orow(r, label, widget):
            ttk.Label(opt, text=label).grid(row=r, column=0, sticky="w", padx=6, pady=2)
            widget.grid(row=r, column=1, sticky="ew", padx=6, pady=2)
            return widget
        self.scope_cb = orow(0, "Scope", ttk.Combobox(opt, textvariable=self.scope_var, state="readonly",
                                                      values=list(self._presets["scopes"]), width=24))
        self.scope_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_scope())
        self.objective_cb = orow(1, "Objective", ttk.Combobox(opt, textvariable=self.objective_var, width=10))
        self.objective_cb.bind("<<ComboboxSelected>>", lambda _e: self._compute_optical())
        self.objective_cb.bind("<KeyRelease>", lambda _e: self._compute_optical())
        e = orow(2, "Zoom (0.7-9.0)", ttk.Entry(opt, textvariable=self.zoom_var, width=10)); e.bind("<KeyRelease>", lambda _e: self._compute_optical())
        e = orow(3, "C-mount", ttk.Entry(opt, textvariable=self.cmount_var, width=10)); e.bind("<KeyRelease>", lambda _e: self._compute_optical())
        self.camera_cb = orow(4, "Camera", ttk.Combobox(opt, textvariable=self.camera_var, state="readonly",
                                                        values=list(self._presets["cameras"]), width=24))
        self.camera_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_camera())
        e = orow(5, "Pixel pitch (um)", ttk.Entry(opt, textvariable=self.pixel_var, width=10)); e.bind("<KeyRelease>", lambda _e: self._compute_optical())
        e = orow(6, "Binning", ttk.Entry(opt, textvariable=self.binning_var, width=10)); e.bind("<KeyRelease>", lambda _e: self._compute_optical())
        outrow = ttk.Frame(opt); outrow.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(2, 4))
        ttk.Label(outrow, textvariable=self.optical_out, font=("Segoe UI", 9, "bold")).pack(side="left", padx=6)
        ttk.Button(outrow, text="Use", command=self._use_optical).pack(side="right", padx=6)

        bar = ttk.LabelFrame(left, text="2. Scale bar (ground truth)")
        bar.pack(fill="x", pady=(6, 0))
        krow = ttk.Frame(bar); krow.pack(fill="x", padx=6, pady=3)
        ttk.Label(krow, text="Known length").pack(side="left")
        ttk.Entry(krow, textvariable=self.known_var, width=8).pack(side="left", padx=4)
        ttk.Combobox(krow, textvariable=self.unit_var, state="readonly", values=["mm", "um"], width=4).pack(side="left")
        if self.frame is not None:
            ttk.Button(bar, text="Draw scale bar on image ->", command=self._start_scalebar).pack(fill="x", padx=6, pady=(0, 4))
        else:
            mrow = ttk.Frame(bar); mrow.pack(fill="x", padx=6, pady=(0, 4))
            ttk.Label(mrow, text="pixels").pack(side="left")
            ttk.Entry(mrow, textvariable=self.manual_px_var, width=8).pack(side="left", padx=4)
            ttk.Button(mrow, text="Use", command=self._manual_scalebar).pack(side="left")

        res = ttk.LabelFrame(left, text="3. Result")
        res.pack(fill="x", pady=(6, 0))
        ttk.Label(res, textvariable=self.current_var, font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6, pady=3)
        ttk.Label(left, textvariable=self.note_var, foreground="#8a6d00", wraplength=240, justify="left").pack(anchor="w", pady=(4, 0))

        self._fig = Figure(figsize=(4.4, 3.6), dpi=100)
        self._ax = self._fig.add_subplot(111); self._ax.set_axis_off()
        self._canvas = FigureCanvasTkAgg(self._fig, master=right)
        self._canvas.get_tk_widget().pack(fill="both", expand=True)
        if self.frame is not None:
            self._ax.imshow(self.frame, cmap="gray")
        else:
            self._ax.text(0.5, 0.5, "No image\n(optical or manual entry only)", ha="center", va="center", color="#888888")
        self._canvas.draw()

    # -- optical (mirrors the dialog) ---------------------------------------
    def _on_scope(self):
        spec = self._presets["scopes"].get(self.scope_var.get(), {})
        self.cmount_var.set(str(spec.get("cmount", 1.0)))
        objectives = spec.get("objectives")
        if objectives:
            self.objective_cb.configure(values=[str(o) for o in objectives]); self.objective_var.set(str(objectives[0]))
        else:
            obj = spec.get("objective", 1.0); self.objective_cb.configure(values=[str(obj)]); self.objective_var.set(str(obj))
        if not spec.get("has_zoom", False):
            self.zoom_var.set("1.0")
        note = spec.get("note", "")
        if not spec.get("optical", True):
            note = (note + "  No microscope optics - use the scale bar.").strip()
        self.note_var.set(note)
        self._compute_optical()

    def _on_camera(self):
        spec = self._presets["cameras"].get(self.camera_var.get(), {})
        self.pixel_var.set(str(spec.get("pixel_um", "")))
        self.binning_var.set(str(spec.get("binning", 1)))
        if spec.get("note"):
            self.note_var.set(spec["note"])
        self._compute_optical()

    def _scope_is_optical(self):
        s = self._presets["scopes"].get(self.scope_var.get(), {})
        c = self._presets["cameras"].get(self.camera_var.get(), {})
        return s.get("optical", True) and c.get("optical", True)

    def _compute_optical(self):
        try:
            if not self._scope_is_optical():
                self.optical_out.set("scale bar only"); return None
            umpp = sc.optical_um_per_px(float(self.pixel_var.get()), float(self.objective_var.get()),
                                        float(self.zoom_var.get()), float(self.cmount_var.get()),
                                        float(self.binning_var.get() or 1))
            mag = sc.total_magnification(float(self.objective_var.get()), float(self.zoom_var.get()), float(self.cmount_var.get()))
            self.optical_out.set(f"{umpp:.4f} um/px ({mag:.2f}x)")
            return umpp
        except (ValueError, ZeroDivisionError):
            self.optical_out.set("-"); return None

    def _use_optical(self):
        umpp = self._compute_optical()
        if umpp is None:
            self.note_var.set("Fill scope, zoom, and camera (pixel pitch), or use the scale bar."); return
        self._set_current(umpp, "optical_estimate", f"{self.scope_var.get()} | {self.camera_var.get()} | {self.optical_out.get()}")

    # -- scale bar on the panel canvas --------------------------------------
    def _start_scalebar(self):
        if self.frame is None:
            return
        self._collect = {"pts": []}
        self._cid = self._canvas.mpl_connect("button_press_event", self._canvas_click)
        self.note_var.set("Click the two ends of the known-length feature on the image.")

    def _canvas_click(self, event):
        if self._collect is None:
            return
        if event.inaxes != self._ax or event.xdata is None:
            return
        self._collect["pts"].append((float(event.xdata), float(event.ydata)))
        self._ax.plot(event.xdata, event.ydata, "+", color="#00e0ff", ms=12, mew=2)
        pts = self._collect["pts"]
        if len(pts) >= 2:
            (x0, y0), (x1, y1) = pts[:2]
            self._ax.plot([x0, x1], [y0, y1], "-", color="#00e0ff", lw=1)
            self._end_collect()
            length = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
            try:
                umpp = sc.scalebar_um_per_px(length, float(self.known_var.get()), self.unit_var.get())
                self._set_current(umpp, "two_point_calibration",
                                  f"scale bar {self.known_var.get()} {self.unit_var.get()} / {length:.1f} px")
                self.note_var.set("")
            except Exception as exc:
                self.note_var.set(str(exc))
        self._canvas.draw_idle()

    def _manual_scalebar(self):
        try:
            umpp = sc.scalebar_um_per_px(float(self.manual_px_var.get()), float(self.known_var.get()), self.unit_var.get())
            self._set_current(umpp, "two_point_calibration",
                              f"manual {self.known_var.get()} {self.unit_var.get()} / {self.manual_px_var.get()} px")
        except Exception as exc:
            self.note_var.set(str(exc))

    def _end_collect(self):
        cid = getattr(self, "_cid", None)
        if cid is not None:
            try:
                self._canvas.mpl_disconnect(cid)
            except Exception:
                pass
        self._cid = None
        self._collect = None

    # -- result plumbing ----------------------------------------------------
    def _set_current(self, umpp, source, details):
        self._current = float(umpp); self._source = source; self._details = details
        self._refresh_current()

    def _refresh_current(self):
        if self._current is None:
            self.current_var.set("Not set"); return
        worm_px = sc.ADULT_WORM_MM * 1000.0 / self._current
        self.current_var.set(f"{self._current:.4f} um/px  (1.14 mm worm = {worm_px:.0f} px)")

    def _ok(self):
        if self._current is None:
            self.note_var.set("Choose an optical estimate or draw/enter a scale bar first."); return
        self._finish({"um_per_px": float(self._current), "source": self._source or "declared",
                      "details": self._details})

    def _cancel(self):
        self._finish(None)

    def _finish(self, result):
        self._end_collect()
        if self.on_done is not None:
            self.on_done(result)


def _raise_modal(win, parent):
    """Show a Toplevel reliably (the withdrawn-root transient trap on Windows
    leaves the window invisible, so only go transient when the parent is
    viewable), then lift/grab like tkinter.simpledialog."""
    try:
        if parent is not None and parent.winfo_viewable():
            win.transient(parent)
    except Exception:
        pass
    try:
        win.update_idletasks()
        win.deiconify()
        win.lift()
        win.update()
        win.grab_set()
    except Exception:
        pass
    try:
        win.focus_force()
    except Exception:
        pass
