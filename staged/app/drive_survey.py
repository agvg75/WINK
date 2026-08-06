"""Survey a lab drive one layer at a time, without ever opening a file.

Andres: a previous attempt crashed because the search tried to inspect each
gigantic image, across millions of them. He wants something hierarchical -
counting files and naming types, nothing heavier - to find out how many
experiments there are and what they are, from their names, so the grant
analysis can be structured.

NOTHING IS OPENED. Everything here comes from the directory entry itself:
name, whether it is a directory, size and modification time. `os.scandir`
carries those on Windows without a second call, so a folder of ten thousand
2 GB stacks costs the same as a folder of ten thousand empty files. No
decoding, no headers, no hashing, no thumbnails. That is the whole reason this
exists.

LAYER BY LAYER, WITH THE NEXT LAYER PRICED BEFORE IT IS RUN. A survey that
takes twenty minutes on a network share and then dies has told you nothing.
So each layer reports what it found AND measures how long it took per entry,
then samples a handful of the next layer's directories to estimate what going
deeper would cost. The estimate is measured on the actual share, because a
guess about L: made from local-disk speed is wrong by an order of magnitude.

EVERY LAYER IS WRITTEN TO DISK AS IT COMPLETES. A crash loses at most the
layer in progress, and the next run resumes from what is already there.

THE SAMPLE IS A SAMPLE AND IS LABELLED AS ONE. Estimating a million files from
five directories is a projection, not a measurement, and the spread across
those five is reported so an obviously lopsided tree is visible rather than
averaged away.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

# Directories that are never experiments and cost a lot to walk.
SKIP_NAMES = {"$RECYCLE.BIN", "System Volume Information", ".git",
              "__pycache__", ".claude", "node_modules", ".venv"}

# Extension families, for saying WHAT a folder holds without opening anything.
FAMILIES = {
    "confocal": {".lif", ".czi", ".nd2", ".oib", ".oif", ".lsm", ".ims"},
    "image_stack": {".tif", ".tiff", ".ome.tif"},
    "image": {".png", ".jpg", ".jpeg", ".bmp", ".gif"},
    "movie": {".avi", ".mp4", ".mov", ".mkv", ".wmv", ".m4v"},
    "table": {".csv", ".tsv", ".xlsx", ".xls", ".xlsb"},
    "document": {".doc", ".docx", ".pdf", ".txt", ".md", ".rtf"},
    "figure": {".svg", ".eps", ".ai", ".pzfx", ".jnb", ".spw"},
    "code": {".py", ".ijm", ".m", ".r", ".ipynb", ".bat"},
    "archive": {".zip", ".7z", ".rar", ".gz"},
}
EXT_TO_FAMILY = {e: fam for fam, exts in FAMILIES.items() for e in exts}


class SurveyError(Exception):
    """Refusals that name the consequence."""


def _family(name):
    low = name.lower()
    for ext, fam in EXT_TO_FAMILY.items():
        if low.endswith(ext):
            return fam
    return "other"


def scan_one(path, *, follow_links=False):
    """One directory, from its entries alone. Never opens a file.

    Returns counts, an extension histogram, total bytes and the subdirectory
    names - everything needed to decide whether to go deeper, and nothing that
    requires reading content.
    """
    p = Path(path)
    subdirs, n_files, total_bytes = [], 0, 0
    exts, families = {}, {}
    newest = oldest = None
    errors = []
    try:
        with os.scandir(p) as it:
            for entry in it:
                try:
                    if entry.is_dir(follow_symlinks=follow_links):
                        if entry.name not in SKIP_NAMES:
                            subdirs.append(entry.name)
                        continue
                    n_files += 1
                    st = entry.stat(follow_symlinks=False)
                    total_bytes += st.st_size
                    mt = st.st_mtime
                    newest = mt if newest is None else max(newest, mt)
                    oldest = mt if oldest is None else min(oldest, mt)
                    ext = os.path.splitext(entry.name)[1].lower()
                    exts[ext] = exts.get(ext, 0) + 1
                    fam = _family(entry.name)
                    families[fam] = families.get(fam, 0) + 1
                except OSError as exc:
                    errors.append(f"{entry.name}: {exc}")
    except OSError as exc:
        return {"path": str(p), "unreadable": str(exc), "n_files": 0,
                "n_subdirs": 0, "subdirs": [], "extensions": {},
                "families": {}, "total_bytes": 0}
    return {
        "path": str(p), "name": p.name,
        "n_files": n_files, "n_subdirs": len(subdirs), "subdirs": subdirs,
        "extensions": dict(sorted(exts.items(), key=lambda kv: -kv[1])),
        "families": dict(sorted(families.items(), key=lambda kv: -kv[1])),
        "total_bytes": total_bytes,
        "newest_mtime": newest, "oldest_mtime": oldest,
        "entry_errors": errors[:5],
        "n_entry_errors": len(errors),
    }


def survey_layer(roots, *, follow_links=False):
    """Scan exactly these directories - one layer, no recursion.

    Timing is measured here rather than assumed, because the same code on a
    local disk and on a network share differs by an order of magnitude and the
    estimate for the next layer is only useful if it comes from this one.
    """
    t0 = time.perf_counter()
    results, entries = [], 0
    for r in roots:
        res = scan_one(r, follow_links=follow_links)
        results.append(res)
        entries += res.get("n_files", 0) + res.get("n_subdirs", 0)
    elapsed = time.perf_counter() - t0
    return {
        "results": results,
        "n_dirs_scanned": len(results),
        "n_entries_seen": entries,
        "elapsed_s": round(elapsed, 3),
        "seconds_per_dir": round(elapsed / max(len(results), 1), 4),
        "entries_per_s": round(entries / elapsed, 1) if elapsed > 0 else None,
    }


def estimate_next_layer(layer, *, sample=5, follow_links=False):
    """Price the next layer by SAMPLING it, not by guessing.

    Scans a few of the next layer's directories, measures how long they took
    and how many children they have, and projects. Labelled a projection
    throughout, with the spread across the sample reported - a tree with one
    enormous folder and four small ones averages to something that describes
    none of them.
    """
    next_dirs = [str(Path(r["path"]) / s)
                 for r in layer["results"] for s in r.get("subdirs", [])]
    if not next_dirs:
        return {"n_dirs_next": 0,
                "why": "Nothing below this layer - the survey is complete here."}

    step = max(1, len(next_dirs) // max(sample, 1))
    picked = next_dirs[::step][:sample]
    probe = survey_layer(picked, follow_links=follow_links)

    per_dir = probe["seconds_per_dir"]
    child_counts = [r.get("n_subdirs", 0) for r in probe["results"]]
    file_counts = [r.get("n_files", 0) for r in probe["results"]]
    est_s = per_dir * len(next_dirs)
    out = {
        "n_dirs_next": len(next_dirs),
        "sampled": len(picked),
        "seconds_per_dir_measured": per_dir,
        "estimated_seconds": round(est_s, 1),
        "estimated_minutes": round(est_s / 60.0, 1),
        "sample_files_per_dir": file_counts,
        "sample_subdirs_per_dir": child_counts,
        "projected_dirs_two_layers_down": (
            int(sum(child_counts) / max(len(child_counts), 1) * len(next_dirs))),
        "is_a_projection": (
            f"Timed on {len(picked)} of {len(next_dirs)} directories on this "
            f"actual drive. It is a projection, not a measurement, and an "
            f"uneven tree will beat it."),
    }
    if file_counts and max(file_counts) > 0:
        spread = max(file_counts) / max(min(file_counts), 1)
        out["sample_spread"] = round(spread, 1)
        if spread > 20:
            out["warning"] = (
                f"The sampled directories differ by {spread:.0f}x in file "
                f"count ({min(file_counts)} to {max(file_counts)}). The "
                f"average describes none of them, so the estimate above could "
                f"be out by a similar factor. Scan the big ones separately.")
    return out


def plan(layer, estimate, *, budget_minutes=5.0):
    """Should the next layer be run now, in pieces, or not at all?"""
    if not estimate.get("n_dirs_next"):
        return {"recommend": "stop", "why": estimate.get("why", "nothing below")}
    mins = estimate.get("estimated_minutes", 0)
    if mins <= budget_minutes:
        return {"recommend": "go",
                "why": (f"About {mins:.1f} min for "
                        f"{estimate['n_dirs_next']} directories, within the "
                        f"{budget_minutes:.0f} min budget.")}
    return {
        "recommend": "split",
        "why": (f"About {mins:.1f} min for {estimate['n_dirs_next']} "
                f"directories, over the {budget_minutes:.0f} min budget. Run "
                f"it a branch at a time so a crash costs one branch, not the "
                f"whole layer - which is what happened last time."),
        "suggested_batches": max(2, int(mins / max(budget_minutes, 0.1)) + 1),
    }


def save(layer, path):
    """Write a layer as soon as it completes, so a crash costs one layer."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(layer, indent=1, default=str), encoding="utf-8")
    return str(p)


def load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return None
    except json.JSONDecodeError as exc:
        raise SurveyError(
            f"{path} is not valid JSON ({exc}). Treating a half-written layer "
            f"as absent would silently re-scan work that is already done; "
            f"treating it as complete would skip directories that were never "
            f"reached.")


def describe_layer(layer, *, top=25):
    """One readable table per layer, sorted by what is worth looking at."""
    rows = sorted(layer["results"],
                  key=lambda r: -(r.get("n_files", 0) + r.get("n_subdirs", 0)))
    L = [f"{layer['n_dirs_scanned']} directories, "
         f"{layer['n_entries_seen']} entries, "
         f"{layer['elapsed_s']}s "
         f"({layer['entries_per_s']} entries/s)", ""]
    L.append(f"{'folder':44s} {'subdirs':>8s} {'files':>7s} {'GB':>8s}  holds")
    L.append("-" * 100)
    for r in rows[:top]:
        if r.get("unreadable"):
            L.append(f"{r['path'][-44:]:44s}    UNREADABLE: {r['unreadable'][:40]}")
            continue
        fam = ", ".join(f"{k} {v}" for k, v in list(r["families"].items())[:3])
        L.append(f"{r.get('name', r['path'])[-44:]:44s} "
                 f"{r['n_subdirs']:8d} {r['n_files']:7d} "
                 f"{r['total_bytes'] / 1e9:8.1f}  {fam}")
    if len(rows) > top:
        L.append(f"... and {len(rows) - top} more")
    return "\n".join(L)
