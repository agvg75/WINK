"""Correction logging for the morphometry tools (myocyte sarcomeres, and
the muscle boundary/volume module's start/end surfaces, which reuses this
same pattern - see that module's own spec).

WHAT THIS DOES AND DOES NOT ENABLE. The automatic sarcomere detector is
classical signal processing (autocorrelation-based period estimation, then
relative peak-spacing rules), not a trained model - there is nothing to
"fine-tune" in the machine-learning sense yet. This log enables two things,
honestly separated. First, immediately: measuring the automatic detector's
real agreement rate against trained student judgment, to recalibrate the
FIXED PARAMETERS already exposed in myocyte_morphometry.py (the relative
spacing bounds, the minimum lag, the sarcomere-um sanity window) against
real disagreement patterns instead of guessing. Second, only once enough
examples accumulate (likely several hundred corrected profiles at minimum):
a labeled dataset (raw intensity profile in, human-confirmed peak positions
out) that COULD support training a learned peak detector as a future
replacement for the autocorrelation heuristic. Framing this to a student as
building a validation and calibration dataset now, with a learned model as
a possible later payoff, is more accurate than framing it as fine-tuning
something that exists today.

One JSON record per correction EVENT (not per row of the main results CSV),
appended to a dedicated JSONL file, one object per line so it can be read
incrementally and merged across sessions without a database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
from typing import Sequence
import uuid

CORRECTION_TYPES = {"EDITED", "MANUAL", "MANUAL_RECOUNT"}


def user_data_root() -> Path:
    """Same shared per-machine data root run_feedback.py uses, so this log
    lives alongside the rest of this tool's quality/feedback data rather
    than inventing a second convention."""
    base = os.environ.get("LOCALAPPDATA")
    if base:
        return Path(base) / "AGVGLab" / "quality"
    return Path.home() / ".agvg_lab_tools" / "quality"


def default_corrections_dir() -> Path:
    return user_data_root() / "morphometry_corrections"


@dataclass(frozen=True)
class DetectorOutput:
    """What the automatic detector produced, in the SAME coordinate space
    (profile sample index, px along the sampling line) as the human
    correction, so the two are directly comparable without a re-derivation."""
    peak_positions_px: Sequence[float]
    estimated_period_px: float
    min_spacing_px: float
    relative_bounds: tuple[float, float]  # (lo_rel, hi_rel) used by detect_band_peaks


@dataclass(frozen=True)
class HumanCorrection:
    peak_positions_px: Sequence[float]
    correction_type: str  # one of CORRECTION_TYPES

    def validate(self) -> "HumanCorrection":
        if self.correction_type not in CORRECTION_TYPES:
            raise ValueError(
                f"correction_type must be one of {sorted(CORRECTION_TYPES)}")
        return self


def agreement_summary(auto_positions: Sequence[float],
                       human_positions: Sequence[float],
                       tolerance_px: float) -> dict:
    """Match auto peaks to human peaks within `tolerance_px` (typically a
    fraction of the estimated period), greedily by nearest distance.

    Returns matched/missed/spurious counts. This is the raw record's own
    stated purpose realized as an immediately queryable number - the raw
    positions remain the source of truth if the matching definition ever
    needs to change; this summary is a convenience computed once at write
    time, not a replacement for them.
      matched   = an auto peak with a human peak within tolerance
      missed    = a human peak with no auto peak within tolerance (the
                  detector missed a real band)
      spurious  = an auto peak with no human peak within tolerance (the
                  detector invented a band)
    """
    auto = sorted(float(p) for p in auto_positions)
    human = sorted(float(p) for p in human_positions)
    human_used = [False] * len(human)
    matched = 0
    spurious = 0
    for a in auto:
        best_j = -1; best_d = tolerance_px
        for j, h in enumerate(human):
            if human_used[j]:
                continue
            d = abs(a - h)
            if d <= best_d:
                best_d = d; best_j = j
        if best_j >= 0:
            human_used[best_j] = True
            matched += 1
        else:
            spurious += 1
    missed = human_used.count(False)
    return {
        "n_auto_peaks": len(auto), "n_human_peaks": len(human),
        "matched": matched, "missed": missed, "spurious": spurious,
        "tolerance_px": tolerance_px,
    }


@dataclass
class CorrectionLog:
    root: Path = field(default_factory=default_corrections_dir)

    def __post_init__(self):
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _log_path(self, when: date | None = None) -> Path:
        when = when or date.today()
        return self.root / f"{when.isoformat()}_corrections.jsonl"

    def record(
        self, *, myocyte_id, worm_id: str, genotype: str, day, region: str,
        raw_profile: Sequence[float], line_x1: float, line_y1: float,
        line_x2: float, line_y2: float, line_width_px: float, um_per_px: float,
        detector: DetectorOutput, human: HumanCorrection,
        student_id: str = "", note: str = "",
    ) -> Path:
        human.validate()
        tolerance_px = max(1.0, 0.3 * detector.estimated_period_px)
        summary = agreement_summary(
            detector.peak_positions_px, human.peak_positions_px, tolerance_px)
        payload = {
            "schema_version": 1,
            "record_id": uuid.uuid4().hex,
            "recorded_utc": datetime.now(timezone.utc).isoformat(),
            "myocyte_id": myocyte_id, "worm_id": str(worm_id),
            "genotype": genotype, "day": day, "region": region,
            "raw_profile": [float(v) for v in raw_profile],
            "line_endpoints_px": {
                "x1": float(line_x1), "y1": float(line_y1),
                "x2": float(line_x2), "y2": float(line_y2)},
            "line_width_px": float(line_width_px),
            "um_per_px": float(um_per_px),
            "auto": {
                "peak_positions_px": [float(p) for p in detector.peak_positions_px],
                "estimated_period_px": float(detector.estimated_period_px),
                "min_spacing_px": float(detector.min_spacing_px),
                "relative_bounds": list(detector.relative_bounds),
            },
            "human": {
                "peak_positions_px": [float(p) for p in human.peak_positions_px],
                "correction_type": human.correction_type,
            },
            "agreement": summary,
            "student_id": student_id, "note": note,
        }
        path = self._log_path()
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload) + "\n")
        return path

    def read_all(self) -> list[dict]:
        """Read every correction record across every dated log file in
        this root, for offline agreement-rate analysis."""
        rows = []
        for log_path in sorted(self.root.glob("*_corrections.jsonl")):
            with log_path.open("r", encoding="utf-8") as stream:
                for line in stream:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        return rows
