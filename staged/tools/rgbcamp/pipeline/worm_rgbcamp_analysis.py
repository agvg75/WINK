"""
worm_rgbcamp_analysis.py
========================
Downstream analysis layer for WormRGBCaMPMap_v1.java output.

The ImageJ plugin is the *extraction* front-end: it tracks a freely-moving
worm on DIC, fits an eigenworm-constrained head->tail midline, cuts it into
`nSeg` hemisegments per side, and exports one long-format CSV with per-segment
blue/green/red intensities, R/G/B ratios, curvature, kinematics, inter-channel
lag, and QC flags. It deliberately does NO normalization, aggregation, or
statistics. This module is that missing layer.

Column contract (matches WormRGBCaMPMap_v1.exportCsv header exactly)
-------------------------------------------------------------------
identity/meta : frame, time_s, worm_id, condition, fps, um_per_px, src8bit
frame QC      : skip, found, coil_flag, area_flag, size_flag, len_short_flag,
                len_long_flag, midline_len_px, partial_flag, self_approach_flag,
                head_tip_conf, tail_tip_conf, head_tip_src, tail_tip_src,
                fluor_outside_frac, dic_confidence, eigen_fit_quality,
                body_source, len_conserved, low_evidence, filled_neighbor
segment id    : segment (0..nSeg-1, 0=anterior), hemisegment (L/R or dorsal/
                ventral), side_curv_label, dorsal_label, dorsal_known,
                body_provenance, edge_source
intensities   : blue_min/mean/max, green_min/mean/max, red_min/mean/max, roi_area_px
rates         : blue_dF_dt, green_dF_dt, red_dF_dt
ratios+rates  : ratio_RG, ratio_RB, ratio_GB, dRG_dt, dRB_dt, dGB_dt
kinematics    : seg_angle_deg, seg_curv_deg, axial_vel_px_s, angular_vel_deg_s
lag           : lag_GB_frames/ms, lag_RG_frames/ms, lag_RB_frames/ms, lag_resolved

Biological channel roles (from the plugin header)
-------------------------------------------------
green = cytoplasmic GCaMP  -> PRIMARY body-wall muscle calcium readout
red   = mito RCaMP / pharynx mCherry
blue  = ER (e.g. GCaMP-ER / low-affinity ER indicator)

For a DMD program the primary readouts are cytoplasmic (green) resting level and
transient kinetics, and the curvature-calcium coupling (does dystrophic muscle
decouple activation from bending?).

Pipeline
--------
1. load_extracted        - read CSV, enforce dtypes, attach genotype grouping
2. qc_filter             - drop / flag untrusted rows by QC policy, report retention
3. add_dff               - per (worm, segment, hemisegment) dF/F0 with a low-percentile F0
4. per_worm_summary      - collapse to one row per worm x segment (or per worm)
5. kymograph             - anterior->posterior x time dF/F map per worm
6. curvature_coupling    - per-segment corr(dF/F, |curvature|) and cross-corr lag
7. condition_stats       - WT vs dystrophic tests on per-worm summaries
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

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



CHANNELS = ("blue", "green", "red")
PRIMARY_CHANNEL = "green"   # cytoplasmic GCaMP

# frame-level QC flags that, when set (=1), mark an untrusted frame
# Frame-level flags that mark an untrusted frame. self_approach_flag is
# deliberately NOT here: it flags curvature-shortcut risk (posture), not
# photometry, and fires on a large fraction of freely-moving frames -- treat it
# as a per-metric caveat for curvature, not a whole-frame reject.
FRAME_REJECT_FLAGS = ("coil_flag", "area_flag", "size_flag",
                      "len_short_flag", "len_long_flag", "partial_flag",
                      "low_evidence")


@dataclass
class QCPolicy:
    """Which rows to trust. Defaults are conservative but not draconian."""
    require_found: bool = True          # drop found==0 (no body this frame)
    drop_skip: bool = True              # drop skip==1
    reject_flags: Sequence[str] = FRAME_REJECT_FLAGS
    max_fluor_outside_frac: float = 0.25   # drop frames leaking signal outside body
    min_eigen_fit_quality: float = 0.0     # set >0 to require a good posture fit
    drop_inferred_body: bool = False       # body_provenance != 'measured'
    # NOTE: the plugin's own note is that on 8-bit (mp4) sources absolute
    # intensities are not fully quantitative but *ratios and dF/F0 are robust*.
    # Their standard acquisition here is 8-bit, so we do NOT blank intensities
    # by default; we flag the recording instead (see analyse_recording).
    drop_src8bit_intensity: bool = False


# ----------------------------------------------------------------------------
# 1. Load
# ----------------------------------------------------------------------------
def load_extracted(
    path: str | Path,
    genotype_map: Optional[dict] = None,
    genotype_col: str = "genotype",
) -> pd.DataFrame:
    """Read a plugin CSV (or several concatenated) and normalise dtypes.

    genotype_map maps worm_id or condition -> genotype label ('WT'/'dystrophic').
    If None, the `condition` column is used verbatim as the genotype.
    """
    df = read_table(path)
    _check_schema(df)

    # integer flag columns -> boolean where it reads cleaner, keep ints for flags
    for c in ("skip", "found", "src8bit", "dorsal_known", "lag_resolved"):
        if c in df:
            df[c] = df[c].astype("int8")

    # genotype grouping
    if genotype_map is not None:
        key = "worm_id" if set(df["worm_id"]).issubset(genotype_map) else "condition"
        df[genotype_col] = df[key].map(genotype_map)
        if df[genotype_col].isna().any():
            missing = df.loc[df[genotype_col].isna(), key].unique()
            warnings.warn(f"genotype_map missing keys: {missing}")
    else:
        df[genotype_col] = df["condition"].astype(str)

    return df


REQUIRED_COLS = (
    "frame", "time_s", "worm_id", "condition", "fps", "found", "skip",
    "segment", "hemisegment", "green_mean", "red_mean", "blue_mean",
    "seg_curv_deg", "roi_area_px",
)


# Filename token -> genotype/RNAi label. The plugin writes one worm per CSV and
# stores the magnetic condition ('1G') in `condition`; the RNAi/genotype lives
# in the FILE NAME. L4440 is the standard empty-vector RNAi control.
def genotype_from_filename(name: str) -> dict:
    """Parse a WormRGBCaMP_extracted_*.csv filename into grouping metadata.

    Returns {rnai_target, is_control, quality_note}. Unknown tokens fall back to
    the raw stem so nothing is silently mislabelled.
    """
    stem = Path(name).stem.replace("WormRGBCaMP_extracted_", "").strip()
    low = stem.lower()
    is_ctrl = "l4440" in low
    # a trailing 'bad'/'bad2' is the user's own QC verdict on the recording
    quality = "flagged_bad" if "bad" in low else ("good" if low in
              ("yes", "new", "l4440") else "unlabelled")
    target = "L4440(empty_vector)" if is_ctrl else stem
    return {"rnai_target": target, "is_control": bool(is_ctrl),
            "quality_note": quality, "file_stem": stem}


def _check_schema(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLS if c not in df.columns]
    if missing:
        raise ValueError(
            f"CSV missing expected WormRGBCaMPMap columns: {missing}. "
            f"Got {list(df.columns)[:8]}...")


# ----------------------------------------------------------------------------
# 2. Quality filter
# ----------------------------------------------------------------------------
def qc_filter(df: pd.DataFrame, policy: QCPolicy = QCPolicy()) -> tuple[pd.DataFrame, dict]:
    """Apply the QC policy. Returns (filtered_df, report_dict).

    Intensity-bearing columns are set to NaN (not dropped) when only the
    photometry is untrusted (src8bit) but the geometry is fine.
    """
    n0 = len(df)
    keep = pd.Series(True, index=df.index)
    report = {"n_rows_in": n0}

    if policy.require_found and "found" in df:
        keep &= df["found"] == 1
    if policy.drop_skip and "skip" in df:
        keep &= df["skip"] == 0
    for flg in policy.reject_flags:
        if flg in df:
            keep &= df[flg] != 1
    if "fluor_outside_frac" in df:
        keep &= (df["fluor_outside_frac"].fillna(0) <= policy.max_fluor_outside_frac)
    if policy.min_eigen_fit_quality > 0 and "eigen_fit_quality" in df:
        keep &= df["eigen_fit_quality"].fillna(0) >= policy.min_eigen_fit_quality
    if policy.drop_inferred_body and "body_provenance" in df:
        keep &= df["body_provenance"] == "measured"

    out = df[keep].copy()
    report["n_rows_kept"] = len(out)
    report["retention_frac"] = len(out) / n0 if n0 else 0.0

    # blank intensity columns on 8-bit-sourced frames (keep kinematics/geometry)
    if policy.drop_src8bit_intensity and "src8bit" in out:
        icols = [f"{ch}_{s}" for ch in CHANNELS for s in ("min", "mean", "max")]
        icols += ["ratio_RG", "ratio_RB", "ratio_GB"]
        icols = [c for c in icols if c in out]
        bad = out["src8bit"] == 1
        out.loc[bad, icols] = np.nan
        report["n_rows_intensity_blanked_src8bit"] = int(bad.sum())

    # 8-bit saturation audit per segment (green channel). Anterior segments in
    # these SP8 movies pile up at the 8-bit ceiling; flag which segments are
    # untrustworthy for intensity metrics rather than silently averaging them in.
    if "green_max" in out:
        sat = (out.assign(_sat=out["green_max"] >= 254)
               .groupby("segment")["_sat"].mean())
        report["segment_saturation_frac"] = sat.round(3).to_dict()
        report["saturated_segments"] = sorted(sat[sat > 0.5].index.tolist())

    # per-worm retention
    report["per_worm_retention"] = (
        df.assign(_keep=keep).groupby("worm_id")["_keep"].mean().round(3).to_dict())
    return out, report


# ----------------------------------------------------------------------------
# 3. dF/F0
# ----------------------------------------------------------------------------
def add_dff(
    df: pd.DataFrame,
    channels: Sequence[str] = CHANNELS,
    f0_percentile: float = 10.0,
    group_cols: Sequence[str] = ("worm_id", "segment", "hemisegment"),
) -> pd.DataFrame:
    """Add `<channel>_dff` columns.

    F0 is a per-(worm,segment,hemisegment) low percentile of the channel mean
    over time. A freely-moving worm never sits at a clean baseline, and each
    hemisegment has its own resting level and shading, so the baseline must be
    computed within that group, not globally.
    """
    out = df.sort_values(list(group_cols) + ["frame"]).copy()
    for ch in channels:
        col = f"{ch}_mean"
        if col not in out:
            continue
        f0 = out.groupby(list(group_cols))[col].transform(
            lambda x: np.nanpercentile(x, f0_percentile) if x.notna().any() else np.nan)
        f0 = f0.replace(0, np.nan)
        out[f"{ch}_f0"] = f0
        out[f"{ch}_dff"] = (out[col] - f0) / f0
    return out


# ----------------------------------------------------------------------------
# 4. Per-worm summary
# ----------------------------------------------------------------------------
def per_worm_summary(
    df: pd.DataFrame,
    genotype_col: str = "genotype",
    primary: str = PRIMARY_CHANNEL,
) -> pd.DataFrame:
    """One row per worm: the DMD-relevant readouts.

    resting_<ch>        median raw channel mean (proxy for resting [ion])
    dff_p95_<ch>        95th-pct dF/F0 (transient magnitude)
    active_frac_<ch>    fraction of segment-frames with dff > 2*noise
    mean_abs_curv       posture activity
    curv_calcium_r      within-worm corr(|curv|, primary dF/F0)
    """
    rows = []
    for wid, g in df.groupby("worm_id"):
        rec = {"worm_id": wid, genotype_col: g[genotype_col].iloc[0],
               "condition": g["condition"].iloc[0],
               "n_segframes": len(g)}
        for ch in CHANNELS:
            m, d = f"{ch}_mean", f"{ch}_dff"
            if m in g:
                rec[f"resting_{ch}"] = g[m].median()
            if d in g and g[d].notna().any():
                dff = g[d].dropna()
                noise = 1.4826 * np.median(np.abs(dff - np.median(dff)))
                rec[f"dff_p95_{ch}"] = np.nanpercentile(g[d], 95)
                rec[f"active_frac_{ch}"] = float((g[d] > 2 * noise).mean())
        if "seg_curv_deg" in g:
            rec["mean_abs_curv"] = g["seg_curv_deg"].abs().mean()
        pdff = f"{primary}_dff"
        if pdff in g and "seg_curv_deg" in g:
            sub = g[[pdff, "seg_curv_deg"]].dropna()
            if len(sub) > 10 and sub[pdff].std() > 0:
                rec["curv_calcium_r"] = np.corrcoef(
                    sub["seg_curv_deg"].abs(), sub[pdff])[0, 1]
        for rt in ("ratio_RG", "ratio_GB", "ratio_RB"):
            if rt in g:
                rec[f"median_{rt}"] = g[rt].median()
        rows.append(rec)
    return pd.DataFrame(rows)


# ----------------------------------------------------------------------------
# 5. Kymograph (anterior -> posterior x time)
# ----------------------------------------------------------------------------
def kymograph(
    df: pd.DataFrame,
    worm_id,
    value: str = "green_dff",
    hemisegment: str = "mean",
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return (M, seg_axis, time_axis) where M[seg, frame] is `value`.

    hemisegment: 'mean' averages the two sides; else a specific label ('L','R',
    'dorsal','ventral'). Segment 0 is anterior (plugin midline index 0 = head).
    """
    g = df[df["worm_id"] == worm_id]
    if hemisegment != "mean":
        g = g[g["hemisegment"] == hemisegment]
    piv = g.pivot_table(index="segment", columns="frame", values=value, aggfunc="mean")
    piv = piv.sort_index()
    return piv.values, piv.index.values, piv.columns.values


# ----------------------------------------------------------------------------
# 6. Curvature-calcium coupling
# ----------------------------------------------------------------------------
def curvature_coupling(
    df: pd.DataFrame,
    value: str = "green_dff",
    curv: str = "seg_curv_deg",
    max_lag_frames: int = 10,
) -> pd.DataFrame:
    """Per (worm, segment) correlation and best cross-correlation lag between
    |curvature| and calcium. A lag != 0 means activation leads or trails bending;
    a coupling that weakens in dystrophic muscle is a candidate phenotype.
    """
    rows = []
    for (wid, seg), g in df.groupby(["worm_id", "segment"]):
        gg = (g[g["hemisegment"].isin(["L", "dorsal"])] if "hemisegment" in g else g)
        s = gg.sort_values("frame")
        a = s[curv].abs().to_numpy(float)
        b = s[value].to_numpy(float)
        ok = np.isfinite(a) & np.isfinite(b)
        if ok.sum() < 20 or np.nanstd(a[ok]) == 0 or np.nanstd(b[ok]) == 0:
            continue
        a, b = a[ok] - a[ok].mean(), b[ok] - b[ok].mean()
        r0 = np.corrcoef(a, b)[0, 1]
        lag, rbest = _best_lag(a, b, max_lag_frames)
        rows.append(dict(worm_id=wid, segment=seg, r_zero_lag=r0,
                         best_lag_frames=lag, r_best_lag=rbest,
                         genotype=g["genotype"].iloc[0] if "genotype" in g else "NA"))
    return pd.DataFrame(rows)


def _best_lag(a, b, maxlag):
    n = len(a)
    denom = np.sqrt(np.sum(a * a) * np.sum(b * b)) + 1e-12
    best_r, best_l = 0.0, 0
    for L in range(-maxlag, maxlag + 1):
        if L < 0:
            r = np.sum(a[:n + L] * b[-L:]) / denom
        elif L > 0:
            r = np.sum(a[L:] * b[:n - L]) / denom
        else:
            r = np.sum(a * b) / denom
        if abs(r) > abs(best_r):
            best_r, best_l = r, L
    return best_l, best_r


# ----------------------------------------------------------------------------
# 7. Condition statistics
# ----------------------------------------------------------------------------
def condition_stats(
    summary: pd.DataFrame,
    metrics: Sequence[str],
    genotype_col: str = "genotype",
    group_a: str = "WT",
    group_b: str = "dystrophic",
) -> pd.DataFrame:
    """Mann-Whitney U per metric between two genotypes, with effect size
    (rank-biserial) and Hodges-Lehmann median difference. Worm is the unit of N.
    """
    rows = []
    A = summary[summary[genotype_col] == group_a]
    B = summary[summary[genotype_col] == group_b]
    for m in metrics:
        if m not in summary:
            continue
        a = A[m].dropna().to_numpy()
        b = B[m].dropna().to_numpy()
        if len(a) < 2 or len(b) < 2:
            rows.append(dict(metric=m, n_A=len(a), n_B=len(b), p=np.nan))
            continue
        U, p = stats.mannwhitneyu(a, b, alternative="two-sided")
        rbc = 1 - 2 * U / (len(a) * len(b))          # rank-biserial effect size
        hl = np.median([bi - ai for ai in a for bi in b])  # HL median diff (B-A)
        rows.append(dict(metric=m, n_A=len(a), n_B=len(b),
                         median_A=np.median(a), median_B=np.median(b),
                         hodges_lehmann_B_minus_A=hl,
                         rank_biserial=rbc, U=U, p=p))
    out = pd.DataFrame(rows)
    if "p" in out and out["p"].notna().any():
        # Benjamini-Hochberg FDR
        out = out.sort_values("p").reset_index(drop=True)
        mask = out["p"].notna()
        pvals = out.loc[mask, "p"].to_numpy()
        n = len(pvals)
        q = pvals * n / (np.arange(1, n + 1))
        q = np.minimum.accumulate(q[::-1])[::-1]
        out.loc[mask, "q_bh"] = np.clip(q, 0, 1)
    return out


# ----------------------------------------------------------------------------
# 8. Per-recording orchestrator
# ----------------------------------------------------------------------------
@dataclass
class RecordingResult:
    stem: str
    meta: dict
    df: pd.DataFrame                 # QC-filtered + dF/F
    qc_report: dict
    worm_summary: pd.DataFrame       # per (worm x segment) or per worm
    coupling: pd.DataFrame
    warnings: list = field(default_factory=list)


def analyse_recording(
    path: str | Path,
    policy: QCPolicy = QCPolicy(),
    f0_percentile: float = 10.0,
) -> RecordingResult:
    """Full single-CSV pipeline: load -> QC -> dF/F -> summary + coupling.

    Attaches filename-derived grouping and raises data-integrity warnings
    (8-bit source, uncalibrated pixels, one-worm N) so downstream stats are honest.
    """
    path = Path(path)
    meta = genotype_from_filename(path.name)
    df = load_extracted(path, genotype_col="genotype")
    df["genotype"] = meta["rnai_target"]
    df["is_control"] = meta["is_control"]

    warns = []
    if "src8bit" in df and (df["src8bit"] == 1).any():
        warns.append("8-bit source: absolute intensities are not fully "
                     "quantitative; trust ratios and dF/F0, caveat raw resting level.")
    if "um_per_px" in df and (df["um_per_px"] == 0).all():
        warns.append("um_per_px=0: spatial metrics are in pixels, not microns.")
    if df["worm_id"].nunique() == 1:
        warns.append("single worm in this file: not a unit-of-inference sample; "
                     "aggregate multiple recordings before genotype statistics.")

    filt, report = qc_filter(df, policy)
    filt = add_dff(filt, f0_percentile=f0_percentile)
    summ = per_worm_summary(filt)
    summ["genotype"] = meta["rnai_target"]
    coup = curvature_coupling(filt)

    return RecordingResult(stem=meta["file_stem"], meta=meta, df=filt,
                           qc_report=report, worm_summary=summ,
                           coupling=coup, warnings=warns)
