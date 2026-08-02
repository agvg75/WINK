"""Population basal-slowing analysis with paired lawn-entry events.

The unit of observation is an unambiguous worm trajectory. Each event compares
that worm with itself before and after its centroid enters a student-drawn lawn.
Body-axis oscillation is a wrMTrck-like proxy, not segment curvature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from dataclasses import replace
from skimage.morphology import skeletonize

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "population_swimming"))
sys.path.insert(0, str(HERE.parents[1] / "app"))
from acquisition import AcquisitionMetadata
from departure_clock import apply_release_gate, summarize_departures
from decision_transparency import write_decision_manifest
from population_swimming import _frequency, link_detections, list_frames, read_gray
from segmentation_review import find_accepted_config, segment_frame


SPINE_POINTS = 25


def _ordered_spine(component, points=SPINE_POINTS):
    """Return the longest endpoint-to-endpoint path through a worm mask."""
    skeleton = skeletonize(component > 0)
    pixels = np.argwhere(skeleton)
    if len(pixels) < 8:
        return None
    lookup = {tuple(p): i for i, p in enumerate(pixels)}
    neighbors = [[] for _ in pixels]
    for i, (y, x) in enumerate(pixels):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if not (dx or dy):
                    continue
                j = lookup.get((y + dy, x + dx))
                if j is not None:
                    neighbors[i].append((j, float(np.hypot(dx, dy))))
    endpoints = [i for i, links in enumerate(neighbors) if len(links) == 1]
    if len(endpoints) < 2:
        return None

    def distances(source):
        import heapq
        dist = np.full(len(pixels), np.inf)
        parent = np.full(len(pixels), -1, dtype=int)
        dist[source] = 0
        queue = [(0.0, source)]
        while queue:
            value, node = heapq.heappop(queue)
            if value != dist[node]:
                continue
            for other, weight in neighbors[node]:
                candidate = value + weight
                if candidate < dist[other]:
                    dist[other], parent[other] = candidate, node
                    heapq.heappush(queue, (candidate, other))
        return dist, parent

    best = None
    for source in endpoints:
        dist, parent = distances(source)
        target = max(endpoints, key=lambda i: dist[i])
        if np.isfinite(dist[target]) and (best is None or dist[target] > best[0]):
            best = (dist[target], source, target, parent)
    if best is None:
        return None
    _, source, node, parent = best
    path = []
    while node >= 0:
        path.append(pixels[node])
        if node == source:
            break
        node = parent[node]
    if not path or node != source:
        return None
    path = np.asarray(path[::-1], dtype=float)[:, ::-1]  # x,y
    distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    if distance[-1] < 10:
        return None
    sample = np.linspace(0, distance[-1], points)
    return np.column_stack([
        np.interp(sample, distance, path[:, 0]),
        np.interp(sample, distance, path[:, 1])])


def _spine_metrics(spine):
    if spine is None:
        return np.nan, np.nan, np.nan
    step = np.linalg.norm(np.diff(spine, axis=0), axis=1)
    tangent = np.unwrap(np.arctan2(
        np.diff(spine[:, 1]), np.diff(spine[:, 0])))
    ds = np.maximum((step[:-1] + step[1:]) / 2, 1e-6)
    curvature = np.diff(tangent) / ds
    full = np.r_[curvature[0], curvature, curvature[-1]]
    middle = full[len(full) // 3: 2 * len(full) // 3]
    return float(step.sum()), float(np.nanmean(middle)), full


def _polygon_array(points):
    poly = np.asarray(points, dtype=np.float32)
    if poly.ndim != 2 or poly.shape[0] < 3 or poly.shape[1] != 2:
        raise ValueError("Every ROI must contain at least three x,y vertices.")
    return poly


def _signed_distance(poly, x, y):
    return float(cv2.pointPolygonTest(poly, (float(x), float(y)), True))


def _detect(files, min_area, max_area, sample_background, lawn_polys=None,
            progress=None, config_source=None):
    """Detect moving bright or dark objects against a robust static background."""
    idx = np.unique(np.linspace(
        0, len(files) - 1, min(sample_background, len(files))).astype(int))
    samples = np.stack([read_gray(files[i]) for i in idx])
    # Worms are bright in this assay. A low temporal quantile prevents animals
    # lingering in the release droplet from becoming worm-shaped background
    # ghosts, as occurs with a median background.
    background = np.percentile(samples, 20, axis=0).astype(np.uint8)
    detections = []
    shape = background.shape
    lawn_masks = []
    for polygon in lawn_polys or []:
        roi_mask = np.zeros(shape, dtype=np.uint8)
        cv2.fillPoly(
            roi_mask, [np.rint(np.asarray(polygon)).astype(np.int32)], 1)
        lawn_masks.append(roi_mask)
    kernel3 = np.ones((3, 3), np.uint8)
    kernel5 = np.ones((5, 5), np.uint8)
    if config_source is not None:
        config_source = Path(config_source)
    else:
        first = files[0]
        config_source = first.parent if hasattr(first, "parent") else Path.cwd()
    reviewed = find_accepted_config(config_source, "population_basal_slowing")
    reviewed_diff = replace(reviewed, feature="gray") if reviewed else None
    for fi, path in enumerate(files):
        image = read_gray(path)
        diff = cv2.subtract(image, background)
        diff = cv2.GaussianBlur(diff, (3, 3), 0)
        if reviewed_diff:
            mask = np.uint8(segment_frame(diff, fi, reviewed_diff)) * 255
        else:
            _, mask = cv2.threshold(
                diff, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel3)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel5)
        n, labels, stats, centers = cv2.connectedComponentsWithStats(mask)
        for k in range(1, n):
            area = int(stats[k, cv2.CC_STAT_AREA])
            if not min_area <= area <= max_area:
                continue
            ys, xs = np.where(labels == k)
            if len(xs) < 3:
                continue
            cov = np.cov(np.vstack([xs, ys]))
            values, vectors = np.linalg.eigh(cov)
            major = vectors[:, np.argmax(values)]
            angle = float(np.degrees(np.arctan2(major[1], major[0])) % 180)
            elongation = float(np.sqrt(max(values) / max(min(values), 1e-6)))
            x, y = centers[k]
            x0 = int(stats[k, cv2.CC_STAT_LEFT])
            y0 = int(stats[k, cv2.CC_STAT_TOP])
            width = int(stats[k, cv2.CC_STAT_WIDTH])
            height = int(stats[k, cv2.CC_STAT_HEIGHT])
            component = labels[y0:y0 + height, x0:x0 + width] == k
            spine = _ordered_spine(component)
            if spine is not None:
                spine[:, 0] += x0
                spine[:, 1] += y0
            spine_length, midbody_curvature, curvature = _spine_metrics(spine)
            edge = bool(xs.min() < 3 or ys.min() < 3 or
                        xs.max() > shape[1] - 4 or ys.max() > shape[0] - 4)
            record = {
                "frame": fi, "x": x, "y": y, "area_px": area,
                "axis_angle_deg": angle, "elongation": elongation,
                "edge": edge, "spine_valid": spine is not None,
                "spine_length_px": spine_length,
                "midbody_curvature_px_inv": midbody_curvature,
                "spine_x_json": (
                    json.dumps(spine[:, 0].round(2).tolist())
                    if spine is not None else ""),
                "spine_y_json": (
                    json.dumps(spine[:, 1].round(2).tolist())
                    if spine is not None else ""),
                "curvature_json": (
                    json.dumps(np.asarray(curvature).round(6).tolist())
                    if spine is not None else ""),
            }
            for lawn_number, roi_mask in enumerate(lawn_masks, 1):
                record[f"fraction_inside_lawn_{lawn_number}"] = float(
                    roi_mask[ys, xs].mean())
            detections.append(record)
        if progress and fi % 20 == 0:
            progress(fi + 1, len(files))
    return pd.DataFrame(detections), background


def _window_frequency(group, fps):
    valid = group[np.isfinite(group.midbody_curvature_px_inv)]
    if (len(valid) < max(12, int(np.ceil(2.5 * fps))) or
            valid.time_s.iloc[-1] - valid.time_s.iloc[0] < 2.5):
        return np.nan
    time = valid.time_s.to_numpy()
    signal = valid.midbody_curvature_px_inv.to_numpy()
    dt = np.median(np.diff(time))
    signal = signal - np.mean(signal)
    frequency = np.fft.rfftfreq(len(signal), dt)
    power = np.abs(np.fft.rfft(signal * np.hanning(len(signal)))) ** 2
    band = (frequency >= .2) & (frequency <= min(3.0, .45 / dt))
    return float(frequency[band][np.argmax(power[band])]) if np.any(band) else np.nan


def _orient_track_spines(tracks):
    """Orient consecutive spines consistently; orientation is continuity-based."""
    table = tracks.copy()
    for _, group in table.groupby("track_id", sort=False):
        previous = None
        for index in group.sort_values("frame").index:
            try:
                x = np.asarray(json.loads(table.at[index, "spine_x_json"]), float)
                y = np.asarray(json.loads(table.at[index, "spine_y_json"]), float)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(x) < 2:
                continue
            spine = np.column_stack([x, y])
            if previous is not None:
                same = np.linalg.norm(spine[0] - previous[0]) + np.linalg.norm(
                    spine[-1] - previous[-1])
                flipped = np.linalg.norm(spine[-1] - previous[0]) + np.linalg.norm(
                    spine[0] - previous[-1])
                if flipped < same:
                    spine = spine[::-1]
                    curvature = json.loads(table.at[index, "curvature_json"])
                    table.at[index, "curvature_json"] = json.dumps(
                        (-np.asarray(curvature)[::-1]).round(6).tolist())
                    table.at[index, "midbody_curvature_px_inv"] *= -1
            table.at[index, "spine_x_json"] = json.dumps(
                spine[:, 0].round(2).tolist())
            table.at[index, "spine_y_json"] = json.dumps(
                spine[:, 1].round(2).tolist())
            previous = spine
    return table


def _window_metrics(group, fps):
    return {
        "frames": int(len(group)),
        "duration_s": float(
            (group.frame.max() - group.frame.min() + 1) / fps),
        "mean_speed_um_s": float(group.speed_um_s.mean()),
        "median_speed_um_s": float(group.speed_um_s.median()),
        "body_axis_frequency_proxy_hz": _window_frequency(group, fps),
        "spine_valid_fraction": float(group.spine_valid.mean()),
        "collision_fraction": float(group.possible_collision.mean()),
        "ambiguity_fraction": float(group.crossing_ambiguous.mean()),
        "edge_fraction": float(group.edge.mean()),
    }


def stitch_tracklets(tracks, max_gap_frames=30, max_distance_px=100,
                     max_heading_change_deg=60, ambiguity_margin=.15):
    """Merge clear, aligned tracklet continuations while preserving provenance.

    A stitch is inferred, never measured. Competing continuations with scores
    within ``ambiguity_margin`` are left separate.
    """
    table = tracks.copy()
    table["original_track_id"] = table.track_id.astype(int)
    descriptors = {}
    for track_id, group in table.groupby("track_id"):
        group = group.sort_values("frame")
        n = min(5, max(1, len(group) - 1))
        start_dx = float(group.x.iloc[n] - group.x.iloc[0]) if len(group) > 1 else 0
        start_dy = float(group.y.iloc[n] - group.y.iloc[0]) if len(group) > 1 else 0
        end_dx = float(group.x.iloc[-1] - group.x.iloc[-n-1]) if len(group) > 1 else 0
        end_dy = float(group.y.iloc[-1] - group.y.iloc[-n-1]) if len(group) > 1 else 0
        descriptors[int(track_id)] = {
            "start_frame": int(group.frame.iloc[0]),
            "end_frame": int(group.frame.iloc[-1]),
            "start": np.array([group.x.iloc[0], group.y.iloc[0]], float),
            "end": np.array([group.x.iloc[-1], group.y.iloc[-1]], float),
            "start_v": np.array([start_dx, start_dy], float) / n,
            "end_v": np.array([end_dx, end_dy], float) / n,
        }
    candidates = []
    ids = sorted(descriptors)
    min_cos = np.cos(np.deg2rad(max_heading_change_deg))
    by_end = {}
    by_start = {}
    for left in ids:
        a = descriptors[left]
        for right in ids:
            if left == right:
                continue
            b = descriptors[right]
            gap = b["start_frame"] - a["end_frame"]
            if not 1 <= gap <= max_gap_frames:
                continue
            av, bv = a["end_v"], b["start_v"]
            an, bn = np.linalg.norm(av), np.linalg.norm(bv)
            heading_cos = float(np.dot(av, bv) / (an * bn)) if an and bn else 1.0
            if heading_cos < min_cos:
                continue
            predicted = a["end"] + av * gap
            distance = float(np.linalg.norm(predicted - b["start"]))
            gate = float(max_distance_px) * np.sqrt(gap / max_gap_frames)
            if distance > gate:
                continue
            score = distance / max(gate, 1) + (1 - heading_cos)
            candidate = (score, left, right, gap, distance, heading_cos)
            candidates.append(candidate)
            by_end.setdefault(left, []).append(candidate)
            by_start.setdefault(right, []).append(candidate)

    accepted = []
    used_left, used_right = set(), set()
    for candidate in sorted(candidates):
        score, left, right, *_ = candidate
        if left in used_left or right in used_right:
            continue
        alternatives = (
            [x[0] for x in by_end[left] if x[2] != right] +
            [x[0] for x in by_start[right] if x[1] != left])
        if alternatives and min(alternatives) <= score * (1 + ambiguity_margin):
            continue
        accepted.append(candidate)
        used_left.add(left)
        used_right.add(right)

    parent = {track_id: track_id for track_id in ids}

    def root(track_id):
        while parent[track_id] != track_id:
            parent[track_id] = parent[parent[track_id]]
            track_id = parent[track_id]
        return track_id

    stitch_records = []
    for score, left, right, gap, distance, heading_cos in sorted(
            accepted, key=lambda x: descriptors[x[1]]["end_frame"]):
        left_root, right_root = root(left), root(right)
        if left_root == right_root:
            continue
        parent[right_root] = left_root
        stitch_records.append({
            "from_tracklet_id": left, "to_tracklet_id": right,
            "gap_frames": gap, "predicted_distance_error_px": distance,
            "heading_difference_deg": float(
                np.degrees(np.arccos(np.clip(heading_cos, -1, 1)))),
            "stitch_score": score,
        })
    mapping = {track_id: root(track_id) for track_id in ids}
    canonical = {old: new for new, old in enumerate(
        sorted(set(mapping.values())), 1)}
    table["track_id"] = table.original_track_id.map(
        lambda x: canonical[mapping[int(x)]])
    source_counts = table.groupby("track_id").original_track_id.transform(
        "nunique")
    table["track_stitched"] = source_counts > 1
    table["stitched_tracklet_count"] = source_counts
    return table.sort_values(["track_id", "frame"]), pd.DataFrame(stitch_records)


def derive_entry_events(tracks, fps, lawns, before_s=10.0, after_s=10.0,
                        pre_entry_gap_s=0.0, outside_buffer_px=10.0,
                        min_window_fraction=0.70):
    """Find paired lawn-entry events in ALREADY ANNOTATED tracks.

    Split out of ``analyze`` so events can be re-derived after a person
    edits the trajectories - splitting, joining or trimming a track changes
    which entries exist and what falls inside their before/after windows, so
    an edited track whose events were not recomputed would describe the old
    trajectory.

    ``tracks`` must already carry the per-frame annotations ``analyze``
    adds: speed_um_s, inside_start, analysis_active, possible_collision,
    inside_lawn_N and inside_any_lawn.
    """
    events = []
    expected_before = max(1, int(round(before_s * fps)))
    expected_after = max(1, int(round(after_s * fps)))
    gap_frames = max(0, int(round(pre_entry_gap_s * fps)))
    event_number = 0
    for track_id, group in tracks.groupby("track_id"):
        group = group.sort_values("frame").copy()
        active_group = group[group.analysis_active].copy()
        if active_group.empty:
            continue
        first_frame = int(group.frame.min())
        born_by_exit = bool(
            (group.inside_start.shift(fill_value=group.inside_start.iloc[0]) &
             ~group.inside_start).any())
        birth_type = "start_roi_exit" if born_by_exit else (
            "already_outside_at_recording_start" if first_frame <= 2
            else "first_seen_outside")
        for lawn_number in range(1, len(lawns) + 1):
            inside_col = f"inside_lawn_{lawn_number}"
            distance_col = f"lawn_{lawn_number}_distance_px"
            entries = active_group[
                active_group[inside_col] &
                ~active_group[inside_col].shift(fill_value=False)]
            for _, entry in entries.iterrows():
                entry_frame = int(entry.frame)
                before_end = entry_frame - gap_frames - 1
                before_start = before_end - expected_before + 1
                after_end = entry_frame + expected_after - 1
                before = group[
                    (group.frame >= before_start) &
                    (group.frame <= before_end) &
                    ~group.inside_any_lawn &
                    (group[distance_col] <= -float(outside_buffer_px))]
                after = group[
                    (group.frame >= entry_frame) &
                    (group.frame <= after_end) &
                    group[inside_col]]
                exits = group[
                    (group.frame > entry_frame) &
                    ~group[inside_col] &
                    group[inside_col].shift(fill_value=False)]
                exit_row = exits.iloc[0] if len(exits) else None
                exit_frame = int(exit_row.frame) if exit_row is not None else None
                post_exit = group.iloc[0:0]
                if exit_frame is not None:
                    post_exit = group[
                        (group.frame >= exit_frame) &
                        (group.frame < exit_frame + expected_after) &
                        ~group.inside_any_lawn]
                bm = _window_metrics(before, fps) if len(before) else None
                am = _window_metrics(after, fps) if len(after) else None
                xm = (_window_metrics(post_exit, fps)
                      if len(post_exit) else None)
                reasons = []
                if len(before) < expected_before * min_window_fraction:
                    reasons.append("insufficient_buffered_before_frames")
                if len(after) < expected_after * min_window_fraction:
                    reasons.append("insufficient_inside_after_frames")
                combined = pd.concat([before, after])
                if len(combined) and combined.possible_collision.any():
                    reasons.append("possible_collision")
                if len(combined) and combined.crossing_ambiguous.any():
                    reasons.append("ambiguous_identity")
                if len(combined) and combined.edge.any():
                    reasons.append("frame_edge")
                frequency_reasons = []
                if bm is None or not np.isfinite(
                        bm["body_axis_frequency_proxy_hz"]):
                    frequency_reasons.append("before_frequency_unavailable")
                if am is None or not np.isfinite(
                        am["body_axis_frequency_proxy_hz"]):
                    frequency_reasons.append("after_frequency_unavailable")
                exit_reasons = []
                if exit_frame is None:
                    exit_reasons.append("no_exit_observed")
                elif len(post_exit) < expected_after * min_window_fraction:
                    exit_reasons.append("insufficient_post_exit_frames")
                if len(post_exit) and post_exit.possible_collision.any():
                    exit_reasons.append("post_exit_possible_collision")
                if len(post_exit) and post_exit.crossing_ambiguous.any():
                    exit_reasons.append("post_exit_ambiguous_identity")
                if xm is None or not np.isfinite(
                        xm["body_axis_frequency_proxy_hz"]):
                    exit_reasons.append("post_exit_frequency_unavailable")
                event_number += 1
                record = {
                    "event_id": event_number,
                    "track_id": int(track_id),
                    "lawn_id": lawn_number,
                    "entry_frame": entry_frame,
                    "entry_time_s": entry_frame / fps,
                    "entry_x": float(entry.x),
                    "entry_y": float(entry.y),
                    "exit_frame": exit_frame,
                    "exit_time_s": (
                        exit_frame / fps if exit_frame is not None else np.nan),
                    "lawn_residence_s": (
                        (exit_frame - entry_frame) / fps
                        if exit_frame is not None else np.nan),
                    "track_birth_type": birth_type,
                    "origin_release_type": str(
                        group.origin_release_type.iloc[0]),
                    "automatic_eligible": not reasons,
                    "exit_automatic_eligible": not exit_reasons,
                    "needs_review": True,
                    "review_reason": "standard_review" if not reasons
                                     else ";".join(reasons),
                    "frequency_review_reason": (
                        "frequency_available" if not frequency_reasons
                        else ";".join(frequency_reasons)),
                    "exit_review_reason": (
                        "standard_review" if not exit_reasons
                        else ";".join(exit_reasons)),
                }
                for prefix, metrics in (
                        ("before", bm), ("after", am), ("post_exit", xm)):
                    metrics = metrics or {
                        "frames": 0, "duration_s": 0,
                        "mean_speed_um_s": np.nan,
                        "median_speed_um_s": np.nan,
                        "body_axis_frequency_proxy_hz": np.nan,
                        "spine_valid_fraction": 0.0,
                        "collision_fraction": np.nan,
                        "ambiguity_fraction": np.nan,
                        "edge_fraction": np.nan}
                    record.update({
                        f"{prefix}_{key}": value
                        for key, value in metrics.items()})
                record["delta_speed_um_s"] = (
                    record["after_mean_speed_um_s"] -
                    record["before_mean_speed_um_s"])
                record["speed_ratio_after_before"] = (
                    record["after_mean_speed_um_s"] /
                    record["before_mean_speed_um_s"]
                    if record["before_mean_speed_um_s"] > 0 else np.nan)
                record["delta_frequency_hz"] = (
                    record["after_body_axis_frequency_proxy_hz"] -
                    record["before_body_axis_frequency_proxy_hz"])
                record["post_exit_minus_inside_speed_um_s"] = (
                    record["post_exit_mean_speed_um_s"] -
                    record["after_mean_speed_um_s"])
                record["post_exit_minus_inside_frequency_hz"] = (
                    record["post_exit_body_axis_frequency_proxy_hz"] -
                    record["after_body_axis_frequency_proxy_hz"])
                events.append(record)

    event_table = pd.DataFrame(events)
    if not event_table.empty:
        event_table = event_table.sort_values(
            ["track_id", "entry_frame", "lawn_id"]).reset_index(drop=True)
        event_table["encounter_number"] = (
            event_table.groupby("track_id").cumcount() + 1)
        event_table["lawn_encounter_number"] = (
            event_table.groupby(["track_id", "lawn_id"]).cumcount() + 1)
        first_entry = event_table.groupby("track_id").entry_time_s.transform(
            "min")
        event_table["time_since_first_encounter_s"] = (
            event_table.entry_time_s - first_entry)
        event_table["time_since_previous_encounter_s"] = (
            event_table.groupby("track_id").entry_time_s.diff())
        residence = event_table.lawn_residence_s.fillna(0)
        event_table["prior_cumulative_lawn_time_s"] = (
            residence.groupby(event_table.track_id).cumsum() - residence)
    return event_table


def recompute_events_from_tracks(results_dir, tracks=None, fps=None,
                                 um_per_px=None, output_dir=None, reason="",
                                 before_s=None, after_s=None,
                                 pre_entry_gap_s=None, outside_buffer_px=None,
                                 min_window_fraction=None):
    """Re-derive entry events from saved (or edited) tracks.

    Two things make this necessary. A declared frame rate or scale that turns
    out to be wrong changes every reported speed and frequency but not the
    trajectories, which are in pixels and frame numbers. And a person editing
    tracks - splitting one that jumped between animals, joining fragments,
    trimming a bad tail - changes which entries exist and what falls inside
    their before/after windows, so the events must be rebuilt or they describe
    a trajectory that no longer exists.

    Detection, linking and spines are NOT repeated. Nothing is decoded.
    The original results are left untouched; output goes to a new folder.
    """
    results_dir = Path(results_dir)
    if tracks is None:
        for name in ("detections_and_tracks_reviewed.csv",
                     "detections_and_tracks.csv"):
            candidate = results_dir / name
            if candidate.exists():
                tracks = pd.read_csv(candidate)
                break
    if tracks is None or not len(tracks):
        raise FileNotFoundError(
            "No saved tracks found to recompute from - this needs a completed run.")
    tracks = tracks.copy()

    metadata = {}
    metadata_path = results_dir / "analysis_metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
    old_fps = metadata.get("fps")
    old_scale = metadata.get("um_per_px")
    fps = float(fps if fps is not None else (old_fps or 0))
    scale = float(um_per_px if um_per_px is not None else (old_scale or 0))
    if fps <= 0 or scale <= 0:
        raise ValueError("Frame rate and scale must both be greater than zero.")

    def pick(value, key, fallback):
        if value is not None:
            return float(value)
        recorded = metadata.get(key)
        return float(recorded) if recorded is not None else float(fallback)

    before_s = pick(before_s, "before_s", 10.0)
    after_s = pick(after_s, "after_s", 10.0)
    pre_entry_gap_s = pick(pre_entry_gap_s, "pre_entry_gap_s", 0.0)
    outside_buffer_px = pick(outside_buffer_px, "outside_buffer_px", 10.0)
    min_window_fraction = pick(min_window_fraction, "minimum_window_fraction", 0.70)

    rois_path = results_dir / "rois.json"
    if not rois_path.exists():
        raise FileNotFoundError(
            "rois.json is required - the lawn geometry defines what an entry is.")
    roi_data = json.loads(rois_path.read_text(encoding="utf-8"))
    lawns = [_polygon_array(x) for x in roi_data.get("lawn_rois", [])]
    if not lawns:
        raise ValueError("rois.json contains no lawn ROIs.")

    # Time and speed follow the declared parameters; positions do not.
    tracks["time_s"] = tracks.frame.astype(float) / fps
    dx = tracks.groupby("track_id")["x"].diff()
    dy = tracks.groupby("track_id")["y"].diff()
    tracks["step_px"] = np.hypot(dx, dy)
    tracks["speed_um_s"] = tracks.step_px * fps * scale

    event_table = derive_entry_events(
        tracks, fps, lawns, before_s=before_s, after_s=after_s,
        pre_entry_gap_s=pre_entry_gap_s, outside_buffer_px=outside_buffer_px,
        min_window_fraction=min_window_fraction)

    out = Path(output_dir) if output_dir else (
        results_dir / f"recomputed_fps{fps:g}_scale{scale:g}")
    out.mkdir(parents=True, exist_ok=True)
    tracks.to_csv(out / "detections_and_tracks.csv", index=False)
    event_table.to_csv(out / "paired_entry_events.csv", index=False)
    for carry in ("rois.json", "background_reference.png"):
        source = results_dir / carry
        if source.exists() and not (out / carry).exists():
            (out / carry).write_bytes(source.read_bytes())

    new_metadata = dict(metadata)
    new_metadata.update({
        "fps": fps, "um_per_px": scale,
        "recomputed_from": str(results_dir),
        "recompute_reason": str(reason or ""),
        "superseded_fps": old_fps, "superseded_um_per_px": old_scale,
        "n_candidate_entries": int(len(event_table)),
        "recompute_note": (
            "Entry events re-derived from saved tracks. Detection, linking and "
            "spine extraction were NOT repeated - they depend only on pixels "
            "and frame numbers. Any manual review of the original run does not "
            "carry over."),
    })
    (out / "analysis_metadata.json").write_text(
        json.dumps(new_metadata, indent=2), encoding="utf-8")
    return event_table, tracks, out


def analyze(folder, fps, um_per_px, start_roi, lawn_rois, output_dir=None,
            min_area=40, max_area=2500, max_link_px=60,
            before_s=10.0, after_s=10.0, pre_entry_gap_s=0.0,
            outside_buffer_px=10.0, min_window_fraction=0.70,
            sample_background=31, max_stitch_gap_s=4.0,
            max_stitch_distance_px=100, max_heading_change_deg=60,
            roi_metadata=None, minimum_worm_fraction_inside=.50,
            progress=None):
    files = list_frames(folder)
    fps, scale = float(fps), float(um_per_px)
    acquisition = AcquisitionMetadata(
        fps, "declared", scale, "declared", None,
        "not_applicable").validate()
    if before_s < 3 or after_s < 3:
        raise ValueError("Before and after windows must each be at least 3 s.")
    if not 0 < min_window_fraction <= 1:
        raise ValueError("Minimum window fraction must be in (0, 1].")
    if not 0 < minimum_worm_fraction_inside <= 1:
        raise ValueError("Worm area required inside a lawn must be in (0, 1].")
    start_poly = _polygon_array(start_roi)
    lawns = [_polygon_array(x) for x in lawn_rois]
    if not lawns:
        raise ValueError("Draw at least one OP50 lawn ROI.")

    config_source = Path(folder)
    detections, background = _detect(
        files, int(min_area), int(max_area), int(sample_background),
        lawn_polys=lawns, progress=progress, config_source=config_source)
    if detections.empty:
        raise ValueError(
            "No worm-sized moving objects were detected. Adjust area limits.")
    for column, default in {
            "spine_valid": False, "spine_length_px": np.nan,
            "midbody_curvature_px_inv": np.nan, "spine_x_json": "",
            "spine_y_json": "", "curvature_json": ""}.items():
        if column not in detections:
            detections[column] = default
    detections["time_s"] = detections.frame / fps
    tracks = link_detections(
        detections, max_link_px=float(max_link_px), max_gap_frames=8)
    tracks, stitches = stitch_tracklets(
        tracks, max_gap_frames=max(1, int(round(max_stitch_gap_s * fps))),
        max_distance_px=float(max_stitch_distance_px),
        max_heading_change_deg=float(max_heading_change_deg))
    tracks = _orient_track_spines(tracks)
    tracks["time_s"] = tracks.frame / fps
    dx = tracks.groupby("track_id").x.diff()
    dy = tracks.groupby("track_id").y.diff()
    tracks["step_px"] = np.hypot(dx, dy)
    tracks["speed_um_s"] = tracks.step_px * fps * scale
    tracks["inside_start"] = [
        _signed_distance(start_poly, x, y) >= 0
        for x, y in zip(tracks.x, tracks.y)]
    tracks = apply_release_gate(tracks)

    med_area = tracks.groupby("track_id").area_px.transform("median")
    tracks["possible_collision"] = (
        (tracks.area_px > 1.8 * med_area) | (tracks.elongation < 1.35))
    for number, lawn in enumerate(lawns, 1):
        tracks[f"lawn_{number}_distance_px"] = [
            _signed_distance(lawn, x, y) for x, y in zip(tracks.x, tracks.y)]
        fraction_column = f"fraction_inside_lawn_{number}"
        if fraction_column in tracks:
            tracks[f"inside_lawn_{number}"] = (
                tracks[fraction_column] >= minimum_worm_fraction_inside)
        else:
            tracks[f"inside_lawn_{number}"] = (
                tracks[f"lawn_{number}_distance_px"] >= 0)
    inside_columns = [
        f"inside_lawn_{number}" for number in range(1, len(lawns) + 1)]
    tracks["inside_any_lawn"] = tracks[inside_columns].any(axis=1)

    event_table = derive_entry_events(
        tracks, fps, lawns, before_s=before_s, after_s=after_s,
        pre_entry_gap_s=pre_entry_gap_s,
        outside_buffer_px=outside_buffer_px,
        min_window_fraction=min_window_fraction)
    events = event_table.to_dict("records") if not event_table.empty else []

    out = Path(output_dir) if output_dir else (
        Path(folder) / "basal_slowing_results")
    out.mkdir(parents=True, exist_ok=True)
    tracks.to_csv(out / "detections_and_tracks.csv", index=False)
    summarize_departures(tracks, start_poly).to_csv(
        out / "departure_clocks.csv", index=False)
    stitches.to_csv(out / "inferred_tracklet_stitches.csv", index=False)
    event_table.to_csv(out / "paired_entry_events.csv", index=False)
    cv2.imwrite(str(out / "background_reference.png"), background)
    roi_data = {
        "start_roi": start_poly.tolist(),
        "lawn_rois": [x.tolist() for x in lawns],
    }
    if roi_metadata is not None:
        roi_data["shape_metadata"] = roi_metadata
    (out / "rois.json").write_text(
        json.dumps(roi_data, indent=2), encoding="utf-8")
    metadata = {
        **acquisition.as_columns(),
        "n_frames": len(files),
        "n_candidate_tracks": int(tracks.track_id.nunique()),
        "n_candidate_entries": len(events),
        "before_s": before_s,
        "after_s": after_s,
        "pre_entry_gap_s": pre_entry_gap_s,
        "outside_buffer_px": outside_buffer_px,
        "minimum_window_fraction": min_window_fraction,
        "minimum_worm_fraction_inside": minimum_worm_fraction_inside,
        "entry_definition":
            f"segmented worm area inside a student-drawn lawn reaches "
            f"{minimum_worm_fraction_inside:.1%}",
        "frequency_definition":
            "dominant oscillation of signed midbody spine curvature",
        "spine_definition":
            f"longest skeleton path, resampled to {SPINE_POINTS} ordered points",
        "background_definition":
            "20th temporal percentile; bright release-droplet worms are not "
            "allowed to become median-background ghosts",
        "origin_gate":
            "measurements begin at a track's first observed exit from the "
            "starting ROI, or at its first individual detection outside when "
            "animals were unresolved in the release droplet; tracks remain "
            "active after any later re-entry",
        "frequency_qc_rule":
            "missing spine frequency is reported separately and does not "
            "invalidate an otherwise usable speed comparison",
        "identity_rule":
            "constant-velocity linking followed by conservative position and "
            "heading-based tracklet stitching; inferred stitches are exported",
        "tracklet_stitch_max_gap_s": max_stitch_gap_s,
        "tracklet_stitch_max_distance_px": max_stitch_distance_px,
        "tracklet_stitch_max_heading_change_deg": max_heading_change_deg,
        "inference_rule":
            "paired within-worm before versus after entry; reviewed events only",
        "incapable_of_returning":
            "reliable identity or paired values when collisions, ambiguous "
            "crossings, or insufficient buffered windows occur",
    }
    (out / "analysis_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8")
    try:
        write_decision_manifest(out, "basal_slowing",
            method_note=(
                "Basal slowing events are proposed only after a linked worm track leaves the start region, "
                "enters a student-drawn lawn ROI, and has enough within-worm before/after windows for paired comparison. "
                "Ambiguous identity, collisions, missing windows, and weak frequency estimates are exported as QC rather than hidden."
            ),
            summary={
                "paired_events": int(len(event_table)) if event_table is not None else 0,
                "tracks_analyzed": int(len(tracks)) if tracks is not None else 0,
                # There is no single "minimum window" parameter - the paired
                # comparison is sized by the before and after windows, so record
                # both. This line previously referenced an undefined name, and
                # because the whole manifest write sits in a try/except the
                # NameError was caught silently: the decision manifest was never
                # written for ANY basal slowing run, leaving only a
                # decision_transparency_error.txt stub.
                "before_window_s": before_s,
                "after_window_s": after_s,
                "minimum_window_fraction": min_window_fraction,
                "minimum_worm_fraction_inside": minimum_worm_fraction_inside,
                "tracklet_stitch_max_gap_s": max_stitch_gap_s,
                "tracklet_stitch_max_distance_px": max_stitch_distance_px,
                "tracklet_stitch_max_heading_change_deg": max_heading_change_deg,
            },
            decision_files={
                "analysis_metadata_json": "analysis_metadata.json",
                "event_table_csv": "paired_entry_events.csv",
                "tracks_csv": "detections_and_tracks.csv",
                "stitches_csv": "inferred_tracklet_stitches.csv",
            },
            fields={
                "entry_definition": metadata["entry_definition"],
                "origin_gate": metadata["origin_gate"],
                "identity_rule": metadata["identity_rule"],
                "frequency_qc_rule": metadata["frequency_qc_rule"],
                "inference_rule": metadata["inference_rule"],
            },
            caveats=[
                "The paired unit is an unambiguous worm trajectory, not an isolated detection.",
                "Frequency uses a body-axis oscillation proxy; missing frequency is reported separately from usable speed.",
            ])
    except Exception as e:
        (out / "decision_transparency_error.txt").write_text(str(e), encoding="utf-8")
    return event_table, tracks, out
