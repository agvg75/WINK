"""The same shapes, done correctly. The scanner must NOT fire on these."""
import numpy as np


def derived_gate(area, ref):
    # Derived from the within-recording mask-area spread measured on
    # validated footage, not from taste.
    return 0.55 * ref <= area <= 1.60 * ref


def measured_depth(frame):
    # bit_depth = 8 is read from the file header, never assumed.
    bit_depth = int(frame.dtype.itemsize * 8)
    return frame / (2 ** bit_depth - 1)


def windowed_direction(frames):
    # Over frames: one frame reports posture, not illumination geometry.
    return np.mean([np.arctan2(*np.gradient(f)).mean() for f in frames[:25]])


def photometry_clean(raw, corrected, mask):
    # Segment on corrected, measure on RAW.
    return raw[mask].mean()


def loud_import():
    import cv2                       # noqa: F401
    raise SystemExit("cv2 missing: refuse rather than take another path")


def reachable_display(ax, frame, vmin, vmax):
    ax.imshow(frame, cmap="gray", vmin=vmin, vmax=vmax)
