"""Fiji-free RGBCaMP extraction: curated geometry in, the same CSV out.

WHAT THIS REPLACES. `WormRGBCaMPMap_v1.java` tracked the worm, fitted a midline,
cut it into hemisegments and wrote one long-format CSV. Everything downstream of
that CSV has always been Python. This writes the same CSV.

WHAT IT DELIBERATELY DOES NOT DO IS TRACK. The DIC tracker already does that,
and more importantly it has a review layer where a person fixes the frames it
got wrong - which is the part no automatic method replaces. So this consumes a
SAVED TRACKER SESSION: the geometry that comes in has already been corrected by
hand, and re-deriving it here would throw that work away and quietly disagree
with the kinematics the same recording is reported with.

That split is the point. Geometry is curated once and measured many times.

HEAD ORIENTATION IS INHERITED, NOT RE-DECIDED. The session's midline is already
head-first - the tracker anchors it on the user's head click and propagates it.
`tools/head_tail` is used only as a CHECK, and disagreement is reported rather
than acted on: the person who clicked the head was looking at the animal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "app"))

import hemisegments as hs                       # noqa: E402

N_SEG = hs.N_SEG


class ExtractError(Exception):
    """Refusals that name the consequence."""


def identify_channels(folder, pattern="ch*"):
    """Work out which chNN folder is which fluorophore, by looking.

    DO NOT ASSUME THE ORDER. On this lab's acquisitions the mapping is
    ch00=blue, ch01=green, ch02=red, ch03=DIC - but that is a fact about the
    microscope's configuration on a given day, not about the file names, and
    naming a channel wrongly silently attributes one fluorophore's signal to
    another. Every downstream measure would still compute, and the calcium
    trace would be the wrong indicator.

    Each frame is written as an RGB image with only ONE plane populated, so the
    fluorophore is readable directly. DIC is the one where all three planes are
    identical - it is greyscale transmitted light, not a fluorophore, and does
    not belong in a fluorescence panel.

    THE PARITY CHECK WILL NOT CATCH A MISLABELLING. Anterior-posterior profiles
    agreed at r = 0.987 between this extractor and the Fiji plugin while the
    channels were shifted by one, because the profile is dominated by worm
    thickness, which every channel shares. Geometry parity and channel identity
    are separate claims and need separate evidence.
    """
    import tifffile
    folder = Path(folder)
    out = {"channels": {}, "dic": None, "unassigned": []}
    for sub in sorted(folder.glob(pattern)):
        if not sub.is_dir():
            continue
        files = sorted(sub.glob("*.tif")) or sorted(sub.glob("*.tiff"))
        if not files:
            continue
        a = np.asarray(tifffile.imread(str(files[0])), dtype=float)
        if a.ndim != 3 or a.shape[2] < 3:
            out["unassigned"].append({"folder": sub.name,
                                      "why": f"not an RGB image ({a.shape})"})
            continue
        planes = [a[..., k] for k in range(3)]
        if all(np.allclose(planes[0], p) for p in planes[1:]):
            out["dic"] = {"folder": sub.name, "n_files": len(files),
                          "why": "all three planes identical - transmitted light"}
            continue
        means = [float(p.mean()) for p in planes]
        live = int(np.argmax(means))
        if means[live] <= 0:
            out["unassigned"].append({"folder": sub.name, "why": "no signal"})
            continue
        name = ("red", "green", "blue")[live]
        out["channels"][name] = {"folder": sub.name, "n_files": len(files),
                                 "plane": live,
                                 "plane_means": [round(m, 3) for m in means]}
    out["mapping"] = {v["folder"]: k for k, v in out["channels"].items()}
    if out["dic"]:
        out["mapping"][out["dic"]["folder"]] = "DIC"
    out["detected_not_assumed"] = (
        "Read from the pixel data, not from the folder order. The order is a "
        "fact about the microscope on the day, and a wrong guess attributes "
        "one fluorophore's signal to another with nothing downstream to "
        "notice.")
    return out


def load_session(path):
    """Read a saved tracker session and return its per-frame states."""
    import json
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    states = doc.get("states")
    if not states:
        raise ExtractError(
            f"{path} contains no per-frame states. Track and review the "
            f"recording first - this tool measures curated geometry, it does "
            f"not produce it.")
    for st in states:
        if st is None:
            continue
        for key in ("pts", "path", "curv", "seg_widths"):
            if st.get(key) is not None:
                st[key] = np.asarray(st[key], float)
    return doc, states


def frame_rows(state, masks_i, channels_i, frame_index, fps, um_per_px,
               worm_id, condition, n_seg=N_SEG, ventral_sign=None,
               dorsal_known=False, src8bit=0):
    """The rows for one frame, or a single skip row when geometry is missing.

    A frame with no usable spine produces ONE row carrying skip=1 rather than
    nothing at all. A silently absent frame is indistinguishable from a frame
    that was never recorded, and every rate downstream would be computed over a
    denominator that quietly shrank.
    """
    base = {"frame": int(frame_index),
            "time_s": round(frame_index / float(fps), 6),
            "worm_id": worm_id, "condition": condition,
            "fps": float(fps), "um_per_px": float(um_per_px),
            "src8bit": int(src8bit)}

    spine = None if state is None else state.get("pts")
    if spine is None or np.asarray(spine).ndim != 2 or len(spine) < 3 \
            or masks_i is None or not np.any(masks_i):
        return [dict(base, skip=1, found=0, segment=-1, hemisegment="",
                     needs_help=1,
                     body_provenance=(state or {}).get("provenance", "missing"),
                     skip_reason="no usable midline or mask for this frame")]

    out = hs.extract_frame(channels_i, masks_i, np.asarray(spine, float),
                           n_seg=n_seg, ventral_sign=ventral_sign,
                           dorsal_known=dorsal_known, um_per_px=um_per_px)
    rows = []
    for r in out["rows"]:
        row = dict(base, skip=0, found=1, **r)
        row["needs_help"] = int((state or {}).get("needs_help", 0))
        row["body_provenance"] = (state or {}).get("provenance", "measured")
        # dorsal_label mirrors hemisegment only when the side is actually known
        row["dorsal_label"] = r["hemisegment"] if out["dorsal_known"] else ""
        rows.append(row)
    return rows


def extract(states, masks, channels, fps, um_per_px, worm_id="worm",
            condition="", n_seg=N_SEG, ventral_sign=None, dorsal_known=False,
            src8bit=0, progress=None):
    """Every frame of one recording, as a list of dict rows.

    `masks` is a sequence of 2-D boolean arrays, one per frame; `channels` a
    sequence of {name: 2-D image} dicts. Both must be as long as `states`, and
    that is checked: a length mismatch would silently pair each frame's geometry
    with a different frame's fluorescence, which produces a complete, plausible
    table describing nothing.
    """
    n = len(states)
    if len(masks) != n or len(channels) != n:
        raise ExtractError(
            f"{n} states, {len(masks)} masks, {len(channels)} channel frames. "
            f"These must correspond one to one - a mismatch pairs each frame's "
            f"geometry with another frame's fluorescence and yields a complete, "
            f"plausible table that describes nothing.")
    rows = []
    for i in range(n):
        rows.extend(frame_rows(states[i], masks[i], channels[i], i, fps,
                               um_per_px, worm_id, condition, n_seg,
                               ventral_sign, dorsal_known, src8bit))
        if progress and i % 25 == 0:
            progress(i, n)
    return rows


def check_head_orientation(states, masks=None, images=None, um_per_px=None):
    """Compare the session's head end against what head_tail would decide.

    Reported, never applied. The session's orientation was set by a person
    looking at the animal; this is a second opinion, and a second opinion that
    silently overrode the first would be worse than no check at all.
    """
    import head_tail as ht
    spines = [None if s is None else s.get("pts") for s in states]
    spines = [None if s is None else np.asarray(s, float) for s in spines]
    usable = [s for s in spines if s is not None and len(s) >= 3]
    if len(usable) < 10:
        return {"checked": False,
                "why": f"only {len(usable)} frames carry a midline."}
    try:
        call = ht.identify_head(usable, masks=masks, images=images,
                               um_per_px=um_per_px)
    except ht.HeadTailError as exc:
        return {"checked": False, "why": str(exc)}
    return {
        "checked": True,
        "session_says": "index 0 is the head (tracker convention)",
        "independent_call": call.get("head_end"),
        "confidence": call.get("confidence"),
        "agrees": call.get("head_end") == 0,
        "cues": call.get("cues"),
        "advisory_only": (
            "This is reported, not applied. The session's head was set by "
            "someone looking at the animal; if the two disagree, look at the "
            "recording rather than trusting either automatically."),
    }


COLUMN_ORDER = [
    "frame", "time_s", "worm_id", "condition", "fps", "um_per_px", "src8bit",
    "skip", "found", "needs_help", "body_provenance", "skip_reason",
    "segment", "hemisegment", "side_sign", "dorsal_label", "dorsal_known",
    "roi_area_px", "seg_angle_deg", "seg_curv_deg", "seg_length_px",
]


def to_frame(rows, channels=("blue", "green", "red")):
    """Rows as a DataFrame with the contract's column order first."""
    import pandas as pd
    df = pd.DataFrame(rows)
    stat_cols = [f"{c}_{s}" for c in channels
                 for s in ("min", "p10", "mean", "median", "p90", "max")
                 if f"{c}_{s}" in df.columns]
    lead = [c for c in COLUMN_ORDER if c in df.columns]
    rest = [c for c in df.columns if c not in lead and c not in stat_cols]
    return df[lead + stat_cols + rest]


def compare_with_fiji(python_rows, fiji_csv, channel="green",
                      stats=("mean", "max", "min")):
    """Parity against a Fiji extraction of the same recording.

    THE ONLY REAL TEST OF THIS MIGRATION. Everything else checks that the new
    code is self-consistent; this checks that it measures the same animal.

    Perfect agreement is not expected and would be suspicious: the segment
    boundaries, the mask and the ROI construction all differ in detail. What
    matters is that per-segment profiles have the same SHAPE and that
    anterior-posterior gradients do not reverse - a correlation near zero, or a
    negative one, means the head is on the wrong end or the segments are
    numbered backwards.
    """
    import pandas as pd
    fj = pd.read_csv(fiji_csv)
    py = pd.DataFrame(python_rows)
    fj = fj[(fj.get("skip", 0) == 0) & (fj.get("found", 1) == 1)]
    py = py[(py["skip"] == 0) & (py["found"] == 1)]
    out = {"n_fiji_rows": len(fj), "n_python_rows": len(py)}
    for st in stats:
        col = f"{channel}_{st}"
        if col not in fj.columns or col not in py.columns:
            out[st] = {"compared": False, "why": f"{col} missing from one side"}
            continue
        a = fj.groupby("segment")[col].median()
        b = py.groupby("segment")[col].median()
        common = a.index.intersection(b.index)
        if len(common) < 5:
            out[st] = {"compared": False, "why": "fewer than 5 shared segments"}
            continue
        r = float(np.corrcoef(a[common], b[common])[0, 1])
        out[st] = {
            "compared": True, "n_segments": int(len(common)),
            "profile_r": round(r, 4),
            "verdict": ("anterior-posterior profiles agree in shape"
                        if r > 0.7 else
                        "profiles agree weakly - check the ROI construction"
                        if r > 0.3 else
                        "PROFILES DISAGREE OR ARE REVERSED. A negative or "
                        "near-zero correlation usually means the head is on "
                        "the wrong end or the segments are numbered backwards, "
                        "not that the measurement is noisy."),
        }
    out["note"] = ("Exact agreement is not the target and would be suspicious. "
                   "Segment boundaries, masks and ROI construction all differ "
                   "in detail; profile SHAPE and direction are what must match.")
    return out
