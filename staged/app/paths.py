"""
lab_paths.py
===========
Small shared helper so the kinematics tools can find the RGBCaMP pipeline
modules (run_one, worm_kinetics, worm_rgbcamp_analysis, results_browser) no
matter which sensible folder layout the lab uses. Import it and call
ensure_pipeline_on_path() BEFORE importing any of those modules.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# folders to look in for the pipeline, relative to this file (the Lab tools root)
_CANDIDATES = [
    "RGBCaMP_Tracker/pipeline",
    "RGBCaMP_Tracker",
    "pipeline",
    ".",
    "../RGBCaMP_Tracker/pipeline",
    "../RGBCaMP_Tracker",
]

# a file that must exist in the pipeline folder for it to be the right one
_MARKER = "run_one.py"


def find_pipeline(base: Path | None = None) -> Path | None:
    base = base or Path(__file__).resolve().parent
    for rel in _CANDIDATES:
        cand = (base / rel).resolve()
        if (cand / _MARKER).exists():
            return cand
    return None


def ensure_pipeline_on_path(base: Path | None = None) -> Path | None:
    """Find the RGBCaMP pipeline folder and put it at the front of sys.path.
    Returns the folder, or None if it could not be found."""
    p = find_pipeline(base)
    if p is not None:
        sp = str(p)
        if sp not in sys.path:
            sys.path.insert(0, sp)
    return p
