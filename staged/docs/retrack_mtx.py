"""Re-track an MTX movie with reference subtraction + nearest-neighbour linking.

The archived wrMTrck output shatters each animal into ~8-frame fragments, so
nothing that follows one worm over time can be computed from it. This rebuilds
tracks from the movie.
"""
import sys
from pathlib import Path

import numpy as np
import tifffile

ROOT = Path(r"C:\Users\avidal\OneDrive - IL State University\Documents"
            r"\Behavior Analysis\LabTools_Reorganization\staged")
sys.path[:0] = [str(ROOT / "app")]
import reference_subtraction as rs   # noqa: E402

MOVIE = sys.argv[1] if len(sys.argv) > 1 else (
    r"L:\03_Magnetic Transduction\Christine"
    r"\Assay2_MTX_8bit_gray_1fps_960-1.tif")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("retracked.csv")
STEP = int(sys.argv[3]) if len(sys.argv) > 3 else 5      # 0.2 Hz, per the paper
FPS = 1.0
MAX_FRAMES = int(sys.argv[4]) if len(sys.argv) > 4 else 0
# Frame 0 carries a ceiling-lamp reflection off the plate that is
# gone by frame 1 and never returns - the one frame unlike every
# other, and the one 'subtract the starting frame' would pick.
REF_INDEX = 1
REF_N = int(sys.argv[5]) if len(sys.argv) > 5 else 10
# A quieter reference should buy SIGNAL-TO-NOISE at the same
# absolute threshold, not a lower threshold - otherwise the gain
# is spent admitting marginal blobs that flicker and fragment
# real tracks, which is what a straight swap measured.
THRESH_SD = float(sys.argv[6]) if len(sys.argv) > 6 else 4.0
PX_PER_MM = 20.10   # from worm length 1.14 mm; FOV 47.8 x 26.9 mm

# LINKING DISTANCE MUST BE BELOW THE SPACING BETWEEN ANIMALS. With ~60 worms
# in a 540x960 frame the mean nearest-neighbour spacing is about 93 px, so a
# jump cap above that lets a track hop onto the wrong worm - which does not
# look like an error, it looks like a fast animal. An adult crawls ~0.15 mm/s;
# at roughly 9.6 px/mm for a 10 cm plate across 960 px that is ~7 px in the 5 s
# between samples, so 30 px is already generous.
MAX_JUMP_PX = 12.0   # ~0.6 mm per linking step
MAX_GAP_STEPS = 2                  # tolerate brief disappearance
# wrMTrck's own accepted blobs had a minimum area of 31 px on this movie, so
# admitting 15 px objects adds noise it had already excluded.
MIN_AREA_PX = 20
MAX_AREA_PX = 2000


def main():
    with tifffile.TiffFile(MOVIE) as tf:
        n_pages = len(tf.pages)
        limit = min(n_pages, MAX_FRAMES) if MAX_FRAMES else n_pages
        # Andres: average the first ten frames rather than trusting one. Correct,
        # and measured - the mean of frames 1-10 drops the difference-image
        # noise floor from 1.48 to 1.00 (32%), which lowers the detection
        # threshold and holds fainter animals. MEAN not median: a median is
        # robust but noisier, and averaging is the point here. Starting at 1,
        # not 0, because frame 0 carries the lamp reflection and would
        # contribute a tenth of a large artefact to every pixel it covers.
        ref = np.mean([tf.pages[i].asarray().astype(np.float32)
                       for i in range(REF_INDEX, REF_INDEX + REF_N)], axis=0)
        print(f"{Path(MOVIE).name}: {n_pages} frames, using {limit}, "
              f"step {STEP} ({FPS / STEP:.2f} Hz)")

        tracks = {}          # id -> list of rows
        active = {}          # id -> (last_xy, last_index)
        next_id = 0
        n_det = 0
        for i in range(0, limit, STEP):
            frame = tf.pages[i].asarray().astype(np.float32)
            try:
                found = rs.detect(frame, ref, threshold_sd=THRESH_SD,
                                  min_area_px=MIN_AREA_PX,
                                  max_area_px=MAX_AREA_PX,
                                  polarity="bright")
            except rs.SubtractionError:
                continue
            blobs = found["blobs"]
            n_det += len(blobs)

            # Greedy nearest-neighbour, closest pairs first.
            pairs = []
            for wid, (xy, last_i) in active.items():
                if (i - last_i) / STEP > MAX_GAP_STEPS:
                    continue
                for bi, b in enumerate(blobs):
                    d = float(np.hypot(b["x_px"] - xy[0], b["y_px"] - xy[1]))
                    if d <= MAX_JUMP_PX:
                        pairs.append((d, wid, bi))
            pairs.sort()
            used_w, used_b = set(), set()
            for d, wid, bi in pairs:
                if wid in used_w or bi in used_b:
                    continue
                used_w.add(wid)
                used_b.add(bi)
                b = blobs[bi]
                tracks[wid].append({"worm_id": wid, "frame": i,
                                    "time_s": i / FPS,
                                    "x_px": b["x_px"], "y_px": b["y_px"],
                                    "x_mm": b["x_px"] / PX_PER_MM,
                                    "y_mm": b["y_px"] / PX_PER_MM,
                                    "area_px": b["area_px"]})
                active[wid] = ((b["x_px"], b["y_px"]), i)
            for bi, b in enumerate(blobs):
                if bi in used_b:
                    continue
                wid = next_id
                next_id += 1
                tracks[wid] = [{"worm_id": wid, "frame": i, "time_s": i / FPS,
                                "x_px": b["x_px"], "y_px": b["y_px"],
                                "x_mm": b["x_px"] / PX_PER_MM,
                                "y_mm": b["y_px"] / PX_PER_MM,
                                "area_px": b["area_px"]}]
                active[wid] = ((b["x_px"], b["y_px"]), i)
            # Retire anything not seen recently.
            active = {w: v for w, v in active.items()
                      if (i - v[1]) / STEP <= MAX_GAP_STEPS}
            if (i // STEP) % 100 == 0:
                print(f"  frame {i:5d}  blobs={len(blobs):3d}  "
                      f"open={len(active):3d}  tracks={len(tracks):5d}")

    rows = [r for t in tracks.values() for r in t]
    lens = np.array([len(t) for t in tracks.values()])
    print(f"\n{len(tracks)} tracks, {len(rows)} detections "
          f"({n_det} raw blobs)")
    print(f"  samples per track: median {np.median(lens):.0f}, "
          f"max {lens.max()}, mean {lens.mean():.1f}")
    for thresh in (10, 60, 120):
        span = thresh * STEP
        print(f"  tracks lasting >= {span:4d} s: "
              f"{int((lens >= thresh).sum()):4d}")

    import csv
    with open(OUT, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["worm_id", "frame", "time_s",
                                           "x_px", "y_px",
                                           "x_mm", "y_mm",
                                           "area_px"])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
