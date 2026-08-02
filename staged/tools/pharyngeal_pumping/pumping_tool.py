"""
Reviewer-driven pharyngeal pumping quantification.

The operator chooses one image from a numbered sequence, marks the usable
interval, and draws a pharynx ROI. Only that approved interval is measured.
The detector stabilizes the ROI, derives a motion signal, and presents detected
pumps for threshold adjustment before CSV export.
"""
from __future__ import annotations

import csv
import os
import re
import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
from acquisition import AcquisitionMetadata
from acquisition_advisor import show_acquisition_advisor
from process_ui import (
    ProcessLog, ModuleWorkbench, MatplotlibProcessPanel,
    TkCanvasEllipseEditor, standardize_matplotlib_window, apply_wink_theme)
from inline_prompt import InlinePrompt
from scale_calibration_ui import ask_scale

import cv2
import numpy as np
from PIL import Image, ImageTk
from scipy import signal

import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from matplotlib.widgets import Slider


IMAGE_EXTS = {".tif", ".tiff", ".pgm", ".png", ".jpg", ".jpeg", ".bmp"}


def numbered_sequence(selected: Path) -> list[Path]:
    """Return only frames belonging to the selected recording prefix."""
    match = re.match(r"^(.*?)-(\d+)$", selected.stem)
    if not match:
        return [selected]
    prefix = match.group(1)
    candidates = []
    for path in selected.parent.iterdir():
        if path.suffix.lower() not in IMAGE_EXTS:
            continue
        m = re.match(r"^(.*?)-(\d+)$", path.stem)
        if m and m.group(1) == prefix:
            candidates.append((int(m.group(2)), path))
    return [p for _, p in sorted(candidates)]


def infer_fps(paths: list[Path], fallback: float = 30.0) -> float:
    if len(paths) < 2:
        return fallback
    try:
        # Whole-recording filesystem time is often distorted by network writes,
        # pauses, and batches sharing one timestamp. Estimate the initial native
        # cadence from a short run of positive adjacent deltas instead.
        sample = paths[:min(len(paths), 301)]
        stamps = np.asarray([p.stat().st_mtime for p in sample])
        deltas = np.diff(stamps)
        deltas = deltas[(deltas > .001) & (deltas < .5)]
        if len(deltas):
            center = np.median(deltas)
            local = deltas[(deltas >= center*.45) & (deltas <= center*2.2)]
            if len(local):
                fps = 1.0 / np.median(local)
                if 2 <= fps <= 200:
                    return float(fps)
    except OSError:
        pass
    return fallback


def read_gray(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        arr = np.asarray(im)
    if arr.ndim == 3:
        arr = arr[..., :3].mean(axis=2)
    if arr.dtype == np.uint8:
        return arr
    # PIL's direct I;16 -> L conversion clips nearly every microscopy pixel to
    # 255, producing a blank white display. Scale the actual numeric data using
    # robust per-frame limits; this also supports 12-bit cameras stored in
    # 16-bit TIFF/PGM containers.
    arr = arr.astype(np.float32)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return np.zeros(arr.shape, np.uint8)
    low, high = np.percentile(finite, (0.5, 99.5))
    if high <= low:
        low, high = float(finite.min()), float(finite.max())
    if high <= low:
        return np.zeros(arr.shape, np.uint8)
    scaled = (arr - low) * (255.0 / (high - low))
    return np.clip(scaled, 0, 255).astype(np.uint8)


def resize_for_display(frame: np.ndarray, max_w=900, max_h=620):
    h, w = frame.shape
    scale = min(max_w / w, max_h / h, 1.0)
    if scale < 1:
        shown = cv2.resize(frame, (round(w * scale), round(h * scale)),
                           interpolation=cv2.INTER_AREA)
    else:
        shown = frame
    return shown, scale


@dataclass
class PumpResult:
    trace: np.ndarray
    peaks: np.ndarray
    stabilized: list[np.ndarray]
    shifts: np.ndarray
    threshold: float
    method: str = "template_svd"
    diagnostics: dict = field(default_factory=dict)


@dataclass
class AutoResult:
    crops: list[np.ndarray]
    centers: np.ndarray
    movement: np.ndarray
    match: np.ndarray
    focus: np.ndarray
    contrast: np.ndarray
    usable: np.ndarray
    pumping: np.ndarray
    uncertain: np.ndarray
    trace: np.ndarray
    peaks: np.ndarray
    segments: list[tuple[int, int]]
    pump_segments: list[tuple[int, int]]
    settings: dict


def _register_crop(frame, reference, x0, y0, w, h, search=14):
    H, W = frame.shape
    sx0, sy0 = max(0, x0 - search), max(0, y0 - search)
    sx1, sy1 = min(W, x0 + w + search), min(H, y0 + h + search)
    area = frame[sy0:sy1, sx0:sx1]
    if area.shape[0] < h or area.shape[1] < w:
        return frame[y0:y0+h, x0:x0+w], (0, 0)
    score = cv2.matchTemplate(area, reference, cv2.TM_CCOEFF_NORMED)
    _, _, _, loc = cv2.minMaxLoc(score)
    xx, yy = sx0 + loc[0], sy0 + loc[1]
    return frame[yy:yy+h, xx:xx+w], (xx - x0, yy - y0)


def analyze(frames: list[np.ndarray], roi, fps: float,
            min_interval_s=0.13, prominence_scale=0.75) -> PumpResult:
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    reference = frames[0][y0:y1, x0:x1]
    if min(reference.shape) < 8:
        raise ValueError("The pharynx ROI is too small.")

    crops, shifts = [], []
    for frame in frames:
        crop, shift = _register_crop(frame, reference, x0, y0, w, h)
        crops.append(crop.astype(np.float32))
        shifts.append(shift)

    # Remove frame-wide brightness changes, then use the dominant temporal
    # deformation mode. This preserves grinder/lumen motion while suppressing
    # slow illumination and contrast drift.
    X = np.stack(crops)
    yy, xx = np.ogrid[:h, :w]
    ellipse = (((xx - (w - 1) / 2) / max(w / 2, 1)) ** 2 +
               ((yy - (h - 1) / 2) / max(h / 2, 1)) ** 2) <= 1
    outside_fill = np.median(X, axis=(1, 2), keepdims=True)
    X = np.where(ellipse[None, :, :], X, outside_fill)
    X -= np.median(X, axis=(1, 2), keepdims=True)
    flat = X.reshape(len(X), -1)
    window = max(3, int(round(fps * 0.8)) | 1)
    baseline = signal.medfilt(flat, kernel_size=(window, 1))
    detrended = flat - baseline
    detrended -= detrended.mean(axis=0, keepdims=True)

    try:
        u, s, _ = np.linalg.svd(detrended, full_matrices=False)
        trace = u[:, 0] * s[0]
    except np.linalg.LinAlgError:
        trace = np.mean(np.abs(np.diff(X, axis=0, prepend=X[:1])), axis=(1, 2))

    # Pick the polarity producing the clearer pump-like peaks.
    trace = signal.savgol_filter(trace, max(3, int(round(fps * 0.09)) | 1), 2)
    trace = signal.detrend(trace)
    mad = np.median(np.abs(trace - np.median(trace))) * 1.4826
    threshold = max(mad * prominence_scale, np.std(trace) * 0.18, 1e-9)
    distance = max(1, int(round(fps * min_interval_s)))
    pos, props_pos = signal.find_peaks(trace, distance=distance, prominence=threshold)
    neg, props_neg = signal.find_peaks(-trace, distance=distance, prominence=threshold)
    pos_strength = np.sum(props_pos.get("prominences", []))
    neg_strength = np.sum(props_neg.get("prominences", []))
    if neg_strength > pos_strength:
        trace = -trace
        peaks = neg
    else:
        peaks = pos

    return PumpResult(
        trace, peaks, crops, np.asarray(shifts), threshold,
        method="template_svd",
        diagnostics={
            "summary": "Template-stabilized ROI, temporal baseline removal, "
                       "dominant deformation mode by SVD.",
            "frames": len(frames),
            "roi_width_px": w,
            "roi_height_px": h,
            "minimum_pump_interval_s": min_interval_s,
            "prominence_scale": prominence_scale,
        })


def _smooth_motion_trace(trace: np.ndarray, fps: float) -> np.ndarray:
    trace = np.asarray(trace, dtype=np.float32)
    finite = np.isfinite(trace)
    if not np.any(finite):
        return np.zeros_like(trace)
    if not np.all(finite):
        x = np.arange(len(trace))
        trace = np.interp(x, x[finite], trace[finite]).astype(np.float32)
    win = max(3, int(round(fps * 0.09)) | 1)
    if win >= len(trace):
        win = max(3, (len(trace) - 1) | 1)
    if win >= 5:
        try:
            trace = signal.savgol_filter(trace, win, 2)
        except Exception:
            pass
    try:
        trace = signal.detrend(trace)
    except Exception:
        trace = trace - np.median(trace)
    return trace


def _pump_peaks_from_trace(trace: np.ndarray, fps: float,
                           min_interval_s: float,
                           prominence_scale: float):
    trace = _smooth_motion_trace(trace, fps)
    mad = np.median(np.abs(trace - np.median(trace))) * 1.4826
    threshold = max(mad * prominence_scale, np.std(trace) * 0.18, 1e-9)
    distance = max(1, int(round(fps * min_interval_s)))
    pos, props_pos = signal.find_peaks(trace, distance=distance, prominence=threshold)
    neg, props_neg = signal.find_peaks(-trace, distance=distance, prominence=threshold)
    pos_strength = np.sum(props_pos.get("prominences", []))
    neg_strength = np.sum(props_neg.get("prominences", []))
    if neg_strength > pos_strength:
        trace = -trace
        peaks = neg
    else:
        peaks = pos

    # PumpKin's useful biological constraint: a pump-like event should be
    # biphasic, not just any single twitch.  Keep peaks that have an opposite
    # trough shortly after them.  If the recording is too noisy for this test,
    # fall back to the one-phase peaks instead of returning nothing.
    troughs, _ = signal.find_peaks(-trace, distance=max(1, distance // 2),
                                   prominence=threshold * 0.55)
    max_lag = max(1, int(round(fps * 0.35)))
    biphasic = []
    for peak in peaks:
        after = troughs[(troughs > peak) & (troughs <= peak + max_lag)]
        if len(after):
            biphasic.append(int(peak))
    if len(biphasic) >= max(1, len(peaks) * 0.35):
        peaks = np.asarray(biphasic, dtype=int)
    return trace, peaks, threshold


def analyze_motion_compensated(frames: list[np.ndarray], roi, fps: float,
                               min_interval_s=0.13,
                               prominence_scale=0.75) -> PumpResult:
    """PumpKin-inspired local-motion detector without requiring ML weights.

    The ROI is first stabilized against the full bulb.  Inside the stabilized
    crop, Shi-Tomasi points are followed with Lucas-Kanade optical flow.  A
    RANSAC affine transform estimates residual whole-ROI motion, and the
    remaining local residual is treated as grinder/pharynx-specific motion.
    """
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    reference = frames[0][y0:y1, x0:x1]
    if min(reference.shape) < 12:
        raise ValueError("The pharynx ROI is too small for local-motion compensation.")

    crops, shifts = [], []
    for frame in frames:
        crop, shift = _register_crop(frame, reference, x0, y0, w, h,
                                     search=max(14, int(max(w, h) * 0.18)))
        crops.append(crop.astype(np.uint8))
        shifts.append(shift)

    residual_vectors = []
    feature_counts = []
    inlier_counts = []
    fallback_count = 0
    yy, xx = np.ogrid[:h, :w]
    central = (((xx - (w - 1) / 2) / max(w * 0.45, 1)) ** 2 +
               ((yy - (h - 1) / 2) / max(h * 0.45, 1)) ** 2) <= 1

    for prev, nxt in zip(crops[:-1], crops[1:]):
        mask = central.astype(np.uint8) * 255
        points = cv2.goodFeaturesToTrack(
            prev, maxCorners=90, qualityLevel=0.01, minDistance=3,
            blockSize=5, mask=mask)
        if points is None or len(points) < 6:
            fallback_count += 1
            residual_vectors.append([0.0, 0.0])
            feature_counts.append(0)
            inlier_counts.append(0)
            continue
        moved, status, _err = cv2.calcOpticalFlowPyrLK(prev, nxt, points, None)
        ok = status.reshape(-1).astype(bool) if status is not None else np.zeros(len(points), bool)
        p0 = points.reshape(-1, 2)[ok]
        p1 = moved.reshape(-1, 2)[ok] if moved is not None else np.empty((0, 2))
        if len(p0) < 6:
            fallback_count += 1
            residual_vectors.append([0.0, 0.0])
            feature_counts.append(len(p0))
            inlier_counts.append(0)
            continue
        affine, inliers = cv2.estimateAffinePartial2D(
            p0, p1, method=cv2.RANSAC, ransacReprojThreshold=2.0,
            maxIters=200)
        if affine is None:
            predicted = p0 + np.median(p1 - p0, axis=0)
            inlier_count = len(p0)
            fallback_count += 1
        else:
            predicted = cv2.transform(p0[None, :, :], affine)[0]
            inlier_count = int(inliers.sum()) if inliers is not None else len(p0)
        residual = p1 - predicted
        residual_vectors.append(np.median(residual, axis=0).tolist())
        feature_counts.append(len(p0))
        inlier_counts.append(inlier_count)

    vec = np.asarray(residual_vectors, dtype=np.float32)
    if len(vec) == 0:
        trace = np.zeros(len(frames), dtype=np.float32)
    else:
        centered = vec - np.nanmedian(vec, axis=0, keepdims=True)
        try:
            _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
            axis = vh[0]
        except np.linalg.LinAlgError:
            axis = np.array([1.0, 0.0], dtype=np.float32)
        pair_trace = centered @ axis
        trace = np.r_[pair_trace[:1], pair_trace]

    trace, peaks, threshold = _pump_peaks_from_trace(
        trace, fps, min_interval_s, prominence_scale)
    return PumpResult(
        trace, peaks, [c.astype(np.float32) for c in crops],
        np.asarray(shifts), threshold,
        method="local_motion_compensated",
        diagnostics={
            "summary": "PumpKin-inspired: template-stabilized ROI, "
                       "Shi-Tomasi/Lucas-Kanade local flow, RANSAC affine "
                       "motion compensation, biphasic peak filter.",
            "frames": len(frames),
            "roi_width_px": w,
            "roi_height_px": h,
            "median_features": float(np.median(feature_counts)) if feature_counts else 0.0,
            "median_inliers": float(np.median(inlier_counts)) if inlier_counts else 0.0,
            "fallback_pairs": int(fallback_count),
            "minimum_pump_interval_s": min_interval_s,
            "prominence_scale": prominence_scale,
        })


def interpolate_roi_trajectory(anchors, n_frames, roi_size, frame_shape):
    """Build a per-frame moving ROI from sparse user-dropped anchors.

    Parameters
    ----------
    anchors:
        Iterable of ``(frame_index, (cx, cy))`` giving the pharynx-ROI centre the
        user placed at particular frames.  Order does not matter; duplicate
        frames keep the last value.
    n_frames:
        Number of frames in the analysed interval.
    roi_size:
        ``(w, h)`` ROI size in pixels, held constant (the user corrects
        *position*, matching the drawn pharynx ROI).
    frame_shape:
        ``(H, W)`` of the frames, used to keep every box fully in bounds.

    Between consecutive anchors the ROI centre is linearly interpolated; before
    the first and after the last anchor the nearest anchor's centre is held
    (``np.interp`` endpoint behaviour).  With no anchors the ROI is centred in
    the frame.  Returns a list of ``(x0, y0, x1, y1)`` integer boxes of length
    ``n_frames``, each shifted inward so the full ``(w, h)`` stays on-image.
    """
    w, h = int(roi_size[0]), int(roi_size[1])
    H, W = int(frame_shape[0]), int(frame_shape[1])
    idx = np.arange(int(n_frames))
    clean = {}
    for frame, center in anchors or []:
        f = int(round(float(frame)))
        if 0 <= f < n_frames:
            clean[f] = (float(center[0]), float(center[1]))
    if clean:
        fs = np.array(sorted(clean), dtype=float)
        cxs = np.array([clean[int(f)][0] for f in fs], dtype=float)
        cys = np.array([clean[int(f)][1] for f in fs], dtype=float)
        cx_series = np.interp(idx, fs, cxs)
        cy_series = np.interp(idx, fs, cys)
    else:
        cx_series = np.full(n_frames, W / 2.0)
        cy_series = np.full(n_frames, H / 2.0)
    boxes = []
    for cx, cy in zip(cx_series, cy_series):
        x0 = int(round(cx - w / 2.0))
        y0 = int(round(cy - h / 2.0))
        # Shift inward (do not shrink) so every crop is exactly (h, w).
        x0 = max(0, min(x0, W - w))
        y0 = max(0, min(y0, H - h))
        boxes.append((x0, y0, x0 + w, y0 + h))
    return boxes


def _svd_deformation_trace(crops, w, h, fps):
    """Raw dominant-deformation trace from a stack of same-size ROI crops.

    This is the same temporal-baseline + SVD deformation signal used by
    :func:`analyze`, factored out so the moving-ROI (trajectory) analyzer reuses
    an identical formula.  Peak detection is intentionally left to
    :func:`_pump_peaks_from_trace`.
    """
    X = np.stack([np.asarray(c, dtype=np.float32) for c in crops])
    yy, xx = np.ogrid[:h, :w]
    ellipse = (((xx - (w - 1) / 2) / max(w / 2, 1)) ** 2 +
               ((yy - (h - 1) / 2) / max(h / 2, 1)) ** 2) <= 1
    outside_fill = np.median(X, axis=(1, 2), keepdims=True)
    X = np.where(ellipse[None, :, :], X, outside_fill)
    X -= np.median(X, axis=(1, 2), keepdims=True)
    flat = X.reshape(len(X), -1)
    window = max(3, int(round(fps * 0.8)) | 1)
    baseline = signal.medfilt(flat, kernel_size=(window, 1))
    detrended = flat - baseline
    detrended -= detrended.mean(axis=0, keepdims=True)
    try:
        u, s, _ = np.linalg.svd(detrended, full_matrices=False)
        trace = u[:, 0] * s[0]
    except np.linalg.LinAlgError:
        trace = np.mean(np.abs(np.diff(X, axis=0, prepend=X[:1])), axis=(1, 2))
    return trace


def _residual_flow_trace(crops, w, h):
    """Raw PumpKin-style local-residual-motion trace from uint8 ROI crops.

    Faithful extraction of the residual optical-flow signal used by
    :func:`analyze_motion_compensated`, so the moving-ROI (trajectory) analyzer
    can offer the same method.  ``crops`` must be uint8.  Peak detection is left
    to :func:`_pump_peaks_from_trace`.
    """
    residual_vectors = []
    yy, xx = np.ogrid[:h, :w]
    central = (((xx - (w - 1) / 2) / max(w * 0.45, 1)) ** 2 +
               ((yy - (h - 1) / 2) / max(h * 0.45, 1)) ** 2) <= 1
    for prev, nxt in zip(crops[:-1], crops[1:]):
        mask = central.astype(np.uint8) * 255
        points = cv2.goodFeaturesToTrack(
            prev, maxCorners=90, qualityLevel=0.01, minDistance=3,
            blockSize=5, mask=mask)
        if points is None or len(points) < 6:
            residual_vectors.append([0.0, 0.0])
            continue
        moved, status, _err = cv2.calcOpticalFlowPyrLK(prev, nxt, points, None)
        ok = status.reshape(-1).astype(bool) if status is not None else np.zeros(len(points), bool)
        p0 = points.reshape(-1, 2)[ok]
        p1 = moved.reshape(-1, 2)[ok] if moved is not None else np.empty((0, 2))
        if len(p0) < 6:
            residual_vectors.append([0.0, 0.0])
            continue
        affine, inliers = cv2.estimateAffinePartial2D(
            p0, p1, method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=200)
        if affine is None:
            predicted = p0 + np.median(p1 - p0, axis=0)
        else:
            predicted = cv2.transform(p0[None, :, :], affine)[0]
        residual = p1 - predicted
        residual_vectors.append(np.median(residual, axis=0).tolist())
    vec = np.asarray(residual_vectors, dtype=np.float32)
    if len(vec) == 0:
        return np.zeros(len(crops), dtype=np.float32)
    centered = vec - np.nanmedian(vec, axis=0, keepdims=True)
    try:
        _u, _s, vh = np.linalg.svd(centered, full_matrices=False)
        axis = vh[0]
    except np.linalg.LinAlgError:
        axis = np.array([1.0, 0.0], dtype=np.float32)
    pair_trace = centered @ axis
    return np.r_[pair_trace[:1], pair_trace]


def analyze_along_trajectory(frames, roi_by_frame, fps,
                             method="template_svd",
                             min_interval_s=0.13, prominence_scale=0.75,
                             refine_search=6):
    """Measure pumping while the ROI follows a user-defined pharynx trajectory.

    ``roi_by_frame`` is a per-frame list of ``(x0, y0, x1, y1)`` boxes (all the
    same size), typically from :func:`interpolate_roi_trajectory`.  Each frame is
    cropped at its own box, with a small local template refine around the
    predicted position so the crop snaps onto the bulb, and the resulting crop
    stack is fed through the same deformation-trace + pump-peak formula as the
    static analyzer.  Only the ROI *position* varies per frame; the pump-signal
    and detection maths are unchanged.
    """
    if len(roi_by_frame) != len(frames):
        raise ValueError("roi_by_frame must have one box per frame.")
    x0, y0, x1, y1 = roi_by_frame[0]
    w, h = x1 - x0, y1 - y0
    if min(w, h) < 8:
        raise ValueError("The pharynx ROI is too small.")
    reference = np.asarray(
        frames[0][y0:y1, x0:x1], dtype=np.float32)
    crops, shifts = [], []
    for frame, box in zip(frames, roi_by_frame):
        bx0, by0, bx1, by1 = box
        if refine_search and min(reference.shape) >= 8:
            crop, shift = _register_crop(
                frame, reference.astype(frame.dtype), bx0, by0, w, h,
                search=int(refine_search))
        else:
            crop, shift = frame[by0:by1, bx0:bx1], (0, 0)
        crop = np.asarray(crop, dtype=np.float32)
        if crop.shape != (h, w):
            # Edge fallback: pad to the reference size so the stack is regular.
            fixed = np.zeros((h, w), dtype=np.float32)
            fixed[:crop.shape[0], :crop.shape[1]] = crop[:h, :w]
            crop = fixed
        crops.append(crop)
        shifts.append(shift)
    if str(method).lower().startswith("motion"):
        crops_u8 = [np.clip(c, 0, 255).astype(np.uint8) for c in crops]
        trace = _residual_flow_trace(crops_u8, w, h)
        method_name = "guided_trajectory_motion"
        summary = ("User-anchored ROI trajectory (linear interpolation between "
                   "dropped anchors), local template refine, PumpKin-style "
                   "residual optical-flow trace, biphasic peak filter.")
    else:
        trace = _svd_deformation_trace(crops, w, h, fps)
        method_name = "guided_trajectory"
        summary = ("User-anchored ROI trajectory (linear interpolation between "
                   "dropped anchors), local template refine, dominant-"
                   "deformation trace, biphasic peak filter.")
    trace, peaks, threshold = _pump_peaks_from_trace(
        trace, fps, min_interval_s, prominence_scale)
    return PumpResult(
        trace, peaks, crops, np.asarray(shifts), threshold,
        method=method_name,
        diagnostics={
            "summary": summary,
            "frames": len(frames),
            "roi_width_px": int(w),
            "roi_height_px": int(h),
            "minimum_pump_interval_s": min_interval_s,
            "prominence_scale": prominence_scale,
        })


def _fill_short_false_gaps(mask: np.ndarray, max_gap: int) -> np.ndarray:
    result = mask.copy()
    i = 0
    while i < len(result):
        if result[i]:
            i += 1
            continue
        start = i
        while i < len(result) and not result[i]:
            i += 1
        if start > 0 and i < len(result) and i - start <= max_gap:
            result[start:i] = True
    return result


def _true_segments(mask: np.ndarray, minimum: int) -> list[tuple[int, int]]:
    segments = []
    i = 0
    while i < len(mask):
        if not mask[i]:
            i += 1
            continue
        start = i
        while i < len(mask) and mask[i]:
            i += 1
        if i - start >= minimum:
            segments.append((start, i))
    return segments


def pumping_occupancy(peaks, n_frames: int, fps: float,
                      max_pause_s: float = 1.0):
    """Convert pump events into active pumping bouts.

    Pumps separated by no more than max_pause_s belong to one bout. Bout edges
    extend by half a typical pump interval so occupancy measures time spent in
    the pumping state rather than only the zero-duration peak instants.
    """
    peaks = np.asarray(sorted(set(int(x) for x in peaks)), dtype=int)
    mask = np.zeros(n_frames, dtype=bool)
    if not len(peaks):
        return mask, []
    intervals = np.diff(peaks) / fps
    typical = float(np.median(intervals[intervals <= max_pause_s])) \
        if np.any(intervals <= max_pause_s) else 0.25
    pad = max(1, int(round(min(typical / 2, max_pause_s / 2) * fps)))
    max_gap = int(round(max_pause_s * fps))
    bouts = []
    start = last = int(peaks[0])
    for peak in peaks[1:]:
        peak = int(peak)
        if peak - last > max_gap:
            a, b = max(0, start-pad), min(n_frames, last+pad+1)
            mask[a:b] = True
            bouts.append((a, b))
            start = peak
        last = peak
    a, b = max(0, start-pad), min(n_frames, last+pad+1)
    mask[a:b] = True
    bouts.append((a, b))
    return mask, bouts


def _track_crop(frame, template, cx, cy, w, h, search):
    H, W = frame.shape
    x0 = int(round(cx - w / 2)); y0 = int(round(cy - h / 2))
    sx0, sy0 = max(0, x0 - search), max(0, y0 - search)
    sx1, sy1 = min(W, x0 + w + search), min(H, y0 + h + search)
    area = frame[sy0:sy1, sx0:sx1]
    if area.shape[0] < h or area.shape[1] < w:
        return None, cx, cy, 0.0
    scores = cv2.matchTemplate(area, template, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(scores)
    xx, yy = sx0 + loc[0], sy0 + loc[1]
    crop = frame[yy:yy+h, xx:xx+w]
    return crop, xx + w / 2, yy + h / 2, float(score)


def automatic_analysis(paths: list[Path], roi, fps: float, settings: dict,
                       progress=None) -> AutoResult:
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    first = read_gray(paths[0])
    template = first[y0:y1, x0:x1]
    if min(template.shape) < 12:
        raise ValueError("Draw a larger ROI around the complete terminal bulb.")

    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    crops, centers, movement, matches, focuses, contrasts = [], [], [], [], [], []
    previous = (cx, cy)
    search = max(8, int(round(max(w, h) * settings["search_fraction"])))

    for index, path in enumerate(paths):
        frame = read_gray(path)
        crop, cx_new, cy_new, score = _track_crop(
            frame, template, cx, cy, w, h, search)
        if crop is None or crop.shape != template.shape:
            crop = np.zeros_like(template)
            cx_new, cy_new, score = cx, cy, 0.0
        step = float(np.hypot(cx_new - previous[0], cy_new - previous[1]))
        focus = float(cv2.Laplacian(crop, cv2.CV_32F).var())
        contrast = float(crop.std())
        crops.append(crop)
        centers.append((cx_new, cy_new))
        movement.append(step)
        matches.append(score)
        focuses.append(focus)
        contrasts.append(contrast)
        previous = (cx_new, cy_new)
        cx, cy = cx_new, cy_new
        if score >= settings["template_update_match"] and step <= settings["movement_px"]:
            template = cv2.addWeighted(template, 0.98, crop, 0.02, 0)
        if progress and (index % 10 == 0 or index == len(paths) - 1):
            progress(index + 1, len(paths))

    centers = np.asarray(centers)
    movement = np.asarray(movement)
    matches = np.asarray(matches)
    focuses = np.asarray(focuses)
    contrasts = np.asarray(contrasts)

    trusted = matches >= max(settings["minimum_match"], np.quantile(matches, .35))
    if np.any(trusted):
        focus_ref = np.median(focuses[trusted])
        contrast_ref = np.median(contrasts[trusted])
    else:
        focus_ref = np.median(focuses)
        contrast_ref = np.median(contrasts)
    visible = (
        (matches >= settings["minimum_match"]) &
        (focuses >= focus_ref * settings["focus_fraction"]) &
        (contrasts >= contrast_ref * settings["contrast_fraction"])
    )
    still = movement <= settings["movement_px"]
    usable = visible & still
    usable = _fill_short_false_gaps(usable, settings["bridge_frames"])
    segments = _true_segments(
        usable, max(3, int(round(settings["minimum_segment_s"] * fps))))
    usable[:] = False
    for start, end in segments:
        usable[start:end] = True

    global_trace = np.full(len(paths), np.nan)
    all_peaks = []
    uncertain = np.zeros(len(paths), dtype=bool)
    for start, end in segments:
        segment_crops = crops[start:end]
        try:
            detected = analyze(
                segment_crops, (0, 0, w, h), fps,
                min_interval_s=settings["minimum_pump_interval_s"],
                prominence_scale=settings["pump_sensitivity"])
            global_trace[start:end] = detected.trace
            all_peaks.extend(start + detected.peaks)
            segment_noise = np.median(
                np.abs(detected.trace - np.median(detected.trace))) * 1.4826
            if segment_noise <= 1e-9 or np.std(detected.trace) <= 1e-9:
                uncertain[start:end] = True
        except Exception:
            uncertain[start:end] = True

    peaks = np.asarray(sorted(set(int(x) for x in all_peaks)), dtype=int)
    pumping, pump_segments = pumping_occupancy(
        peaks, len(paths), fps, settings["pumping_bout_gap_s"])
    pumping &= usable
    uncertain &= usable
    pumping &= ~uncertain
    pump_segments = _true_segments(pumping, 1)

    return AutoResult(
        crops, centers, movement, matches, focuses, contrasts, usable,
        pumping, uncertain, global_trace, peaks, segments, pump_segments,
        {**settings, "focus_reference": focus_ref,
         "contrast_reference": contrast_ref, "fps": fps})


class PumpingTool(tk.Tk):
    def __init__(self):
        super().__init__()
        apply_wink_theme(self)
        self.title("Pharyngeal Pumping")
        self.geometry("1000x780")
        self.paths: list[Path] = []
        self.fps = 30.0
        self.fps_source = "declared"
        self.um_per_px = 1.0
        self.um_per_px_source = "declared"
        self.exposure_ms = 5.0
        self.exposure_source = "declared"
        self.index = 0
        self.start = 0
        self.end = 0
        self.roi = None
        # Optional moving-ROI trajectory: absolute frame index -> (cx, cy) centre
        # in original image coordinates.  One anchor behaves exactly like the
        # classic fixed ROI; two or more make the ROI follow the pharynx by
        # interpolating between the dropped positions.  self.roi always holds the
        # ROI *size* (from the first draw).
        self.roi_anchors: dict[int, tuple[float, float]] = {}
        self.photo = None
        self.current_scale = 1.0
        self.result = None
        self.auto_result = None
        self._roi_anchor = None
        self._roi_preview = None
        self._ellipse_editor = None
        self.use_motion_compensation = tk.BooleanVar(value=True)
        self.pump_sensitivity = tk.DoubleVar(value=0.75)
        self.min_pump_interval_s = tk.DoubleVar(value=0.13)
        self.preview_max_dimension = tk.IntVar(value=900)
        self.process_log = ProcessLog("Pharyngeal pumping process")
        self._display_cache = OrderedDict()
        self._slide_job = None
        self._build()

    def _build(self):
        self.controls_visible = tk.BooleanVar(value=True)
        self.hood_visible = tk.BooleanVar(value=True)

        header = ttk.Frame(self)
        header.pack(fill="x", padx=8, pady=(8, 3))
        ttk.Button(header, text="< controls", command=self.toggle_controls).pack(side="left", padx=4)
        ttk.Label(
            header,
            text="Pharyngeal pumping cockpit: controls | image/ROI navigator | hood. "
                 "Keys: c hides controls, h hides hood.").pack(side="left", padx=8)
        ttk.Button(header, text="hood >", command=self.toggle_hood).pack(side="right", padx=4)

        main = ttk.Frame(self)
        main.pack(fill="both", expand=True, padx=8, pady=5)
        main.grid_columnconfigure(0, weight=0)
        main.grid_columnconfigure(1, weight=1)
        main.grid_columnconfigure(2, weight=0)
        main.grid_rowconfigure(0, weight=1)

        self.controls_frame = ttk.LabelFrame(main, text="Controls")
        self.controls_frame.grid(row=0, column=0, sticky="nsw", padx=(0, 5))
        # In-panel prompt host: value questions (fps, um/px, exposure, ...) are
        # rendered here at the top of the controls instead of as pop-up windows
        # that can hide behind the main window.
        self.prompt_host = ttk.Frame(self.controls_frame)
        self.prompt_host.pack(fill="x", side="top")
        self._prompt = InlinePrompt(self.prompt_host, self)
        self.center_frame = ttk.Frame(main)
        self.center_frame.grid(row=0, column=1, sticky="nsew", padx=3)
        self.center_frame.grid_columnconfigure(0, weight=1)
        self.center_frame.grid_rowconfigure(1, weight=1)
        self.hood_frame = ttk.LabelFrame(main, text="Hood: process and timing")
        self.hood_frame.grid(row=0, column=2, sticky="nse", padx=(5, 0))

        top = ttk.Frame(self.controls_frame); top.pack(fill="x", padx=6, pady=8)
        ttk.Button(top, text="1. Choose recording", command=self.choose).pack(fill="x", pady=2)
        ttk.Button(top, text="Choose folder", command=self.choose_folder).pack(fill="x", pady=2)
        ttk.Button(top, text="Set START", command=self.set_start).pack(fill="x", pady=(10, 2))
        ttk.Button(top, text="Set END", command=self.set_end).pack(fill="x", pady=2)
        ttk.Button(top, text="2. Draw / add pharynx ROI", command=self.draw_roi).pack(fill="x", pady=(10, 2))
        ttk.Button(top, text="Accept ROI", command=self.accept_roi_draw).pack(fill="x", pady=2)
        ttk.Button(top, text="Remove ROI here", command=self.remove_roi_anchor).pack(fill="x", pady=2)
        ttk.Button(top, text="Clear all ROIs", command=self.clear_roi).pack(fill="x", pady=2)
        ttk.Label(top, wraplength=205, justify="left", foreground="#555555",
                  text="One ROI = fixed window. To follow a moving pharynx, scroll "
                       "and draw again at each new position; the ROI path is "
                       "interpolated between the dropped positions.").pack(
                      fill="x", pady=(0, 2))
        ttk.Button(top, text="3. Analyze interval", command=self.run_analysis).pack(fill="x", pady=(10, 2))
        ttk.Button(top, text="3b. Review: move ROI along pharynx",
                   command=self.guided_review).pack(fill="x", pady=2)
        ttk.Button(top, text="AUTO: full recording",
                   command=self.run_automatic).pack(fill="x", pady=2)
        ttk.Button(top, text="Calibrate scale (um/px)",
                   command=self.calibrate_scale).pack(fill="x", pady=(10, 2))
        ttk.Button(top, text="Before you film",
                   command=lambda: show_acquisition_advisor(self)).pack(fill="x", pady=(2, 2))

        options = ttk.LabelFrame(self.controls_frame, text="Analysis options")
        options.pack(fill="x", padx=6, pady=(0, 6))
        ttk.Checkbutton(
            options, text="Use PumpKin-style local motion compensation",
            variable=self.use_motion_compensation).pack(anchor="w", padx=6, pady=4)
        row = ttk.Frame(options); row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="Sensitivity").pack(side="left")
        ttk.Entry(row, textvariable=self.pump_sensitivity, width=7).pack(side="right")
        row = ttk.Frame(options); row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="Min interval (s)").pack(side="left")
        ttk.Entry(row, textvariable=self.min_pump_interval_s, width=7).pack(side="right")
        row = ttk.Frame(options); row.pack(fill="x", padx=6, pady=2)
        ttk.Label(row, text="Preview max px").pack(side="left")
        ttk.Entry(row, textvariable=self.preview_max_dimension, width=7).pack(side="right")

        self.status = ttk.Label(self, text="Choose one frame from a numbered image sequence.")
        self.status.pack(fill="x", padx=10, pady=(0, 4))
        # Tk discards callback errors to stderr under pythonw, so a failing
        # button looks like one that does nothing. Report them instead.
        try:
            from process_ui import install_error_reporting
            install_error_reporting(
                self, status=lambda m: self.status.config(text="Action failed: " + m))
        except Exception:
            pass
        self.canvas = tk.Canvas(self.center_frame, bg="#202020", highlightthickness=0)
        self.canvas.grid(row=1, column=0, sticky="nsew", padx=0, pady=4)
        # In-panel analysis graph: the trace + detected pumps appear here, below
        # the image, instead of in a separate pop-up window.  Hidden until an
        # interval is analysed.
        self.review_area = ttk.Frame(self.center_frame)
        self.review_area.grid(row=2, column=0, sticky="ew", pady=(2, 0))
        self.review_area.grid_columnconfigure(0, weight=1)
        self.trace_fig = Figure(figsize=(7.6, 2.6), dpi=100)
        self.trace_ax = self.trace_fig.add_subplot(111)
        self.trace_canvas = FigureCanvasTkAgg(self.trace_fig, master=self.review_area)
        self.trace_canvas.get_tk_widget().grid(row=0, column=0, sticky="ew")
        self.review_area.grid_remove()
        self.review_controls = None
        nav = ttk.Frame(self.center_frame)
        nav.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        ttk.Button(nav, text="Home", command=lambda: self.goto_frame(0)).pack(side="left")
        ttk.Button(nav, text="-10", command=lambda: self.step_frame(-10)).pack(side="left", padx=(4, 0))
        ttk.Button(nav, text="-1", command=lambda: self.step_frame(-1)).pack(side="left")
        ttk.Button(nav, text="+1", command=lambda: self.step_frame(1)).pack(side="left")
        ttk.Button(nav, text="+10", command=lambda: self.step_frame(10)).pack(side="left")
        ttk.Button(nav, text="End", command=lambda: self.goto_frame(len(self.paths) - 1)).pack(side="left", padx=(0, 10))
        ttk.Label(nav, text="Jump to frame").pack(side="left")
        self.jump_var = tk.StringVar(value="1")
        ttk.Entry(nav, textvariable=self.jump_var, width=8).pack(side="left", padx=4)
        ttk.Button(nav, text="Go", command=self.jump_to_frame).pack(side="left")
        self.slider = ttk.Scale(self, from_=0, to=1, orient="horizontal",
                                command=self.slide)
        self.slider.pack(fill="x", padx=10, pady=(0, 6))
        self.info = ttk.Label(self, text="")
        self.info.pack(fill="x", padx=10, pady=(0, 10))

        self.hood_text = tk.Text(self.hood_frame, width=40, height=28, wrap="word")
        self.hood_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.refresh_hood()

        for key, step in (("<Left>", -1), ("<Right>", 1),
                          ("<Prior>", -10), ("<Next>", 10)):
            self.bind(key, lambda _e, step=step: self.step_frame(step))
        self.bind("<Home>", lambda _e: self.goto_frame(0))
        self.bind("<End>", lambda _e: self.goto_frame(len(self.paths) - 1))
        self.bind("<Return>", lambda _e: self.jump_to_frame())
        self.bind("<c>", lambda _e: self.toggle_controls())
        self.bind("<C>", lambda _e: self.toggle_controls())
        self.bind("<h>", lambda _e: self.toggle_hood())
        self.bind("<H>", lambda _e: self.toggle_hood())

    def refresh_hood(self):
        try:
            self.hood_text.configure(state="normal")
            self.hood_text.delete("1.0", "end")
            self.hood_text.insert("1.0", self.process_log.as_text(max_rows=18))
            self.hood_text.configure(state="disabled")
        except Exception:
            pass

    def toggle_controls(self):
        if self.controls_visible.get():
            self.controls_frame.grid_remove()
            self.controls_visible.set(False)
        else:
            self.controls_frame.grid()
            self.controls_visible.set(True)

    def toggle_hood(self):
        if self.hood_visible.get():
            self.hood_frame.grid_remove()
            self.hood_visible.set(False)
        else:
            self.hood_frame.grid()
            self.hood_visible.set(True)

    def choose(self):
        name = filedialog.askopenfilename(
            parent=self,
            title="Choose one frame from the pumping recording",
            filetypes=[("Image sequences", "*.tif *.tiff *.pgm *.png *.jpg *.jpeg"),
                       ("All files", "*.*")])
        if not name:
            return
        selected = Path(name)
        self.paths = numbered_sequence(selected)
        self.fps = infer_fps(self.paths)
        entered = self._prompt.ask_float(
            "Frame rate",
            "Frames per second:\n\n"
            "This is estimated from early file-write cadence. Use the camera "
            "acquisition setting when known; network timestamps can be misleading.",
            initialvalue=round(self.fps, 3),
            minvalue=2, maxvalue=200)
        if entered is None:
            return
        self.fps = entered
        self.fps_source = "declared"
        if not self._ask_acquisition_details():
            return
        self.index = 0
        self.start = 0
        self.end = len(self.paths) - 1
        self.slider.configure(to=max(1, self.end))
        self.slider.set(0)
        self.roi = None
        self.roi_anchors = {}
        self._display_cache.clear()
        self.process_log = ProcessLog("Pharyngeal pumping process")
        self.process_log.add(
            "Loaded recording",
            f"{len(self.paths)} frame(s); fps={self.fps:.3f}; scale={self.um_per_px:g} um/px",
            status="done")
        self.refresh_hood()
        self.show()

    def choose_folder(self):
        folder = filedialog.askdirectory(parent=self, title="Choose a folder containing one pumping recording")
        if not folder:
            return
        self.status.config(
            text="Indexing the folder in the background. Large archives may take several seconds...")
        threading.Thread(
            target=self._scan_folder_worker, args=(Path(folder),), daemon=True).start()

    def _scan_folder_worker(self, folder: Path):
        groups = {}
        try:
            with os.scandir(folder) as entries:
                for entry in entries:
                    if not entry.is_file():
                        continue
                    path = Path(entry.path)
                    if path.suffix.lower() not in IMAGE_EXTS:
                        continue
                    match = re.match(r"^(.*?)-(\d+)$", path.stem)
                    key = match.group(1) if match else path.stem
                    groups.setdefault(key, []).append(path)
            self.after(0, lambda: self._folder_scan_complete(folder, groups))
        except Exception as exc:
            text = str(exc)
            self.after(0, lambda text=text: messagebox.showerror("Folder scan failed", text))

    def _folder_scan_complete(self, folder: Path, groups: dict):
        if not groups:
            messagebox.showerror("No frames found", "No supported image frames were found.")
            return
        if len(groups) == 1:
            self._load_group(next(iter(groups.values())))
            return
        picker = tk.Toplevel(self)
        picker.title("Choose one recording")
        picker.geometry("620x360")
        ttk.Label(
            picker,
            text=f"{len(groups)} recordings were found in {folder.name}. "
                 "Choose one sequence to analyze.",
            wraplength=580).pack(fill="x", padx=12, pady=10)
        box = tk.Listbox(picker, font=("Consolas", 10))
        box.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        ordered = sorted(groups.items())
        for key, paths in ordered:
            box.insert("end", f"{key}    ({len(paths):,} frames)")

        def accept():
            selection = box.curselection()
            if not selection:
                return
            paths = ordered[selection[0]][1]
            picker.destroy()
            self._load_group(paths)

        ttk.Button(picker, text="Load selected recording", command=accept).pack(pady=(0, 12))
        box.bind("<Double-Button-1>", lambda _e: accept())
        box.selection_set(0)
        box.focus_set()

    def _load_group(self, paths):
        def frame_number(path):
            match = re.search(r"(\d+)$", path.stem)
            return int(match.group(1)) if match else 0
        self.paths = sorted(paths, key=frame_number)
        self.fps = infer_fps(self.paths)
        entered = self._prompt.ask_float(
            "Frame rate",
            "Frames per second:\n\n"
            "This is estimated from early file-write cadence. Use the camera "
            "acquisition setting when known; network timestamps can be misleading.",
            initialvalue=round(self.fps, 3),
            minvalue=2, maxvalue=200)
        if entered is None:
            return
        self.fps = entered
        self.fps_source = "declared"
        if not self._ask_acquisition_details():
            return
        self.index = self.start = 0
        self.end = len(self.paths) - 1
        self.slider.configure(to=max(1, self.end))
        self.slider.set(0)
        self.roi = None
        self.roi_anchors = {}
        self._display_cache.clear()
        self.process_log = ProcessLog("Pharyngeal pumping process")
        self.process_log.add(
            "Loaded recording",
            f"{len(self.paths)} frame(s); fps={self.fps:.3f}; scale={self.um_per_px:g} um/px",
            status="done")
        self.refresh_hood()
        self.show()

    def calibrate_scale(self):
        """Open the shared scale/magnification dialog and store the result."""
        frame = None
        if self.paths:
            try:
                frame = read_gray(self.paths[self.index])
            except Exception:
                frame = None
        res = ask_scale(self, frame=frame, initial_um_per_px=self.um_per_px)
        if res is None:
            return
        self.um_per_px = float(res["um_per_px"])
        self.um_per_px_source = res.get("source", "declared")
        self.process_log.add(
            "Scale calibrated",
            f"{self.um_per_px:.4f} um/px ({res.get('details', '')})",
            status="edit")
        self.refresh_hood()
        self.status.config(text=f"Scale set to {self.um_per_px:.4f} um/px.")

    def _ask_acquisition_details(self):
        scale = self._prompt.ask_float(
            "Spatial calibration",
            "Micrometers per pixel (enter the declared camera calibration):",
            initialvalue=self.um_per_px, minvalue=0.0001)
        if scale is None:
            return False
        exposure = self._prompt.ask_float(
            "Exposure",
            "Exposure time in milliseconds (enter the camera setting):",
            initialvalue=self.exposure_ms, minvalue=0.0001)
        if exposure is None:
            return False
        self.um_per_px = scale
        self.um_per_px_source = "declared"
        self.exposure_ms = exposure
        self.exposure_source = "declared"
        self.acquisition = AcquisitionMetadata(
            self.fps,self.fps_source,self.um_per_px,self.um_per_px_source,
            self.exposure_ms,self.exposure_source).validate()
        return True

    def slide(self, value):
        if not self.paths:
            return
        self.index = max(0, min(len(self.paths) - 1, int(float(value))))
        self.jump_var.set(str(self.index + 1))
        if self._slide_job is not None:
            try:
                self.after_cancel(self._slide_job)
            except Exception:
                pass
        self._slide_job = self.after(35, self.show)

    def step_frame(self, delta):
        if self.paths:
            self.goto_frame(self.index + int(delta))

    def goto_frame(self, index):
        if not self.paths:
            return
        self.index = max(0, min(len(self.paths) - 1, int(index)))
        self.slider.set(self.index)
        self.jump_var.set(str(self.index + 1))
        self.show()

    def jump_to_frame(self):
        if not self.paths:
            return
        try:
            value = int(float(self.jump_var.get()))
        except ValueError:
            messagebox.showwarning("Jump to frame", "Enter a source frame number.")
            return
        self.goto_frame(value - 1)

    def _display_frame(self, index):
        max_dim = max(256, int(self.preview_max_dimension.get() or 900))
        key = (int(index), int(max_dim))
        cached = self._display_cache.get(key)
        if cached is not None:
            self._display_cache.move_to_end(key)
            return cached
        frame = read_gray(self.paths[index])
        shown, scale = resize_for_display(frame, max_w=max_dim, max_h=max_dim)
        self._display_cache[key] = (shown, scale)
        while len(self._display_cache) > 24:
            self._display_cache.popitem(last=False)
        return shown, scale

    def show(self):
        if not self.paths:
            return
        shown, self.current_scale = self._display_frame(self.index)
        im = Image.fromarray(shown)
        self.photo = ImageTk.PhotoImage(im)
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        s = self.current_scale
        if self.roi and len(self.roi_anchors) >= 2:
            # Moving ROI: draw the interpolated path, numbered anchor markers, and
            # the ROI box at its interpolated position for the current frame.
            w = self.roi[2] - self.roi[0]
            h = self.roi[3] - self.roi[1]
            fs = sorted(self.roi_anchors)
            path = []
            for f in fs:
                ax, ay = self.roi_anchors[f]
                path.extend([ax * s, ay * s])
            if len(path) >= 4:
                self.canvas.create_line(*path, fill="#00CCFF", width=1, dash=(4, 3))
            for i, f in enumerate(fs, start=1):
                ax, ay = self.roi_anchors[f]
                self.canvas.create_oval(ax * s - 3, ay * s - 3, ax * s + 3, ay * s + 3,
                                        outline="#00CCFF", fill="#00CCFF")
                self.canvas.create_text(ax * s + 6, ay * s - 6, text=str(i),
                                        fill="#00CCFF", anchor="w")
            center = self._roi_center_at(self.index)
            if center is not None:
                cx, cy = center
                edge = "#00FF66" if int(self.index) in self.roi_anchors else "#FFCC00"
                self.canvas.create_oval(
                    (cx - w / 2.0) * s, (cy - h / 2.0) * s,
                    (cx + w / 2.0) * s, (cy + h / 2.0) * s,
                    outline=edge, width=2)
        elif self.roi:
            x0, y0, x1, y1 = [v * s for v in self.roi]
            self.canvas.create_oval(x0, y0, x1, y1, outline="#00FF66", width=2)
        self.info.config(
            text=f"Frame {self.index + 1}/{len(self.paths)}   "
                 f"time {self.index/self.fps:.2f} s   "
                 f"approved interval {self.start/self.fps:.2f}–{self.end/self.fps:.2f} s   "
                 f"{self.fps:.3f} fps   "
                 "keys: Left/Right=1 frame, PgUp/PgDn=10, Home/End, Enter=jump")

    def set_start(self):
        self.start = self.index
        if self.end < self.start:
            self.end = self.start
        self.show()

    def set_end(self):
        self.end = self.index
        if self.end < self.start:
            self.start = self.end
        self.show()

    def draw_roi(self):
        if not self.paths:
            return
        self._finish_roi_draw()
        self.show()
        self.status.config(
            text="Draw or adjust the semi-transparent oval around the terminal bulb/pharynx. "
                 "Drag handles to resize, drag inside to move, then press Enter/Accept.")
        self.process_log.add(
            "ROI editor opened",
            "Editable oval: drag to draw, handles resize, center/inside moves. "
            "Enter accepts; right-click/Esc cancels.",
            status="edit")
        self.refresh_hood()
        initial = None
        if self.roi:
            initial = tuple(v * self.current_scale for v in self.roi)
        self._ellipse_editor = TkCanvasEllipseEditor(
            self.canvas,
            on_accept=self._roi_accept,
            on_cancel=self._roi_cancel,
            on_message=lambda text: self.status.config(text=text),
            min_size=8)
        self._ellipse_editor.start(initial)

    def accept_roi_draw(self):
        if self._ellipse_editor is not None:
            self._ellipse_editor.accept()

    def _roi_accept(self, bbox):
        scale = self.current_scale
        x0, y0, x1, y1 = bbox
        box_orig = tuple(int(round(v / scale)) for v in (x0, y0, x1, y1))
        cx = (box_orig[0] + box_orig[2]) / 2.0
        cy = (box_orig[1] + box_orig[3]) / 2.0
        self.roi_anchors[int(self.index)] = (cx, cy)
        # The first draw (or a redraw while there is still a single anchor) also
        # defines the ROI *size*; once two or more anchors exist the size is
        # locked so the box that travels the path stays a constant window.
        if self.roi is None or len(self.roi_anchors) == 1:
            self.roi = box_orig
        self._ellipse_editor = None
        n = len(self.roi_anchors)
        if n >= 2:
            self.status.config(
                text=f"ROI position {n} saved (moving ROI). Scroll and draw again "
                     "to add more, or Analyze to measure along the path.")
            self.process_log.add(
                "ROI anchor added",
                f"{n} anchors; ROI now follows the pharynx along the "
                "interpolated path between dropped positions.",
                status="edit")
        else:
            self.status.config(
                text="ROI saved. Mark the interval and Analyze, or scroll and draw "
                     "again at a new pharynx position to make the ROI follow it.")
            self.process_log.add(
                "ROI saved",
                f"x={self.roi[0]}-{self.roi[2]}, y={self.roi[1]}-{self.roi[3]}",
                status="edit")
        self.refresh_hood()
        self.show()

    def _roi_center_at(self, frame):
        """Interpolate the ROI centre (original coords) at an absolute frame."""
        if not self.roi_anchors:
            return None
        fs = sorted(self.roi_anchors)
        if len(fs) == 1:
            return self.roi_anchors[fs[0]]
        xs = [self.roi_anchors[f][0] for f in fs]
        ys = [self.roi_anchors[f][1] for f in fs]
        return (float(np.interp(frame, fs, xs)),
                float(np.interp(frame, fs, ys)))

    def remove_roi_anchor(self):
        """Delete the ROI anchor at the current frame, if any."""
        key = int(self.index)
        if key in self.roi_anchors:
            del self.roi_anchors[key]
            if not self.roi_anchors:
                self.roi = None
            self.process_log.add(
                "ROI anchor removed",
                f"{len(self.roi_anchors)} anchor(s) remain.", status="edit")
            self.refresh_hood()
            self.status.config(text="Removed the ROI position at this frame.")
            self.show()
        else:
            self.status.config(text="No ROI anchor at this frame to remove.")

    def _roi_cancel(self):
        self._ellipse_editor = None
        self.status.config(
            text="ROI editing canceled. Existing ROI was preserved; click Draw pharynx ROI to try again.")
        self.process_log.add("ROI editing canceled", "Existing ROI preserved.", status="edit")
        self.refresh_hood()
        self.show()

    def _finish_roi_draw(self):
        if self._ellipse_editor is not None:
            try:
                self._ellipse_editor.stop()
            except Exception:
                pass
            self._ellipse_editor = None
        self.canvas.delete("roi_preview")
        self._roi_preview = None
        self._roi_anchor = None

    def cancel_roi_draw(self, _event=None):
        if self._ellipse_editor is not None:
            self._ellipse_editor.cancel()
            return
        self._finish_roi_draw()
        self.status.config(text="ROI drawing canceled. Existing ROI was preserved; click Draw pharynx ROI to try again.")
        self.process_log.add("ROI drawing canceled", "Existing ROI preserved.", status="edit")
        self.refresh_hood()
        self.show()

    def clear_roi(self):
        self.cancel_roi_draw()
        self.roi = None
        self.roi_anchors = {}
        self.result = None
        self.auto_result = None
        self.status.config(text="ROI cleared. Click Draw pharynx ROI and place a new oval.")
        self.process_log.add("ROI cleared", "Draw a new pharynx ROI (or ROI path) before analyzing.", status="edit")
        self.refresh_hood()
        self.show()

    def run_analysis(self):
        if not self.paths or not self.roi:
            messagebox.showerror("Missing selection", "Choose a recording and draw the pharynx ROI.")
            return
        if self.end - self.start + 1 < max(20, int(self.fps * 2)):
            messagebox.showerror("Interval too short", "Choose at least two seconds of visible pumping.")
            return
        self.status.config(text="Loading and analyzing only the approved interval...")
        self.update_idletasks()
        try:
            self.process_log = ProcessLog("Pharyngeal pumping process")
            self.refresh_hood()
            with self.process_log.timed(
                    "Load approved interval",
                    f"frames {self.start + 1}-{self.end + 1}"):
                frames = [read_gray(p) for p in self.paths[self.start:self.end + 1]]
            self.refresh_hood()
            sensitivity = float(self.pump_sensitivity.get())
            min_interval = float(self.min_pump_interval_s.get())
            n = len(frames)
            H, W = frames[0].shape[:2]
            rel_anchors = [(int(f) - self.start, c)
                           for f, c in self.roi_anchors.items()
                           if self.start <= int(f) <= self.end]
            if len(rel_anchors) >= 2:
                w = self.roi[2] - self.roi[0]
                h = self.roi[3] - self.roi[1]
                roi_by_frame = interpolate_roi_trajectory(
                    rel_anchors, n, (w, h), (H, W))
                method = ("motion_compensated"
                          if self.use_motion_compensation.get()
                          else "template_svd")
                with self.process_log.timed(
                        "Analyze moving ROI (trajectory)",
                        f"{len(rel_anchors)} anchors; ROI follows the interpolated "
                        "pharynx path, local template refine per frame"):
                    self.result = analyze_along_trajectory(
                        frames, roi_by_frame, self.fps, method=method,
                        min_interval_s=min_interval,
                        prominence_scale=sensitivity)
                self.refresh_hood()
            elif self.use_motion_compensation.get():
                with self.process_log.timed(
                        "Analyze local residual motion",
                        "PumpKin-style ROI stabilization, optical flow, affine "
                        "motion compensation, biphasic event filter"):
                    self.result = analyze_motion_compensated(
                        frames, self.roi, self.fps,
                        min_interval_s=min_interval,
                        prominence_scale=sensitivity)
                self.refresh_hood()
            else:
                with self.process_log.timed(
                        "Analyze template/SVD signal",
                        "Legacy template-stabilized ROI and dominant temporal "
                        "deformation mode"):
                    self.result = analyze(
                        frames, self.roi, self.fps,
                        min_interval_s=min_interval,
                        prominence_scale=sensitivity)
                self.refresh_hood()
            self.process_log.add(
                "Detected candidate pumps",
                f"{len(self.result.peaks)} events before user review; "
                f"method={self.result.method}",
                status="done")
            self.refresh_hood()
            self._show_inpanel_review()
        except Exception as exc:
            self.process_log.add("Analysis failed", str(exc), status="failed")
            self.refresh_hood()
            messagebox.showerror("Analysis failed", str(exc))

    def _automatic_settings(self):
        movement = self._prompt.ask_float(
            "Stillness threshold",
            "Maximum pharynx movement between frames (pixels).\n"
            "Lower is stricter; 2–3 pixels is a reasonable starting range.",
            initialvalue=2.5, minvalue=0.25, maxvalue=50)
        if movement is None:
            return None
        sensitivity = self._prompt.ask_float(
            "Pump sensitivity",
            "Pump detection threshold multiplier.\n"
            "Lower detects more events; higher is more conservative.",
            initialvalue=0.75, minvalue=0.2, maxvalue=3.0)
        if sensitivity is None:
            return None
        return {
            "movement_px": float(movement),
            "minimum_match": 0.42,
            "template_update_match": 0.72,
            "focus_fraction": 0.38,
            "contrast_fraction": 0.45,
            "search_fraction": 0.45,
            "bridge_frames": max(1, int(round(self.fps * .10))),
            "minimum_segment_s": 1.0,
            "minimum_pump_interval_s": 0.13,
            "pump_sensitivity": float(sensitivity),
            "pumping_bout_gap_s": 1.0,
            "isolated_pump_window_s": 0.5,
        }

    def run_automatic(self):
        if not self.paths or not self.roi:
            messagebox.showerror(
                "Missing selection",
                "Choose a recording and draw the complete terminal-bulb ROI first.")
            return
        settings = self._automatic_settings()
        if settings is None:
            return

        def progress(done, total):
            self.status.config(
                text=f"Automatic analysis: tracking frame {done:,}/{total:,}...")
            self.update_idletasks()

        try:
            self.process_log = ProcessLog("Pharyngeal pumping process")
            self.process_log.add(
                "Automatic analysis started",
                "Tracking ROI stability and pump signal across the full recording.",
                status="running")
            self.refresh_hood()
            self.auto_result = automatic_analysis(
                self.paths, self.roi, self.fps, settings, progress)
            self.process_log.add(
                "Automatic analysis finished",
                f"{len(self.auto_result.peaks)} pump candidate(s) detected.",
                status="done")
            self.refresh_hood()
            self._show_automatic_summary()
        except Exception as exc:
            self.process_log.add("Automatic analysis failed", str(exc), status="failed")
            self.refresh_hood()
            messagebox.showerror("Automatic analysis failed", str(exc))

    def _auto_metrics(self):
        r = self.auto_result
        total = len(self.paths)
        usable_n = int(r.usable.sum())
        pumping_n = int(r.pumping.sum())
        uncertain_n = int(r.uncertain.sum())
        nonpumping_n = max(0, usable_n - pumping_n - uncertain_n)
        duration = total / self.fps
        usable_s = usable_n / self.fps
        pumping_s = pumping_n / self.fps
        intervals = np.diff(r.peaks) / self.fps
        return {
            "total_frames": total,
            "duration_s": duration,
            "usable_frames": usable_n,
            "usable_duration_s": usable_s,
            "usable_fraction": usable_n / total if total else 0,
            "pump_count": len(r.peaks),
            "pumps_per_min_usable": (
                len(r.peaks) / usable_s * 60 if usable_s > 0 else np.nan),
            "pumping_frequency_hz_usable": (
                len(r.peaks) / usable_s if usable_s > 0 else np.nan),
            "mean_interpump_s": (
                float(np.mean(intervals)) if len(intervals) else np.nan),
            "median_interpump_s": (
                float(np.median(intervals)) if len(intervals) else np.nan),
            "interpump_sd_s": (
                float(np.std(intervals, ddof=1)) if len(intervals) > 1 else np.nan),
            "interpump_cv": (
                float(np.std(intervals, ddof=1) / np.mean(intervals))
                if len(intervals) > 1 and np.mean(intervals) > 0 else np.nan),
            "pumping_duration_s": pumping_s,
            "pumping_fraction_of_usable": (
                pumping_n / usable_n if usable_n else np.nan),
            "detectable_nonpumping_duration_s": nonpumping_n / self.fps,
            "detectable_nonpumping_fraction_of_usable": (
                nonpumping_n / usable_n if usable_n else np.nan),
            "uncertain_duration_s": uncertain_n / self.fps,
            "uncertain_fraction_of_usable": (
                uncertain_n / usable_n if usable_n else np.nan),
            "usable_segments": len(r.segments),
            "pumping_bouts": len(r.pump_segments),
        }

    def _show_automatic_summary(self):
        m = self._auto_metrics()
        text = (
            f"Usable recording: {m['usable_duration_s']:.1f} s "
            f"({m['usable_fraction']*100:.1f}%)\n"
            f"Detected pumps: {m['pump_count']} "
            f"({m['pumping_frequency_hz_usable']:.3f} Hz during usable time)\n"
            f"Pumping: {m['pumping_fraction_of_usable']*100:.1f}% of usable time\n"
            f"Detectable but not pumping: "
            f"{m['detectable_nonpumping_fraction_of_usable']*100:.1f}%\n"
            f"Uncertain: {m['uncertain_fraction_of_usable']*100:.1f}%\n\n"
            "Save the frame states, segments, pump events, summary, and timeline?")
        if messagebox.askyesno("Automatic pumping analysis", text):
            self.save_automatic()

    def save_automatic(self):
        r = self.auto_result
        m = self._auto_metrics()
        parent = filedialog.askdirectory(
            parent=self, title="Choose output folder", initialdir=str(self.paths[0].parent))
        if not parent:
            return
        stem = self.paths[0].stem.rsplit("-", 1)[0]
        out = Path(parent) / f"{stem}_pumping_output"
        out.mkdir(parents=True, exist_ok=True)

        with open(out / "pumping_summary.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["metric", "value"])
            writer.writerow(["source", str(self.paths[0].parent)])
            writer.writerow(["fps", self.fps])
            writer.writerow(["fps_source", self.fps_source])
            writer.writerow(["um_per_px", self.um_per_px])
            writer.writerow(["um_per_px_source", self.um_per_px_source])
            writer.writerow(["exposure_ms", self.exposure_ms])
            writer.writerow(["exposure_source", self.exposure_source])
            for key, value in m.items():
                writer.writerow([key, value])
            for key, value in r.settings.items():
                writer.writerow([f"setting_{key}", value])

        segment_id = np.full(len(self.paths), -1, dtype=int)
        for number, (start, end) in enumerate(r.segments, 1):
            segment_id[start:end] = number
        peak_set = set(r.peaks.tolist())
        with open(out / "pumping_frame_states.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "frame", "time_s", "pharynx_x", "pharynx_y",
                "movement_px", "tracking_match", "focus", "contrast",
                "usable", "pumping", "uncertain", "pump_event",
                "segment_id", "pump_signal", "fps", "fps_source",
                "um_per_px", "um_per_px_source", "exposure_ms",
                "exposure_source"])
            for i in range(len(self.paths)):
                writer.writerow([
                    i, i / self.fps, r.centers[i, 0], r.centers[i, 1],
                    r.movement[i], r.match[i], r.focus[i], r.contrast[i],
                    int(r.usable[i]), int(r.pumping[i]), int(r.uncertain[i]),
                    int(i in peak_set), segment_id[i],
                    "" if np.isnan(r.trace[i]) else r.trace[i],
                    self.fps, self.fps_source, self.um_per_px,
                    self.um_per_px_source, self.exposure_ms,
                    self.exposure_source])

        with open(out / "pumping_segments.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "segment_id", "start_frame", "end_frame", "start_s", "end_s",
                "duration_s", "pump_count", "pumps_per_min", "fps",
                "fps_source", "um_per_px", "um_per_px_source",
                "exposure_ms", "exposure_source"])
            for number, (start, end) in enumerate(r.segments, 1):
                count = int(np.sum((r.peaks >= start) & (r.peaks < end)))
                duration = (end - start) / self.fps
                writer.writerow([
                    number, start, end - 1, start / self.fps, end / self.fps,
                    duration, count, count / duration * 60 if duration else np.nan,
                    self.fps, self.fps_source, self.um_per_px,
                    self.um_per_px_source, self.exposure_ms,
                    self.exposure_source])

        with open(out / "pumping_events.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "pump_number", "frame", "time_s", "signal", "fps",
                "fps_source", "um_per_px", "um_per_px_source",
                "exposure_ms", "exposure_source"])
            for number, peak in enumerate(r.peaks, 1):
                writer.writerow([
                    number, peak, peak / self.fps, r.trace[peak],
                    self.fps, self.fps_source, self.um_per_px,
                    self.um_per_px_source, self.exposure_ms,
                    self.exposure_source])

        self._save_timeline(out / "pumping_timeline.png")
        self.status.config(text=f"Automatic results saved to {out}")

    def _save_timeline(self, path):
        r = self.auto_result
        t = np.arange(len(self.paths)) / self.fps
        fig, axes = plt.subplots(3, 1, figsize=(12, 7), sharex=True)
        axes[0].plot(t, r.movement, color="#555555", lw=.7)
        axes[0].axhline(r.settings["movement_px"], color="#990000", ls="--")
        axes[0].set_ylabel("ROI movement (px)")
        axes[1].plot(t, r.trace, color="#7d0000", lw=.7)
        if len(r.peaks):
            axes[1].plot(t[r.peaks], r.trace[r.peaks], "o", ms=3, color="#00804b")
        axes[1].set_ylabel("Pump signal")
        state = np.zeros(len(t))
        state[r.usable] = 1
        state[r.pumping] = 2
        state[r.uncertain] = 3
        axes[2].step(t, state, where="post", color="#7d0000")
        axes[2].set_yticks([0, 1, 2, 3],
                           ["unusable", "usable/no pump", "pumping", "uncertain"])
        axes[2].set_xlabel("Time (s)")
        axes[2].set_ylabel("State")
        fig.tight_layout()
        fig.savefig(path, dpi=160)
        plt.close(fig)

    def guided_review(self):
        """Rebuilt guided review: the pharynx ROI follows user-dropped anchors.

        Scroll the interval; the ROI box is drawn on every frame and turns green
        (blinking) on frames where a pump was counted.  Click the pharynx to drop
        or move an anchor at the current frame; Reanalyze interpolates the ROI
        trajectory between anchors and re-counts pumps in every intervening
        frame.  This is the correctable, visually-inspectable review the older
        tool had, rebuilt on the tested trajectory core.
        """
        if not self.paths or not self.roi:
            messagebox.showerror(
                "Missing selection",
                "Choose a recording and draw the pharynx ROI first.")
            return
        if self.end - self.start + 1 < max(20, int(self.fps * 2)):
            messagebox.showerror(
                "Interval too short",
                "Choose at least two seconds of visible pumping.")
            return
        self.status.config(text="Loading interval for guided review...")
        self.update_idletasks()
        try:
            frames = [read_gray(p) for p in self.paths[self.start:self.end + 1]]
        except Exception as exc:
            messagebox.showerror("Load failed", str(exc))
            return
        n = len(frames)
        H, W = frames[0].shape[:2]
        x0, y0, x1, y1 = [int(v) for v in self.roi]
        w, h = x1 - x0, y1 - y0
        if min(w, h) < 8:
            messagebox.showerror("ROI too small", "Draw a larger pharynx ROI.")
            return
        fps = float(self.fps)
        min_interval = float(self.min_pump_interval_s.get())
        sensitivity = float(self.pump_sensitivity.get())

        # Carry any anchors dropped before analysis into review (interval-
        # relative); fall back to a single centre anchor if none were placed.
        seed = {}
        for f, (cx, cy) in self.roi_anchors.items():
            rel = int(f) - int(self.start)
            if 0 <= rel < n:
                seed[rel] = (float(cx), float(cy))
        if not seed:
            seed = {0: ((x0 + x1) / 2.0, (y0 + y1) / 2.0)}
        state = {
            "anchors": seed,
            "frame": 0, "threshold_mult": 1.0, "result": None,
            "roi_by_frame": None, "blink": True, "saved": False,
            "method": ("motion_compensated"
                       if self.use_motion_compensation.get() else "template_svd"),
        }

        proc = ProcessLog("Guided pharyngeal review")
        proc.add(
            "Guided review",
            "Scroll the movie; click the pharynx to drop/move an anchor; "
            "Reanalyze connects anchors and re-counts pumps.", status="ready")
        wb = ModuleWorkbench(
            self, "Guided pharyngeal review (drop anchors)", proc,
            width=1400, height=920)
        fig = wb.fig
        fig.clear()
        gs = fig.add_gridspec(3, 1, hspace=0.38)
        ax_img = fig.add_subplot(gs[0:2, 0])
        ax_trace = fig.add_subplot(gs[2, 0])
        wb.ax = ax_img

        def _trajectory():
            return interpolate_roi_trajectory(
                state["anchors"].items(), n, (w, h), (H, W))

        def _apply_threshold():
            r = state["result"]
            if r is None:
                return
            thr = r.threshold * state["threshold_mult"]
            peaks, _ = signal.find_peaks(
                r.trace, distance=max(1, int(round(fps * min_interval))),
                prominence=thr)
            r.peaks = peaks

        def _method_label():
            return ("PumpKin motion-compensated"
                    if str(state["method"]).startswith("motion")
                    else "template deformation")

        def recompute():
            state["roi_by_frame"] = _trajectory()
            state["result"] = analyze_along_trajectory(
                frames, state["roi_by_frame"], fps,
                method=state["method"],
                min_interval_s=min_interval, prominence_scale=sensitivity)
            _apply_threshold()
            proc.add(
                "Reanalyzed",
                f"{len(state['anchors'])} anchor(s); "
                f"{len(state['result'].peaks)} pumps at "
                f"x{state['threshold_mult']:.2f} threshold; "
                f"method: {_method_label()}.", status="done")

        def draw_trace():
            r = state["result"]
            ax_trace.clear()
            t = np.arange(len(r.trace)) / fps
            ax_trace.plot(t, r.trace, color="#7d0000", lw=1)
            if len(r.peaks):
                ax_trace.plot(t[r.peaks], r.trace[r.peaks], "o", ms=4,
                              color="#00a050")
            ax_trace.axvline(state["frame"] / fps, color="#0066cc", lw=1)
            secs = len(r.trace) / fps if len(r.trace) else 1
            hz = len(r.peaks) / secs
            ax_trace.set_title(
                f"{len(r.peaks)} pumps, {hz:.3f} Hz ({hz*60:.1f}/min)",
                fontsize=9)
            ax_trace.set_xlabel("Time in interval (s)")
            ax_trace.grid(alpha=.2)

        def draw_image():
            idx = state["frame"]
            ax_img.clear()
            ax_img.imshow(frames[idx], cmap="gray")
            bx0, by0, bx1, by1 = state["roi_by_frame"][idx]
            r = state["result"]
            is_pump = r is not None and idx in set(r.peaks.tolist())
            if is_pump and state["blink"]:
                edge, lwv = "#00ff40", 3.0
            elif is_pump:
                edge, lwv = "#0a7a2a", 2.0
            else:
                edge, lwv = "#ffcc00", 1.6
            ax_img.add_patch(Rectangle(
                (bx0, by0), bx1 - bx0, by1 - by0, fill=False,
                edgecolor=edge, lw=lwv))
            if idx in state["anchors"]:
                cx, cy = state["anchors"][idx]
                ax_img.plot(cx, cy, "+", color="#00ccff", ms=16, mew=2)
            ax_img.set_title(
                f"Frame {idx+1}/{n}   {'PUMP' if is_pump else ''}   "
                f"anchors: {len(state['anchors'])}   "
                "(left-click the pharynx to drop/move an anchor here)",
                fontsize=9)
            ax_img.set_xticks([]); ax_img.set_yticks([])

        def refresh_all():
            draw_image(); draw_trace(); wb.refresh()

        def _set_slider(idx):
            sl = state.get("_slider")
            if sl is not None:
                try:
                    sl.set(idx + 1)
                except Exception:
                    pass

        def goto(idx, from_slider=False):
            state["frame"] = max(0, min(n - 1, int(idx)))
            # Don't push the value back into the Scale while it is being dragged
            # (that freezes the thumb on Windows); only sync it for button/key nav.
            if not from_slider:
                _set_slider(state["frame"])
            refresh_all()

        def on_slider(value):
            if state["roi_by_frame"] is None:
                return
            goto(int(round(float(value))) - 1, from_slider=True)

        def step(delta):
            goto(state["frame"] + delta)

        def next_pump():
            r = state["result"]
            if r is None or not len(r.peaks):
                return
            after = r.peaks[r.peaks > state["frame"]]
            goto(int(after[0]) if len(after) else int(r.peaks[0]))

        def on_click(event):
            if event.inaxes != ax_img or event.xdata is None or event.button != 1:
                return
            state["anchors"][int(state["frame"])] = (
                float(event.xdata), float(event.ydata))
            state["roi_by_frame"] = _trajectory()
            proc.add(
                "Anchor dropped",
                f"frame {state['frame']+1}: x={event.xdata:.0f}, "
                f"y={event.ydata:.0f} (Reanalyze to apply)", status="edit")
            refresh_all()

        def add_anchor_here():
            idx = int(state["frame"])
            bx0, by0, bx1, by1 = state["roi_by_frame"][idx]
            state["anchors"][idx] = ((bx0 + bx1) / 2.0, (by0 + by1) / 2.0)
            state["roi_by_frame"] = _trajectory()
            proc.add("Anchor added",
                     f"frame {idx+1} at the ROI centre; left-click the pharynx "
                     "to fine-tune its position, then Reanalyze.", status="edit")
            refresh_all()

        def remove_anchor():
            f = int(state["frame"])
            if f in state["anchors"] and len(state["anchors"]) > 1:
                del state["anchors"][f]
                state["roi_by_frame"] = _trajectory()
                proc.add("Anchor removed", f"frame {f+1}", status="edit")
                refresh_all()

        def reanalyze():
            wb.set_status(f"Reanalyzing along anchors ({_method_label()})...")
            wb.refresh()
            recompute(); refresh_all()
            wb.set_status(
                f"Reanalyzed with {_method_label()}. Scroll to inspect; adjust "
                "anchors, switch method, or reanalyze as needed.")

        def toggle_method():
            state["method"] = ("template_svd"
                               if str(state["method"]).startswith("motion")
                               else "motion_compensated")
            proc.add("Method switched", _method_label(), status="edit")
            reanalyze()

        def thr_up():
            state["threshold_mult"] = min(3.0, state["threshold_mult"] + 0.1)
            _apply_threshold(); refresh_all()

        def thr_down():
            state["threshold_mult"] = max(0.2, state["threshold_mult"] - 0.1)
            _apply_threshold(); refresh_all()

        def save_and_close():
            self.result = state["result"]
            state["saved"] = True
            wb.close()

        wb.clear_controls()
        wb.add_control_label(
            "The ROI follows your anchors. Green box = a counted pump on this "
            "frame. Scroll to where the pharynx has moved, click it (or Add "
            "anchor here), then Reanalyze.")
        slider_row = ttk.Frame(wb.controls_frame)
        slider_row.pack(fill="x", padx=6, pady=(2, 6))
        ttk.Label(slider_row, text="Frame").pack(side="left")
        state["_slider"] = ttk.Scale(
            slider_row, from_=1, to=max(1, n), orient="horizontal",
            command=on_slider)
        state["_slider"].pack(side="left", fill="x", expand=True, padx=4)
        wb.add_control_button("< prev frame", lambda: step(-1))
        wb.add_control_button("next frame >", lambda: step(1))
        wb.add_control_button("- 10 frames", lambda: step(-10))
        wb.add_control_button("+ 10 frames", lambda: step(10))
        wb.add_control_button("Jump to next pump (n)", next_pump)
        wb.add_control_separator()
        wb.add_control_button("Add anchor here", add_anchor_here)
        wb.add_control_button("Remove anchor here", remove_anchor)
        wb.add_control_button("Reanalyze along anchors (Enter)", reanalyze)
        wb.add_control_button("Switch method (template / motion)", toggle_method)
        wb.add_control_separator()
        wb.add_control_button("Threshold -", thr_down)
        wb.add_control_button("Threshold +", thr_up)
        wb.add_control_separator()
        wb.add_control_button("Save reviewed detections", save_and_close)
        wb.add_control_button("Close without saving", wb.close)
        wb.add_control_separator()
        wb.add_control_button("Hide controls (c)", wb.toggle_controls)
        wb.add_control_button("Hide hood (h)", wb.toggle_hood)

        fig.canvas.mpl_connect("button_press_event", on_click)

        def on_key(event):
            k = str(getattr(event, "key", "") or "").lower()
            if k == "left":
                step(-1)
            elif k == "right":
                step(1)
            elif k == "n":
                next_pump()
            elif k in ("enter", "return"):
                reanalyze()
        fig.canvas.mpl_connect("key_press_event", on_key)

        def tick():
            if getattr(wb, "_closed", False):
                return
            r = state["result"]
            if r is not None and int(state["frame"]) in set(r.peaks.tolist()):
                state["blink"] = not state["blink"]
                draw_image()
                wb.draw_idle()
            try:
                wb.window.after(450, tick)
            except Exception:
                pass

        recompute()
        refresh_all()
        wb.window.after(450, tick)
        wb.wait()
        if state["saved"]:
            self.save()

    def _show_inpanel_review(self):
        """Show the analysis trace and detected pumps inside the main window.

        Replaces the old separate review pop-up: the graph appears below the
        image, review controls go on the left panel, and the process hood on the
        right is shared.  Threshold changes update the pumps live.
        """
        r = self.result
        t = np.arange(len(r.trace)) / self.fps
        self.trace_ax.clear()
        self._trace_line, = self.trace_ax.plot(t, r.trace, color="#7d0000", lw=1)
        self._trace_dots, = self.trace_ax.plot(
            t[r.peaks], r.trace[r.peaks], "o", ms=4, color="#00804b")
        self.trace_ax.set_xlabel("Time in interval (s)")
        self.trace_ax.set_ylabel("Stabilized motion")
        self.trace_ax.grid(alpha=.2)
        self._update_review_title()
        try:
            self.trace_fig.tight_layout()
        except Exception:
            pass
        self.review_area.grid()
        self._build_review_controls()
        self.trace_canvas.draw_idle()
        self.status.config(
            text="Reviewing detected pumps in this window. Adjust the threshold "
                 "on the left, then Save.")

    def _update_review_title(self):
        r = self.result
        secs = len(r.trace) / self.fps if len(r.trace) else 1
        hz = len(r.peaks) / secs
        self.trace_ax.set_title(
            f"Detected pumps ({r.method}): {len(r.peaks)}, "
            f"{hz:.3f} Hz ({hz*60:.1f}/min)", fontsize=9)

    def _review_threshold_changed(self, value):
        r = self.result
        if r is None:
            return
        thr = r.threshold * float(value)
        peaks, _ = signal.find_peaks(
            r.trace, distance=max(1, int(round(self.fps * .13))),
            prominence=thr)
        r.peaks = peaks
        t = np.arange(len(r.trace)) / self.fps
        self._trace_dots.set_data(t[peaks], r.trace[peaks])
        self._update_review_title()
        self.trace_canvas.draw_idle()
        self.process_log.add(
            "Threshold adjusted",
            f"multiplier={float(value):.2f}; candidates={len(peaks)}",
            status="info")
        self.refresh_hood()

    def _build_review_controls(self):
        if getattr(self, "review_controls", None) is not None:
            try:
                self.review_controls.destroy()
            except Exception:
                pass
        self.review_controls = ttk.LabelFrame(
            self.controls_frame, text="Pumping review")
        self.review_controls.pack(fill="x", padx=6, pady=(8, 4))
        ttk.Label(
            self.review_controls,
            text="Green dots are detected pumps. Adjust the threshold, then "
                 "Save.", wraplength=200, justify="left").pack(
            anchor="w", padx=6, pady=(4, 2))
        self._thr_var = tk.DoubleVar(value=1.0)
        ttk.Scale(
            self.review_controls, from_=0.2, to=3.0, variable=self._thr_var,
            command=self._review_threshold_changed).pack(fill="x", padx=6)
        ttk.Button(
            self.review_controls, text="Save reviewed detections",
            command=self.save).pack(fill="x", padx=6, pady=2)
        ttk.Button(
            self.review_controls, text="Hide graph",
            command=self._hide_inpanel_review).pack(fill="x", padx=6, pady=(2, 6))

    def _hide_inpanel_review(self):
        self.review_area.grid_remove()
        if getattr(self, "review_controls", None) is not None:
            try:
                self.review_controls.destroy()
            except Exception:
                pass
            self.review_controls = None

    def review(self):
        r = self.result
        t = np.arange(len(r.trace)) / self.fps
        proc = self.process_log or ProcessLog("Pharyngeal pumping process")
        proc.add(
            "Review window",
            "Threshold review is now inside the WINK workbench: controls on the left, graph in the center, transparent process hood on the right.",
            status="info")
        wb = ModuleWorkbench(self, "Review pharyngeal pumping", proc,
                             width=1380, height=840)
        wb.set_status(
            "Adjust threshold, inspect peaks, then save. Keys: c hides controls; h hides hood.")
        fig, ax = wb.fig, wb.ax
        fig.subplots_adjust(bottom=0.23)
        line, = ax.plot(t, r.trace, color="#7d0000", lw=1)
        dots, = ax.plot(t[r.peaks], r.trace[r.peaks], "o", color="#00804b")
        ax.set(title=f"Review detected pumps ({r.method})",
               xlabel="Time within approved interval (s)",
               ylabel="Stabilized pharynx motion")
        ax.grid(alpha=.2)
        slider_ax = fig.add_axes([0.18, 0.08, 0.62, 0.04])
        prom = Slider(slider_ax, "Detection threshold", 0.2, 3.0,
                      valinit=1.0, valstep=0.05)
        saved = {"value": False}

        def save_and_close():
            saved["value"] = True
            wb.close()

        def close_without_saving():
            saved["value"] = False
            wb.close()

        wb.clear_controls()
        wb.add_control_label("Pumping review")
        wb.add_control_label(
            "Use the threshold slider below the plot. Green dots are proposed pumps. "
            "Zoom/pan with the toolbar under the graph.")
        wb.add_control_button("Save reviewed detections", save_and_close)
        wb.add_control_button("Close without saving", close_without_saving)
        wb.add_control_separator()
        wb.add_control_button("Hide controls (c)", wb.toggle_controls)
        wb.add_control_button("Hide hood (h)", wb.toggle_hood)

        def update(_):
            threshold = r.threshold * prom.val
            peaks, _ = signal.find_peaks(
                r.trace, distance=max(1, int(round(self.fps * .13))),
                prominence=threshold)
            r.peaks = peaks
            dots.set_data(t[peaks], r.trace[peaks])
            hz = len(peaks)/(len(r.trace)/self.fps)
            ax.set_title(
                f"Review detected pumps ({r.method}): {len(peaks)} pumps, "
                f"{hz:.3f} Hz ({hz*60:.1f} pumps/min)")
            proc.add(
                "Threshold adjusted",
                f"multiplier={prom.val:.2f}; candidates={len(peaks)}",
                status="info")
            wb.refresh()
        prom.on_changed(update)
        update(None)
        wb.wait()

        if saved["value"]:
            self.save()

    def save(self):
        r = self.result
        default = self.paths[0].parent / f"{self.paths[0].stem.rsplit('-', 1)[0]}_pumping.csv"
        out = filedialog.asksaveasfilename(
            title="Save pumping results", initialdir=str(default.parent),
            initialfile=default.name, defaultextension=".csv",
            filetypes=[("CSV", "*.csv")])
        if not out:
            return
        duration = len(r.trace) / self.fps
        rate = len(r.peaks) / duration * 60
        intervals = np.diff(r.peaks) / self.fps
        max_pause = self._prompt.ask_float(
            "Pumping bouts",
            "Maximum pause between pumps that still counts as continuous pumping (seconds):",
            initialvalue=1.0, minvalue=0.1, maxvalue=10.0)
        if max_pause is None:
            return
        pumping_mask, bouts = pumping_occupancy(
            r.peaks, len(r.trace), self.fps, max_pause)
        pumping_duration = float(pumping_mask.sum()/self.fps)
        nonpumping_duration = max(0.0, duration-pumping_duration)
        with open(out, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["recording", str(self.paths[0].parent)])
            writer.writerow(["fps", self.fps])
            writer.writerow(["fps_source", self.fps_source])
            writer.writerow(["um_per_px", self.um_per_px])
            writer.writerow(["um_per_px_source", self.um_per_px_source])
            writer.writerow(["exposure_ms", self.exposure_ms])
            writer.writerow(["exposure_source", self.exposure_source])
            writer.writerow(["start_frame", self.start])
            writer.writerow(["end_frame", self.end])
            writer.writerow(["analysis_method", r.method])
            writer.writerow(["detection_threshold", r.threshold])
            writer.writerow(["pump_sensitivity", self.pump_sensitivity.get()])
            writer.writerow(["minimum_pump_interval_s", self.min_pump_interval_s.get()])
            for key, value in sorted((r.diagnostics or {}).items()):
                writer.writerow([f"diagnostic_{key}", value])
            writer.writerow(["duration_s", duration])
            writer.writerow(["pump_count", len(r.peaks)])
            writer.writerow(["pumps_per_min", rate])
            writer.writerow(["pumping_frequency_hz", rate / 60])
            writer.writerow(["usable_duration_s", duration])
            writer.writerow(["pumping_bout_max_pause_s", max_pause])
            writer.writerow(["pumping_bout_count", len(bouts)])
            writer.writerow(["pumping_duration_s", pumping_duration])
            writer.writerow(["fraction_usable_time_pumping",
                             pumping_duration/duration if duration else ""])
            writer.writerow(["detectable_not_pumping_duration_s", nonpumping_duration])
            writer.writerow(["fraction_usable_time_detectable_not_pumping",
                             nonpumping_duration/duration if duration else ""])
            writer.writerow(["median_interpump_s",
                             float(np.median(intervals)) if len(intervals) else ""])
            writer.writerow([])
            writer.writerow(["pump_number", "frame", "time_s", "signal"])
            for number, peak in enumerate(r.peaks, 1):
                writer.writerow([number, self.start + int(peak),
                                 (self.start + peak) / self.fps,
                                 float(r.trace[peak])])
        self.status.config(text=f"Saved {len(r.peaks)} pumps ({rate:.1f}/min) to {out}")


def main():
    PumpingTool().mainloop()


if __name__ == "__main__":
    main()
