"""Pre-build feasibility measurement for posterior body-contraction detection.

This is deliberately an analysis helper, not a student-facing tool.  It uses
the staged corrected DIC segmentation and continuity logic without applying
the invariant-length trim, because that trim would erase the candidate pBoc
signal.  Source images are read only.  Results are written in the workspace.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
STAGED = ROOT.parents[1]
sys.path.insert(0, str(STAGED / "tools" / "movie"))
sys.path.insert(0, str(STAGED / "tools" / "afd_neuron"))
sys.path.insert(0, str(STAGED / "tools" / "worm_kinematics" / "dic_tracker"))

from worm_dic_tracker import DICWormTracker  # noqa: E402
from image_sequence import discover_images, read_image  # noqa: E402


def numbered_images(folder: Path) -> list[Path]:
    return discover_images(folder)


def load_downsampled(paths: list[Path], scale: float, stride: int) -> np.ndarray:
    selected = paths[::stride]
    first = read_image(selected[0], grayscale=True)
    h, w = first.shape[:2]
    out_w = max(32, int(round(w * scale)))
    out_h = max(32, int(round(h * scale)))
    frames = np.empty((len(selected), out_h, out_w), np.float32)
    for i, path in enumerate(selected):
        image = read_image(path, grayscale=True)
        frames[i] = cv2.resize(
            image.astype(np.float32), (out_w, out_h), interpolation=cv2.INTER_AREA
        )
        if i % 250 == 0:
            print(f"loaded {i + 1}/{len(selected)}", flush=True)
    return frames


def raw_track(
    frames: np.ndarray,
    fps: float,
    head_xy_full: tuple[float, float],
    scale: float,
    contrast_pct: float,
    thickness_iter: int,
    um_per_px: float,
    um_per_px_source: str,
    segmentation_config=None,
    tail_xy_full=None,
    outline_xy_full=None,
        exclusion_masks=None, seed_frame=0, anchor_outlines=None,
) -> DICWormTracker:
    tracker = DICWormTracker(
        frames,
        fps=fps,
        um_per_px=um_per_px,
        fps_source="declared",
        um_per_px_source=um_per_px_source,
        worm_id="feasibility",
        n_segments=24,
        contrast_pct=contrast_pct,
        thickness_iter=thickness_iter,
        segmentation_config=segmentation_config,
        strict_target_identity=outline_xy_full is not None,
        exclusion_masks=exclusion_masks,
    )
    seed = (head_xy_full[0] * scale, head_xy_full[1] * scale)
    seed_mask = None
    if outline_xy_full is not None and len(outline_xy_full) >= 3:
        from skimage.draw import polygon2mask
        vertices = np.asarray(outline_xy_full, float) * scale
        seed_mask = polygon2mask(
            frames.shape[1:], np.asarray([(y, x) for x, y in vertices]))
        path, length = __import__("neuron_tracker").geodesic_midline(seed_mask)
        if path is None or length <= 0:
            raise ValueError("The initial full-worm outline has no usable centerline.")
        if tail_xy_full is not None:
            tail = np.asarray(tail_xy_full, float) * scale
            endpoints = np.asarray([path[0], path[-1]])
            if np.min(np.linalg.norm(endpoints - tail, axis=1)) > .35 * length:
                raise ValueError(
                    "The tail click is not near an endpoint of the outlined worm. "
                    "Repeat the head, tail, and full-body outline.")
        tracker.len_ref = float(length)
        tracker.area_ref = float(seed_mask.sum())
    anchor_masks = {}
    anchor_lengths, anchor_areas = [], []
    if anchor_outlines:
        from skimage.draw import polygon2mask
        for frame_index, outline in anchor_outlines.items():
            vertices = np.asarray(outline, float) * scale
            anchor_mask = polygon2mask(
                frames.shape[1:], np.asarray([(y, x) for x, y in vertices]))
            anchor_masks[int(frame_index)] = anchor_mask
            anchor_path, anchor_length = __import__("neuron_tracker").geodesic_midline(anchor_mask)
            if anchor_path is not None and anchor_length > 0:
                anchor_lengths.append(float(anchor_length))
                anchor_areas.append(float(anchor_mask.sum()))
    if anchor_lengths:
        # pBoc shortening is calibrated by the user's three outlines. Allow a
        # modest margin around that observed biological range, but never admit
        # a substantially shorter larva as the target adult.
        tracker.identity_length_bounds = (
            0.90*min(anchor_lengths), 1.10*max(anchor_lengths))
        tracker.identity_area_bounds = (
            0.75*min(anchor_areas), 1.25*max(anchor_areas))
    seed_frame = int(np.clip(seed_frame, 0, tracker.T-1))
    masks = [None] * tracker.T
    masks[seed_frame] = seed_mask if seed_mask is not None else tracker._mask(seed_frame, hint=seed)
    anchor_hint = tuple(__import__("scipy").ndimage.center_of_mass(masks[seed_frame])[::-1]) \
        if masks[seed_frame] is not None else seed
    for direction in (1, -1):
        hint = anchor_hint
        indices = (range(seed_frame+1, tracker.T) if direction > 0
                   else range(seed_frame-1, -1, -1))
        for i in indices:
            mask = tracker._mask(i, hint=hint)
            masks[i] = mask
            if mask is not None:
                cy, cx = __import__("scipy").ndimage.center_of_mass(mask)
                hint = (float(cx), float(cy))
            if i % 250 == 0:
                print(f"segmented {i + 1}/{tracker.T}", flush=True)
    for frame_index, anchor_mask in anchor_masks.items():
        masks[int(frame_index)] = anchor_mask
    # One untrimmed pass. This is the key difference from the kinematics export.
    seeded_length, seeded_area = tracker.len_ref, tracker.area_ref
    tracker.run_pass_from_anchor(masks, seed, seed_frame)
    # Every user outline is authoritative. Keep all supplied calibration/correction
    # anchors as trusted observations so temporal repair uses the complete ordered
    # anchor set rather than treating any of them as replaceable automatic frames.
    for frame_index in anchor_masks:
        state = tracker.state[int(frame_index)]
        if state is not None and state.get("pts") is not None:
            state["provenance"] = "manual"
            state["needs_help"] = 0
            state["calibration_anchor"] = 1
    lengths = [s["length"] for s in tracker.state if np.isfinite(s["length"])]
    areas = [s["area"] for s in tracker.state if np.isfinite(s["area"])]
    tracker.len_ref = (seeded_length if seeded_length else
                       float(np.median(lengths)) if lengths else np.nan)
    tracker.area_ref = (seeded_area if seeded_area else
                        float(np.median(areas)) if areas else np.nan)
    tracker._qc()
    tracker._temporal_reconstruct(
        variable_length=lambda frame, fraction, left, right:
        (1-fraction)*left.get("length", tracker.len_ref)
        + fraction*right.get("length", tracker.len_ref))
    if seeded_length:
        for state in tracker.state:
            length = state.get("length", np.nan)
            area = state.get("area", np.nan)
            length_bounds = tracker.identity_length_bounds or (
                .75 * seeded_length, 1.25 * seeded_length)
            area_bounds = tracker.identity_area_bounds or (
                .60 * seeded_area, 1.60 * seeded_area)
            complete = (np.isfinite(length) and length_bounds[0] <= length <= length_bounds[1]
                        and np.isfinite(area) and area_bounds[0] <= area <= area_bounds[1])
            if state.get("geometry_inferred"):
                # The inferred spine passed the shared two-flank bridgeability
                # gate; retain raw area as evidence without re-failing geometry.
                complete = True
            if not complete:
                state["needs_help"] = 1
                state["provenance"] = "help"
                state["identity_warning"] = "incomplete_or_wrong_sized_body"
    tracker._feasibility_masks = masks
    return tracker


def track_distractor_episodes(
        frames, fps, scale, um_per_px, um_per_px_source, episodes,
        target_outline_xy):
    """Track each user-seeded moving distractor over its declared episode."""
    h_full = int(round(frames.shape[1] / scale))
    w_full = int(round(frames.shape[2] / scale))
    target = np.asarray(target_outline_xy, np.float32)
    target_area = abs(cv2.contourArea(target))
    target_span = max(float(np.linalg.norm(target.max(0)-target.min(0))), 1.0)
    line_width = max(5, int(round(target_area / target_span)))
    combined = [np.zeros(frames.shape[1:], bool) for _ in range(len(frames))]
    episode_results = []
    for episode in episodes:
        start, end = int(episode["start_frame"]), int(episode["end_frame"])
        if not (0 <= start <= end < len(frames)):
            raise ValueError(
                f"Distractor {episode['episode_id']} has an invalid frame interval.")
        line = np.asarray(episode["seed_centerline_xy"], np.float32)
        canvas = np.zeros((h_full, w_full), np.uint8)
        cv2.polylines(canvas, [np.rint(line).astype(np.int32)], False, 1,
                      thickness=line_width)
        contours, _ = cv2.findContours(
            canvas, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            raise ValueError(
                f"Distractor {episode['episode_id']} seed line produced no body mask.")
        outline = max(contours, key=cv2.contourArea).reshape(-1, 2).tolist()
        tracker = raw_track(
            frames[start:end + 1], fps, tuple(line[0]), scale, 90, 1,
            um_per_px, um_per_px_source, tail_xy_full=tuple(line[-1]),
            outline_xy_full=outline)
        usable = []
        for local, mask in enumerate(tracker._feasibility_masks):
            frame = start + local
            if mask is not None and tracker.state[local].get("needs_help", 1) == 0:
                combined[frame] |= np.asarray(mask, bool)
                usable.append(frame)
        episode_results.append({
            "episode_id": episode["episode_id"], "start_frame": start,
            "end_frame": end, "usable_frames": usable,
            "usable_fraction": len(usable) / max(1, end - start + 1),
            "masks": tracker._feasibility_masks,
            "states": tracker.state,
        })
    return combined, episode_results


def arc_series(tracker: DICWormTracker) -> dict[str, np.ndarray]:
    total, ant, post, usable = [], [], [], []
    for state in tracker.state:
        pts = state.get("pts")
        if pts is None or len(pts) != 25:
            total.append(np.nan); ant.append(np.nan); post.append(np.nan); usable.append(0)
            continue
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        total.append(float(np.sum(seg)))
        ant.append(float(np.sum(seg[:7])))
        post.append(float(np.sum(seg[17:24])))
        # Keep questionable frames labeled, but use only continuous measured shapes.
        usable.append(int(state.get("needs_help", 1) == 0))
    return {
        "total_arc": np.asarray(total),
        "ant_arc": np.asarray(ant),
        "post_arc": np.asarray(post),
        "usable": np.asarray(usable, dtype=np.uint8),
    }


def interpolate_short_gaps(x: np.ndarray, usable: np.ndarray, max_gap: int) -> np.ndarray:
    y = x.copy()
    good = np.isfinite(y) & (usable > 0)
    indices = np.arange(len(y))
    if good.sum() < 3:
        return np.full_like(y, np.nan)
    missing = ~good
    labels, n = __import__("scipy").ndimage.label(missing)
    for k in range(1, n + 1):
        loc = np.where(labels == k)[0]
        if len(loc) <= max_gap and loc[0] > 0 and loc[-1] < len(y) - 1:
            y[loc] = np.interp(loc, indices[good], y[good])
    return y


def robust_detrend(x: np.ndarray, fps: float) -> np.ndarray:
    from scipy.ndimage import median_filter

    window = max(3, int(round(15 * fps)) | 1)
    baseline = median_filter(x, size=window, mode="nearest")
    return (x - baseline) / np.maximum(baseline, 1e-6)


def autocorrelation(x: np.ndarray, max_lag: int) -> np.ndarray:
    x = x - np.nanmean(x)
    x = np.where(np.isfinite(x), x, 0.0)
    denom = float(np.dot(x, x))
    if denom <= 0:
        return np.full(max_lag + 1, np.nan)
    full = np.correlate(x, x, mode="full")[len(x) - 1:len(x) + max_lag]
    counts = np.arange(len(x), len(x) - len(full), -1)
    return full / denom * len(x) / counts


def summarize(name: str, tracker: DICWormTracker, series: dict[str, np.ndarray], fps: float):
    clean = {}
    cvs = {}
    for key in ("total_arc", "ant_arc", "post_arc"):
        clean[key] = interpolate_short_gaps(series[key], series["usable"], max_gap=max(2, int(fps)))
        good = np.isfinite(series[key]) & (series["usable"] > 0)
        values = series[key][good]
        cvs[key] = float(np.std(values, ddof=1) / np.mean(values)) if len(values) > 2 else np.nan

    max_lag = min(len(series["usable"]) - 2, int(round(120 * fps)))
    ac = {}
    peak = {}
    for key in ("total_arc", "ant_arc", "post_arc"):
        y = clean[key]
        if not np.isfinite(y).all():
            ac[key] = np.full(max_lag + 1, np.nan)
            peak[key] = {"period_s": np.nan, "autocorrelation": np.nan}
            continue
        fractional = robust_detrend(y, fps)
        ac[key] = autocorrelation(fractional, max_lag)
        lo = max(1, int(round(20 * fps)))
        hi = min(max_lag, int(round(90 * fps)))
        j = lo + int(np.nanargmax(ac[key][lo:hi + 1]))
        peak[key] = {"period_s": float(j / fps), "autocorrelation": float(ac[key][j])}

    summary = {
        "recording": name,
        "fps": fps,
        "fps_source": "declared",
        "frames": tracker.T,
        "duration_s": tracker.T / fps,
        "usable_frames": int(series["usable"].sum()),
        "usable_fraction": float(series["usable"].mean()),
        "cv": cvs,
        "autocorrelation_peak_20_90_s": peak,
    }
    return summary, ac


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--name", required=True)
    parser.add_argument("--fps", type=float, required=True)
    parser.add_argument("--um-per-px", type=float, required=True)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--scale", type=float, default=0.5)
    parser.add_argument("--head-x", type=float, required=True)
    parser.add_argument("--head-y", type=float, required=True)
    parser.add_argument("--contrast-pct", type=float, default=94.0)
    parser.add_argument("--thickness-iter", type=int, default=1)
    args = parser.parse_args()

    paths = numbered_images(args.folder)
    frames = load_downsampled(paths, args.scale, args.stride)
    effective_fps = args.fps / args.stride
    tracker = raw_track(
        frames, effective_fps, (args.head_x, args.head_y), args.scale,
        args.contrast_pct, args.thickness_iter, args.um_per_px/args.scale,
        "declared",
    )
    series = arc_series(tracker)
    summary, ac = summarize(args.name, tracker, series, effective_fps)
    out_dir = ROOT / "defecation_feasibility_results"
    out_dir.mkdir(exist_ok=True)
    with (out_dir / f"{args.name}_arcs.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "frame", "time_s", "total_arc_px", "ant_arc_px", "post_arc_px",
            "usable", "provenance",
        ])
        for i, state in enumerate(tracker.state):
            writer.writerow([
                i + 1, i / effective_fps, series["total_arc"][i],
                series["ant_arc"][i], series["post_arc"][i], series["usable"][i],
                state.get("provenance", "help"),
            ])
    with (out_dir / f"{args.name}_autocorrelation.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["lag_s", "total_arc", "ant_arc", "post_arc"])
        for i in range(len(ac["total_arc"])):
            writer.writerow([i / effective_fps, ac["total_arc"][i], ac["ant_arc"][i], ac["post_arc"][i]])
    (out_dir / f"{args.name}_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
