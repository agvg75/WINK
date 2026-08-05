"""Inspect a whole folder of recordings at once, worst first.

The three pieces built separately, joined: `kymogram` renders one recording,
`contact_sheet` ranks many, and `implausible` finds the sections a person
should actually look at. This is the thing that runs over an archive.

WHAT IT IS FOR, in Andres's words: not one file at a time. A recording survives
one bad frame; what has to surface from sixteen terabytes is the recording with
a bad SECTION, a head flip, or a break in the continuity of the wave - and it
has to surface with a hundred animals on one screen.

THE RANKING DOES THE WORK THE EYE CANNOT AT THUMBNAIL SIZE. The sheet is
ordered worst-first and the thumbnail only has to confirm or dismiss what the
score proposed. Scanning a hundred unordered thumbnails finds the fourth-worst
by luck.

NOTHING IS EXCLUDED BY THE SCORE. It is a reading order. A recording that
scores zero is still on the sheet, the components are reported so a rank can be
traced to its cause, and every recording appears in the summary whether or not
anyone looked at it.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
for sub in ("app", "tools", "tools/rgbcamp"):
    p = str(ROOT / sub)
    if p not in sys.path:
        sys.path.insert(0, p)


class BatchError(Exception):
    """Refusals that name the consequence."""


def discover_csv(root, pattern="WormRGBCaMP_extracted.csv"):
    """Find recordings by their EXTRACTED CSV rather than their sidecar.

    The archive turned out to have 36 acquired recordings and exactly ONE
    geometry sidecar, so requiring a sidecar left nothing to batch. The
    extracted CSV carries segment, frame and seg_curv_deg, which is all a
    curvature grid needs - so ranking works on everything already put
    through the extractor, which is the population that actually exists.
    """
    root = Path(root)
    if not root.exists():
        raise BatchError(f"{root} does not exist.")
    return [{"folder": str(c.parent), "csv": str(c),
             "name": c.parent.name, "usable": True}
            for c in sorted(root.rglob(pattern))]


def curvature_from_csv(csv_path, n_seg=24, curv_col="seg_curv_deg"):
    """Curvature grid straight from an extracted CSV.

    Frames are placed by INDEX, so a skipped frame leaves a gap rather
    than sliding everything after it leftward - the same rule the kymogram
    follows, and for the same reason.
    """
    import csv as _csv
    frames, cells = set(), []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in _csv.DictReader(fh):
            try:
                if int(float(row.get("skip") or 0)) or not int(float(row.get("found") or 1)):
                    continue
                f, sg = int(float(row["frame"])), int(float(row["segment"]))
                v = row.get(curv_col)
                if v in (None, "", "NA", "nan"):
                    continue
                frames.add(f); cells.append((sg, f, float(v)))
            except (KeyError, ValueError, TypeError):
                continue
    if not cells:
        raise BatchError(f"{csv_path} yielded no usable curvature rows.")
    n = max(frames) + 1
    grid = np.full((n_seg, n), np.nan)
    for sg, f, v in cells:
        if 0 <= sg < n_seg:
            grid[sg, f] = v
    return grid


def discover(root, pattern="*_geometry.json", require_channels=True):
    """Find recordings under `root` that can be inspected without re-tracking.

    A recording qualifies when it carries a geometry sidecar - midline and
    outline per frame - because that is curated geometry and re-deriving it
    would throw away the correction work and disagree with the kinematics the
    same recording is reported with.
    """
    root = Path(root)
    if not root.exists():
        raise BatchError(f"{root} does not exist.")
    out = []
    for side in sorted(root.rglob(pattern)):
        rec = side.parent
        chans = sorted(d.name for d in rec.glob("ch*") if d.is_dir())
        if require_channels and not chans:
            out.append({"folder": str(rec), "sidecar": str(side),
                        "channels": [], "usable": False,
                        "why": "no chNN channel folders beside the sidecar"})
            continue
        out.append({"folder": str(rec), "sidecar": str(side),
                    "channels": chans, "usable": True})
    return out


def curvature_grid(sidecar, n_seg=24, max_frames=None):
    """A (segment x frame) curvature grid straight from the sidecar.

    Deliberately does NOT load the image channels. Ranking a whole archive
    needs geometry only, and reading three TIFFs per frame to decide whether a
    recording is worth opening would make the triage cost as much as the
    analysis it was meant to save.
    """
    import hemisegments as hs
    doc = json.loads(Path(sidecar).read_text(encoding="utf-8-sig"))
    frames = doc.get("frames") or []
    if not frames:
        raise BatchError(f"{sidecar} carries no frames.")
    n = len(frames) if max_frames is None else min(len(frames), int(max_frames))
    grid = np.full((n_seg, n), np.nan)
    for i in range(n):
        fr = frames[i]
        if not fr.get("found") or fr.get("skip"):
            continue
        mid = fr.get("midline")
        if not mid or len(mid) < 4:
            continue
        try:
            kin = hs.segment_kinematics(np.asarray(mid, float), n_seg=n_seg)
        except Exception:
            continue
        for r in kin:
            v = r.get("seg_curv_deg")
            if v is not None:
                grid[r["segment"], i] = v
    return grid


def run(root, n_seg=24, max_frames=None, absolute_min=25.0, progress=print,
        source="csv"):
    """Rank every discovered recording and locate the sections to review.

     is "csv" by default because that is the population that exists:
    the archive holds 36 acquired recordings and one geometry sidecar, so
    requiring a sidecar would rank a single animal. "sidecar" is kept for the
    recordings that have curated geometry, which is the better input when it
    is available.
    """
    import contact_sheet as cs
    import implausible as im

    if source == "csv":
        usable = discover_csv(root)
        loader = lambda f: curvature_from_csv(f["csv"], n_seg)
        need = "an extracted CSV carrying seg_curv_deg"
    else:
        usable = [f for f in discover(root) if f["usable"]]
        loader = lambda f: curvature_grid(f["sidecar"], n_seg, max_frames)
        need = "a geometry sidecar"
    if not usable:
        raise BatchError(
            f"No inspectable recordings under {root}. Each needs {need}, so a "
            f"folder without one has nothing to rank.")

    grids, failed = {}, []
    for i, f in enumerate(usable):
        name = f.get("name") or Path(f["folder"]).name
        try:
            grids[name] = loader(f)
        except Exception as exc:
            failed.append({"recording": name, "why": str(exc)})
        if progress:
            progress(f"  {i + 1}/{len(usable)}  {name[:52]}")

    if not grids:
        raise BatchError(
            f"{len(usable)} recordings were found but none yielded a "
            f"curvature grid. Check that the sidecars carry midlines.")

    ranked = cs.rank(grids)
    queue = []
    for row in ranked:
        try:
            q = im.review_queue({"curvature": grids[row["name"]]},
                                absolute_min=absolute_min)
        except Exception:
            continue
        for s in q["sections"]:
            if "peak_z" in s:
                queue.append({"recording": row["name"], **s})
    queue.sort(key=lambda s: -s["peak_z"])

    return {
        "root": str(root),
        "n_usable": len(usable),
        "n_ranked": len(ranked), "n_failed": len(failed),
        "failed": failed,
        "ranked": ranked,
        "grids": grids,
        "sections": queue,
        "n_sections": len(queue),
        "worst": [r["name"] for r in ranked[:5]],
        "nothing_excluded": (
            "The score is a reading order. Every recording appears in this "
            "summary whether or not it was looked at, and the components are "
            "reported so a rank can be traced to what caused it."),
    }


def report(result, top=12):
    """A text summary. What a person reads before opening anything."""
    L = [f"{result['n_ranked']} recordings ranked from {result['root']}",
         ""]
    if result["n_failed"]:
        L.append(f"{result['n_failed']} could not be read:")
        for f in result["failed"][:5]:
            L.append(f"    {f['recording']}: {f['why'][:70]}")
        L.append("")
    L.append(f"{'recording':44s} {'score':>6}  {'frames':>6}  worst component")
    L.append("-" * 88)
    for r in result["ranked"][:top]:
        L.append(f"{r['name'][:44]:44s} {r['score']:6.2f}  "
                 f"{r.get('n_frames', 0):6d}  {r.get('worst', '')}")
    if len(result["ranked"]) > top:
        L.append(f"... and {len(result['ranked']) - top} more, all scoring "
                 f"below {result['ranked'][top]['score']:.2f}")
    L += ["", f"{result['n_sections']} sections flagged for review"]
    for s in result["sections"][:8]:
        L.append(f"    {s['recording'][:34]:34s} frames "
                 f"{s['start_frame']}-{s['end_frame']}  "
                 f"segments {s['segments'][:6]}  z={s['peak_z']}")
    return "\n".join(L)


def main(argv=None):                                       # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("root", help="folder to search for recordings")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--sheet", action="store_true",
                    help="draw the ranked contact sheet")
    ap.add_argument("--out", default=None, help="write the sheet here")
    a = ap.parse_args(argv)

    res = run(a.root, max_frames=a.max_frames)
    print(report(res))
    if a.sheet or a.out:
        import matplotlib
        if a.out:
            matplotlib.use("Agg")
        import contact_sheet as cs
        fig, _ = cs.sheet(res["grids"], columns=4,
                          title=f"{res['n_ranked']} recordings, worst first")
        if a.out:
            fig.savefig(a.out, dpi=140, facecolor="white")
            print(f"\nwrote {a.out}")
        else:
            import matplotlib.pyplot as plt
            plt.show()
    return 0


if __name__ == "__main__":                                 # pragma: no cover
    sys.exit(main())
