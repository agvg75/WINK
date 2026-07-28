"""Shared temporal constraints for single-worm outline/spine trackers.

The helpers here never overwrite a directly measured frame unless it has already
failed QC.  Reconstructed frames carry explicit provenance and retain the raw
geometry in ``raw_pts``/``raw_path``.
"""
from __future__ import annotations

import numpy as np


def polyline_length(points):
    points = np.asarray(points, float)
    if len(points) < 2:
        return np.nan
    return float(np.hypot(np.diff(points[:, 0]), np.diff(points[:, 1])).sum())


def resample_polyline(points, count):
    points = np.asarray(points, float)
    if len(points) < 2:
        return None
    step = np.hypot(np.diff(points[:, 0]), np.diff(points[:, 1]))
    arc = np.r_[0.0, np.cumsum(step)]
    if not np.isfinite(arc[-1]) or arc[-1] <= 0:
        return None
    target = np.linspace(0.0, arc[-1], int(count))
    return np.column_stack([
        np.interp(target, arc, points[:, 0]),
        np.interp(target, arc, points[:, 1]),
    ])


def centerline_jaggedness(points):
    """Return a scale-free roughness score for a worm centerline.

    A real crawling/swimming worm can bend strongly, but the centerline should
    remain a smooth biological wave rather than a saw-tooth polyline.  The
    score is the excess polyline length relative to end-to-end distance; higher
    values flag jagged or overfit spines.
    """
    points = np.asarray(points, float)
    if len(points) < 3:
        return np.nan
    length = polyline_length(points)
    chord = float(np.linalg.norm(points[-1]-points[0]))
    if not np.isfinite(length) or not np.isfinite(chord) or chord <= 0:
        return np.nan
    return float(max(0.0, length/chord-1.0))


def smooth_centerline(points, count=None, window_fraction=0.18,
                      iterations=2, preserve_endpoints=True,
                      preserve_length=True):
    """Smooth a measured centerline without changing its biological contract.

    This is intentionally conservative and dependency-light: resample to a
    stable number of points, apply a short symmetric moving-average along the
    arc, optionally pin endpoints, and rescale to the original arc length.  It
    is meant for optional QC/editing paths, not as a silent replacement for raw
    measurements.
    """
    raw = np.asarray(points, float)
    if len(raw) < 4:
        return raw.copy()
    if count is None:
        count = len(raw)
    pts = resample_polyline(raw, int(count))
    if pts is None:
        return raw.copy()
    original_length = polyline_length(pts)
    n = len(pts)
    window = int(round(max(3, min(n//2*2-1, n*float(window_fraction)))))
    if window % 2 == 0:
        window += 1
    window = max(3, min(window, n if n % 2 else n-1))
    kernel = np.ones(window, float)/window
    pad = window//2
    for _ in range(max(1, int(iterations))):
        padded = np.pad(pts, ((pad, pad), (0, 0)), mode="edge")
        pts = np.column_stack([
            np.convolve(padded[:, 0], kernel, mode="valid"),
            np.convolve(padded[:, 1], kernel, mode="valid"),
        ])
        if preserve_endpoints:
            pts[0] = raw[0]
            pts[-1] = raw[-1]
    if preserve_length and np.isfinite(original_length) and original_length > 0:
        current = polyline_length(pts)
        if np.isfinite(current) and current > 0:
            origin = pts[0].copy()
            pts = origin+(pts-origin)*(original_length/current)
            if preserve_endpoints:
                pts[0] = raw[0]
                pts[-1] = raw[-1]
    return pts


def centerline_qc(points, expected_length=None):
    """Summarize centerline plausibility for transparent review exports."""
    points = np.asarray(points, float)
    length = polyline_length(points)
    jagged = centerline_jaggedness(points)
    out = {
        "length_px": float(length) if np.isfinite(length) else np.nan,
        "jaggedness": float(jagged) if np.isfinite(jagged) else np.nan,
        "point_count": int(len(points)),
    }
    if expected_length is not None and np.isfinite(expected_length) and expected_length > 0 and np.isfinite(length):
        out["length_fraction_of_expected"] = float(length/expected_length)
        out["length_deviation_fraction"] = float(abs(length-expected_length)/expected_length)
    return out


def orient_to_reference(points, reference):
    """Return the polarity whose whole-spine displacement is smallest."""
    points = np.asarray(points, float)
    reference = np.asarray(reference, float)
    if len(points) != len(reference):
        points = resample_polyline(points, len(reference))
    if points is None:
        return None
    forward = np.nanmean(np.linalg.norm(points-reference, axis=1))
    reverse = np.nanmean(np.linalg.norm(points[::-1]-reference, axis=1))
    return points[::-1].copy() if reverse < forward else points.copy()


def stabilize_endpoints(states, max_offset_fraction=0.08):
    """Replace isolated endpoint jumps only when both temporal neighbors agree."""
    fixed = 0
    for i in range(1, len(states)-1):
        state, left, right = states[i], states[i-1], states[i+1]
        if not state or not left or not right or state.get("provenance") == "manual":
            continue
        pts = state.get("pts")
        lp, rp = left.get("pts"), right.get("pts")
        if pts is None or lp is None or rp is None:
            continue
        pts = orient_to_reference(pts, (np.asarray(lp)+np.asarray(rp))/2.0)
        scale = np.nanmedian([left.get("length", np.nan), right.get("length", np.nan)])
        if not np.isfinite(scale) or scale <= 0:
            continue
        changed = False
        for endpoint in (0, -1):
            expected = (np.asarray(lp)[endpoint]+np.asarray(rp)[endpoint])/2.0
            neighbor_disagreement = np.linalg.norm(np.asarray(lp)[endpoint]-np.asarray(rp)[endpoint])
            tolerance = max(max_offset_fraction*scale, 2.5*neighbor_disagreement, 2.0)
            if np.linalg.norm(pts[endpoint]-expected) > tolerance:
                pts[endpoint] = expected
                changed = True
        if changed:
            state.setdefault("raw_pts", np.asarray(state["pts"], float).copy())
            state["pts"] = pts
            state["head"] = tuple(map(float, pts[0]))
            state["tail"] = tuple(map(float, pts[-1]))
            state["endpoint_stabilized"] = 1
            state["provenance"] = "measured_endpoint_stabilized"
            fixed += 1
    return fixed


def _spine_centroid(points):
    points = np.asarray(points, float)
    return np.nanmean(points, axis=0)


def _gap_bridgeability(left_points, right_points, target_length=None,
                       max_translation_fraction=0.5,
                       max_shape_disagreement_fraction=0.35):
    """Assess a gap in body-length units, never in a fixed number of frames."""
    left_points = np.asarray(left_points, float)
    right_points = orient_to_reference(right_points, left_points)
    if right_points is None:
        return False, "right spine could not be oriented", np.nan, np.nan, None
    scale = target_length
    if scale is None or not np.isfinite(scale) or scale <= 0:
        scale = np.nanmedian([polyline_length(left_points),
                              polyline_length(right_points)])
    if not np.isfinite(scale) or scale <= 0:
        return False, "body length is unavailable", np.nan, np.nan, right_points
    translation = float(np.linalg.norm(
        _spine_centroid(right_points)-_spine_centroid(left_points))/scale)
    # Remove translation before comparing posture. This prevents a stationary
    # shape change from being mistaken for a safely bridgeable interval.
    aligned = right_points-(_spine_centroid(right_points)-_spine_centroid(left_points))
    shape = float(np.sqrt(np.nanmean(np.sum((aligned-left_points)**2, axis=1)))/scale)
    if translation > max_translation_fraction:
        return False, (f"flanking centroids differ by {translation:.2f} body lengths "
                       f"(limit {max_translation_fraction:.2f})"), translation, shape, right_points
    if shape > max_shape_disagreement_fraction:
        return False, (f"flanking postures differ by {shape:.2f} body lengths RMS "
                       f"(limit {max_shape_disagreement_fraction:.2f})"), translation, shape, right_points
    return True, "flanking spines are bridgeable", translation, shape, right_points


def suggest_manual_anchor_frames(states, good=None):
    """Return one uncertainty-halving anchor per unresolved run.

    Re-running this function after a user correction recursively bisects only
    the intervals that remain unresolved, minimizing hand-drawn outlines.
    """
    if good is None:
        good = lambda s: bool(s and s.get("pts") is not None and not s.get("needs_help", 1))
    suggestions = []
    i = 0
    while i < len(states):
        if good(states[i]):
            i += 1
            continue
        start = i
        while i < len(states) and not good(states[i]):
            i += 1
        end = i-1
        suggestions.append((start+end)//2)
    return suggestions


def fill_adaptive_spine_gaps(states, target_length=None, good=None,
                             variable_length=None,
                             max_translation_fraction=0.5,
                             max_shape_disagreement_fraction=0.35):
    """Bridge any two-sided QC failure that is safe in body-length units.

    There is deliberately no frame-count ceiling. Gap duration is represented
    by the actual displacement and posture disagreement of its trusted flanks.
    ``variable_length`` preserves calibrated biological length changes (pBoc).
    Unbridgeable runs receive an uncertainty-halving manual-anchor suggestion.
    """
    if good is None:
        good = lambda s: bool(s and s.get("pts") is not None and not s.get("needs_help", 1))
    for state in states:
        if state is not None:
            state["suggested_manual_anchor"] = 0
    filled = []
    i = 0
    while i < len(states):
        if good(states[i]):
            i += 1
            continue
        start = i
        while i < len(states) and not good(states[i]):
            i += 1
        end, left, right = i-1, start-1, i
        if left < 0 or right >= len(states):
            reason = "trusted spines are not available on both sides"
            anchor = (start+end)//2
            for frame in range(start, end+1):
                if states[frame] is not None:
                    states[frame]["reconstruction_reason"] = reason
                    states[frame]["suggested_manual_anchor"] = int(frame == anchor)
            continue
        lp, rp = states[left].get("pts"), states[right].get("pts")
        if lp is None or rp is None:
            continue
        bridgeable, reason, translation, shape, rp = _gap_bridgeability(
            lp, rp, target_length=target_length,
            max_translation_fraction=max_translation_fraction,
            max_shape_disagreement_fraction=max_shape_disagreement_fraction)
        if not bridgeable:
            anchor = (start+end)//2
            for frame in range(start, end+1):
                if states[frame] is not None:
                    states[frame]["reconstruction_reason"] = reason
                    states[frame]["flank_translation_body_lengths"] = translation
                    states[frame]["flank_shape_disagreement_body_lengths"] = shape
                    states[frame]["suggested_manual_anchor"] = int(frame == anchor)
            continue
        for frame in range(start, end+1):
            fraction = (frame-left)/(right-left)
            pts = (1-fraction)*np.asarray(lp, float)+fraction*np.asarray(rp, float)
            desired = (variable_length(frame, fraction, states[left], states[right])
                       if variable_length is not None else target_length)
            if desired is not None and np.isfinite(desired) and desired > 0:
                current = polyline_length(pts)
                if np.isfinite(current) and current > 0:
                    origin = pts[0].copy()
                    pts = origin+(pts-origin)*(desired/current)
            state = states[frame] or {}
            if state.get("pts") is not None:
                state.setdefault("raw_pts", np.asarray(state["pts"], float).copy())
                state.setdefault("raw_path", state.get("path"))
                state.setdefault("raw_length", state.get("length", np.nan))
            state.update(
                pts=pts, path=pts.copy(), length=polyline_length(pts),
                head=tuple(map(float, pts[0])), tail=tuple(map(float, pts[-1])),
                provenance="inferred_between_neighbors", needs_help=0,
                temporal_left_frame=left, temporal_right_frame=right,
                geometry_inferred=1, reconstruction_reason=reason,
                flank_translation_body_lengths=translation,
                flank_shape_disagreement_body_lengths=shape,
                suggested_manual_anchor=0)
            states[frame] = state
            filled.append(frame)
    return filled


def fill_short_spine_gaps(states, max_gap=None, target_length=None,
                          good=None, variable_length=None):
    """Compatibility wrapper for releases that used a frame-count limit.

    ``max_gap`` is accepted but intentionally ignored: current policy is based
    on animal displacement and posture, not recording frame rate.
    """
    return fill_adaptive_spine_gaps(
        states, target_length=target_length, good=good,
        variable_length=variable_length)
