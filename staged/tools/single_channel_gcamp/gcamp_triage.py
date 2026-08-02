"""
GCaMP-only movie triage
========================

Purpose
-------
Sort a folder of blue-channel-only Pmyo-3::GCaMP movies (no DIC/brightfield
channel) into "workable" vs "needs manual review" vs "not workable" before
committing to full extraction, and only pay the full-resolution cost for
brightness sampling on movies that pass triage.

Design choices, and why (mirrors patterns already in the Hub)
---------------------------------------------------------------
- Detection runs on a downsampled frame (cheap); brightness is always read
  back from the full-resolution frame at the mapped coordinates (accurate).
  This is the same split used in the earlier single-frame test.
- ROI support, same idea as the pharyngeal-pumping ROI: if you know roughly
  where the worm/arena lives in the frame, restrict candidate detection to
  that region instead of the whole frame. Optional; full-frame is the default.
- Persistent-track logic, same idea as pBoc's explicit distractor handling:
  rather than blindly grabbing "largest connected component" every frame
  (which silently jumps to a stray bright pixel or a second worm), candidate
  blobs are linked frame-to-frame by nearest centroid. A movie is only
  called "workable" if one blob track is persistent and dominant across the
  sampled frames. Movies with multiple similarly-sized blobs that trade off
  which one is "largest" are flagged for manual distractor annotation
  instead of being silently resolved by the script.
- Nothing here is a substitute for the real Track one worm tool. This is a
  pre-flight triage step only: it tells you which movies are worth taking
  into the Hub tools, and which need a human to look first.

Usage
-----
    python gcamp_triage.py /path/to/movie_folder --out report.csv

Requires: opencv-python-headless, scikit-image, numpy, pandas, ffmpeg on PATH
"""

import argparse
import subprocess
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
from skimage.morphology import skeletonize

# ---------------------------------------------------------------------------
# Tunable defaults. Record any non-default value used for a real batch run,
# same as any other exposed threshold in the Hub tools.
# ---------------------------------------------------------------------------
DOWNSAMPLE_SCALE = 0.25       # detection resolution factor
N_SAMPLE_FRAMES = 8           # frames sampled per movie, evenly spaced
MIN_BLOB_AREA_PX = 15         # at downsample scale; rejects single-pixel noise
MAX_CENTROID_JUMP_FRAC = 0.15 # max centroid movement (fraction of frame diag)
                               # to still count as "same track" between samples
DOMINANT_SIZE_RATIO = 1.5     # main blob must be >= this x the runner-up
                               # to count as unambiguous in a given frame


def get_frame_count(video_path: str) -> int:
    cap = cv2.VideoCapture(video_path)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n


def read_frame(video_path: str, frame_idx: int):
    cap = cv2.VideoCapture(video_path)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def roi_mask_for_shape(shape, roi):
    """roi = (x, y, w, h) in ORIGINAL full-res frame coordinates, or None."""
    mask = np.ones(shape, dtype=bool)
    if roi is not None:
        x, y, w, h = roi
        mask[:] = False
        mask[y:y + h, x:x + w] = True
    return mask


def find_candidate_blobs(gray_full, roi=None, scale=DOWNSAMPLE_SCALE,
                          min_area=MIN_BLOB_AREA_PX):
    """Downsample, threshold, and return candidate blobs.

    Returns list of dicts: {area, centroid (full-res xy), mask_small}
    """
    small = cv2.resize(gray_full, None, fx=scale, fy=scale,
                        interpolation=cv2.INTER_AREA)

    small_mask_roi = None
    if roi is not None:
        x, y, w, h = roi
        small_mask_roi = np.zeros(small.shape, dtype=bool)
        small_mask_roi[int(y * scale):int((y + h) * scale),
                        int(x * scale):int((x + w) * scale)] = True

    blur = cv2.GaussianBlur(small, (5, 5), 0)
    _, mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if small_mask_roi is not None:
        mask[~small_mask_roi] = 0

    n_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        mask, connectivity=8)

    blobs = []
    for i in range(1, n_labels):  # skip background label 0
        area = stats[i, cv2.CC_STAT_AREA]
        if area < min_area:
            continue
        cx, cy = centroids[i]
        blobs.append({
            "area_small": int(area),
            "centroid_full": (cx / scale, cy / scale),
            "label_mask_small": (labels == i),
        })
    blobs.sort(key=lambda b: b["area_small"], reverse=True)
    return blobs, mask.shape


def link_tracks(frame_blobs, frame_diag_full):
    """Very small nearest-centroid linker across sampled frames.

    frame_blobs: list (per sampled frame) of list-of-blob-dicts
    Returns: dict track_id -> list of (frame_index, blob) it appears in
    """
    max_jump = MAX_CENTROID_JUMP_FRAC * frame_diag_full
    tracks = {}
    next_id = 0
    active = {}  # track_id -> last centroid

    for f_idx, blobs in enumerate(frame_blobs):
        assigned = set()
        for tid, last_c in list(active.items()):
            if not blobs:
                continue
            dists = [np.hypot(b["centroid_full"][0] - last_c[0],
                               b["centroid_full"][1] - last_c[1])
                     for b in blobs]
            j = int(np.argmin(dists))
            if dists[j] <= max_jump and j not in assigned:
                tracks[tid].append((f_idx, blobs[j]))
                active[tid] = blobs[j]["centroid_full"]
                assigned.add(j)

        for j, b in enumerate(blobs):
            if j in assigned:
                continue
            tid = next_id
            next_id += 1
            tracks[tid] = [(f_idx, b)]
            active[tid] = b["centroid_full"]

    return tracks


def sample_full_res_brightness(gray_full, mask_small, scale):
    """Skeletonize the (already chosen) blob mask at low res, map to full
    res, and read real intensity values there. Downsample is for shape only;
    brightness always comes from the full-resolution frame."""
    skel = skeletonize(mask_small)
    ys, xs = np.nonzero(skel)
    if len(xs) == 0:
        return None
    xs_full = np.clip((xs / scale).astype(int), 0, gray_full.shape[1] - 1)
    ys_full = np.clip((ys / scale).astype(int), 0, gray_full.shape[0] - 1)
    vals = gray_full[ys_full, xs_full]
    return {
        "n_midline_px": int(len(vals)),
        "brightness_min": int(vals.min()),
        "brightness_max": int(vals.max()),
        "brightness_mean": float(vals.mean()),
    }


def triage_one_movie(video_path: str, roi=None,
                      n_samples=N_SAMPLE_FRAMES) -> dict:
    n_frames = get_frame_count(video_path)
    if n_frames <= 0:
        return {"file": Path(video_path).name, "status": "unreadable",
                "note": "could not read frame count"}

    sample_idxs = np.linspace(0, n_frames - 1, num=min(n_samples, n_frames),
                               dtype=int)

    per_frame_blobs = []
    frame_shape_full = None
    last_gray = None
    for idx in sample_idxs:
        gray = read_frame(video_path, int(idx))
        if gray is None:
            per_frame_blobs.append([])
            continue
        frame_shape_full = gray.shape
        last_gray = gray
        blobs, _ = find_candidate_blobs(gray, roi=roi)
        per_frame_blobs.append(blobs)

    if frame_shape_full is None:
        return {"file": Path(video_path).name, "status": "unreadable",
                "note": "no frames decoded"}

    frame_diag_full = np.hypot(*frame_shape_full)
    tracks = link_tracks(per_frame_blobs, frame_diag_full)

    n_sampled = len(sample_idxs)
    frames_with_any_blob = sum(1 for b in per_frame_blobs if b)

    # dominant-track logic: which track appears in the most frames, and by
    # how much does it beat any competing track (distractor signal)
    track_lengths = {tid: len(entries) for tid, entries in tracks.items()}
    if not track_lengths:
        status = "not_workable"
        note = "no candidate blob detected in any sampled frame"
        dominant_tid = None
    else:
        sorted_tracks = sorted(track_lengths.items(), key=lambda x: x[1],
                                reverse=True)
        dominant_tid, dominant_len = sorted_tracks[0]
        runner_len = sorted_tracks[1][1] if len(sorted_tracks) > 1 else 0

        coverage = dominant_len / n_sampled
        if coverage >= 0.75 and (runner_len == 0 or
                                  dominant_len >= DOMINANT_SIZE_RATIO * runner_len):
            status = "workable"
            note = f"dominant track present in {dominant_len}/{n_sampled} sampled frames"
        elif coverage >= 0.4:
            status = "needs_review_distractor"
            note = (f"multiple competing blob tracks (best track "
                    f"{dominant_len}/{n_sampled}, runner-up {runner_len}); "
                    f"likely needs manual distractor annotation, same as pBoc")
        else:
            status = "not_workable"
            note = f"no persistent blob track (best coverage {dominant_len}/{n_sampled})"

    result = {
        "file": Path(video_path).name,
        "n_frames_total": n_frames,
        "n_sampled": n_sampled,
        "frames_with_any_blob": frames_with_any_blob,
        "n_candidate_tracks": len(tracks),
        "status": status,
        "note": note,
        "roi_used": bool(roi),
    }

    # only pay full-res brightness cost for movies that passed triage
    if status == "workable" and dominant_tid is not None:
        last_frame_idx, last_blob = tracks[dominant_tid][-1]
        gray_last = read_frame(video_path, int(sample_idxs[last_frame_idx]))
        brightness = sample_full_res_brightness(
            gray_last, last_blob["label_mask_small"], DOWNSAMPLE_SCALE)
        if brightness:
            result.update({f"brightness_{k}": v for k, v in brightness.items()})

    return result


def triage_folder(folder: str, roi=None, pattern="*.mp4") -> pd.DataFrame:
    folder_path = Path(folder)
    videos = sorted(folder_path.glob(pattern))
    rows = [triage_one_movie(str(v), roi=roi) for v in videos]
    return pd.DataFrame(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("folder", help="folder containing movie files")
    ap.add_argument("--pattern", default="*.mp4")
    ap.add_argument("--out", default="triage_report.csv")
    ap.add_argument("--roi", nargs=4, type=int, default=None,
                     metavar=("X", "Y", "W", "H"),
                     help="optional ROI in full-res pixel coords")
    args = ap.parse_args()

    roi = tuple(args.roi) if args.roi else None
    df = triage_folder(args.folder, roi=roi, pattern=args.pattern)
    df.to_csv(args.out, index=False)
    print(df.to_string(index=False))
    print(f"\nSaved report to {args.out}")
