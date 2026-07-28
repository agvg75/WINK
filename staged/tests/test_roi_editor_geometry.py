from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
from roi_geometry import ellipse_polygon, line_polygon, rectangle_polygon


oval = np.asarray(ellipse_polygon(10, 20, 30, 60))
assert oval.shape == (72, 2)
assert np.allclose(oval[:, 0].min(), 10, atol=.05)
assert np.allclose(oval[:, 0].max(), 30, atol=.05)
assert np.allclose(oval[:, 1].min(), 20, atol=.05)
assert np.allclose(oval[:, 1].max(), 60, atol=.05)

rectangle = rectangle_polygon(30, 60, 10, 20)
assert rectangle == [[10, 20], [30, 20], [30, 60], [10, 60]]

line = np.asarray(line_polygon([0, 0], [20, 0], width=6))
assert line.shape == (4, 2)
assert np.allclose(line[:, 1].min(), -3)
assert np.allclose(line[:, 1].max(), 3)

print("ROI editor geometry regression passed")
