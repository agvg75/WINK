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


def detect_episodes(frame_means, min_length=20, jump_factor=4.0):
    """Split a session into separate RECORDINGS by illumination changes.

    A folder is not always one recording. The usual protocol here is: find a
    worm under transmitted light at low magnification, zoom in, turn the
    transmitted light off, film under blue light, then move to the next worm.
    So one folder holds alternating BRIGHT search sequences and DIM
    fluorescence takes, several worms deep.

    Treating that as a single recording is what produced 88% frame-to-frame
    brightness variation and 106 abrupt level changes across 9000 frames, and
    it makes every whole-session statistic meaningless - a dF/F0 computed with
    a baseline drawn from transmitted-light frames is not a calcium
    measurement.

    Episodes are cut at abrupt level changes, since switching the illumination
    is a step and biology is not. Each is classified bright or dim relative to
    the session median, and only the dim ones are candidate fluorescence takes.
    """
    m = np.asarray(frame_means, dtype=float)
    if m.size < max(min_length * 2, 8):
        return [{"start": 0, "end": int(m.size) - 1, "n": int(m.size),
                 "mean": float(m.mean()) if m.size else 0.0,
                 "kind": "single", "stable": True}]
    jumps = np.abs(np.diff(m))
    typical = float(np.median(jumps))
    cuts = [0] + [int(i) + 1 for i in np.nonzero(
        jumps > max(jump_factor * typical, 1e-9))[0]] + [int(m.size)]

    episodes = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        if b - a < min_length:
            continue
        seg = m[a:b]
        episodes.append({"start": int(a), "end": int(b) - 1, "n": int(b - a),
                         "mean": float(np.mean(seg)),
                         "sd_over_mean": float(np.std(seg) / max(np.mean(seg), 1e-9))})
    if not episodes:
        return [{"start": 0, "end": int(m.size) - 1, "n": int(m.size),
                 "mean": float(m.mean()), "kind": "single", "stable": True}]

    # Split at the largest RATIO gap between episode levels, not at the median.
    # The median assumes half the episodes are bright, which is false - a
    # session may hold one brief transmitted-light look per worm and a long
    # fluorescence take. Measured on a real session: transmitted light sits at
    # ~22000 and fluorescence at ~1400, a factor of 16, while the median of the
    # episode levels landed at ~1400 and mislabelled four fluorescence takes as
    # bright. A gap that large is unmistakable; a median is not.
    levels = np.array(sorted(e["mean"] for e in episodes), dtype=float)
    split = float("inf")
    if levels.size >= 2:
        ratios = levels[1:] / np.maximum(levels[:-1], 1e-9)
        k = int(np.argmax(ratios))
        if ratios[k] >= 2.0:                     # a real illumination change
            split = float(np.sqrt(levels[k] * levels[k + 1]))
    for e in episodes:
        if np.isfinite(split):
            e["kind"] = ("bright (transmitted light?)" if e["mean"] > split
                         else "dim (fluorescence?)")
        else:
            # no clear gap: do not invent two classes where there is one
            e["kind"] = "uniform illumination"
        e["stable"] = bool(e["sd_over_mean"] < 0.05)
    return episodes


def _otsu_threshold(values, robust_percentiles=(0.1, 99.9)):
    """Otsu split of a 1-D/2-D array (numpy only, no skimage dependency).

    The histogram is built over a ROBUST range, not min-to-max. A 16-bit camera
    frame with a few hot or saturated pixels spans 0 to 64000 while the actual
    image content occupies a few hundred levels - so a 256-bin histogram over
    the full range put all the real data into about 13 bins and Otsu chose a
    threshold far above the object. Measured on a real GCaMP recording it
    declared a plainly visible worm "not separable from background": 13% of
    frames separable, contrast 1.55 against a floor of 2.0, on frames where the
    worm is obvious to the eye at a 1-99.5 percentile display.

    Clipping to percentiles keeps the resolution where the decision is actually
    made. Outliers are still counted - they are clipped into the end bins, not
    discarded - so a genuinely bimodal bright object is unaffected.
    """
    v = np.asarray(values, dtype=float).ravel()
    v = v[np.isfinite(v)]
    if v.size == 0:
        return 0.0
    lo = float(np.percentile(v, robust_percentiles[0]))
    hi = float(np.percentile(v, robust_percentiles[1]))
    if hi <= lo:
        lo, hi = float(v.min()), float(v.max())
    if hi <= lo:
        return lo
    v = np.clip(v, lo, hi)
    hist, edges = np.histogram(v, bins=256, range=(lo, hi))
    p = hist.astype(float)
    total = p.sum()
    if total <= 0:
        return lo
    p /= total
    omega = np.cumsum(p)
    mids = (edges[:-1] + edges[1:]) / 2.0
    mu = np.cumsum(p * mids)
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = 1e-12
    sigma_b = (mu_t * omega - mu) ** 2 / denom
    return float(mids[int(np.nanargmax(sigma_b))])


def body_visibility_pass(frames, *, min_area_frac=0.004, max_area_frac=0.5,
                         contrast_floor=2.0) -> dict:
    """Job 1: can the WORM BODY be told apart from the background well enough to
    infer its outline / spine / kinematics, even on dim (relaxed-muscle) frames?

    This makes no calcium claim. For each sampled frame it Otsu-splits the image,
    tries both polarities (body brighter OR dimmer than background), keeps the
    largest worm-plausible component, and scores |body-background| against the
    background noise. Reports the fraction of frames where the body is separable
    and the worst (dimmest) frame, so a myo-3::GCaMP recording can be judged for
    trackability before the single-worm tracker is run.
    """
    data = np.asarray(frames, dtype=float)
    if data.ndim != 3:
        raise ValueError("frames must be T,H,W.")
    H, W = data.shape[1:]
    area = float(H * W)
    per_frame = []
    for frame in data:
        thr = _otsu_threshold(frame)
        best = None
        for polarity, mask in (("bright", frame > thr), ("dark", frame < thr)):
            labels, count = ndi.label(mask)
            if count == 0:
                continue
            counts = np.bincount(labels.ravel())
            counts[0] = 0
            k = int(np.argmax(counts))
            comp_area = float(counts[k])
            if comp_area < min_area_frac * area or comp_area > max_area_frac * area:
                continue
            comp = labels == k
            fg = float(np.median(frame[comp]))
            rest = frame[~comp]
            bg = float(np.median(rest))
            # ROBUST noise, not the standard deviation. On a 16-bit camera
            # frame a handful of hot pixels sit three orders of magnitude above
            # the background, and std over that range is dominated entirely by
            # them - so contrast, which divides by it, collapses toward zero and
            # a plainly visible worm is declared "not separable from
            # background". Measured on a real GCaMP recording: contrast 1.55
            # against a floor of 2.0, on frames where the worm is obvious.
            # The MAD describes the typical fluctuation, which is what "noise"
            # was always meant to mean here.
            bgn = float(np.median(np.abs(rest - bg))) * 1.4826
            if bgn <= 0:
                bgn = float(np.std(rest))
            contrast = abs(fg - bg) / max(bgn, 1e-9)
            cand = {"polarity": polarity, "area_frac": comp_area / area,
                    "contrast": contrast, "separable": contrast >= contrast_floor}
            if best is None or contrast > best["contrast"]:
                best = cand
        per_frame.append(best or {"polarity": "none", "area_frac": 0.0,
                                  "contrast": 0.0, "separable": False})
    contrasts = np.asarray([f["contrast"] for f in per_frame], dtype=float)
    separable = np.asarray([f["separable"] for f in per_frame], dtype=bool)
    frac_sep = float(np.mean(separable)) if separable.size else 0.0
    median_contrast = float(np.median(contrasts)) if contrasts.size else 0.0
    worst_contrast = float(np.min(contrasts)) if contrasts.size else 0.0
    if frac_sep >= 0.9 and worst_contrast >= contrast_floor:
        tier = "outline reliably inferable"
    elif frac_sep >= 0.7:
        tier = "inferable in most frames"
    elif frac_sep >= 0.4:
        tier = "marginal - expect tracking gaps"
    else:
        tier = "not separable from background"
    return {
        "fraction_frames_body_separable": frac_sep,
        "median_body_background_contrast": median_contrast,
        "worst_frame_contrast": worst_contrast,
        "kinematics_inferable": bool(frac_sep >= 0.7),
        "difficulty_tier": tier,
        "contrast_floor": contrast_floor,
        "per_frame": per_frame,
        "thresholds_provisional": True}


def extract_oriented_cell(frames, soma_xy, tip_xy, neuron_radius_px, fps,
                          um_per_px, *, detection_snr=3, search_radius_px=20):
    """Job 2: track an elongated cell and its LONG AXIS over time.

    The user seeds the soma and the process tip (toward the nose); that vector
    defines orientation (soma -> process), NOT the direction of travel. Each
    frame the bright cell pixels near the predicted position are found, its
    intensity-weighted centroid and principal (long) axis are computed by
    weighted PCA, and the axis sign is kept continuous with the previous frame so
    the reported angle stays soma->tip. Outputs per-frame position, brightness,
    elongation, translational speed (px/s and um/s), and angular velocity
    (deg/s = rotation of the long axis). Low-signal frames hold the prediction.
    """
    data = np.asarray(frames, dtype=float)
    yy, xx = np.indices(data.shape[1:])
    center = np.asarray(soma_xy, dtype=float)
    tip = np.asarray(tip_xy, dtype=float)
    prev_dir = tip - center
    norm = np.linalg.norm(prev_dir)
    prev_dir = prev_dir / norm if norm > 1e-9 else np.asarray([1.0, 0.0])
    velocity = np.zeros(2)
    rows = []
    for index, frame in enumerate(data):
        predicted = center + velocity
        local = (xx - predicted[0]) ** 2 + (yy - predicted[1]) ** 2 <= search_radius_px ** 2
        background = float(np.median(frame[local])) if np.any(local) else 0.0
        noise = float(np.std(frame[local])) if np.any(local) else 1e-9
        smooth = ndi.gaussian_filter(frame, max(1, neuron_radius_px / 3))
        score = np.where(local, smooth, -np.inf)
        peak = np.unravel_index(np.argmax(score), score.shape)
        peak_snr = (float(score[peak]) - background) / max(noise, 1e-9)
        low_signal = peak_snr < detection_snr
        thr = background + max(float(detection_snr), 1.0) * max(noise, 1e-9)
        cell_mask = local & (frame >= thr)
        if low_signal or int(cell_mask.sum()) < 3:
            new_center = predicted
            orientation = prev_dir
            elongation = float("nan")
            roi = (xx - new_center[0]) ** 2 + (yy - new_center[1]) ** 2 <= neuron_radius_px ** 2
            brightness = float(np.mean(frame[roi])) if np.any(roi) else background
            provenance = "predicted_low_signal"
        else:
            wy, wx = np.where(cell_mask)
            weight = np.clip(frame[cell_mask].astype(float) - background, 0, None)
            wsum = float(weight.sum()) or 1.0
            cx = float((wx * weight).sum() / wsum)
            cy = float((wy * weight).sum() / wsum)
            new_center = np.asarray([cx, cy])
            dx = wx - cx
            dy = wy - cy
            cxx = float((weight * dx * dx).sum() / wsum)
            cyy = float((weight * dy * dy).sum() / wsum)
            cxy = float((weight * dx * dy).sum() / wsum)
            evals, evecs = np.linalg.eigh(np.asarray([[cxx, cxy], [cxy, cyy]]))
            major = evecs[:, int(np.argmax(evals))]
            vdir = np.asarray([float(major[0]), float(major[1])])
            if np.dot(vdir, prev_dir) < 0:
                vdir = -vdir
            vnorm = np.linalg.norm(vdir)
            orientation = vdir / vnorm if vnorm > 1e-9 else prev_dir
            lam = np.sort(evals)[::-1]
            elongation = float(np.sqrt(max(lam[0], 0.0) / max(lam[1], 1e-9)))
            brightness = float(weight.mean() + background)
            velocity = 0.7 * velocity + 0.3 * (new_center - center)
            provenance = "local_detection"
        angle = float(np.degrees(np.arctan2(orientation[1], orientation[0])))
        rows.append({
            "frame": index, "x": float(new_center[0]), "y": float(new_center[1]),
            "orientation_deg": angle,
            "orientation_dx": float(orientation[0]),
            "orientation_dy": float(orientation[1]),
            "brightness_f": brightness, "elongation": elongation,
            "detection_snr": peak_snr, "low_signal": bool(low_signal),
            "position_provenance": provenance})
        center = new_center
        prev_dir = orientation
    dt = 1.0 / float(fps) if fps else 1.0
    xs = np.asarray([r["x"] for r in rows], dtype=float)
    ys = np.asarray([r["y"] for r in rows], dtype=float)
    ang = np.radians(np.asarray([r["orientation_deg"] for r in rows], dtype=float))
    ang_unwrapped = np.unwrap(ang) if len(ang) else ang
    if len(rows) >= 2:
        trans = np.hypot(np.gradient(xs), np.gradient(ys)) / dt
        angv = np.gradient(ang_unwrapped) / dt
    else:
        trans = np.zeros(len(rows))
        angv = np.zeros(len(rows))
    for i, row in enumerate(rows):
        row["translational_speed_px_s"] = float(trans[i])
        row["translational_speed_um_s"] = float(trans[i] * um_per_px)
        row["angular_velocity_deg_s"] = float(np.degrees(angv[i]))
        row["orientation_unwrapped_deg"] = float(np.degrees(ang_unwrapped[i]))
    brights = [r["brightness_f"] for r in rows]
    baseline = float(np.percentile(brights, 20)) if brights else 0.0
    for row in rows:
        row["relative_dff"] = (
            None if baseline <= 0 else (row["brightness_f"] - baseline) / baseline)
    return {
        "rows": rows,
        "brightness_baseline": baseline,
        "seed_soma_xy": [float(soma_xy[0]), float(soma_xy[1])],
        "seed_tip_xy": [float(tip_xy[0]), float(tip_xy[1])],
        "orientation_convention": (
            "long axis soma->process(nose); angle in image degrees (x right, "
            "y down); angular velocity is rotation of that axis, not heading")}


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
