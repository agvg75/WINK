"""What each golden record actually runs. One callable per entry.

ENTRY #1 IS THE SIX FROZEN RECORDINGS, which is what closes the outstanding
tracker regression gate. That gate was never a piece of engineering - it was
"someone must run the six and record what comes out". Baselining IS running
them, so the gate closes by being done rather than by being argued about.

Each callable returns a flat dict of outputs. Keys in golden.MEASURED_KEYS
block on change; unclassified keys also block, because a new number nobody
has classified might be a measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STAGED = HERE.parents[1]
sys.path.insert(0, str(STAGED / "app"))

CORPUS = Path(r"L:\10_AGVG LAB\Lab Tools\repro_corpus")

# The frozen development set, confirmed by Andres on 6 Aug 2026 as
# 05_Proprioception\pezo-1 CRISPR mutants.
FROZEN_SIX = ("41921_cop1367", "41921_cop1553", "42821_AG406",
              "5121_AG405", "CRISPR mutants food density",
              "pezo CRISPR mutants")


def _frames(folder):
    return sorted(p for p in Path(folder).rglob("*")
                  if p.is_file() and p.suffix.lower() in (".tif", ".tiff"))


def frozen_six_sessions():
    """Session structure across the six. READS THE FROZEN LISTING, not the drive.

    My first draft walked the live folders. If anyone adds, renames or moves
    one file the baseline shifts, and the next diff reports drift that never
    happened - the record would measure the drive rather than the pipeline.
    """
    sys.path.insert(0, str(STAGED / "tools" / "acquisition_pass"))
    import session_structure as ss
    import json

    clip = CORPUS / "pezo1_frozen_six"
    manifest = json.loads((clip / "CORPUS.json").read_text(encoding="utf-8"))
    total_sessions = total_frames = bracketed = 0
    per_folder = {}
    for folder, info in sorted(manifest["folders"].items()):
        listing = clip / info.get("listing", "")
        if not listing.is_file():
            per_folder[folder] = "MISSING"
            continue
        by_dir = {}
        for line in listing.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rel = line.split("	")[0]
            parent = str(Path(rel).parent)
            by_dir.setdefault(parent, []).append(Path(rel).name)
        rows = []
        for parent, names in by_dir.items():
            if len(names) >= 20:
                rows.extend(ss.analyse(f"{folder}/{parent}", names))
        per_folder[folder] = len(rows)
        total_sessions += len(rows)
        total_frames += sum(r["frames"] for r in rows)
        bracketed += sum(1 for r in rows if r["rate_measured"] == "yes")
    return {
        "n_folders_present": sum(1 for v in per_folder.values()
                                 if isinstance(v, int)),
        "n_sessions": total_sessions,
        "n_frames": total_frames,
        "n_bracketed": bracketed,
        "per_folder": per_folder,
    }


ENTRIES = {
    "frozen_six_sessions": frozen_six_sessions,
}
