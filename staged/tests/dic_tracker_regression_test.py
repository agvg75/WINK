"""Regression checks for clip cuts and authoritative manual polarity."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "afd_neuron"))
sys.path.insert(0, str(ROOT / "tools" / "worm_kinematics" / "dic_tracker"))

from worm_dic_tracker import DICWormTracker


def worm_frame(head, tail, background=128):
    image = np.full((120, 180), background, np.float32)
    # Static thin tracks should not become the animal.
    for y in (20, 35, 95):
        cv2.line(image, (5, y), (175, y+12), 145, 1)
        cv2.line(image, (5, y+2), (175, y+14), 112, 1)
    cv2.line(image, head, tail, 82, 18)
    cv2.circle(image, head, 10, 70, -1)
    image = cv2.GaussianBlur(image, (5, 5), 1)
    return image


frames = []
for i in range(12):
    frames.append(worm_frame((40+i, 70), (105+i, 70), 128))
# Hard cut: same worm reappears elsewhere and reversed in the image.
for i in range(12):
    frames.append(worm_frame((145-i, 45), (80-i, 45), 154))
G = np.stack(frames)

try:
    DICWormTracker(G, fps=10, um_per_px=0, fps_source="declared",
                   um_per_px_source="declared")
    raise AssertionError("zero scale was accepted")
except ValueError:
    pass

tracker = DICWormTracker(
    G, fps=10, um_per_px=2.35, fps_source="declared",
    um_per_px_source="declared", contrast_pct=88, thickness_iter=1, n_segments=12)
assert any(start >= 10 for start in tracker.clip_starts), tracker.clip_starts

tracker.track_all(head_seed=(40, 70))
cut = tracker.clip_starts[1]
assert tracker.state[cut]["needs_help"] == 1

# Clicking near the opposite endpoint must override previous-centerline matching.
clicked_head = (145, 45)
fixed = tracker.recompute_frame(cut, head=clicked_head)
assert np.hypot(fixed["head"][0]-clicked_head[0],
                fixed["head"][1]-clicked_head[1]) < 25
tracker.retrack_from(cut)
rows = tracker.export_rows()
assert "seg_width_px" in rows[0] and rows[0]["seg_width_px"] > 0
assert rows[0]["um_per_px"] == 2.35 and rows[0]["um_per_px_source"] == "declared"
next_state = tracker.state[cut+1]
assert np.hypot(next_state["head"][0]-144, next_state["head"][1]-45) < 30
print("DIC_REGRESSION_PASS", tracker.clip_starts, fixed["head"], next_state["head"])
