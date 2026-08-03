"""Display-geometry core for the orthogonal neurite viewer.

Pure functions and small classes, no Tk and no matplotlib, so the two
things that actually decide whether the viewer is usable can be tested
directly instead of judged by eye.

THE TWO PROBLEMS THIS SOLVES
-----------------------------
Measured on this lab's own Leica stack (24 x 3 x 1807 x 4512, dz 0.1712,
dy = dx 0.0545):

1. REDRAW COST. One XY plane is 8,153,184 pixels. Handing that to imshow on
   every z-step makes scrubbing sluggish, and it is the reason a GPU-backed
   viewer feels different from a matplotlib one. The fix is to draw from a
   DECIMATED texture while keeping every click, anchor and measurement in
   full-resolution coordinates - so the display gets cheaper without the
   data getting coarser. `DisplayTexture` owns that mapping.

2. XZ / YZ ASPECT. The stack is 246 um wide and 4.1 um deep: a 60:1 ratio.
   At true physical aspect a 500 px-wide XZ panel is 8 px tall - about a
   third of a screen pixel per z plane. Dragging a boundary point there is
   impossible, which is exactly how a panel ends up being routed around
   rather than used. So z is STRETCHED for display, by a factor computed
   from how many screen pixels a plane needs to be clickable.

   Stretching is a distortion, so it is never silent: `z_stretch_label`
   produces the caption the panel must carry, and the stretch factor is
   part of the returned geometry rather than hidden inside a draw call.
   Shape must not be judged from a stretched panel; position can be.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np

# A z plane narrower than this on screen cannot be clicked reliably.
MIN_SCREEN_PX_PER_PLANE = 4.0
# Above this, the panel is tall enough that further stretch just wastes space.
MAX_Z_STRETCH = 60.0
DEFAULT_MAX_DISPLAY_PX = 1200
# Within this much of 1.0, a panel counts as physically true.
TRUE_ASPECT_TOLERANCE = 0.02


@dataclass(frozen=True)
class OrthoAspect:
    """How a panel should be drawn, and what to tell the person about it."""
    aspect: float             # matplotlib imshow aspect for the panel
    z_stretch: float          # 1.0 = true physical proportions
    physically_true: bool

    def label(self):
        if self.physically_true:
            return "z to scale"
        # Below 10x the factor needs a decimal: rounding 1.2 to "1x" produces
        # "stretched 1x - not to scale", which reads as a bug and teaches the
        # student to ignore the caption.
        factor = (f"{self.z_stretch:.1f}" if self.z_stretch < 10
                  else f"{self.z_stretch:.0f}")
        return f"z stretched {factor}x for clicking - not to scale"


def true_z_aspect(dz_um, lateral_um):
    """imshow aspect that makes one z step its real physical size."""
    if lateral_um <= 0:
        raise ValueError("Lateral voxel size must be positive.")
    return float(dz_um) / float(lateral_um)


def auto_z_stretch(n_z, dz_um, lateral_um, n_lateral, panel_width_px,
                   min_px_per_plane=MIN_SCREEN_PX_PER_PLANE):
    """How much to stretch z so a plane is thick enough to click.

    Returns 1.0 when the panel is already tall enough - a stack with few
    lateral pixels or near-isotropic voxels needs no distortion, and
    applying one anyway would be gratuitous.
    """
    n_z = int(n_z)
    if n_z <= 1 or panel_width_px <= 0 or n_lateral <= 0:
        return 1.0
    # Height in screen pixels if drawn at true physical aspect.
    px_per_lateral_voxel = panel_width_px / float(n_lateral)
    true_height_px = n_z * true_z_aspect(dz_um, lateral_um) * px_per_lateral_voxel
    px_per_plane = true_height_px / n_z
    if px_per_plane >= min_px_per_plane:
        return 1.0
    return float(min(MAX_Z_STRETCH, min_px_per_plane / px_per_plane))


def ortho_aspect(n_z, dz_um, lateral_um, n_lateral, panel_width_px,
                 z_stretch=None, min_px_per_plane=MIN_SCREEN_PX_PER_PLANE):
    """Aspect for an XZ or YZ panel, plus whether it is physically honest."""
    if z_stretch is None:
        z_stretch = auto_z_stretch(n_z, dz_um, lateral_um, n_lateral,
                                   panel_width_px, min_px_per_plane)
    z_stretch = float(max(z_stretch, 1e-6))
    # A stretch inside a couple of percent is not a distortion anyone can see;
    # calling it one would put a "not to scale" warning on a panel that is,
    # for every practical purpose, to scale.
    if abs(z_stretch - 1.0) <= TRUE_ASPECT_TOLERANCE:
        z_stretch = 1.0
    return OrthoAspect(aspect=true_z_aspect(dz_um, lateral_um) * z_stretch,
                       z_stretch=z_stretch,
                       physically_true=z_stretch == 1.0)


def z_stretch_label(aspect):
    """The caption a stretched panel must carry."""
    return aspect.label()


class DisplayTexture:
    """A decimated copy of a volume for drawing, with exact coordinate mapping.

    Z is never decimated: a confocal stack has tens of planes, not
    thousands, so the cost is entirely lateral. Every method that returns a
    coordinate returns it in FULL-RESOLUTION voxels, because anchors,
    snapping and all measurement live there - the decimation exists only so
    the screen redraw is cheap.
    """

    def __init__(self, volume, max_display_px=DEFAULT_MAX_DISPLAY_PX):
        volume = np.asarray(volume)
        if volume.ndim != 3:
            raise ValueError(
                f"DisplayTexture needs a (Z, Y, X) volume, got {volume.shape}.")
        self.full_shape = tuple(int(v) for v in volume.shape)
        n_lat = max(self.full_shape[1], self.full_shape[2])
        self.step = max(1, int(math.ceil(n_lat / float(max_display_px))))
        self._small = np.ascontiguousarray(volume[:, ::self.step, ::self.step])

    # -- the decimated arrays the panels actually draw -------------------
    @property
    def shape(self):
        return tuple(int(v) for v in self._small.shape)

    def xy_slice(self, z):
        return self._small[int(np.clip(z, 0, self.full_shape[0] - 1))]

    def xz_slice(self, y_full):
        """A (Z, X) panel at one full-resolution y."""
        return self._small[:, self._to_small(y_full, axis=1), :]

    def yz_slice(self, x_full):
        """A (Z, Y) panel at one full-resolution x."""
        return self._small[:, :, self._to_small(x_full, axis=2)]

    # -- coordinate mapping ----------------------------------------------
    def _to_small(self, full_index, axis):
        limit = self._small.shape[axis] - 1
        return int(np.clip(int(full_index) // self.step, 0, limit))

    def to_full(self, display_row, display_col):
        """Panel (row, col) -> full-resolution (y, x).

        Adds half a step so a click lands in the MIDDLE of the block of
        full-res pixels the drawn pixel represents, rather than its corner -
        otherwise every click is biased up and left by half a texel.
        """
        offset = (self.step - 1) / 2.0
        y = int(round(display_row * self.step + offset))
        x = int(round(display_col * self.step + offset))
        return (int(np.clip(y, 0, self.full_shape[1] - 1)),
                int(np.clip(x, 0, self.full_shape[2] - 1)))

    def to_display(self, full_y, full_x):
        """Full-resolution (y, x) -> panel (row, col), for drawing markers."""
        return (full_y / self.step, full_x / self.step)

    def memory_ratio(self):
        """How much cheaper a panel redraw became."""
        return float(self.step ** 2)

    def describe(self):
        z, y, x = self.full_shape
        _, sy, sx = self.shape
        return (f"display texture {sy}x{sx} from {y}x{x} "
                f"(1/{self.step} per axis, {self.memory_ratio():.0f}x fewer "
                f"pixels per redraw); clicks map back to full resolution")


def crosshair_positions(full_point_zyx, texture):
    """Where the crosshair sits in each panel, in that panel's own axes.

    Returned separately per panel because each has different axes: XY is
    (x, y), XZ is (x, z), YZ is (y, z). Getting these confused is the classic
    orthogonal-viewer bug where clicking one panel moves the wrong marker.
    """
    z, y, x = (int(v) for v in full_point_zyx)
    disp_y, disp_x = texture.to_display(y, x)
    return {
        "xy": (disp_x, disp_y),      # (col, row)
        "xz": (disp_x, z),           # (col, z)
        "yz": (disp_y, z),           # (col=y, z)
    }


def panel_click_to_full(panel, click_x, click_y, current_zyx, texture):
    """Turn a click in one panel into a full-resolution (z, y, x).

    Each panel constrains two of the three axes and leaves the third at its
    current value - clicking XZ sets x and z but keeps y, because y is what
    that panel is a slice THROUGH.
    """
    z, y, x = (int(v) for v in current_zyx)
    if panel == "xy":
        y_full, x_full = texture.to_full(click_y, click_x)
        return (z, y_full, x_full)
    if panel == "xz":
        _, x_full = texture.to_full(0, click_x)
        new_z = int(np.clip(round(click_y), 0, texture.full_shape[0] - 1))
        return (new_z, y, x_full)
    if panel == "yz":
        y_full, _ = texture.to_full(click_x, 0)
        new_z = int(np.clip(round(click_y), 0, texture.full_shape[0] - 1))
        return (new_z, y_full, x)
    raise ValueError(f"Unknown panel '{panel}' (expected xy, xz or yz).")
