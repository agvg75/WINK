"""
run_one_kinematics.py
=====================
Kinematics-only analysis of ONE transmitted-light recording CSV, for the
standalone student tool. It reuses run_one.py's loaders and its AnalysisResult
object, but runs ONLY the posture analyses (no calcium), so a transmitted-light
export with no fluorescence columns produces a clean result instead of a pile
of failed calcium attempts.

    python run_one_kinematics.py path/to/recording.csv

Writes <recording_stem>_kinematics_output/ next to the input, containing:
  qc_report.json
  undulation_descriptors.csv   body-wave frequency, speed, direction,
                               wavelength, bend amplitude
  locomotion_summary.csv       forward/backward fraction, reversals, signed
                               crawl speed, angular velocity, omega turns
  foraging_descriptors.csv     head-swing amplitude and frequency
  posterior_dampening.csv      anterior-to-posterior fall in bend amplitude
  fig_curvature_kymograph.png  segment x time body curvature
  fig_posterior_dampening.png  bend amplitude vs body position
  fig_head_bend.png            head-swing trace over time (foraging)

Requires foraging_descriptors() and posterior_dampening() to be present in
worm_kinetics.py (see the earlier worm_kinetics patch). If they are absent this
still runs undulation + locomotion and just logs the two as unavailable.

This is the ONE kinematics computation path shared by the analyse launcher and
(when you build it) a kinematics results browser: neither reimplements the
analysis, both read the returned AnalysisResult.

Cannot execute here without the pipeline data and venv; run it in the pinned
environment and confirm on a real transmitted-light export.
"""
from __future__ import annotations

import json
import sys
import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The staged layout has one explicit canonical RGBCaMP pipeline.
ROOT = Path(__file__).resolve().parents[2]
PIPELINE = ROOT / "tools" / "rgbcamp" / "pipeline"
if not (PIPELINE / "run_one.py").exists():
    raise ImportError(f"Canonical RGBCaMP pipeline not found: {PIPELINE}")
sys.path.insert(0, str(PIPELINE))

import numpy as np
import pandas as pd

import worm_rgbcamp_analysis as wa
import worm_kinetics as wk

# Result tables are read through read_table. Under pandas 3 a numeric column
# holding one stray non-numeric cell reads as StringDtype, and numpy then
# refuses np.isfinite on it - aborting an analysis with an error that names
# numpy internals rather than the column at fault. The import is guarded
# because these modules are launched several different ways and sys.path is
# not identical in all of them; a hard import would turn a latent dtype
# problem into a tool that will not start.
try:
    from table_io import read_table as _read_table
except Exception:                                    # pragma: no cover
    try:
        import sys as _sys
        from pathlib import Path as _Path
        _sys.path.insert(0, str(_Path(__file__).resolve().parents[2] / "app"))
        from table_io import read_table as _read_table
    except Exception:
        _read_table = None


def read_table(path, **kwargs):
    """pandas.read_csv with the pandas-3 dtype trap handled where available."""
    import pandas as _pd
    if _read_table is not None:
        return _read_table(path, **kwargs)
    return _pd.read_csv(path, **kwargs)



@dataclass
class AnalysisResult:
    csv_path: Path
    out_dir: Path
    worm_id: str
    qc_report: dict
    channel_report: dict
    tables: dict
    figures: dict
    log: list = field(default_factory=list)


KINEMATICS_REQUIRED = {
    "worm_id", "frame", "time_s", "segment", "seg_curv_deg", "fps",
}


def load_kinematics_csv(path):
    """Load a transmitted-light export without invoking photometry schema."""
    data = read_table(path)
    missing = sorted(KINEMATICS_REQUIRED - set(data.columns))
    if missing:
        raise ValueError(
            "This is not a Track one worm / kinematics CSV. Missing: "
            + ", ".join(missing))
    for column in KINEMATICS_REQUIRED - {"worm_id"}:
        data[column] = pd.to_numeric(data[column], errors="coerce")
    # The shared kinematics algorithms use these canonical names. The DIC
    # tracker reports equivalent whole-worm quantities under clearer names.
    aliases = {
        "centroid_speed_px_s": "axial_vel_px_s",
        "head_angular_velocity_deg_s": "angular_vel_deg_s",
    }
    for source, target in aliases.items():
        if target not in data and source in data:
            data[target] = pd.to_numeric(data[source], errors="coerce")
    if "hemisegment" not in data:
        data["hemisegment"] = "midline"
    if "self_approach_flag" not in data:
        data["self_approach_flag"] = 0
    if "eigen_fit_quality" not in data:
        data["eigen_fit_quality"] = np.nan
    return data


def qc_kinematics(data):
    keep = data["seg_curv_deg"].notna()
    if "needs_help" in data:
        keep &= pd.to_numeric(data["needs_help"], errors="coerce").fillna(1) == 0
    filtered = data.loc[keep].copy()
    if filtered.empty:
        raise ValueError(
            "No reviewed kinematics rows remain after excluding flagged or "
            "missing-curvature frames.")
    return filtered, {
        "n_rows_in": int(len(data)), "n_rows_kept": int(len(filtered)),
        "retention_frac": float(len(filtered) / len(data)),
        "policy": "finite curvature and needs_help=0 when present",
    }

# Foraging and posterior dampening may be pasted into worm_kinetics, or live in
# the standalone module; attach them to wk so the rest of the code is uniform.
if not hasattr(wk, "foraging_descriptors") or not hasattr(wk, "posterior_dampening"):
    try:
        import worm_kinetics_foraging_dampening as _fd
        _fd.wave_propagation = wk.wave_propagation
        if not hasattr(wk, "foraging_descriptors"):
            wk.foraging_descriptors = _fd.foraging_descriptors
        if not hasattr(wk, "posterior_dampening"):
            wk.posterior_dampening = _fd.posterior_dampening
    except Exception:
        pass


def _has_calcium(df: pd.DataFrame) -> bool:
    return any(f"{c}_mean" in df.columns for c in ("green", "red", "blue"))


def analyse_one_kinematics(csv_path: str | Path,
                           out_dir: str | Path | None = None) -> AnalysisResult:
    csv_path = Path(csv_path)
    out_dir = (Path(out_dir) if out_dir is not None
               else csv_path.parent / f"{csv_path.stem}_kinematics_output")
    out_dir.mkdir(parents=True, exist_ok=True)

    log = [f"Loading {csv_path.name} (kinematics-only)"]
    raw = load_kinematics_csv(csv_path)
    worm_id = str(raw["worm_id"].iloc[0])
    if _has_calcium(raw):
        log.append("NOTE: calcium columns present but ignored in kinematics-only mode.")

    filt, qc_report = qc_kinematics(raw)
    log.append(f"QC: kept {qc_report['n_rows_kept']}/{qc_report['n_rows_in']} rows "
               f"(retention {qc_report['retention_frac']:.2f})")

    # No head mask and no channel normalisation: those exist only for calcium.
    # Posture (curvature, velocity, head bend) is valid over the whole body and
    # is read straight from the QC-filtered frame.
    body = filt

    tables: dict[str, pd.DataFrame] = {}

    def _try(name, fn):
        try:
            result = fn()
            if isinstance(result, dict):
                result = pd.DataFrame([result])
            tables[name] = result
            log.append(f"  {name}: {len(result)} row(s)")
        except Exception as e:
            log.append(f"  {name}: FAILED ({e})")

    _try("undulation_descriptors", lambda: wk.undulation_descriptors(body, worm_id))
    _try("locomotion_summary", lambda: wk.locomotion_summary(body, worm_id))
    if hasattr(wk, "foraging_descriptors"):
        _try("foraging_descriptors", lambda: wk.foraging_descriptors(body, worm_id))
    else:
        log.append("  foraging_descriptors: unavailable (not yet added to worm_kinetics.py)")
    if hasattr(wk, "posterior_dampening"):
        _try("posterior_dampening", lambda: wk.posterior_dampening(body, worm_id))
    else:
        log.append("  posterior_dampening: unavailable (not yet added to worm_kinetics.py)")

    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)

    figures = _make_kinematics_figures(body, worm_id, tables, out_dir, log)

    (out_dir / "qc_report.json").write_text(json.dumps(
        dict(qc_report=qc_report, worm_id=worm_id, mode="kinematics_only", log=log),
        indent=2, default=str))
    print("\n".join(log))
    print(f"Wrote {len(tables)} table(s) + {len(figures)} figure(s) to {out_dir}")

    return AnalysisResult(csv_path=csv_path, out_dir=out_dir, worm_id=worm_id,
                          qc_report=qc_report, channel_report={"mode": "kinematics_only"},
                          tables=tables, figures=figures, log=log)


def _make_kinematics_figures(body: pd.DataFrame, worm_id: str, tables: dict,
                             out_dir: Path, log: list) -> dict:
    figures: dict[str, Path] = {}
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # curvature kymograph (segment x time), full body, own colour scale
    try:
        Mc, seg_axis_c, frames_c = wa.kymograph(body, worm_id, value="seg_curv_deg")
        vmin = float(np.nanmin(Mc)) if np.isfinite(Mc).any() else None
        vmax = float(np.nanmax(Mc)) if np.isfinite(Mc).any() else None
        fig, ax = plt.subplots(figsize=(7, 4))
        im = ax.imshow(Mc, aspect="auto", origin="lower",
                       extent=[frames_c.min(), frames_c.max(), seg_axis_c.min(), seg_axis_c.max()],
                       cmap="RdBu_r", vmin=vmin, vmax=vmax)
        ax.set_xlabel("frame"); ax.set_ylabel("segment (0 = head)")
        ax.set_title(f"{worm_id}: body curvature kymograph")
        fig.colorbar(im, ax=ax, label="curvature (deg)")
        fig.tight_layout()
        p = out_dir / "fig_curvature_kymograph.png"
        fig.savefig(p, dpi=150); plt.close(fig)
        figures["fig_curvature_kymograph"] = p
        log.append("  fig_curvature_kymograph.png written")
    except Exception as e:
        log.append(f"  fig_curvature_kymograph.png FAILED ({e})")

    # posterior dampening profile: bend amplitude vs body position
    try:
        pd_tab = tables.get("posterior_dampening")
        if pd_tab is not None and len(pd_tab):
            row = pd_tab.iloc[0]
            pos = row.get("seg_positions"); amp = row.get("seg_amplitudes")
            if isinstance(pos, (list, tuple)) and isinstance(amp, (list, tuple)) and len(pos) == len(amp):
                fig, ax = plt.subplots(figsize=(6, 4))
                ax.plot(pos, amp, "o-", color="#b2182b")
                ax.set_xlabel("body position (0 = head, 1 = tail)")
                ax.set_ylabel("bend amplitude (deg)")
                slope = row.get("slope_per_bodylen")
                pa = row.get("pa_ratio")
                ax.set_title(f"{worm_id}: posterior dampening "
                             f"(slope={slope:.2f}, post/ant={pa:.2f})"
                             if slope is not None and pa is not None
                             else f"{worm_id}: bend amplitude vs body position")
                fig.tight_layout()
                p = out_dir / "fig_posterior_dampening.png"
                fig.savefig(p, dpi=150); plt.close(fig)
                figures["fig_posterior_dampening"] = p
                log.append("  fig_posterior_dampening.png written")
    except Exception as e:
        log.append(f"  fig_posterior_dampening.png FAILED ({e})")

    # foraging: head-bend trace over time
    try:
        if "head_bend_deg" in body.columns:
            d = body[body["worm_id"] == worm_id]
            s = d.groupby("frame")["head_bend_deg"].first().sort_index()
            t = d.groupby("frame")["time_s"].first().sort_index() if "time_s" in d.columns else s.index
            fig, ax = plt.subplots(figsize=(8, 3))
            ax.plot(np.asarray(t), s.to_numpy(), color="#1a9850", lw=0.8)
            ax.axhline(0, color="#999", lw=0.6)
            ax.set_xlabel("time (s)"); ax.set_ylabel("head bend (deg)")
            ax.set_title(f"{worm_id}: head-swing trace (foraging)")
            fig.tight_layout()
            p = out_dir / "fig_head_bend.png"
            fig.savefig(p, dpi=150); plt.close(fig)
            figures["fig_head_bend"] = p
            log.append("  fig_head_bend.png written")
        else:
            log.append("  fig_head_bend.png skipped (no head_bend_deg column; "
                       "re-export with the kinematics extractor)")
    except Exception as e:
        log.append(f"  fig_head_bend.png FAILED ({e})")

    return figures


def main():
    if len(sys.argv) < 2:
        print(__doc__); sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: {csv_path} does not exist"); sys.exit(1)
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        analyse_one_kinematics(csv_path, out_dir)
    except Exception:
        traceback.print_exc(); sys.exit(1)


if __name__ == "__main__":
    main()
