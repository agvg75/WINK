"""Prototype full-recording pBoc scan using worm-centered optical flow.

This is an analysis prototype. It reads source TIFFs without changing them and
writes derived tables under defecation_feasibility_results.
"""
from __future__ import annotations

import argparse
import csv
import gzip
import json
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import gaussian_filter1d

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
from defecation_feasibility import (
    load_downsampled, numbered_images, raw_track, track_distractor_episodes)
from segmentation_review import find_accepted_config, scaled_config
from acquisition import AcquisitionMetadata
from decision_transparency import write_decision_manifest
from skimage.draw import polygon2mask
from neuron_tracker import geodesic_midline


ROOT = Path(__file__).resolve().parent


def json_clean(value):
    if isinstance(value, dict): return {k: json_clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [json_clean(v) for v in value]
    if isinstance(value, np.generic): value = value.item()
    if isinstance(value, float) and not np.isfinite(value): return None
    return value


def display_u8(frame: np.ndarray) -> np.ndarray:
    lo, hi = np.percentile(frame, [1, 99])
    return np.clip((frame - lo) * 255 / max(hi - lo, 1), 0, 255).astype(np.uint8)


def sample_flow(flow, image, points, direction, radius=8):
    direction = np.asarray(direction, float)
    norm = np.linalg.norm(direction)
    if norm <= 0:
        return np.nan, np.nan
    tangent = direction / norm
    normal = np.array([-tangent[1], tangent[0]])
    gx = cv2.Sobel(image, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(image, cv2.CV_32F, 0, 1)
    gradient = np.hypot(gx, gy)
    tangential, normal_motion, weights = [], [], []
    h, w = image.shape
    yy, xx = np.ogrid[:h, :w]
    for x, y in points:
        mask = (xx - x) ** 2 + (yy - y) ** 2 <= radius ** 2
        if not mask.any():
            continue
        local_flow = flow[mask]
        local_weight = gradient[mask] + 1.0
        tangential.extend(local_flow @ tangent)
        normal_motion.extend(np.abs(local_flow @ normal))
        weights.extend(local_weight)
    if not weights:
        return np.nan, np.nan
    weights = np.asarray(weights)
    return (
        float(np.average(np.asarray(tangential), weights=weights)),
        float(np.average(np.asarray(normal_motion), weights=weights)),
    )


def axial_participating_fraction(flow, image, points, body_mask, index_range):
    """Fraction of textured worm pixels whose residual motion is chiefly axial."""
    if points is None or body_mask is None or not np.any(body_mask):
        return np.nan, 0
    points = np.asarray(points, float)
    ys, xs = np.where(np.asarray(body_mask, bool))
    if not len(xs):
        return np.nan, 0
    coords = np.column_stack([xs, ys])
    nearest = np.argmin(((coords[:, None, :]-points[None, :, :])**2).sum(2), axis=1)
    lo, hi = index_range
    keep = (nearest >= lo) & (nearest <= hi)
    if not np.any(keep):
        return np.nan, 0
    coords, nearest = coords[keep], nearest[keep]
    gx = cv2.Sobel(image, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(image, cv2.CV_32F, 0, 1)
    texture = np.hypot(gx[coords[:, 1], coords[:, 0]],
                       gy[coords[:, 1], coords[:, 0]])
    reliable = texture >= np.percentile(texture, 35)
    if reliable.sum() < 10:
        return np.nan, int(reliable.sum())
    coords, nearest = coords[reliable], nearest[reliable]
    before = np.maximum(0, nearest-1)
    after = np.minimum(len(points)-1, nearest+1)
    tangent = points[after]-points[before]
    tangent /= np.maximum(np.linalg.norm(tangent, axis=1, keepdims=True), 1e-6)
    normal = np.column_stack([-tangent[:, 1], tangent[:, 0]])
    vectors = flow[coords[:, 1], coords[:, 0]]
    axial = np.abs(np.sum(vectors*tangent, axis=1))
    transverse = np.abs(np.sum(vectors*normal, axis=1))
    speed_floor = max(0.05, float(np.percentile(np.linalg.norm(vectors, axis=1), 35)))
    participating = (axial >= speed_floor) & (axial > transverse)
    return float(participating.mean()), int(len(participating))


def robust_z(x):
    finite = np.isfinite(x)
    out = np.full_like(x, np.nan, dtype=float)
    if finite.sum() < 10:
        return out
    median = np.median(x[finite])
    mad = np.median(np.abs(x[finite] - median)) * 1.4826
    out[finite] = (x[finite] - median) / max(mad, 1e-6)
    return out


def build_pboc_calibration(seed_document, image_shape, scale, fps):
    """Measure the traced baseline -> peak -> recovered example."""
    anchors = seed_document.get("pboc_anchors", []) if seed_document else []
    if len(anchors) != 3 or [a.get("state") for a in anchors] != [
            "baseline", "peak", "recovered"]:
        raise ValueError("pBoc requires baseline, peak, and recovered outline anchors.")
    measured = []
    for anchor in anchors:
        vertices = np.asarray(anchor["outline_xy"], float) * scale
        mask = polygon2mask(image_shape, np.asarray([(y, x) for x, y in vertices]))
        path, length = geodesic_midline(mask)
        if path is None or length <= 0:
            raise ValueError(f"The {anchor['state']} pBoc outline has no usable spine.")
        measured.append({**anchor, "length_px": float(length),
                         "area_px": float(mask.sum())})
    baseline, peak, recovered = measured
    shortening = (baseline["length_px"]-peak["length_px"])/baseline["length_px"]
    recovery_error = abs(recovered["length_px"]-baseline["length_px"])/baseline["length_px"]
    area_values = np.asarray([a["area_px"] for a in measured])
    area_cv = float(np.std(area_values)/max(np.mean(area_values), 1.0))
    if shortening <= 0:
        raise ValueError("Peak pBoc outline is not shorter than the baseline outline.")
    warnings = []
    if not 0.03 <= shortening <= 0.12:
        warnings.append("shortening_outside_expected_3_to_12_percent")
    if recovery_error > 0.08:
        warnings.append("recovered_length_differs_from_baseline_over_8_percent")
    if area_cv > 0.15:
        warnings.append("anchor_area_not_conserved")
    contract_frames = peak["frame"]-baseline["frame"]
    recover_frames = recovered["frame"]-peak["frame"]
    if contract_frames <= 0 or recover_frames <= 0:
        raise ValueError("pBoc anchors must be ordered baseline < peak < recovered.")
    delta = baseline["length_px"]-peak["length_px"]
    return {
        "anchors": measured, "baseline_length_px": baseline["length_px"],
        "peak_length_px": peak["length_px"],
        "recovered_length_px": recovered["length_px"],
        "shortening_fraction": float(shortening), "area_cv": area_cv,
        "contraction_duration_s": contract_frames/fps,
        "recovery_duration_s": recover_frames/fps,
        "contraction_rate_px_s": delta/(contract_frames/fps),
        "recovery_rate_px_s": delta/(recover_frames/fps), "warnings": warnings,
    }


def calibrated_pboc_score(flow_score, lengths, areas, calibration):
    baseline, peak = calibration["baseline_length_px"], calibration["peak_length_px"]
    contraction = np.clip(
        (baseline-np.asarray(lengths, float))/max(baseline-peak, 1e-6), -1.0, 2.0)
    area_ref = np.median([a["area_px"] for a in calibration["anchors"]])
    area_error = np.abs(np.asarray(areas, float)-area_ref)/max(area_ref, 1.0)
    geometry = robust_z(contraction)-2.0*np.clip(area_error, 0, 1)
    flow_z = robust_z(flow_score)
    combined = np.where(np.isfinite(flow_z), flow_z, 0.0) + 0.75*np.where(
        np.isfinite(geometry), geometry, 0.0)
    return combined, contraction, area_error


def candidate_events(score_z, fps, contraction_z, recovery_z, merge=True,
                     merge_s=5.0):
    """Detect pBoc events in a z-scored contraction signal.

    `merge` FUSES events closer than `merge_s` seconds into one. It is on by
    default because two supra-threshold islands from a single contraction
    should not count twice - but it is the reason an animal whose defecation
    cycle is shorter than 5 s is silently undercounted, with nothing in the
    output to say so.

    That is exactly why it is now optional. `sensitive_rescanner` below turns
    it off inside the narrow windows where the animal's own rhythm says an
    event went missing, which recovers the merged pairs without loosening
    detection anywhere else - and without changing anything at all for an
    animal whose record was already regular.
    """
    above = np.isfinite(score_z) & (score_z >= contraction_z)
    labels, count = __import__("scipy").ndimage.label(above)
    peaks = []
    for label in range(1, count + 1):
        indices = np.where(labels == label)[0]
        if not len(indices):
            continue
        peak = int(indices[np.nanargmax(score_z[indices])])
        recover_end = min(len(score_z), peak + max(3, int(round(6 * fps))))
        recovery_slice = score_z[peak + 1:recover_end]
        recovery = None
        if len(recovery_slice) and np.isfinite(recovery_slice).any():
            local = int(np.nanargmin(recovery_slice))
            if recovery_slice[local] <= recovery_z:
                recovery = peak + 1 + local
        peaks.append({
            "peak_frame": peak,
            "peak_time_s": peak / fps,
            "peak_z": float(score_z[peak]),
            "recovery_frame": recovery,
            "recovery_time_s": recovery / fps if recovery is not None else np.nan,
            "has_recovery": recovery is not None,
        })
    if not merge:
        return peaks
    # Merge duplicate supra-threshold islands that are part of the same event,
    # AND RECORD EVERY MERGE. Inferring merges afterwards from over-long
    # intervals only works when the absorbed event sat mid-cycle; a second
    # contraction close to an existing one is absorbed without disturbing the
    # interval structure at all, so the rhythm never reveals it. The detector
    # does not have to infer what it just did - each surviving event carries
    # the count and frames of what was folded into it.
    merged = []
    merge_distance = int(round(merge_s * fps))
    for event in peaks:
        if merged and event["peak_frame"] - merged[-1]["peak_frame"] < merge_distance:
            keeper = dict(event) if event["peak_z"] > merged[-1]["peak_z"] \
                else dict(merged[-1])
            absorbed = list(merged[-1].get("absorbed_frames", []))
            absorbed += list(event.get("absorbed_frames", []))
            loser = (merged[-1] if keeper["peak_frame"] == event["peak_frame"]
                     else event)
            absorbed.append(int(loser["peak_frame"]))
            keeper["absorbed_frames"] = sorted(set(absorbed))
            keeper["n_absorbed"] = len(keeper["absorbed_frames"])
            merged[-1] = keeper
        else:
            e = dict(event)
            e.setdefault("absorbed_frames", [])
            e.setdefault("n_absorbed", 0)
            merged.append(e)
    return merged


def merge_report(events, fps, merge_s=5.0):
    """What the merge step removed, so it can be reviewed rather than inferred.

    THE SIGNAL THE RHYTHM CANNOT GIVE YOU. A rescan driven by over-long
    intervals recovers events that were absorbed MID-CYCLE, because those
    lengthen an interval. An extra contraction a second or two after a normal
    one is absorbed with the interval structure untouched, and no amount of
    looking at periodicity will surface it. This does, because the detector
    recorded it at the time.

    A recording with a non-zero merge count is a candidate for review whatever
    its rhythm looks like - and the count is worth comparing across genotypes
    on its own, since an animal that genuinely contracts in doublets would show
    up here as a merge rate rather than as a phenotype.
    """
    absorbed = [f for e in events for f in e.get("absorbed_frames", [])]
    per_event = [e for e in events if e.get("n_absorbed", 0) > 0]
    return {
        "n_events_reported": len(events),
        "n_absorbed": len(absorbed),
        "absorbed_frames": sorted(absorbed),
        "events_that_absorbed_something": len(per_event),
        "merge_window_s": float(merge_s),
        "true_upper_bound": len(events) + len(absorbed),
        "needs_review": bool(absorbed),
        "why": (
            f"{len(absorbed)} supra-threshold contraction(s) were folded into "
            f"a neighbour within {merge_s} s. If those were separate events "
            f"the true count is up to {len(events) + len(absorbed)}, not "
            f"{len(events)}. Periodicity will NOT reveal these: an event "
            f"absorbed next to an existing one leaves the interval structure "
            f"unchanged." if absorbed else
            f"No contractions were merged, so the reported count of "
            f"{len(events)} is not affected by the {merge_s} s window."),
    }


def sensitive_rescanner(score_z, fps, contraction_z, recovery_z,
                        threshold_factor=0.65):
    """Build the second-pass detector for `app.adaptive_rescan.rescan`.

    Returns `rescanner(start_frame, end_frame)` giving any additional peak
    frames strictly inside that window. Two things are relaxed, and ONLY inside
    the window:

      merging is off      so a genuine second contraction less than 5 s after
                          the first is kept rather than absorbed
      threshold lowered   by `threshold_factor`, because an event that the
                          first pass missed is by definition one that did not
                          clear the original bar

    Relaxing both everywhere would buy the missed events back at the cost of
    false ones throughout, and would do it unevenly between genotypes if one
    sits closer to the threshold than the other. Restricted to windows the
    animal's OWN rhythm flagged, neither risk applies: a regular animal is
    never rescanned at all.
    """
    z = np.asarray(score_z, dtype=float)

    def rescanner(start_frame, end_frame):
        a, b = int(start_frame), int(end_frame)
        if b - a < 3:
            return []
        window = z[a:b + 1]
        found = candidate_events(window, fps,
                                 contraction_z * float(threshold_factor),
                                 recovery_z, merge=False)
        return [a + int(e["peak_frame"]) for e in found]

    return rescanner


def apply_distractor_identity_gate(target_states, target_masks,
                                   distractor_masks, distractor_results,
                                   proximity_px=8):
    """Fail closed wherever a moving distractor is lost or contacts the target."""
    unknown_frames = set()
    for result in distractor_results:
        usable_frames = set(result["usable_frames"])
        unknown_frames.update(
            set(range(result["start_frame"], result["end_frame"] + 1))
            - usable_frames)
    for i, (state, target_mask, excluded) in enumerate(zip(
            target_states, target_masks, distractor_masks)):
        contact = False
        if target_mask is not None and np.any(excluded):
            contact = bool(np.any(
                __import__("scipy").ndimage.binary_dilation(
                    np.asarray(target_mask, bool), iterations=proximity_px)
                & np.asarray(excluded, bool)))
        if i in unknown_frames or contact:
            state["needs_help"] = 1
            state["provenance"] = "help"
            state["identity_warning"] = (
                "target_distractor_contact" if contact else
                "distractor_identity_not_observable")


def build_focus_exclusion(focus_document, n_frames, image_shape_hw, scale):
    """Per-frame masks that exclude everything OUTSIDE a user's moving worm box.

    ``focus_document`` is written by the tool as
    ``{"box_wh": [w, h], "anchors": [[frame, cx, cy], ...]}`` in FULL-resolution
    source pixels. The box centre is linearly interpolated between anchors (held
    flat before the first and after the last), then converted to the downsampled
    analysis grid with the same ``* scale`` convention the seed outline uses.
    Returns a list of boolean masks (``True`` = excluded) of length ``n_frames``,
    or ``None`` when there is nothing to focus on. This only restricts WHERE the
    tracker looks; it does not touch any pBoc measurement formula.
    """
    if not focus_document:
        return None
    anchors = focus_document.get("anchors") or []
    box = focus_document.get("box_wh") or []
    if not anchors or len(box) < 2:
        return None
    H, W = int(image_shape_hw[0]), int(image_shape_hw[1])
    w = max(1, int(round(float(box[0]) * scale)))
    h = max(1, int(round(float(box[1]) * scale)))
    frames_sorted = sorted({int(a[0]) for a in anchors})
    cx_by_frame = {int(a[0]): float(a[1]) * scale for a in anchors}
    cy_by_frame = {int(a[0]): float(a[2]) * scale for a in anchors}
    idx = np.arange(int(n_frames))
    fs = np.asarray(frames_sorted, dtype=float)
    cx_series = np.interp(idx, fs, np.asarray([cx_by_frame[f] for f in frames_sorted]))
    cy_series = np.interp(idx, fs, np.asarray([cy_by_frame[f] for f in frames_sorted]))
    masks = []
    for cx, cy in zip(cx_series, cy_series):
        x0 = int(round(cx - w / 2.0)); y0 = int(round(cy - h / 2.0))
        x0 = max(0, min(x0, W - w)); y0 = max(0, min(y0, H - h))
        excluded = np.ones((H, W), dtype=bool)
        excluded[y0:y0 + h, x0:x0 + w] = False
        masks.append(excluded)
    return masks


def _union_exclusions(distractor_masks, focus_masks, n_frames):
    """Combine distractor masks and worm-focus masks (True = excluded)."""
    if focus_masks is None:
        return distractor_masks
    combined = []
    for i in range(n_frames):
        focus = focus_masks[i]
        dm = None
        if distractor_masks is not None and i < len(distractor_masks):
            dm = distractor_masks[i]
        if dm is None:
            combined.append(focus)
        else:
            combined.append(np.asarray(dm, bool) | focus)
    return combined


def main():
    p = argparse.ArgumentParser()
    p.add_argument("folder", type=Path)
    p.add_argument("--name", required=True)
    p.add_argument("--fps", type=float, required=True)
    p.add_argument("--um-per-px", type=float, required=True)
    p.add_argument("--exposure-ms", type=float, required=True)
    p.add_argument("--fps-source", choices=["camera", "declared", "inferred"],
                   default="declared")
    p.add_argument("--scale-source", choices=["two_point_calibration", "declared", "inferred"],
                   default="declared")
    p.add_argument("--exposure-source", choices=["camera", "declared", "inferred"],
                   default="declared")
    p.add_argument("--head-x", type=float, required=True)
    p.add_argument("--head-y", type=float, required=True)
    p.add_argument("--tail-x", type=float)
    p.add_argument("--tail-y", type=float)
    p.add_argument("--seed-outline-json", type=Path)
    p.add_argument("--distractor-annotations-json", type=Path)
    p.add_argument("--scale", type=float, default=0.5)
    p.add_argument("--contrast-pct", type=float, default=94)
    p.add_argument("--contraction-z", type=float, default=2.5)
    p.add_argument("--recovery-z", type=float, default=-1.0)
    p.add_argument("--min-period", type=float, default=30)
    p.add_argument("--max-period", type=float, default=90)
    p.add_argument("--focus-roi-json", type=Path,
                   help="Optional moving worm-focus ROI: restrict tracking to a "
                        "box that follows user-dropped anchors so other worms / "
                        "distractors outside it are ignored.")
    p.add_argument("--output-dir", type=Path)
    args = p.parse_args()
    acquisition=AcquisitionMetadata(args.fps,args.fps_source,args.um_per_px,
        args.scale_source,args.exposure_ms,args.exposure_source).validate()
    acq=acquisition.as_columns()

    frames = load_downsampled(numbered_images(args.folder), args.scale, 1)
    seed_document = None
    if args.seed_outline_json:
        seed_document = json.loads(
            args.seed_outline_json.read_text(encoding="utf-8-sig"))
    calibration = build_pboc_calibration(
        seed_document, frames.shape[1:], args.scale, args.fps)
    distractor_document = {"episodes": []}
    if args.distractor_annotations_json:
        distractor_document = json.loads(
            args.distractor_annotations_json.read_text(encoding="utf-8-sig"))
    distractor_masks, distractor_results = track_distractor_episodes(
        frames, args.fps, args.scale, args.um_per_px, args.scale_source,
        distractor_document.get("episodes", []),
        seed_document.get("outline_xy") if seed_document else [])
    segmentation_config = scaled_config(
        find_accepted_config(args.folder, "defecation_cycle"), args.scale)
    # Optional worm-focus ROI: exclude everything outside a moving box so the
    # tracker stays on the intended worm in a crowded field. Distractor masks are
    # kept separate for the identity gate; only the tracker's search is narrowed.
    focus_document = None
    if args.focus_roi_json:
        focus_document = json.loads(
            args.focus_roi_json.read_text(encoding="utf-8-sig"))
    focus_masks = build_focus_exclusion(
        focus_document, len(frames), frames.shape[1:], args.scale)
    track_exclusion_masks = _union_exclusions(
        distractor_masks, focus_masks, len(frames))
    tracker = raw_track(
        frames, args.fps, (args.head_x, args.head_y), args.scale,
        args.contrast_pct, 1, args.um_per_px/args.scale, args.scale_source,
        segmentation_config=segmentation_config,
        tail_xy_full=(None if args.tail_x is None else (args.tail_x, args.tail_y)),
        outline_xy_full=(None if seed_document is None else
                         seed_document.get("outline_xy")),
        exclusion_masks=track_exclusion_masks,
        seed_frame=int(seed_document.get("source_frame", 0)),
        anchor_outlines={int(a["frame"]): a["outline_xy"]
                         for a in seed_document.get("pboc_anchors", [])},
    )
    apply_distractor_identity_gate(
        tracker.state, tracker._feasibility_masks, distractor_masks,
        distractor_results)
    u8 = [display_u8(frame) for frame in frames]
    n = len(frames)
    post_tan = np.full(n, np.nan)
    ant_tan = np.full(n, np.nan)
    post_normal = np.full(n, np.nan)
    ant_normal = np.full(n, np.nan)
    post_axial_fraction = np.full(n, np.nan)
    ant_axial_fraction = np.full(n, np.nan)
    axial_pixel_count = np.zeros(n, dtype=int)
    length = np.asarray([s.get("length", np.nan) for s in tracker.state])
    area = np.asarray([s.get("area", np.nan) for s in tracker.state])
    usable = np.asarray([s.get("needs_help", 1) == 0 for s in tracker.state])

    for i in range(1, n):
        pts = tracker.state[i - 1].get("pts")
        if pts is None:
            continue
        flow = cv2.calcOpticalFlowFarneback(
            u8[i - 1], u8[i], None, 0.5, 4, 31, 4, 7, 1.5, 0
        )
        flow -= np.median(flow.reshape(-1, 2), axis=0)
        post_tan[i], post_normal[i] = sample_flow(
            flow, u8[i - 1], pts[19:25], pts[17] - pts[24]
        )
        ant_tan[i], ant_normal[i] = sample_flow(
            flow, u8[i - 1], pts[0:6], pts[0] - pts[7]
        )
        post_axial_fraction[i], post_count = axial_participating_fraction(
            flow, u8[i-1], pts, tracker._feasibility_masks[i-1], (17, 24))
        ant_axial_fraction[i], ant_count = axial_participating_fraction(
            flow, u8[i-1], pts, tracker._feasibility_masks[i-1], (0, 7))
        axial_pixel_count[i] = post_count+ant_count
        if i % 250 == 0:
            print(f"flow {i}/{n}", flush=True)

    axial_difference = post_tan - ant_tan
    normal_control = 0.5 * (post_normal + ant_normal)
    # Positive means localized headward posterior flow. Penalize strong
    # dorsoventral motion but keep the score in pixel-motion units.
    flow_score = axial_difference / (1.0 + normal_control)
    flow_score[~usable] = np.nan
    combined, contraction_fraction, area_error = calibrated_pboc_score(
        flow_score, length, area, calibration)
    participation_contrast = post_axial_fraction-ant_axial_fraction
    participation_z = robust_z(participation_contrast)
    combined += 0.5*np.where(np.isfinite(participation_z), participation_z, 0.0)
    combined[~usable] = np.nan
    smooth = gaussian_filter1d(np.nan_to_num(combined, nan=0.0), sigma=max(0.5, args.fps * 0.2))
    smooth[~usable] = np.nan
    score_z = robust_z(smooth)
    events = candidate_events(score_z, args.fps, args.contraction_z, args.recovery_z)

    anchor_peak = int(calibration["anchors"][1]["frame"])
    anchor_recovered = int(calibration["anchors"][2]["frame"])
    calibration["axial_participation_signature"] = {
        "peak_posterior_fraction": float(post_axial_fraction[anchor_peak]),
        "peak_anterior_fraction": float(ant_axial_fraction[anchor_peak]),
        "peak_posterior_minus_anterior": float(participation_contrast[anchor_peak]),
        "recovery_posterior_fraction": float(post_axial_fraction[anchor_recovered]),
        "recovery_anterior_fraction": float(ant_axial_fraction[anchor_recovered]),
        "definition": "fraction of textured worm-mask pixels with residual axial motion exceeding transverse motion",
    }
    if not any(abs(event["peak_frame"]-anchor_peak) <= max(1, int(args.fps))
               for event in events):
        events.append({
            "peak_frame": anchor_peak, "peak_time_s": anchor_peak/args.fps,
            "peak_z": float(score_z[anchor_peak]) if np.isfinite(score_z[anchor_peak]) else np.nan,
            "recovery_frame": int(calibration["anchors"][2]["frame"]),
            "recovery_time_s": calibration["anchors"][2]["frame"]/args.fps,
            "has_recovery": True, "calibration_anchor": True,
        })
        events.sort(key=lambda event: event["peak_frame"])

    previous = None
    for event in events:
        gap = event["peak_time_s"] - previous if previous is not None else np.nan
        event["review_gap_s"] = gap
        event["rhythm_statistics_eligible"] = False
        event["decision"] = "pending"
        event["provenance"] = "automatic"
        event["contraction_fraction_at_peak"] = float(
            contraction_fraction[event["peak_frame"]])
        event["area_error_fraction_at_peak"] = float(area_error[event["peak_frame"]])
        event["posterior_axial_pixel_fraction_at_peak"] = float(
            post_axial_fraction[event["peak_frame"]])
        event["anterior_axial_pixel_fraction_at_peak"] = float(
            ant_axial_fraction[event["peak_frame"]])
        event["cadence_priority"] = bool(
            np.isfinite(gap) and args.min_period <= gap <= args.max_period)
        if event.get("calibration_anchor"):
            event["decision"] = "calibration_example"
            event["provenance"] = "user_three_anchor_calibration"
        if not event["has_recovery"]:
            event["review_note"] = "inspect_recovery_not_found"
        elif np.isfinite(gap) and gap < args.min_period:
            event["review_note"] = "inspect_closely_spaced_candidates"
        elif np.isfinite(gap) and gap > args.max_period:
            event["review_note"] = "inspect_gap_for_missed_candidate"
        else:
            event["review_note"] = "standard_review"
        previous = event["peak_time_s"]

    out = args.output_dir or (args.folder / "PBOC_results")
    out.mkdir(exist_ok=True)
    with (out / f"{args.name}_full_scan.csv").open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "frame", "time_s", "usable", "posterior_tangential",
            "anterior_tangential", "posterior_normal", "anterior_normal",
            "axial_difference", "flow_score", "combined_score", "score_z",
            "untrimmed_length_px", "contraction_fraction", "area_error_fraction",
            "posterior_axial_pixel_fraction", "anterior_axial_pixel_fraction",
            "axial_participation_contrast", "axial_pixel_count",
            "geometry_provenance", "geometry_inferred",
            "fps", "fps_source", "um_per_px", "um_per_px_source",
            "exposure_ms", "exposure_source",
        ])
        for i in range(n):
            writer.writerow([
                i, i / args.fps, int(usable[i]), post_tan[i], ant_tan[i],
                post_normal[i], ant_normal[i], axial_difference[i],
                flow_score[i], smooth[i], score_z[i], length[i],
                contraction_fraction[i], area_error[i],
                post_axial_fraction[i], ant_axial_fraction[i],
                participation_contrast[i], axial_pixel_count[i],
                tracker.state[i].get("provenance", ""),
                int(tracker.state[i].get("geometry_inferred", 0)),
                acq["fps"], acq["fps_source"], acq["um_per_px"], acq["um_per_px_source"],
                acq["exposure_ms"], acq["exposure_source"],
            ])
    summary = {
        "recording": args.name,
        **acq,
        "duration_s": n / args.fps,
        "usable_fraction": float(usable.mean()),
        "settings": {
            "contraction_z": args.contraction_z,
            "recovery_z": args.recovery_z,
            "min_period_s": args.min_period,
            "max_period_s": args.max_period,
        },
        "pboc_calibration": calibration,
        "rhythm_output_gate": (
            "No period, IDI, IDI CV, or rhythm statistic is reported. "
            "Cadence limits only order human review until unbroken tracking "
            "spans at least ten manually accepted cycles."
        ),
        "events": events,
        "distractor_tracking": [{
            "episode_id": result["episode_id"],
            "start_frame": result["start_frame"],
            "end_frame": result["end_frame"],
            "usable_fraction": result["usable_fraction"],
        } for result in distractor_results],
        "analysis_source": {
            "frame_folder": str(args.folder.resolve()),
            "full_scan_csv": str((out / f"{args.name}_full_scan.csv").resolve()),
            "tracking_overlays": f"{args.name}_tracking_overlays.json.gz",
            "tracking_overlay_contents": (
                "mask outline, centerline, head/tail, anterior/posterior regions; "
                "dense optical-flow vectors are not retained"),
        },
    }
    (out / f"{args.name}_full_scan.json").write_text(
        json.dumps(json_clean(summary), indent=2, allow_nan=False), encoding="utf-8"
    )
    try:
        write_decision_manifest(out, "defecation_cycle_pboc",
            method_note=(
                "pBoc candidates are proposed when posterior worm pixels show localized axial motion, "
                "the calibrated body geometry shortens in the expected direction, area conservation is acceptable, "
                "and recovery/cadence gates mark whether the event deserves routine or close review. "
                "The user-provided baseline/peak/recovered example anchors the scale of the detector."
            ),
            summary={
                "recording": args.name,
                "automatic_event_candidates": len(events),
                "usable_fraction": float(usable.mean()),
                "contraction_z_threshold": args.contraction_z,
                "recovery_z_threshold": args.recovery_z,
                "min_period_s": args.min_period,
                "max_period_s": args.max_period,
                "calibration_shortening_fraction": calibration.get("shortening_fraction"),
                "calibration_warnings": calibration.get("warnings", []),
            },
            decision_files={
                "full_scan_csv": f"{args.name}_full_scan.csv",
                "full_scan_json": f"{args.name}_full_scan.json",
                "tracking_overlays_json_gz": f"{args.name}_tracking_overlays.json.gz",
            },
            fields={
                "score_z": "Robust z-score of the combined pBoc evidence trace.",
                "contraction_fraction": "How much the calibrated worm outline shortened relative to the baseline/peak example.",
                "area_error_fraction": "Penalty term; real contraction should not look like a wildly different body area.",
                "posterior_axial_pixel_fraction": "Fraction of posterior textured worm pixels moving axially.",
                "anterior_axial_pixel_fraction": "Anterior control region; helps reject whole-body/camera motion.",
                "review_note": "Plain-language reason a candidate should receive standard or closer human review.",
                "decision": "pending, calibration_example, accepted, or rejected after review.",
            },
            caveats=[
                "Rhythm statistics are intentionally withheld until enough manually accepted cycles exist.",
                "Larvae/crossing objects are treated as distractors and can make frames unusable rather than forcing a false call.",
            ])
    except Exception as e:
        (out / "decision_transparency_error.txt").write_text(str(e), encoding="utf-8")
    overlay_frames = []
    for frame_index, (state, mask) in enumerate(zip(
            tracker.state, tracker._feasibility_masks)):
        outline = []
        if mask is not None and np.any(mask):
            contours, _ = cv2.findContours(
                np.uint8(mask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                contour = max(contours, key=cv2.contourArea)
                contour = cv2.approxPolyDP(contour, 1.5, True).reshape(-1, 2)
                outline = (contour / args.scale).round(1).tolist()
        pts = state.get("pts")
        centerline = [] if pts is None else (
            np.asarray(pts) / args.scale).round(1).tolist()
        distractors = []
        for result in distractor_results:
            if not (result["start_frame"] <= frame_index <= result["end_frame"]):
                continue
            local = frame_index - result["start_frame"]
            dmask = result["masks"][local]
            dstate = result["states"][local]
            doutline = []
            if dmask is not None and np.any(dmask):
                contours, _ = cv2.findContours(
                    np.uint8(dmask), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                if contours:
                    contour = cv2.approxPolyDP(
                        max(contours, key=cv2.contourArea), 1.5, True).reshape(-1, 2)
                    doutline = (contour / args.scale).round(1).tolist()
            dpts = dstate.get("pts")
            distractors.append({
                "episode_id": result["episode_id"], "outline": doutline,
                "centerline": [] if dpts is None else
                    (np.asarray(dpts) / args.scale).round(1).tolist(),
                "usable": not bool(dstate.get("needs_help", 1)),
            })
        overlay_frames.append({"outline": outline, "centerline": centerline,
                               "usable": not bool(state.get("needs_help", 1)),
                               "identity_warning": state.get("identity_warning"),
                               "distractors": distractors})
    overlay_doc = {"schema_version": "1.0", "coordinate_space": "source_pixels",
                   "frames": overlay_frames,
                   "unavailable": ["dense_optical_flow_vectors"]}
    with gzip.open(out / f"{args.name}_tracking_overlays.json.gz", "wt",
                   encoding="utf-8") as handle:
        json.dump(json_clean(overlay_doc), handle, separators=(",", ":"),
                  allow_nan=False)
    print(json.dumps(json_clean(summary), indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
