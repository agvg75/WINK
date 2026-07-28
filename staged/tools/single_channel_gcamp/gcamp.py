"""T13: transparent feasibility pass and low-signal-safe extractor."""
from __future__ import annotations

import numpy as np
from scipy import ndimage as ndi


def feasibility_pass(frames, centers_xy, neuron_radius_px, fps,
                     *, structural_frames_present=False) -> dict:
    data = np.asarray(frames, dtype=float)
    centers = np.asarray(centers_xy, dtype=float)
    if data.ndim != 3 or len(data) != len(centers):
        raise ValueError("frames must be T,H,W and centers one per sampled frame.")
    yy, xx = np.indices(data.shape[1:])
    contrasts, sharpness, competing = [], [], []
    detectable = []
    signals = []
    for frame, (cx, cy) in zip(data, centers):
        roi = (xx - cx)**2 + (yy - cy)**2 <= neuron_radius_px**2
        ann = ((xx - cx)**2 + (yy - cy)**2 >
               (neuron_radius_px * 1.5)**2) & (
              (xx - cx)**2 + (yy - cy)**2 <=
               (neuron_radius_px * 4)**2)
        signal = float(np.mean(frame[roi]))
        background = float(np.median(frame[ann])) if np.any(ann) else np.nan
        noise = float(np.std(frame[ann])) if np.any(ann) else np.nan
        contrast = (signal - background) / max(noise, 1e-9)
        signals.append(signal); contrasts.append(contrast)
        detectable.append(contrast >= 3)
        sharpness.append(float(np.var(ndi.laplace(frame))))
        labels, count = ndi.label(
            ann & (frame > background + 3 * max(noise, 1e-9)))
        competing.append(int(count))
    displacement = np.linalg.norm(np.diff(centers, axis=0), axis=1)
    time = np.arange(len(signals)) / float(fps)
    bleach_slope = (
        None if len(signals) < 2 else float(np.polyfit(time, signals, 1)[0]))
    below = 1 - float(np.mean(detectable))
    manual = min(1.0, below + 0.05 * np.mean(competing))
    if below > 0.5 or np.median(contrasts) < 1:
        tier = "do not attempt"
    elif manual > 0.25:
        tier = "difficult"
    elif manual > 0.05:
        tier = "moderate"
    else:
        tier = "favorable"
    return {
        "target_contrast_over_local_background_f0": float(
            np.median(contrasts)),
        "fraction_below_detection": below,
        "displacement_per_frame_relative_to_neuron_size": (
            None if not len(displacement) else float(
                np.median(displacement) / neuron_radius_px)),
        "competing_bright_objects_median": float(np.median(competing)),
        "focus_sharpness_variance": float(np.var(sharpness)),
        "photobleaching_slope_intensity_per_s": bleach_slope,
        "structural_frames_present": bool(structural_frames_present),
        "difficulty_tier": tier,
        "expected_manual_relink_fraction": manual,
        "thresholds_provisional": True}


def extract_trace(frames, seed_xy, neuron_radius_px, *,
                  detection_snr=3, search_radius_px=15):
    """Track by local continuity; hold/predict on low signal, never jump globally."""
    data = np.asarray(frames, dtype=float)
    yy, xx = np.indices(data.shape[1:])
    center = np.asarray(seed_xy, dtype=float)
    velocity = np.zeros(2)
    rows = []
    raw_values = []
    for index, frame in enumerate(data):
        predicted = center + velocity
        local = (xx - predicted[0])**2 + (yy - predicted[1])**2 <= (
            search_radius_px**2)
        background = float(np.median(frame[local]))
        noise = float(np.std(frame[local]))
        smooth = ndi.gaussian_filter(frame, max(1, neuron_radius_px / 3))
        score = np.where(local, smooth, -np.inf)
        peak_index = np.unravel_index(np.argmax(score), score.shape)
        candidate = np.asarray([peak_index[1], peak_index[0]], dtype=float)
        peak_snr = (float(score[peak_index]) - background) / max(noise, 1e-9)
        low_signal = peak_snr < detection_snr
        if low_signal:
            chosen = predicted
            provenance = "predicted_low_signal"
        else:
            chosen = candidate
            velocity = 0.7 * velocity + 0.3 * (candidate - center)
            provenance = "local_detection"
        center = chosen
        roi = (xx - center[0])**2 + (yy - center[1])**2 <= neuron_radius_px**2
        raw = float(np.mean(frame[roi]))
        raw_values.append(raw)
        rows.append({
            "frame": index, "x": float(center[0]), "y": float(center[1]),
            "absolute_f0_signal": raw, "detection_snr": peak_snr,
            "low_signal": low_signal, "position_provenance": provenance,
            "manual_relink_required": low_signal})
    baseline = float(np.percentile(raw_values, 20))
    for row in rows:
        row["relative_dff"] = (
            None if baseline <= 0 else
            (row["absolute_f0_signal"] - baseline) / baseline)
    return {
        "rows": rows, "absolute_f0_baseline": baseline,
        "relative_signal_kept_distinct": True,
        "global_brightest_blob_search_used": False}
