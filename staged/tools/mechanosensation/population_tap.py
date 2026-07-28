"""Population tap-response analysis (centroid-based).

Piggybacks on the population tracker: it consumes a per-worm centroid track
table (columns ``track_id, frame, x, y``) plus a per-frame global-motion signal
(the plate tap moves the whole field of view).  From those it:

  * detects one or more taps as peaks in the global motion, with an intensity
    (peak motion above baseline), a duration (how long the field stays disturbed),
    and, across taps, a frequency (inter-tap interval);
  * splits each worm's centroid trajectory into a BEFORE and an AFTER window
    around each tap and pairs them, so each animal is its own control;
  * classifies, per worm x tap, whether the animal responded by altering speed
    and/or direction (and, when available, oscillation frequency), and rolls the
    per-worm calls up to a population summary (fraction responding, strength).

Everything here is pure NumPy/pandas and is unit-tested; it needs no clean
spines, only centroids.
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def global_motion_signal(gray_frames):
    """Per-frame global motion = mean absolute frame-to-frame difference.

    ``gray_frames`` is an indexable stack of 2-D grayscale frames.  Returns an
    array the same length as the stack (the first value repeats the second so
    the signal aligns with the frames).
    """
    n = len(gray_frames)
    if n < 2:
        return np.zeros(max(n, 1), dtype=float)
    diffs = np.empty(n, dtype=float)
    prev = np.asarray(gray_frames[0], dtype=np.float32)
    diffs[0] = 0.0
    for i in range(1, n):
        cur = np.asarray(gray_frames[i], dtype=np.float32)
        diffs[i] = float(np.mean(np.abs(cur - prev)))
        prev = cur
    diffs[0] = diffs[1]
    return diffs


def detect_taps(motion, times_s, *, k_mad=8.0, k_std=3.0, min_gap_s=1.0):
    """Detect taps as runs of global motion above a robust threshold.

    Returns a list of dicts (in time order): ``onset_s``, ``peak_frame``,
    ``intensity`` (peak motion above baseline), ``duration_s``, and
    ``interval_s`` (seconds since the previous tap, or None for the first).
    Runs whose onsets fall within ``min_gap_s`` of the previous tap are merged.
    """
    m = np.asarray(motion, dtype=float)
    t = np.asarray(times_s, dtype=float)
    n = m.size
    if n != t.size or n < 3:
        return []
    base = float(np.median(m))
    mad = float(np.median(np.abs(m - base)))
    thr = base + max(k_mad * mad, k_std * float(np.std(m)))
    above = m > thr
    taps = []
    i = 0
    last_onset = None
    while i < n:
        if above[i]:
            j = i
            while j + 1 < n and above[j + 1]:
                j += 1
            seg = np.arange(i, j + 1)
            peak = int(seg[int(np.argmax(m[seg]))])
            onset = float(t[i])
            if last_onset is not None and (onset - last_onset) < min_gap_s:
                # merge into the previous tap (same disturbance)
                prev = taps[-1]
                if m[peak] - base > prev["intensity"]:
                    prev["intensity"] = float(m[peak] - base)
                    prev["peak_frame"] = peak
                prev["duration_s"] = float(t[j] - t[prev["_start_idx"]])
            else:
                taps.append({
                    "onset_s": onset, "peak_frame": peak,
                    "intensity": float(m[peak] - base),
                    "duration_s": float(t[j] - t[i]),
                    "_start_idx": i})
                last_onset = onset
            i = j + 1
        else:
            i += 1
    previous = None
    for k, tap in enumerate(taps, start=1):
        tap.pop("_start_idx", None)
        tap["tap_number"] = k
        tap["interval_s"] = (None if previous is None
                             else round(tap["onset_s"] - previous, 4))
        previous = tap["onset_s"]
    return taps


def _segment_kinematics(t, x, y, scale=1.0):
    """Speed (units/s) and net heading (deg) over a centroid segment."""
    if t.size < 2:
        return {"speed": np.nan, "heading_deg": np.nan, "displacement": np.nan}
    dt = np.diff(t)
    dx = np.diff(x)
    dy = np.diff(y)
    ok = np.isfinite(dt) & (dt > 0) & np.isfinite(dx) & np.isfinite(dy)
    if not np.any(ok):
        return {"speed": np.nan, "heading_deg": np.nan, "displacement": np.nan}
    step = np.hypot(dx[ok], dy[ok])
    speed = float(np.mean(step / dt[ok])) * scale
    net_dx = float(np.nansum(dx))
    net_dy = float(np.nansum(dy))
    heading = float(np.degrees(np.arctan2(net_dy, net_dx)))
    disp = float(np.hypot(net_dx, net_dy)) * scale
    return {"speed": speed, "heading_deg": heading, "displacement": disp}


def _angle_diff_deg(a, b):
    if not (np.isfinite(a) and np.isfinite(b)):
        return np.nan
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


def tap_response_table(tracks, taps, fps, *, before_s=3.0, after_s=3.0,
                       scale=1.0, speed_change_frac=0.30,
                       direction_change_deg=45.0, min_baseline_speed=1e-6):
    """Per worm x tap paired before/after metrics and a responder call.

    ``tracks`` needs columns ``track_id, frame, x, y``.  For each worm and tap,
    the centroid track is split into a before window ``[t0-before_s, t0)`` and an
    after window starting once the tap disturbance has passed.  An animal is
    counted as having responded if its speed changed by more than
    ``speed_change_frac`` of its baseline speed OR its heading turned by more
    than ``direction_change_deg``.  Returns a DataFrame, one row per worm x tap.
    """
    need = {"track_id", "frame", "x", "y"}
    missing = sorted(need - set(tracks.columns))
    if missing:
        raise ValueError("tracks is missing columns: " + ", ".join(missing))
    tracks = tracks.sort_values(["track_id", "frame"])
    rows = []
    for tid, g in tracks.groupby("track_id", sort=False):
        t = pd.to_numeric(g["frame"], errors="coerce").to_numpy() / float(fps)
        x = pd.to_numeric(g["x"], errors="coerce").to_numpy()
        y = pd.to_numeric(g["y"], errors="coerce").to_numpy()
        for tap in taps:
            t0 = float(tap["onset_s"])
            dur = float(tap.get("duration_s", 0.0))
            bmask = (t >= t0 - before_s) & (t < t0)
            amask = (t > t0 + dur) & (t <= t0 + dur + after_s)
            before = _segment_kinematics(t[bmask], x[bmask], y[bmask], scale)
            after = _segment_kinematics(t[amask], x[amask], y[amask], scale)
            speed_change = after["speed"] - before["speed"]
            dir_change = _angle_diff_deg(before["heading_deg"],
                                         after["heading_deg"])
            base = before["speed"]
            speed_responded = bool(
                np.isfinite(speed_change) and np.isfinite(base)
                and base > min_baseline_speed
                and abs(speed_change) > speed_change_frac * base)
            dir_responded = bool(
                np.isfinite(dir_change) and dir_change > direction_change_deg)
            trackable = bool(bmask.sum() >= 2 and amask.sum() >= 2)
            rows.append({
                "track_id": int(tid),
                "tap_number": tap.get("tap_number"),
                "tap_onset_s": t0,
                "tap_intensity": tap.get("intensity"),
                "tap_interval_s": tap.get("interval_s"),
                "speed_before": before["speed"], "speed_after": after["speed"],
                "speed_change": speed_change,
                "heading_before_deg": before["heading_deg"],
                "heading_after_deg": after["heading_deg"],
                "direction_change_deg": dir_change,
                "displacement_before": before["displacement"],
                "displacement_after": after["displacement"],
                "trackable": trackable,
                "responded_speed": speed_responded,
                "responded_direction": dir_responded,
                "responded": bool(trackable
                                  and (speed_responded or dir_responded)),
            })
    return pd.DataFrame(rows)


def population_summary(response_table):
    """Per-tap population response summary from a tap_response_table."""
    if response_table is None or response_table.empty:
        return []
    rows = []
    for tap, g in response_table.groupby("tap_number", sort=True):
        eligible = g[g["trackable"]]
        n_elig = int(len(eligible))
        responders = eligible[eligible["responded"]]
        rows.append({
            "tap_number": (int(tap) if pd.notna(tap) else None),
            "tap_onset_s": float(g["tap_onset_s"].iloc[0]),
            "tap_intensity": float(g["tap_intensity"].iloc[0])
            if pd.notna(g["tap_intensity"].iloc[0]) else None,
            "tap_interval_s": (float(g["tap_interval_s"].iloc[0])
                               if pd.notna(g["tap_interval_s"].iloc[0])
                               else None),
            "n_eligible": n_elig,
            "n_responded": int(len(responders)),
            "fraction_responding": (len(responders) / n_elig
                                    if n_elig else None),
            "fraction_by_speed": (int(eligible["responded_speed"].sum()) / n_elig
                                  if n_elig else None),
            "fraction_by_direction": (
                int(eligible["responded_direction"].sum()) / n_elig
                if n_elig else None),
            "mean_abs_speed_change": (
                float(np.nanmean(np.abs(responders["speed_change"])))
                if len(responders) else None),
            "mean_direction_change_deg": (
                float(np.nanmean(responders["direction_change_deg"]))
                if len(responders) else None),
        })
    return rows
