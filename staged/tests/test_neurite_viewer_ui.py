"""Drives the real neurite viewer window: load, scrub, click, mark, save.

Construction alone proves nothing - a Tk tool can build cleanly and still
have a canvas with no height or a click that lands on the wrong axis. So
this opens a real stack through the real load path, moves the real crosshair
by synthesising matplotlib events, and checks the geometry the widgets
actually got.
"""
from pathlib import Path
import shutil
import sys
import tempfile

import numpy as np
import matplotlib
matplotlib.use("TkAgg")

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "tools", ROOT / "app"):
    sys.path.insert(0, str(p))

import tifffile                              # noqa: E402
import neurite_annotation as na              # noqa: E402
import neurite_viewer_core as vc             # noqa: E402
import neurite_viewer as nv                  # noqa: E402
from neurite_viewer import NeuriteViewer     # noqa: E402

# Modal dialogs block until somebody clicks them, so an unattended run would
# simply hang. Record the calls instead - what the tool CHOSE to warn about
# is worth asserting on, and a silent stub would throw that away.
DIALOGS = []


class _StubMessagebox:
    def _record(self, kind, default):
        def call(title, message, **_kw):
            DIALOGS.append((kind, title, message))
            return default
        return call

    def __getattr__(self, name):
        if name.startswith("ask"):
            return self._record(name, True)
        return self._record(name, "ok")


nv.messagebox = _StubMessagebox()

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


class FakeEvent:
    """Enough of a matplotlib MouseEvent for the handlers under test."""
    def __init__(self, inaxes, xdata, ydata, button=1):
        self.inaxes = inaxes
        self.xdata = xdata
        self.ydata = ydata
        self.button = button


print("neurite_viewer (Tk UI) - regression\n")
tmp = Path(tempfile.mkdtemp())
app = None
try:
    # A stack shaped like the lab's: very anisotropic, wide, few planes.
    NZ, NY, NX = 24, 600, 1500
    VOX = (0.17118, 0.05454, 0.05454)
    vol = np.zeros((NZ, NY, NX), dtype=np.uint16)
    rng = np.random.default_rng(0)
    vol += rng.integers(0, 40, vol.shape, dtype=np.uint16)
    vol[12, 300, 200:1300] = 4000            # a bright neurite in one plane
    stack_path = tmp / "demo.ome.tif"
    tifffile.imwrite(str(stack_path), vol, photometric="minisblack",
                     metadata={"axes": "ZYX", "PhysicalSizeX": VOX[2],
                               "PhysicalSizeY": VOX[1], "PhysicalSizeZ": VOX[0]},
                     ome=True)

    app = NeuriteViewer()
    app.update()
    check("the viewer builds", app.winfo_exists() == 1)

    app.load_path(stack_path)
    app.update()

    # ---------------------------------------------------------------- load
    check("the stack loaded with its real shape",
          app.stack.array.shape == (NZ, 1, NY, NX), app.stack.array.shape)
    check("the voxel size was read from the file, not guessed",
          app.stack.voxel_size_um is not None
          and abs(app.stack.voxel_size_um[0] - VOX[0]) < 1e-6,
          app.stack.voxel_size_um)

    # ------------------------------------------------- the two flagged risks
    check("a display texture was built rather than drawing 900k pixels raw",
          app.texture is not None and app.texture.step > 1, app.texture.step)
    check("the texture keeps every z plane", app.texture.shape[0] == NZ)
    check("the depth panels were stretched, because at true aspect a plane "
          "here is a fraction of a screen pixel",
          app.aspect.physically_true is False, app.aspect)
    check("the stretch is enough to make a plane clickable",
          app.aspect.z_stretch * vc.true_z_aspect(VOX[0], VOX[2] * app.texture.step)
          * (760.0 / app.texture.shape[2]) >= vc.MIN_SCREEN_PX_PER_PLANE - 1e-6)
    check("the XZ panel title CARRIES the distortion warning, so shape is "
          "never read off a stretched picture",
          "not to scale" in app.ax_xz.get_title(), app.ax_xz.get_title())
    check("the YZ panel says so too", "not to scale" in app.ax_yz.get_title())
    check("BOTH depth strips use the SAME z stretch - shown side by side, two "
          "different z scales would have them disagree about how deep the "
          "same feature is",
          app.aspect.z_stretch == app.aspect_yz.z_stretch,
          (app.aspect.z_stretch, app.aspect_yz.z_stretch))
    check("neither caption rounds its factor away to a meaningless "
          "'stretched 1x - not to scale'",
          "1x for clicking" not in app.ax_xz.get_title()
          and "1x for clicking" not in app.ax_yz.get_title(),
          (app.ax_xz.get_title(), app.ax_yz.get_title()))
    check("the XY panel makes no such claim, because it is undistorted",
          "not to scale" not in app.ax_xy.get_title(), app.ax_xy.get_title())

    # Panels sized to their content, not a fixed split that leaves XY
    # floating in empty space while the depth strips stay cramped.
    r_xy, r_xz, r_yz = app._panel_height_ratios()
    check("the XY row is sized from the stack's own proportions",
          abs(r_xy - app.texture.shape[1] / app.texture.shape[2]) < 1e-9, r_xy)
    check("both depth rows get the same height, because they carry the same "
          "stretched z axis", abs(r_xz - r_yz) < 1e-9, (r_xz, r_yz))
    check("the depth strips are given real height rather than a sliver",
          r_xz * 700 >= 40, r_xz * 700)
    heights = [ax.get_position().height
               for ax in (app.ax_xy, app.ax_xz, app.ax_yz)]
    check("and the figure actually allocated it that way",
          heights[0] > heights[1] and heights[1] > 0.03, heights)

    check("the z readout is filled in on load, not left as a placeholder",
          "of" in app.z_label.cget("text"), app.z_label.cget("text"))

    check("blitting is armed: a static background was cached",
          app._static_bg is not None)
    check("and a slice background on top of it, so a crosshair move repaints "
          "only the crosshair", app._slice_bg is not None)
    check("every overlay artist is animated (otherwise canvas.draw would "
          "bake it into the cached background)",
          all(a.get_animated() for group in app._overlays.values() for a in group))
    check("the images are animated too", all(im.get_animated()
                                             for im in app._images.values()))

    # ------------------------------------------------------------- geometry
    app.update_idletasks()
    widget = app.canvas.get_tk_widget()
    check("the canvas got real width from its pack container",
          widget.winfo_width() > 300, widget.winfo_width())
    check("the canvas got real height (a zero-height canvas is the classic "
          "pack/grid mistake and looks identical in a construction test)",
          widget.winfo_height() > 300, widget.winfo_height())

    # ------------------------------------------------------------ scrubbing
    start_z = app.point[0]
    app.z_scale.set(3)
    app.update()
    check("the z slider moves the crosshair plane",
          app.point[0] == 3 and app.point[0] != start_z, app.point)
    check("scrubbing z leaves y and x alone",
          app.point[1] != 0 and app.point[2] != 0, app.point)
    app._step_z(1)
    app.update()
    check("the arrow keys step one plane", app.point[0] == 4, app.point)
    app.z_scale.set(10 ** 4)
    app.update()
    check("a z beyond the stack is clamped, not an exception",
          app.point[0] == NZ - 1, app.point)

    # --------------------------------------------------- clicking each panel
    app.z_scale.set(12)
    app.update()
    before = app.point
    app._on_click(FakeEvent(app.ax_xy, 100.0, 60.0))
    app.update()
    xy_point = app.point
    check("clicking XY moves y and x but NOT the plane you are looking at",
          xy_point[0] == before[0] and xy_point[1] != before[1]
          and xy_point[2] != before[2], (before, xy_point))
    check("the click maps back to full-resolution voxels, not display texels",
          xy_point[2] > 100 * app.texture.step - app.texture.step
          and xy_point[2] >= 100, xy_point)

    app._on_click(FakeEvent(app.ax_xz, 250.0, 7.0))
    app.update()
    xz_point = app.point
    check("clicking XZ sets x and z and keeps y - XZ is the view THROUGH y",
          xz_point[0] == 7 and xz_point[1] == xy_point[1]
          and xz_point[2] != xy_point[2], (xy_point, xz_point))
    check("a click in a depth strip also moves the z slider, so the two "
          "controls cannot disagree", int(float(app.z_scale.get())) == 7,
          app.z_scale.get())

    app._on_click(FakeEvent(app.ax_yz, 80.0, 15.0))
    app.update()
    yz_point = app.point
    check("clicking YZ sets y and z and keeps x",
          yz_point[0] == 15 and yz_point[2] == xz_point[2]
          and yz_point[1] != xz_point[1], (xz_point, yz_point))

    # ---------------------------------------------------------- contrast
    # A neurite is a thin bright thread in a big dark volume. Here it is
    # ~0.005% of the voxels, so any ceiling short of the very top clips it
    # away entirely and the panel shows nothing but background.
    peak = float(app.texture._small.max())
    check("the default ceiling sits far below the brightest voxel on sparse "
          "data - which is exactly why the slider has to reach further",
          app._display_range[1] < peak, (app._display_range[1], peak))
    check("the contrast readout names the brightest voxel, so a student can "
          "SEE the structure is being clipped rather than absent",
          str(int(peak)) in app.contrast_label.cget("text"),
          app.contrast_label.cget("text"))
    check("the upper slider spans the last percent, where all the useful "
          "range on sparse data actually is",
          float(app.hi_scale.cget("from")) >= 99.0
          and float(app.hi_scale.cget("to")) == 100.0,
          (app.hi_scale.cget("from"), app.hi_scale.cget("to")))
    app.hi_var.set(100.0)
    app._on_contrast()
    check("and it can be taken all the way to the structure",
          abs(app._display_range[1] - peak) < 1e-6, app._display_range)

    lo_before = app._display_range
    app.lo_var.set(10.0)
    app.hi_var.set(99.5)
    app._on_contrast()
    app.update()
    check("the contrast sliders change the display range",
          app._display_range != lo_before, (lo_before, app._display_range))
    check("and the change reaches the images",
          app._images["xy"].get_clim() == app._display_range)
    app.lo_var.set(50.0)
    app.hi_var.set(50.0)
    app._on_contrast()
    check("a collapsed range is repaired rather than raising",
          app._display_range[1] > app._display_range[0], app._display_range)

    # ------------------------------------------------------------- marking
    app.lo_var.set(2.0); app.hi_var.set(99.7); app._on_contrast()
    app.point = (12, 300, 200)
    app._add_point()
    app.point = (12, 300, 700)
    app._add_point()
    app.point = (12, 300, 1290)
    app._add_point()
    app.update()
    check("points accumulate", len(app.current_points) == 3, app.current_points)
    check("the label distinguishes anchors from endpoints",
          "anchor" in app.points_label.cget("text"), app.points_label.cget("text"))
    app._undo_point()
    check("undo removes the last point", len(app.current_points) == 2)
    app.point = (12, 300, 1290)
    app._add_point()

    near_far = app._point_markers("xy")
    check("marked points render on the plane they belong to",
          len(near_far[2]) == 3 and len(near_far[0]) == 0, near_far)
    app.point = (2, 300, 1290)
    far = app._point_markers("xy")
    check("seen from a distant plane the same points render as FAR, so they "
          "are not mistaken for structure in the plane on screen",
          len(far[0]) == 3 and len(far[2]) == 0, far)
    app.point = (12, 300, 1290)

    app.id_var.set("PVDa")
    app.annotator_var.set("student_a")
    app._finish_neurite()
    app.update()
    check("finishing produces one annotation", len(app.annotations) == 1)
    check("the middle point became a correction anchor, not an endpoint",
          app.annotations[0].anchors_zyx == [[12, 300, 700]],
          app.annotations[0].anchors_zyx)
    check("the point buffer is cleared for the next neurite",
          app.current_points == [])
    check("the id advances so two neurites cannot silently share one",
          app.id_var.get() != "PVDa", app.id_var.get())
    check("finished neurites stay drawn, so what is done is visible",
          len(app._finished_paths("xy")[0]) == 4)   # 3 points + nan break

    app.current_points = [(1, 1, 1)]
    n_before = len(app.annotations)
    DIALOGS.clear()
    app._finish_neurite()
    check("a one-point neurite is refused rather than saved as a trace",
          len(app.annotations) == n_before)
    check("and the refusal SAYS why instead of the button just doing nothing",
          DIALOGS and "start and an end" in DIALOGS[-1][2], DIALOGS[-1:])
    app.current_points = []

    app.current_points = [(1, 1, 1), (2, 2, 2)]
    app.id_var.set("PVDa")                      # already used above
    DIALOGS.clear()
    app._finish_neurite()
    check("a duplicate neurite id is refused, so two neurites cannot be "
          "silently merged in the sidecar",
          len(app.annotations) == n_before and DIALOGS
          and "already used" in DIALOGS[-1][2], DIALOGS[-1:])
    app.current_points = []

    # ---------------------------------------------------------------- save
    DIALOGS.clear()
    app._save()
    side = na.sidecar_path(stack_path, app.series_index)
    check("saving reminds the student the numbers need no viewer, which is "
          "the whole point of the split",
          any("any station" in m for _k, _t, m in DIALOGS), DIALOGS)
    DIALOGS.clear()
    app._save()
    check("overwriting an existing sidecar asks first, naming what would be "
          "lost", any(k.startswith("ask") and "will be replaced" in m
                      for k, _t, m in DIALOGS), DIALOGS)
    check("a sidecar was written beside the stack", side.is_file(), side.name)
    text = side.read_text(encoding="utf-8")
    check("the sidecar is small - coordinates and provenance, no pixels",
          len(text) < 3000, len(text))
    identity = na.stack_identity(stack_path, app.series_index,
                                 app.stack.array.shape, app.stack.voxel_size_um)
    loaded, _ = na.load_annotations(side, identity)
    check("the saved marks reload against this exact stack",
          loaded[0].points_zyx == app.annotations[0].points_zyx)
    check("the annotator travelled with them",
          loaded[0].annotator == "student_a")

    # ------------------------------------- the split actually holds up
    traced = na.trace_annotations(app.stack, loaded, radius_um=VOX[1] * 3)
    check("the marks trace headlessly - the half that runs on any station",
          len(traced) == 1 and traced[0]["length_um"] > 0,
          traced[0]["length_um"])
    expected_um = (1290 - 200) * VOX[2]
    check("the traced length is in the right physical ballpark for the "
          "neurite that was drawn",
          abs(traced[0]["length_um"] - expected_um) < expected_um * 0.35,
          (traced[0]["length_um"], expected_um))

    # ------------------------------------------------------------- help
    app._set_help_for("mark")
    body = app._help_body()
    check("help is contextual to the stage the student is on",
          "crosshair" in body.lower(), body[:60])
    check("the help warns that stretched panels are for position, not shape",
          "thick" in body.lower() or "shape" in body.lower())
    check("help lives in the hood and is off until summoned",
          app._help_visible is False)
finally:
    if app is not None:
        try:
            app.destroy()
        except Exception:
            pass
    shutil.rmtree(tmp, ignore_errors=True)

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("NEURITE_VIEWER_UI_REGRESSION_PASS")
