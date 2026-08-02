"""Population swimming analysis for low-magnification TIFF sequences.

Outputs candidate tracks and review flags. The reported oscillation frequency
is a body-axis proxy, not segment-level curvature frequency.
"""
from __future__ import annotations
import json
import time
import itertools
import sys
import shutil
import tempfile
from pathlib import Path
import cv2
import numpy as np
import pandas as pd
from dataclasses import replace
from scipy.optimize import linear_sum_assignment
from scipy.signal import find_peaks, savgol_filter
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"movie"))
from acquisition import AcquisitionMetadata
from movie_reader import open_movie
from segmentation_review import find_accepted_config, segment_frame

SPINE_POINTS = 25
MODALITIES = ("swimming", "crawling", "burrowing", "uncertain")


SPINE_METHODS = ("morphological", "thinning")
SPINE_METHOD_DEFAULT = "morphological"


def _morphological_skeleton(component):
    """Erosion-residue skeleton. The historical WINK method, kept as the default
    so existing results remain reproducible.

    Known weakness: the residue is not guaranteed connected. Masks thicker than
    a few pixels can skeletonise into several disconnected pieces, in which case
    the longest-path search below can only traverse one piece - yielding either
    no spine at all or a spine describing part of the animal. Compare against
    ``thinning`` on your own recording before trusting it on thick masks.
    """
    image = np.uint8(component > 0) * 255
    skel = np.zeros_like(image)
    element = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(image):
        eroded = cv2.erode(image, element)
        opened = cv2.dilate(eroded, element)
        skel = cv2.bitwise_or(skel, cv2.subtract(image, opened))
        # TERMINATION GUARD. cv2.erode treats the border as maximal, so it never
        # erodes inward from the crop edge. A component that fills its own
        # bounding box therefore erodes to itself: `image` stops changing,
        # countNonZero never reaches zero, and this loop spins forever at 100%
        # CPU. That is reachable in normal use - `min_area` is scaled by
        # detection_scale**2, so a 25% proxy admits ~2 px components, and any
        # tiny solid blob fills its bounding box.
        #
        # Breaking at the fixed point is output-preserving: for every mask that
        # already terminated the loop is unchanged, and a mask that hung
        # produced no result at all.
        if np.array_equal(eroded, image):
            break
        image = eroded
    return skel > 0


def _thinning_skeleton(component):
    """Zhang-Suen/Lee thinning (scikit-image). Produces a single connected
    curve for a worm-shaped mask regardless of thickness.

    Not a speed optimisation - measured slower than the morphological loop on
    large crops - but it does not fragment, so the extracted spine spans the
    whole animal.
    """
    from skimage.morphology import skeletonize
    return np.asarray(skeletonize(np.asarray(component) > 0))


def _skeleton(component, method=SPINE_METHOD_DEFAULT):
    if method == "thinning":
        try:
            return _thinning_skeleton(component)
        except Exception:
            return _morphological_skeleton(component)
    return _morphological_skeleton(component)


def _ordered_spine(component, points=SPINE_POINTS, method=SPINE_METHOD_DEFAULT):
    """Longest endpoint-to-endpoint skeleton path, resampled to fixed points."""
    skel = _skeleton(component, method)
    pixels = np.argwhere(skel)
    if len(pixels) < 8:
        return None
    lookup = {tuple(p): i for i, p in enumerate(pixels)}
    graph = [[] for _ in pixels]
    for i, (y, x) in enumerate(pixels):
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    j = lookup.get((y + dy, x + dx))
                    if j is not None:
                        graph[i].append((j, float(np.hypot(dx, dy))))
    ends = [i for i, links in enumerate(graph) if len(links) == 1]
    if len(ends) < 2:
        return None
    import heapq

    def farthest_endpoint(source):
        dist = np.full(len(pixels), np.inf)
        parent = np.full(len(pixels), -1, int)
        dist[source] = 0
        queue = [(0.0, source)]
        while queue:
            value, node = heapq.heappop(queue)
            if value != dist[node]:
                continue
            for other, weight in graph[node]:
                candidate = value + weight
                if candidate < dist[other]:
                    dist[other], parent[other] = candidate, node
                    heapq.heappush(queue, (candidate, other))
        reachable = [i for i in ends if np.isfinite(dist[i])]
        if not reachable:
            return None, dist, parent
        target = max(reachable, key=lambda i: dist[i])
        return target, dist, parent

    # A worm skeleton is tree-like. Two endpoint sweeps recover the exact tree
    # diameter and avoid a complete Dijkstra search for every tiny segmentation
    # spur. This changes endpoint-search complexity, not the output sampling.
    first, _, _ = farthest_endpoint(ends[0])
    if first is None:
        return None
    node, dist, parent = farthest_endpoint(first)
    if node is None or not np.isfinite(dist[node]):
        return None
    source = first
    path = []
    while node >= 0:
        path.append(pixels[node])
        if node == source:
            break
        node = parent[node]
    if node != source:
        return None
    path = np.asarray(path[::-1], float)[:, ::-1]
    distance = np.r_[0, np.cumsum(np.linalg.norm(np.diff(path, axis=0), axis=1))]
    if distance[-1] < 10:
        return None
    sample = np.linspace(0, distance[-1], points)
    return np.column_stack([
        np.interp(sample, distance, path[:, 0]),
        np.interp(sample, distance, path[:, 1])])


def _curvature(spine):
    if spine is None:
        return None
    tangent = np.unwrap(np.arctan2(np.diff(spine[:, 1]), np.diff(spine[:, 0])))
    step = np.linalg.norm(np.diff(spine, axis=0), axis=1)
    ds = np.maximum((step[:-1] + step[1:]) / 2, 1e-6)
    curv = np.diff(tangent) / ds
    return np.r_[curv[0], curv, curv[-1]]


def _orient_spines(tracks):
    tracks = tracks.copy()
    for _, group in tracks.groupby("track_id", sort=False):
        previous = None
        for index in group.sort_values("frame").index:
            try:
                spine = np.column_stack([
                    json.loads(tracks.at[index, "spine_x_json"]),
                    json.loads(tracks.at[index, "spine_y_json"])])
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(spine) < 2:
                continue
            if previous is not None:
                same = np.linalg.norm(spine[0] - previous[0]) + np.linalg.norm(spine[-1] - previous[-1])
                flip = np.linalg.norm(spine[-1] - previous[0]) + np.linalg.norm(spine[0] - previous[-1])
                if flip < same:
                    spine = spine[::-1]
            curve = _curvature(spine)
            tracks.at[index, "spine_x_json"] = json.dumps(spine[:, 0].round(2).tolist())
            tracks.at[index, "spine_y_json"] = json.dumps(spine[:, 1].round(2).tolist())
            tracks.at[index, "curvature_json"] = json.dumps(curve.round(6).tolist())
            tracks.at[index, "midbody_curvature_px_inv"] = float(np.mean(curve[8:17]))
            previous = spine
    return tracks


def _posture_scores(curvature):
    """Continuous C/S/W evidence from signed curvature topology."""
    c = np.asarray(curvature, float)[2:-2]
    if len(c) < 8 or not np.all(np.isfinite(c)):
        return np.nan, np.nan, np.nan, 0
    scale = max(float(np.percentile(np.abs(c), 75)), 1e-6)
    z = c / scale
    signs = np.sign(z[np.abs(z) > .25])
    sign_changes = int(np.sum(signs[1:] != signs[:-1])) if len(signs) > 1 else 0
    peaks, _ = find_peaks(np.abs(z), prominence=.35, distance=3)
    extrema = len(peaks)
    c_score = float(np.clip(1 - sign_changes / 1.5, 0, 1))
    s_score = float(np.exp(-((sign_changes - 1) ** 2) / 1.2) * np.clip(extrema / 2, 0, 1))
    w_score = float(np.exp(-((sign_changes - 2) ** 2) / 1.2) * np.clip(extrema / 3, 0, 1))
    return c_score, s_score, w_score, extrema


def _wave_direction(curves):
    """Correlation-lag estimate; positive evidence means anterior-to-posterior."""
    if len(curves) < 8:
        return np.nan
    matrix = np.asarray(curves, float)
    anterior = np.nanmean(matrix[:, 4:9], axis=1)
    posterior = np.nanmean(matrix[:, 16:21], axis=1)
    anterior -= np.nanmean(anterior); posterior -= np.nanmean(posterior)
    corr = np.correlate(posterior, anterior, mode="full")
    lag = int(np.argmax(corr) - (len(anterior) - 1))
    return float(lag)


def classify_modality_windows(tracks, fps, window_s=4.0, step_s=1.0, progress=None,
                              spine_stride=1, min_spine_evidence=.65):
    """Generate conservative, reviewable modality proposals.

    ``spine_stride`` is the frame interval at which spines were ATTEMPTED - the
    detailed pass deliberately samples at about 15 Hz rather than every frame.
    The posture gate is therefore measured against attempted frames, not against
    every frame in the window: at 30 fps the stride is 2, so a window with a
    perfect skeleton on every attempted frame still only carries curvature on
    ~50% of its frames, and a gate expressed against all frames is unreachable
    by construction. That made every proposal "uncertain" on any recording at
    30 fps or above, regardless of data quality.
    """
    rows = []
    width = max(12, int(round(window_s * fps)))
    step = max(1, int(round(step_s * fps)))
    grouped = list(tracks.groupby("track_id"))
    n_tracks = len(grouped)
    for track_index, (tid, group) in enumerate(grouped):
        group = group.sort_values("frame")
        # Windows overlap heavily (step << width), so each frame is revisited
        # ~width/step times. Parse each frame's curvature JSON and posture score
        # ONCE here, then just gather them per window below - same values, far
        # less work than re-parsing every row inside every window.
        curve_by_frame = {}
        score_by_frame = {}
        for frame_value, curvature_json in zip(
                group.frame.to_numpy(), group.curvature_json.to_numpy()):
            try:
                curve = np.asarray(json.loads(curvature_json), float)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if len(curve) != SPINE_POINTS:
                continue
            curve_by_frame[int(frame_value)] = curve
            score_by_frame[int(frame_value)] = _posture_scores(curve)
        start, stop = int(group.frame.min()), int(group.frame.max())
        for first in range(start, stop - width + 2, step):
            window = group[(group.frame >= first) & (group.frame < first + width)]
            coverage = len(window) / width
            curves = []
            scores = []
            for frame_value in window.frame.to_numpy():
                curve = curve_by_frame.get(int(frame_value))
                if curve is None:
                    continue
                curves.append(curve)
                scores.append(score_by_frame[int(frame_value)])
            # Spines exist only on attempted frames; judge coverage against those.
            stride = max(1, int(spine_stride))
            attempted = max(1, int(np.ceil(len(window) / stride)))
            spine_frames_used = len(curves)
            # `attempted` is an estimate: a window need not start on a stride
            # boundary, so it can under-count by one and push the ratio slightly
            # over 1. Report a fraction, not a number that reads as >100%.
            valid = min(1.0, spine_frames_used / attempted)
            valid_of_all_frames = spine_frames_used / max(len(window), 1)
            spine_rate_hz = (spine_frames_used / (len(window) / float(fps))
                             if len(window) else np.nan)
            valid_signal = window[np.isfinite(window.midbody_curvature_px_inv)]
            curvature_freq = (_frequency(valid_signal.time_s.to_numpy(),
                                         valid_signal.midbody_curvature_px_inv.to_numpy())
                              if valid >= min_spine_evidence else np.nan)
            centroid_freq = _centroid_frequency(window, fps)
            freq = centroid_freq if np.isfinite(centroid_freq) else curvature_freq
            c_score, s_score, w_score = (np.nanmean(np.asarray(scores)[:, i]) if scores else np.nan for i in range(3))
            speed = float(window.speed_um_s.median())
            wave_lag = _wave_direction(curves)
            collision = float(((window.area_px > 1.8 * window.area_px.median()) |
                               (window.elongation < 1.35)).mean())
            # Distinguish WHY a window is uncertain: too little of the animal
            # tracked, too little posture evidence, a collision, no usable
            # frequency, or genuinely overlapping evidence. They call for
            # different actions and were previously indistinguishable.
            if coverage < .7:
                reason = "insufficient_track_coverage"
            elif valid < min_spine_evidence:
                reason = "insufficient_spine_evidence"
            elif collision > .1:
                reason = "possible_collision_in_window"
            elif not np.isfinite(freq):
                reason = "no_usable_frequency"
            else:
                reason = "overlapping_modality_evidence"
            label, confidence = "uncertain", 0.0
            if coverage >= .7 and valid >= min_spine_evidence and collision <= .1 and np.isfinite(freq):
                evidence = {
                    "swimming": .55 * c_score + .45 * np.clip((freq - .6) / .4, 0, 1),
                    "crawling": .70 * s_score + .30 * np.clip(1 - abs(freq - .4) / .3, 0, 1),
                    "burrowing": .65 * w_score + .20 * np.clip((.55 - freq) / .35, 0, 1) +
                                 .15 * float(np.isfinite(wave_lag) and wave_lag > 0),
                }
                ordered = sorted(evidence.items(), key=lambda item: item[1], reverse=True)
                margin = ordered[0][1] - ordered[1][1]
                confidence = float(np.clip(.65 * ordered[0][1] + .35 * margin, 0, 1))
                if ordered[0][1] >= .55 and margin >= .08:
                    label = ordered[0][0]
                    reason = "combined_frequency_posture_wave_and_speed_evidence"
                else:
                    reason = "overlapping_modality_evidence"
            rows.append(dict(
                track_id=int(tid), start_frame=first, end_frame=first + width - 1,
                start_time_s=first / fps, end_time_s=(first + width - 1) / fps,
                proposed_modality=label, confidence=confidence, bend_frequency_hz=freq,
                centroid_oscillation_frequency_hz=centroid_freq,
                curvature_frequency_hz=curvature_freq,
                median_speed_um_s=speed, c_score=c_score, s_score=s_score, w_score=w_score,
                posterior_wave_lag_frames=wave_lag, coverage_fraction=coverage,
                spine_valid_fraction=valid, collision_fraction=collision, proposal_reason=reason,
                # Provenance: how much real posture evidence backs this window.
                spine_frames_used=int(spine_frames_used),
                spine_frames_attempted=int(attempted),
                spine_stride_frames=int(stride),
                spine_sampling_rate_hz=float(spine_rate_hz),
                spine_fraction_of_all_frames=float(valid_of_all_frames),
                window_frames=int(len(window))))
        if progress is not None:
            try:
                progress(track_index + 1, n_tracks, "Classifying locomotion modality")
            except TypeError:
                progress(track_index + 1, n_tracks)
    return pd.DataFrame(rows)


def windows_to_bouts(windows, fps):
    """Merge adjacent proposals after a three-window majority smoother."""
    if windows.empty:
        return pd.DataFrame()
    smoothed = []
    for _, group in windows.groupby("track_id"):
        group = group.sort_values("start_frame").copy()
        labels = group.proposed_modality.tolist()
        for i in range(len(labels)):
            neighborhood = labels[max(0, i - 1):min(len(labels), i + 2)]
            counts = {label: neighborhood.count(label) for label in MODALITIES}
            labels[i] = max(counts, key=counts.get)
        group["smoothed_modality"] = labels
        smoothed.append(group)
    table = pd.concat(smoothed, ignore_index=True)
    bouts = []
    bout_id = 1
    for tid, group in table.groupby("track_id"):
        group = group.sort_values("start_frame")
        blocks = (group.smoothed_modality != group.smoothed_modality.shift()).cumsum()
        for _, block in group.groupby(blocks):
            start = int(block.start_frame.min()); end = int(block.end_frame.max())
            bouts.append(dict(
                bout_id=bout_id, track_id=int(tid), start_frame=start, end_frame=end,
                start_time_s=start / fps, end_time_s=end / fps, duration_s=(end - start + 1) / fps,
                proposed_modality=block.smoothed_modality.iloc[0],
                confidence=float(block.confidence.mean()),
                bend_frequency_hz=float(block.bend_frequency_hz.mean()),
                median_speed_um_s=float(block.median_speed_um_s.median()),
                c_score=float(block.c_score.mean()), s_score=float(block.s_score.mean()),
                w_score=float(block.w_score.mean()), review_status="pending",
                # Posture provenance carried through to the bout a human reviews.
                spine_frames_used=int(block.spine_frames_used.sum())
                    if "spine_frames_used" in block else 0,
                spine_frames_attempted=int(block.spine_frames_attempted.sum())
                    if "spine_frames_attempted" in block else 0,
                spine_evidence_fraction=float(block.spine_valid_fraction.mean()),
                spine_sampling_rate_hz=float(block.spine_sampling_rate_hz.mean())
                    if "spine_sampling_rate_hz" in block else np.nan,
                proposal_reason=(block.proposal_reason.mode().iloc[0]
                                 if len(block.proposal_reason.mode()) else ""),
                reviewed_modality="", reviewer_note=""))
            bout_id += 1
    return pd.DataFrame(bouts)


def _point_in_any_roi(x, y, roi_records):
    for record in roi_records or []:
        polygon = np.asarray(record.get("polygon", []), np.float32)
        if len(polygon) >= 3 and cv2.pointPolygonTest(polygon, (float(x), float(y)), False) >= 0:
            return True
    return False


class FrameSource:
    """Lazy, indexable frames from a video, TIFF stack, or image folder.

    ``fast=True`` opens a compressed video without the full decode pass that an
    exact frame count costs, for previews/ROI drawing/scrubbing.  The length is
    then approximate until :meth:`ensure_exact_length` is called, so nothing
    that reaches a reported measurement may use it.
    """
    def __init__(self, source, *, fast=False):
        self.source = Path(source)
        self.movie = open_movie(self.source, exact_count=not fast)

    def __len__(self):
        return int(self.movie.n_frames)

    @property
    def length_is_exact(self):
        return bool(getattr(self.movie, "n_frames_is_exact", True))

    def ensure_exact_length(self):
        """Pay for an exact frame count. Required before any reported number."""
        ensure = getattr(self.movie, "ensure_exact_n_frames", None)
        return int(ensure()) if ensure else int(self.movie.n_frames)

    def __getitem__(self, index):
        return self.movie.get_frame(int(index))

    def frames(self):
        return self.movie.frames()

    def proxy_frames(self, scale=1.0):
        if self.movie.source_kind=="video" and hasattr(self.movie,"gray_proxy_frames"):
            return self.movie.gray_proxy_frames(scale=scale)
        return (read_gray(frame) if scale==1.0 else cv2.resize(
            read_gray(frame),None,fx=scale,fy=scale,interpolation=cv2.INTER_AREA)
            for frame in self.movie.frames())

    def sampled_proxy_frames(self, indices, scale=1.0):
        if self.movie.source_kind=="video" and hasattr(self.movie,"sampled_gray_proxy_frames"):
            return self.movie.sampled_gray_proxy_frames(indices,scale=scale)
        wanted=set(int(i) for i in indices)
        return (frame for index,frame in enumerate(self.proxy_frames(scale))
                if index in wanted)

    def close(self):
        self.movie.close()


def list_frames(source, *, fast=False):
    return FrameSource(source, fast=fast)


def read_gray(frame):
    a = np.asarray(frame)
    if a.ndim == 3:
        if a.shape[-1] == 1:
            a = a[..., 0]
        else:
            a = cv2.cvtColor(a[..., :3], cv2.COLOR_RGB2GRAY)
    a = a.astype(np.float32); lo, hi = np.percentile(a, [.1, 99.9])
    if hi-lo < 1:
        lo, hi = float(np.min(a)), float(np.max(a))
    return np.uint8(np.clip((a-lo)*255/max(hi-lo, 1), 0, 255))


def _frequency(t, y, lo=.2, hi=5):
    if len(y) < 12 or t[-1]-t[0] < 3: return np.nan
    dt=np.median(np.diff(t)); y=np.asarray(y)-np.mean(y); f=np.fft.rfftfreq(len(y),dt)
    p=np.abs(np.fft.rfft(y*np.hanning(len(y))))**2; band=(f>=lo)&(f<=min(hi,.45/dt))
    return float(f[band][np.argmax(p[band])]) if np.any(band) else np.nan


def _centroid_frequency(track, fps, lo=.2, hi=5):
    """Frequency of lateral centroid motion around its slowly varying path.

    Interpolation restores the regular movie clock (rather than pretending
    sparse detections were adjacent samples). The signed displacement along
    the local path normal preserves one oscillation per body-beat cycle.
    """
    if len(track) < max(24, int(3 * fps)):
        return np.nan
    g = track.sort_values("frame").drop_duplicates("frame")
    frames = np.arange(int(g.frame.min()), int(g.frame.max()) + 1)
    if len(frames) < 3 * fps or len(g) / len(frames) < .55:
        return np.nan
    x = np.interp(frames, g.frame, g.x)
    y = np.interp(frames, g.frame, g.y)
    # A 1.5 s baseline follows migration/turning but not ordinary swim beats.
    window = min(len(frames) if len(frames) % 2 else len(frames)-1,
                 max(7, int(round(1.5 * fps)) | 1))
    if window < 7:
        return np.nan
    sx = savgol_filter(x, window, 2, mode="interp")
    sy = savgol_filter(y, window, 2, mode="interp")
    dx, dy = np.gradient(sx), np.gradient(sy)
    norm = np.hypot(dx, dy)
    good = norm > np.percentile(norm, 20)
    if good.sum() < len(good) * .35:
        # Nearly stationary animals still have a stable principal oscillation.
        residual = np.column_stack([x-sx, y-sy])
        _, _, vh = np.linalg.svd(residual-residual.mean(axis=0), full_matrices=False)
        signal = residual @ vh[0]
    else:
        norm = np.maximum(norm, 1e-6)
        signal = (x-sx) * (-dy/norm) + (y-sy) * (dx/norm)
    return _frequency(frames / float(fps), signal, lo=lo, hi=hi)


MANUAL_POINT_COLUMN = "manual_point"


def measured_rows(tracks):
    """Rows that may contribute to a measurement.

    Manually placed points carry identity across frames the detector missed -
    they say "this animal is here" - but they are human judgement, not a
    measurement. Speed, coverage, frequency and curvature are therefore
    computed WITHOUT them; only continuity and identity use them.
    """
    if MANUAL_POINT_COLUMN not in tracks:
        return tracks
    return tracks[~tracks[MANUAL_POINT_COLUMN].fillna(False).astype(bool)]


def summarize_tracks(tracks, fps, scale, actual_frames):
    """Rebuild track statistics after automatic linking or manual stitching.

    Manual points are excluded from every reported statistic; the count of them
    is reported per track so a reader can see how much of a track was human-
    asserted rather than detected.
    """
    tracks = tracks.sort_values(["track_id", "frame"]).copy()
    if MANUAL_POINT_COLUMN in tracks:
        manual_flag = tracks[MANUAL_POINT_COLUMN].fillna(False).astype(bool)
        manual_counts = manual_flag.groupby(tracks.track_id).sum().to_dict()
        tracks = tracks.copy()
        tracks[MANUAL_POINT_COLUMN] = manual_flag
    else:
        manual_counts = {}
    # Steps and speeds are derived from DETECTED positions only; a manual point
    # would otherwise contribute a human-drawn displacement to a reported speed.
    measured = measured_rows(tracks)
    dx = measured.groupby("track_id")["x"].diff()
    dy = measured.groupby("track_id")["y"].diff()
    tracks["step_px"] = np.nan
    tracks.loc[measured.index, "step_px"] = np.hypot(dx, dy)
    tracks["speed_um_s"] = tracks.step_px * fps * scale
    summaries=[]
    for tid,g_all in tracks.groupby("track_id"):
        g=measured_rows(g_all)
        manual_count=int(manual_counts.get(tid,0))
        if len(g)<2:
            # Nothing detected for this track - identity only, no measurement.
            summaries.append(dict(track_id=int(tid),frames=len(g_all),detected_frames=int(len(g)),
                manual_points=manual_count,duration_s=float(g_all.time_s.max()-g_all.time_s.min()),
                coverage_fraction=0.0,activity_fraction=np.nan,mean_speed_um_s=None,
                spine_bend_frequency_hz=None,centroid_oscillation_frequency_hz=None,
                curvature_frequency_hz=None,spine_valid_fraction=0.0,
                edge_fraction=float(g_all.edge.mean()),collision_fraction=np.nan,
                crossing_ambiguity_fraction=float(g_all.crossing_ambiguous.mean()),
                eligible_for_frequency=False,needs_review=True,
                review_reason="no_detected_frames"))
            continue
        med_area=float(g.area_px.median()); equiv_len=max(2*np.sqrt(med_area),1)
        active_state=(g.step_px*fps/equiv_len)>=.08
        valid=g[np.isfinite(g.midbody_curvature_px_inv)]
        spine_freq=_frequency(valid.time_s.to_numpy(),valid.midbody_curvature_px_inv.to_numpy())
        centroid_freq=_centroid_frequency(g,fps)
        freq=centroid_freq if np.isfinite(centroid_freq) else spine_freq
        collision=(g.area_px>1.8*med_area) | (g.elongation<1.35)
        eligible=bool((g.time_s.max()-g.time_s.min()) >= 3.0 and len(g) >= fps*2.5 and collision.mean() <= .05)
        if not eligible: freq=np.nan
        crossing_ambiguous=bool(g.crossing_ambiguous.any())
        review=bool(g.edge.any() or collision.mean()>.05 or crossing_ambiguous or not eligible)
        summaries.append(dict(track_id=int(tid),frames=len(g_all),detected_frames=int(len(g)),
            manual_points=manual_count,duration_s=float(g.time_s.max()-g.time_s.min()),
            coverage_fraction=float(len(g)/actual_frames),activity_fraction=float(active_state.mean()),
            mean_speed_um_s=float(g.speed_um_s.mean()),spine_bend_frequency_hz=None if not np.isfinite(freq) else freq,
            centroid_oscillation_frequency_hz=None if not np.isfinite(centroid_freq) else centroid_freq,
            curvature_frequency_hz=None if not np.isfinite(spine_freq) else spine_freq,
            spine_valid_fraction=float(g.spine_valid.mean()),edge_fraction=float(g.edge.mean()),
            collision_fraction=float(collision.mean()),crossing_ambiguity_fraction=float(g.crossing_ambiguous.mean()),
            eligible_for_frequency=eligible,needs_review=review,
            review_reason="edge" if g.edge.any() else "possible_collision" if collision.mean()>.05 else "ambiguous_crossing" if crossing_ambiguous else "short_or_fragmented" if not eligible else "standard_review"))
    return tracks, pd.DataFrame(summaries)


def link_detections(det, max_link_px=60, max_gap_frames=8,
                    crossing_memory_frames=45, enforce_speed_limit=True):
    """Link detections while preserving momentum through merged crossings.

    Ordinary missing detections use ``max_gap_frames``. When an unassigned
    trajectory projects into a collision-like blob, its last clean position,
    heading and speed are retained for ``crossing_memory_frames`` so the two
    outgoing animals are matched to their incoming trajectories.
    """
    next_id=1; active={}; rows=[]
    for fi,g in det.groupby("frame"):
        g=g.reset_index(drop=True); ids=list(active); cur=g[["x","y"]].to_numpy(); assigned={}; errors={}; ambiguous={}
        if ids and len(cur):
            predicted=[]
            for tid in ids:
                s=active[tid]; gap=fi-s["frame"]
                predicted.append([s["x"]+s["vx"]*gap,s["y"]+s["vy"]*gap])
            position_cost=np.linalg.norm(np.asarray(predicted)[:,None,:]-cur[None,:,:],axis=2)
            # Distance from where the animal was actually SEEN, not from where
            # momentum projects it to be. `predicted` drifts by velocity x gap,
            # so across a long crossing hold the projection can land most of a
            # frame away and drag the identity onto a different animal. The raw
            # displacement is the physical quantity: an animal cannot exceed its
            # own per-frame travel limit however long it went unseen.
            observed=np.asarray([[active[tid]["x"],active[tid]["y"]] for tid in ids],float)
            raw_cost=np.linalg.norm(observed[:,None,:]-cur[None,:,:],axis=2)
            cost=position_cost.copy()
            # Prefer the continuation requiring the smallest heading and speed
            # change, not merely the nearest endpoint after a crossing.
            for r,tid in enumerate(ids):
                s=active[tid];gap=max(fi-s["frame"],1)
                implied=(cur-np.array([s["x"],s["y"]]))/gap
                old=np.array([s["vx"],s["vy"]]);old_speed=np.linalg.norm(old)
                new_speed=np.linalg.norm(implied,axis=1)
                if old_speed>.15:
                    cosine=np.clip((implied@old)/(np.maximum(new_speed,1e-6)*old_speed),-1,1)
                    turn=np.arccos(cosine)/np.pi
                    speed_change=np.abs(np.log((new_speed+.25)/(old_speed+.25)))
                    gate=max_link_px*np.sqrt(gap)
                    cost[r] += .35*gate*turn + .12*gate*np.minimum(speed_change,2)
            rr,cc=linear_sum_assignment(cost)
            for r,c in zip(rr,cc):
                gap=fi-active[ids[r]]["frame"]
                gate=max_link_px*np.sqrt(max(gap,1))
                speed_limit=(max_link_px*max(gap,1)) if enforce_speed_limit else np.inf
                if (position_cost[r,c]<=gate and cost[r,c]<=1.45*gate
                        and raw_cost[r,c]<=speed_limit):
                    assigned[c]=ids[r]; errors[c]=float(position_cost[r,c])
                    alternatives=np.delete(cost[:,c],r)
                    ambiguous[c]=bool(len(alternatives) and np.min(alternatives)-cost[r,c] < max(4.0,.12*gate))
        # A large or rounded component near multiple predictions is probably a
        # merged animal blob. Keep every incoming clean trajectory alive.
        collision_candidates=set()
        for c,row in g.iterrows():
            nearby=[]
            for tid in ids:
                s=active[tid];gap=max(fi-s["frame"],1)
                predicted=np.array([s["x"]+s["vx"]*gap,s["y"]+s["vy"]*gap])
                if np.linalg.norm(cur[c]-predicted)<=max_link_px*np.sqrt(gap):
                    nearby.append(tid)
            large=any(row.area_px>1.45*active[tid].get("area",row.area_px) for tid in nearby)
            rounded=bool(row.get("elongation",99)<1.35)
            if len(nearby)>=2 and (large or rounded):
                collision_candidates.add(c)
                for tid in nearby:
                    active[tid]["seen_frame"]=fi
                    active[tid]["crossing_hold"]=True
        updated=set()
        for c,row in g.iterrows():
            if c not in assigned: assigned[c]=next_id; next_id+=1; errors[c]=np.nan; ambiguous[c]=False
            tid=assigned[c]; rec=row.to_dict(); rec.update(track_id=tid,prediction_error_px=errors[c],crossing_ambiguous=ambiguous[c]); rows.append(rec)
            old=active.get(tid); vx=vy=0.0
            if old is not None and c not in collision_candidates:
                gap=max(fi-old["frame"],1); nvx=(row.x-old["x"])/gap; nvy=(row.y-old["y"])/gap
                vx=.65*old["vx"]+.35*nvx; vy=.65*old["vy"]+.35*nvy
                active[tid]={"x":row.x,"y":row.y,"frame":fi,"seen_frame":fi,
                             "vx":vx,"vy":vy,"area":row.area_px,"crossing_hold":False}
            elif old is None:
                active[tid]={"x":row.x,"y":row.y,"frame":fi,"seen_frame":fi,
                             "vx":0.0,"vy":0.0,"area":row.area_px,"crossing_hold":False}
            else:
                old["seen_frame"]=fi
            updated.add(tid)
        active={i:s for i,s in active.items()
                if fi-s.get("seen_frame",s["frame"]) <=
                (crossing_memory_frames if s.get("crossing_hold") else max_gap_frames)}
    return pd.DataFrame(rows).sort_values(["track_id","frame"])


def _attach_selective_spines(tracks, fps, detection_scale, target_spine_fps=15.0,
                             progress=None, spine_method=SPINE_METHOD_DEFAULT):
    """Detailed second pass on already-linked plausible objects.

    Component crops were packed during the fast pass, so this never rescans or
    re-decodes a full frame.  Sampling remains >= target_spine_fps; centroid and
    ellipse measurements retain every source frame.
    """
    tracks=tracks.copy();stride=max(1,int(np.floor(float(fps)/max(float(target_spine_fps),1.0))))
    tracks["spine_valid"]=False;tracks["spine_x_json"]="";tracks["spine_y_json"]=""
    tracks["curvature_json"]="";tracks["midbody_curvature_px_inv"]=np.nan
    tracks["spine_skip_reason"]=""
    detailed_tracks=0;detailed_frames=0
    groups=list(tracks.groupby("track_id"));total_groups=max(1,len(groups))
    # Tk progress callbacks can be much more expensive than this eligibility
    # scan when a noisy recording produces thousands of short fragments.  A
    # bounded number of UI refreshes keeps the phase responsive without
    # changing which tracks receive detailed spines.
    progress_interval=max(1,int(np.ceil(total_groups/200.0)))
    for group_number,(tid,g) in enumerate(groups,1):
        g=g.sort_values("frame");duration=(float(g.frame.max()-g.frame.min())/float(fps))
        span=max(1,int(g.frame.max()-g.frame.min()+1));coverage=len(g)/span
        median_area=float(g.area_px.median())
        collision=((g.area_px>1.8*median_area)|(g.elongation<1.35)).mean()
        # Match the downstream scientific eligibility gate. Short, sparse, or
        # collision-contaminated fragments cannot yield a reported frequency,
        # so detailed skeletons would add cost without adding a measurement.
        if duration<3.0 or coverage<.55 or collision>.05:
            if progress and (group_number==1 or group_number==total_groups or
                             group_number%progress_interval==0):
                progress(group_number,total_groups,"Selecting tracks for detailed spines")
            continue
        detailed_tracks+=1;first=int(g.frame.min());last=int(g.frame.max())
        chosen=g.index[((g.frame.astype(int)-first)%stride==0)|(g.frame.astype(int)==last)]
        chosen_count=max(1,len(chosen))
        within_track_interval=max(1,int(np.ceil(chosen_count/40.0)))
        if progress:
            progress(group_number-1,total_groups,
                     f"Detailed spines: track {group_number}/{total_groups} (0/{chosen_count})")
        for chosen_number,row_index in enumerate(chosen,1):
            row=tracks.loc[row_index];shape=row.get("_mask_shape");packed=row.get("_packed_mask")
            if shape is None or packed is None:
                tracks.at[row_index,"spine_skip_reason"]="mask_not_available"
                continue
            h,w=int(shape[0]),int(shape[1])
            component=np.unpackbits(
                np.frombuffer(packed,dtype=np.uint8),count=h*w
            ).reshape(h,w).astype(bool)
            foreground_pixels=max(1,int(component.sum()))
            # A thin connected artifact can contain few foreground pixels while
            # spanning a scene-wide rectangular crop. Morphological
            # skeletonization scales with the crop, not just foreground area,
            # and can otherwise monopolize a run for minutes. Normal worm
            # masks are far denser than this conservative gate.
            if h*w>max(250_000,150*foreground_pixels):
                tracks.at[row_index,"spine_skip_reason"]="pathological_sparse_bounding_box"
                if progress:
                    progress(group_number-1+(chosen_number/chosen_count),total_groups,
                             f"Skipped scene-spanning artifact: track "
                             f"{group_number}/{total_groups} "
                             f"({chosen_number}/{chosen_count})")
                continue
            spine=_ordered_spine(component,method=spine_method)
            if spine is None:
                tracks.at[row_index,"spine_skip_reason"]="no_valid_skeleton_path"
                continue
            spine[:,0]=(spine[:,0]+float(row["_bbox_x0"]))/detection_scale
            spine[:,1]=(spine[:,1]+float(row["_bbox_y0"]))/detection_scale
            curve=_curvature(spine);detailed_frames+=1
            tracks.at[row_index,"spine_valid"]=True
            tracks.at[row_index,"spine_x_json"]=json.dumps(spine[:,0].round(2).tolist())
            tracks.at[row_index,"spine_y_json"]=json.dumps(spine[:,1].round(2).tolist())
            tracks.at[row_index,"curvature_json"]=json.dumps(curve.round(6).tolist()) if curve is not None else ""
            tracks.at[row_index,"midbody_curvature_px_inv"]=(float(np.mean(curve[8:17])) if curve is not None else np.nan)
            if progress and (chosen_number==chosen_count or
                             chosen_number%within_track_interval==0):
                progress(group_number-1+(chosen_number/chosen_count),total_groups,
                         f"Detailed spines: track {group_number}/{total_groups} "
                         f"({chosen_number}/{chosen_count})")
        if progress and (group_number==1 or group_number==total_groups or
                         group_number%progress_interval==0):
            progress(group_number,total_groups,"Detailed spines for eligible tracks")
    return tracks,stride,detailed_tracks,detailed_frames


def recompute_from_detections(results_dir, fps, um_per_px, output_dir=None,
                              progress=None, reason=""):
    """Re-derive a finished run under a corrected frame rate and/or scale.

    A declared frame rate or micrometres-per-pixel that turns out to be wrong
    does not invalidate the detection work: positions are in source pixels and
    frame numbers are integers, neither of which depends on either parameter.
    Everything downstream does.

    Speed and frequency could in principle be rescaled arithmetically, but the
    modality classifier compares frequency against FIXED thresholds - so a run
    whose frequency changes must be reclassified, not multiplied. This therefore
    recomputes rather than rescales: it reloads the saved detections, restamps
    time from the corrected rate, and re-runs the summary and the classifier.
    No frames are decoded, so it is fast.

    The original results are never modified; output goes to a new folder.
    """
    results_dir = Path(results_dir)
    detections_path = results_dir / "detections_and_tracks.csv"
    if not detections_path.exists():
        raise FileNotFoundError(
            f"{detections_path.name} not found - recompute needs a completed run.")
    fps = float(fps); um_per_px = float(um_per_px)
    if fps <= 0 or um_per_px <= 0:
        raise ValueError("Frame rate and scale must both be greater than zero.")

    def report(done, total, phase="Recomputing"):
        if progress is None:
            return
        try:
            progress(done, total, phase)
        except TypeError:
            progress(done, total)

    report(0, 1, "Reloading saved detections")
    tracks = pd.read_csv(detections_path)

    metadata = {}
    metadata_path = results_dir / "analysis_metadata.json"
    if metadata_path.exists():
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:
            metadata = {}
    old_fps = metadata.get("fps")
    old_scale = metadata.get("um_per_px")
    analyzed_frames = int(metadata.get("n_frames") or (int(tracks.frame.max()) + 1))
    spine_stride = int(metadata.get("detailed_spine_stride_frames") or 1)

    # Time is the only per-row quantity that depends on the frame rate; the
    # positions, areas, spines and curvatures are all in pixel units already.
    tracks["time_s"] = tracks.frame.astype(float) / fps

    report(0, 1, "Rebuilding track summaries")
    tracks, summary = summarize_tracks(tracks, fps, um_per_px, analyzed_frames)

    out = Path(output_dir) if output_dir else (
        results_dir / f"recomputed_fps{fps:g}_scale{um_per_px:g}")
    out.mkdir(parents=True, exist_ok=True)
    tracks.to_csv(out / "detections_and_tracks.csv", index=False)
    summary.to_csv(out / "track_summary.csv", index=False)

    windows = classify_modality_windows(tracks, fps, progress=report,
                                        spine_stride=spine_stride)
    report(0, 1, "Writing recomputed proposals")
    bouts = windows_to_bouts(windows, fps)
    windows.to_csv(out / "modality_window_proposals.csv", index=False)
    bouts.to_csv(out / "modality_bouts_for_review.csv", index=False)

    new_metadata = dict(metadata)
    new_metadata.update({
        "fps": fps, "um_per_px": um_per_px, "n_frames": analyzed_frames,
        "recomputed_from": str(results_dir),
        "recompute_reason": str(reason or ""),
        "superseded_fps": old_fps, "superseded_um_per_px": old_scale,
        "recompute_note": (
            "Re-derived from the saved detections of the run named in "
            "recomputed_from. Detection, linking and spine extraction were NOT "
            "repeated - those depend only on pixels and frame numbers. Track "
            "summaries and modality proposals WERE recomputed, because the "
            "classifier compares frequency against fixed thresholds and so "
            "cannot be rescaled arithmetically. Any human review of the "
            "original run does not carry over and must be redone."),
    })
    (out / "analysis_metadata.json").write_text(
        json.dumps(new_metadata, indent=2), encoding="utf-8")
    (out / "recompute_provenance.json").write_text(json.dumps({
        "source_results": str(results_dir),
        "declared_before": {"fps": old_fps, "um_per_px": old_scale},
        "declared_after": {"fps": fps, "um_per_px": um_per_px},
        "fps_factor": (fps / float(old_fps)) if old_fps else None,
        "scale_factor": (um_per_px / float(old_scale)) if old_scale else None,
        "reason": str(reason or ""),
        "recomputed_outputs": ["detections_and_tracks.csv", "track_summary.csv",
                               "modality_window_proposals.csv",
                               "modality_bouts_for_review.csv"],
        "not_carried_over": ["reviewed_track_summary.csv",
                             "reviewed_modality_bouts.csv",
                             "track_stitch_edits.json"],
    }, indent=2), encoding="utf-8")
    return summary, out


def analyze(source, fps, um_per_px, output_dir=None, min_area=40, max_area=2500,
            max_link_px=60, activity_speed_lengths_s=.08, sample_background=31,
            progress=None, roi_records=None, roi_mode="none", start_frame=1,
            end_frame=None, detection_scale=1.0,
            adaptive_background_sampling=True,fast_first_pass=True,
            single_pass_background=False,cache_two_pass_proxy=False,
            low_resolution_background=False,selective_background_decode=False,
            direct_uint8_proxy=True,locked_tracks=None,
            locked_exclusion_radius_px=40.0,
            spine_method=SPINE_METHOD_DEFAULT):
    run_started=time.perf_counter();timings={};detection_scale=float(detection_scale)
    if detection_scale not in (1.0,0.5,0.25):
        raise ValueError("Detection scale must be 1.0, 0.5, or 0.25.")
    def proxy(gray):
        if detection_scale==1.0:return gray
        return cv2.resize(gray,None,fx=detection_scale,fy=detection_scale,interpolation=cv2.INTER_AREA)
    def proxy_gray(frame):
        a=np.asarray(frame)
        if direct_uint8_proxy and a.ndim==2 and a.dtype==np.uint8:
            return a
        return read_gray(a)
    def report(done,total,phase):
        if progress is None:return
        try:progress(done,total,phase)
        except TypeError:progress(done,total)
    load_started=time.perf_counter()
    files=list_frames(source); fps=float(fps); scale=float(um_per_px)
    # A blank end frame means "to the last frame", so len(files) sets
    # selected_count and therefore coverage_fraction. Interactive callers run on
    # a cheap container estimate; analysis must not. Force the exact count here,
    # by the same method as before, so reported numbers are unchanged.
    report(0,1,"Indexing frames")
    files.ensure_exact_length()
    if len(files) < 2:
        files.close()
        raise ValueError("Population swimming requires a multi-frame movie, stack, or image sequence.")
    start_frame=int(start_frame); end_frame=len(files) if end_frame is None else int(end_frame)
    if start_frame<1 or start_frame>len(files):
        files.close();raise ValueError(f"Start frame must be between 1 and {len(files)}.")
    if end_frame<start_frame or end_frame>len(files):
        files.close();raise ValueError(f"End frame must be between {start_frame} and {len(files)}.")
    start_index=start_frame-1;end_index=end_frame-1;selected_count=end_index-start_index+1
    if selected_count<2:
        files.close();raise ValueError("Select at least two frames for population swimming analysis.")
    roi_records=list(roi_records or [])
    locked_tracks=(locked_tracks.copy() if isinstance(locked_tracks,pd.DataFrame)
                   else pd.DataFrame())
    locked_by_frame={}
    if not locked_tracks.empty:
        required={"frame","x","y"}
        if not required.issubset(locked_tracks.columns):
            raise ValueError("Locked tracks must contain frame, x, and y columns.")
        for locked_frame,group in locked_tracks.groupby(locked_tracks.frame.astype(int)):
            locked_by_frame[int(locked_frame)]=group[["x","y"]].to_numpy(float)
    roi_mode=str(roi_mode).lower()
    if roi_mode not in {"none","include","exclude"}:
        raise ValueError("ROI mode must be none, include, or exclude.")
    if roi_mode != "none" and not roi_records:
        raise ValueError("ROI filtering was enabled but no ROIs were supplied.")
    acquisition=AcquisitionMetadata(fps,"declared",scale,"declared",None,"not_applicable").validate()
    proxy_h=max(1,int(round(files.movie.height*detection_scale)))
    proxy_w=max(1,int(round(files.movie.width*detection_scale)))
    pixel_count=max(1,proxy_h*proxy_w)
    effective_background_samples=(min(sample_background,max(7,120_000_000//pixel_count))
                                  if adaptive_background_sampling else sample_background)
    idx=np.unique(np.linspace(start_index,end_index,min(effective_background_samples,selected_count)).astype(int))
    analysis_frame_stream=None
    analysis_stream_start=0
    background=None
    proxy_cache=None
    proxy_cache_used=False
    background_decode_scale=(min(detection_scale,0.25)
                             if low_resolution_background else detection_scale)
    if files.movie.source_kind=="video" and single_pass_background:
        # wrMTrck-style fast preparation: buffer only a short initial interval,
        # use a high percentile so moving dark worms do not become background,
        # then continue from the SAME decoder stream.
        raw_stream=iter(files.proxy_frames(detection_scale))
        for _ in range(start_index):
            try:next(raw_stream)
            except StopIteration:break
        buffer_count=min(selected_count,max(31,min(60,int(round(2*fps)))))
        buffered=[]
        for j in range(buffer_count):
            try:buffered.append(proxy_gray(next(raw_stream)))
            except StopIteration:break
            report(j+1,buffer_count,"Building single-pass background")
        samples=buffered
        background=np.percentile(np.stack(samples),90,axis=0).astype(np.uint8)
        analysis_frame_stream=itertools.chain(buffered,raw_stream)
        analysis_stream_start=start_index
    elif files.movie.source_kind=="video":
        wanted=set(int(i) for i in idx);samples=[]
        expected_cache_bytes=selected_count*pixel_count
        if cache_two_pass_proxy:
            try:
                free_bytes=shutil.disk_usage(tempfile.gettempdir()).free
                if free_bytes>expected_cache_bytes+1_000_000_000:
                    proxy_cache=tempfile.TemporaryFile(prefix="nike_swim_proxy_",suffix=".gray")
            except OSError:
                proxy_cache=None
        cached_frames=0
        if selective_background_decode and proxy_cache is None:
            for sample_number,frame in enumerate(
                    files.sampled_proxy_frames(idx,background_decode_scale),1):
                samples.append(proxy_gray(frame))
                report(sample_number,len(idx),"Building robust background samples")
        else:
            for fi,frame in enumerate(files.proxy_frames(background_decode_scale)):
                im=proxy_gray(frame)
                if fi in wanted:samples.append(im.copy())
                if proxy_cache is not None and background_decode_scale==detection_scale and start_index<=fi<=end_index:
                    proxy_cache.write(np.ascontiguousarray(im,dtype=np.uint8).tobytes())
                    cached_frames+=1
                if fi%100==0:report(min(fi+1,end_index+1),end_index+1,"Building background proxy")
                if fi>=end_index:break
        if proxy_cache is not None and cached_frames==selected_count:
            proxy_cache.flush();proxy_cache.seek(0)
            def cached_proxy_frames():
                for _ in range(selected_count):
                    payload=proxy_cache.read(pixel_count)
                    if len(payload)!=pixel_count:
                        break
                    yield np.frombuffer(payload,dtype=np.uint8).reshape(proxy_h,proxy_w)
            analysis_frame_stream=cached_proxy_frames()
            analysis_stream_start=start_index
            proxy_cache_used=True
        elif proxy_cache is not None:
            proxy_cache.close();proxy_cache=None
    else:samples=[proxy(read_gray(files[int(i)])) for i in idx]
    if not samples:
        files.close()
        raise ValueError("No readable frames were found in the selected recording.")
    if background is None:
        background=np.median(np.stack(samples),axis=0).astype(np.uint8)
        if background.shape!=(proxy_h,proxy_w):
            background=cv2.resize(background,(proxy_w,proxy_h),interpolation=cv2.INTER_LINEAR)
    timings["source_index_and_background_s"]=time.perf_counter()-load_started
    reviewed = find_accepted_config(source, "population_swimming")
    reviewed_diff = replace(reviewed, feature="gray") if reviewed else None
    detections=[]; frame_shape=background.shape
    actual_frames = selected_count
    tracking_started=time.perf_counter()
    scaled_min_area=float(min_area)*detection_scale*detection_scale
    scaled_max_area=float(max_area)*detection_scale*detection_scale
    frame_stream=(analysis_frame_stream if analysis_frame_stream is not None else
                  files.proxy_frames(detection_scale) if files.movie.source_kind=="video" else files.frames())
    for fi, frame in enumerate(frame_stream,start=analysis_stream_start):
        if fi<start_index:continue
        if fi>end_index:break
        im=(proxy_gray(frame) if files.movie.source_kind=="video" else proxy(read_gray(frame))); diff=cv2.absdiff(im,background); diff=cv2.GaussianBlur(diff,(3,3),0)
        if reviewed_diff:
            mask=np.uint8(segment_frame(diff,fi,reviewed_diff))*255
        else:
            _,mask=cv2.threshold(diff,0,255,cv2.THRESH_BINARY+cv2.THRESH_OTSU)
        mask=cv2.morphologyEx(mask,cv2.MORPH_OPEN,np.ones((3,3),np.uint8))
        mask=cv2.morphologyEx(mask,cv2.MORPH_CLOSE,np.ones((5,5),np.uint8))
        n,lab,stats,cents=cv2.connectedComponentsWithStats(mask)
        for k in range(1,n):
            area=stats[k,cv2.CC_STAT_AREA]
            if not scaled_min_area<=area<=scaled_max_area: continue
            # Work only inside this component's bounding box.  The former
            # np.where(lab==k) rescanned the entire 4K/proxy frame once per
            # candidate and became catastrophically slow on textured scenes.
            x0, y0 = int(stats[k, cv2.CC_STAT_LEFT]), int(stats[k, cv2.CC_STAT_TOP])
            width, height = int(stats[k, cv2.CC_STAT_WIDTH]), int(stats[k, cv2.CC_STAT_HEIGHT])
            component=(lab[y0:y0+height,x0:x0+width]==k)
            ys,xs=np.where(component); cov=np.cov(np.vstack([xs,ys]))
            vals,vec=np.linalg.eigh(cov); major=vec[:,np.argmax(vals)]
            angle=float(np.degrees(np.arctan2(major[1],major[0]))%180)
            elong=float(np.sqrt(max(vals)/max(min(vals),1e-6)))
            x,y=cents[k]; edge=bool(x0<3 or y0<3 or x0+width>frame_shape[1]-4 or y0+height>frame_shape[0]-4)
            x_out,y_out=float(x/detection_scale),float(y/detection_scale)
            locked_positions=locked_by_frame.get(int(fi))
            if locked_positions is not None and len(locked_positions):
                distances=np.hypot(locked_positions[:,0]-x_out,
                                   locked_positions[:,1]-y_out)
                if float(np.min(distances))<=float(locked_exclusion_radius_px):
                    continue
            inside_roi=_point_in_any_roi(x_out,y_out,roi_records)
            if roi_mode=="include" and not inside_roi:
                continue
            if roi_mode=="exclude" and inside_roi:
                continue
            spine=None;curve=None
            packed_mask=np.packbits(component.reshape(-1)).tobytes() if fast_first_pass else None
            if not fast_first_pass:
                spine = _ordered_spine(component)
                if spine is not None:
                    spine[:, 0] = (spine[:, 0]+x0)/detection_scale
                    spine[:, 1] = (spine[:, 1]+y0)/detection_scale
                curve = _curvature(spine)
            detections.append(dict(frame=fi,time_s=fi/fps,x=x_out,y=y_out,area_px=area/(detection_scale*detection_scale),axis_angle_deg=angle,elongation=elong,edge=edge,
                spine_valid=spine is not None,
                spine_x_json=json.dumps(spine[:, 0].round(2).tolist()) if spine is not None else "",
                spine_y_json=json.dumps(spine[:, 1].round(2).tolist()) if spine is not None else "",
                curvature_json=json.dumps(curve.round(6).tolist()) if curve is not None else "",
                midbody_curvature_px_inv=float(np.mean(curve[8:17])) if curve is not None else np.nan,
                _packed_mask=packed_mask,_mask_shape=component.shape,_bbox_x0=x0,_bbox_y0=y0))
        selected_position=fi-start_index+1
        if selected_position==1 or selected_position%5==0 or selected_position==selected_count:report(selected_position,selected_count,"Fast detection and linking measurements")
    if proxy_cache is not None:
        proxy_cache.close();proxy_cache=None
    timings["decode_detection_and_spines_s"]=time.perf_counter()-tracking_started
    det=pd.DataFrame(detections)
    if det.empty: raise ValueError("No worm-sized moving objects were detected. Adjust area limits.")
    report(0,1,"Linking trajectories");linking_started=time.perf_counter();tracks=link_detections(det,max_link_px=max_link_px)
    spine_stride=1;detailed_tracks=int(tracks.track_id.nunique());detailed_frames=int(tracks.spine_valid.sum())
    if fast_first_pass:
        spine_started=time.perf_counter();tracks,spine_stride,detailed_tracks,detailed_frames=_attach_selective_spines(
            tracks,fps,detection_scale,progress=report,spine_method=spine_method)
        timings["selective_detailed_spines_s"]=time.perf_counter()-spine_started
    tracks=tracks.drop(columns=[c for c in ("_packed_mask","_mask_shape","_bbox_x0","_bbox_y0") if c in tracks],errors="ignore")
    report(0,1,"Orienting spines and calculating summaries");tracks=_orient_spines(tracks)
    locked_track_ids=[]
    if not locked_tracks.empty:
        locked_tracks=locked_tracks.copy()
        locked_track_ids=sorted(locked_tracks.track_id.astype(int).unique().tolist())
        next_track_id=(max(locked_track_ids)+1) if locked_track_ids else 0
        rescue_ids=sorted(tracks.track_id.astype(int).unique())
        rescue_map={old:next_track_id+offset for offset,old in enumerate(rescue_ids)}
        tracks["track_id"]=tracks.track_id.astype(int).map(rescue_map)
        common_columns=sorted(set(tracks.columns)|set(locked_tracks.columns))
        tracks=pd.concat([
            locked_tracks.reindex(columns=common_columns),
            tracks.reindex(columns=common_columns),
        ],ignore_index=True).sort_values(["track_id","frame"])
    tracks,summary=summarize_tracks(tracks,fps,scale,actual_frames)
    timings["linking_and_summary_s"]=time.perf_counter()-linking_started
    source_path = Path(source)
    default_out = (source_path / "population_swimming_results" if source_path.is_dir()
                   else source_path.parent / f"{source_path.stem}_population_swimming_results")
    out=Path(output_dir) if output_dir else default_out; out.mkdir(parents=True,exist_ok=True)
    report(0,1,"Writing tracks and summary tables");export_started=time.perf_counter();tracks.to_csv(out/"detections_and_tracks.csv",index=False); summary.to_csv(out/"track_summary.csv",index=False)
    modality_windows=classify_modality_windows(tracks,fps,progress=report,
                                               spine_stride=spine_stride)
    report(0,1,"Writing modality proposals and metadata");modality_bouts=windows_to_bouts(modality_windows,fps)
    modality_windows.to_csv(out/"modality_window_proposals.csv",index=False)
    modality_bouts.to_csv(out/"modality_bouts_for_review.csv",index=False)
    (out/"analysis_rois.json").write_text(json.dumps({
        "mode":roi_mode,"rule":"component centroid inside union of supplied ROIs",
        "rois":roi_records},indent=2),encoding="utf-8")
    meta={**acquisition.as_columns(),
          "source_frame_width":int(files.movie.width),
          "source_frame_height":int(files.movie.height),
          "n_frames":actual_frames,"source_frame_start_1_based":start_frame,
          "source_frame_end_1_based":end_frame,"source_total_frames":len(files),
          "n_candidate_tracks":len(summary),"min_area_px":min_area,"max_area_px":max_area,
          "input_source":str(source_path.resolve()),
          "input_source_kind":files.movie.source_kind,
          "detection_scale":detection_scale,
          "adaptive_background_sampling":bool(adaptive_background_sampling),
          "background_sample_count":int(len(samples)),
          "single_pass_background":bool(single_pass_background),
          "local_proxy_cache_requested":bool(cache_two_pass_proxy),
          "local_proxy_cache_used":bool(proxy_cache_used),
          "low_resolution_background":bool(low_resolution_background),
          "background_decode_scale":float(background_decode_scale),
          "selective_background_decode":bool(selective_background_decode),
          "direct_uint8_proxy":bool(direct_uint8_proxy),
          "locked_track_ids":locked_track_ids,
          "locked_exclusion_radius_px":float(locked_exclusion_radius_px),
          "fast_wrmtrck_style_first_pass":bool(fast_first_pass),
          "detailed_spine_stride_frames":int(spine_stride),
          "detailed_spine_tracks":int(detailed_tracks),
          "detailed_spine_frames":int(detailed_frames),
          "spine_skeleton_method":str(spine_method),
          "spine_skeleton_method_note":(
              "morphological = erosion-residue skeleton (historical default; can "
              "fragment on masks more than a few pixels thick, yielding a partial "
              "spine or none). thinning = scikit-image Zhang-Suen/Lee thinning "
              "(stays connected). Spine, curvature and bend frequency depend on "
              "this choice, so results from different methods are not comparable."),
          "roi_mode":roi_mode,"roi_count":len(roi_records),
          "roi_rule":"none" if roi_mode=="none" else f"{roi_mode} detections by component centroid within the union of optional ROIs",
          "frequency_definition":"dominant lateral centroid oscillation about the smoothed trajectory; signed midbody spine curvature is retained as a fallback and diagnostic",
          "spine_definition":f"longest skeleton path resampled to {SPINE_POINTS} ordered points",
          "modality_detector":"4 s overlapping windows; C/S/W curvature topology, bend frequency, centroid speed, posterior wave lag, collision and coverage gates; three-window temporal smoothing",
          "modality_thresholds":"swimming typically >0.8 Hz with C posture; crawling typically 0.2-0.6 Hz with S posture; burrowing typically <0.5 Hz with persistent W posture and posterior wave evidence; overlapping evidence remains uncertain",
          "modality_review_required":"Every proposed bout is pending until a user confirms, relabels, or rejects it.",
          "activity_definition":f"centroid speed >= {activity_speed_lengths_s} estimated body lengths/s",
          "frequency_gate":"Frequency is blank for tracks shorter than 3 s, sparsely detected, or with >5% possible-collision frames.",
          "identity_linking":"position, heading, and speed continuation through crossings; incoming clean trajectories are retained across merged blobs; nearly equal alternatives are flagged",
          "review_required":"All tracks require review; edges, likely collisions, and short fragments receive explicit reasons."}
    (out/"analysis_metadata.json").write_text(json.dumps(meta,indent=2),encoding="utf-8")
    timings["export_s"]=time.perf_counter()-export_started
    timings["processing_total_s"]=time.perf_counter()-run_started
    (out/"timing_report.json").write_text(json.dumps({"tool":"population_swimming",
        "performance_options":{"detection_scale":detection_scale,
            "adaptive_background_sampling":bool(adaptive_background_sampling),
            "single_pass_background":bool(single_pass_background),
            "local_proxy_cache_requested":bool(cache_two_pass_proxy),
            "local_proxy_cache_used":bool(proxy_cache_used),
            "low_resolution_background":bool(low_resolution_background),
            "background_decode_scale":float(background_decode_scale),
            "selective_background_decode":bool(selective_background_decode),
            "direct_uint8_proxy":bool(direct_uint8_proxy),
            "locked_track_count":len(locked_track_ids),
            "fast_wrmtrck_style_first_pass":bool(fast_first_pass),
            "detailed_spine_stride_frames":int(spine_stride),
            "spine_skeleton_method":str(spine_method)},
        "frames_analyzed":actual_frames,"frame_pixels_processed":int(background.size),
        "timings_seconds":{k:round(float(v),4) for k,v in timings.items()}},indent=2),encoding="utf-8")
    files.close()
    return summary,out
