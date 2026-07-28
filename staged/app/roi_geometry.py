"""Pure geometry helpers shared by interactive ROI editors and tests."""
from __future__ import annotations

import numpy as np


def ellipse_polygon(x0, y0, x1, y1, n=72):
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
    angle = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + rx * np.cos(angle),
                            cy + ry * np.sin(angle)]).tolist()


def rectangle_polygon(x0, y0, x1, y1):
    left, right = sorted([float(x0), float(x1)])
    top, bottom = sorted([float(y0), float(y1)])
    return [[left, top], [right, top], [right, bottom], [left, bottom]]


def line_polygon(p0, p1, width=5.0):
    a, b = np.asarray(p0, float), np.asarray(p1, float)
    vector = b - a
    length = np.linalg.norm(vector)
    if length == 0:
        return []
    normal = np.array([-vector[1], vector[0]]) / length * width / 2
    return [(a + normal).tolist(), (b + normal).tolist(),
            (b - normal).tolist(), (a - normal).tolist()]
