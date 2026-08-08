"""Deliberate violations, one per rule. The scanner MUST catch every one.

A scanner nobody has seen fire is a scanner that might be matching nothing.
These fixtures exist so that "0 findings" is a result rather than a silence.
"""
import numpy as np


def pixel_scale():
    return 0.45 * 1100          # 0.45 px/um for this set


def reference_length():
    body = 495                  # 495 px body length
    return body


def area_gate(area, ref):
    return 0.55 * ref <= area <= 1.60 * ref


def bright_mask(image):
    threshold = 128.0
    return image > threshold


def normalise_frame(frame):
    bit_depth = 8
    return frame / (2 ** bit_depth - 1)


def single_frame_direction(frames):
    return np.arctan2(*np.gradient(frames[0])).mean()   # azimuth from frames[0]


def photometry_leak(corrected, mask):
    return corrected[mask].mean()


def runtime_fallback():
    try:
        import cv2
    except ImportError:
        cv2 = None
    return cv2


def unreachable_display(ax, frame):
    ax.imshow(frame, cmap="gray")


def handler_name_bound_in_try(path):
    # PLANTED: ContextError is imported inside the try its own handler
    # catches. If the import is what fails, the except clause raises
    # NameError while handling the error it exists to report.
    try:
        from analysis_context import ContextError
        return ContextError(path)
    except ContextError:
        return None
