"""
worm_batch.py — multi-file batch processing with the WORM as the unit of N.

Implements the "Multi file batch processing" and "Metadata convention" sections
of RGBCaMP_fixes_batch_spec.docx.

Pipeline per file:  load -> QC -> channel normalisation (bg + dF/F0) ->
head mask -> all kinetics.  Files are ASSEMBLED, not processed in isolation.

Metadata:  a metadata.csv MANIFEST is preferred (auditable, catches typos);
filename-token parsing is the fallback. Every file's parse result is emitted to
a parse log so a mislabel cannot pass silently.

Statistics contract:  aggregate to the ANIMAL level first (per animal, per
region, per metric), then compare only ACROSS animals. Transients/segments are
never pooled as independent replicates.

Guardrail:  if genotype or age is missing for a group, only per-recording
description is produced and no group inference is made (current pilot state).
"""
from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional, Sequence

import numpy as np
import pandas as pd

import worm_rgbcamp_analysis as wr
import worm_channels as wc
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


MANIFEST_COLS = ("filename", "genotype", "age_day", "rnai_target",
                 "magnetic_condition", "animal_id", "quality")


# --------------------------------------------------------------------------- #
# Metadata: manifest (preferred) or filename tokens (fallback)
# --------------------------------------------------------------------------- #
def parse_magnetic_condition(name: str) -> Optional[str]:
    """Filename token for the magnetosensation program: magON / magOFF / magN."""
    import re
    stem = re.sub(r"\.csv$", "", name, flags=re.I)
    for t in re.split(r"[ _\-]+", stem):
        m = re.fullmatch(r"mag(on|off|[ns]|null|sham)", t, flags=re.I)
        if m:
            return "mag" + m.group(1).upper()
    return None


def metadata_for_file(path: Path, manifest: Optional[pd.DataFrame],
                      df: Optional[pd.DataFrame] = None) -> dict:
    """Return a metadata dict for one file.

    Priority (highest wins, per-field): CSV metadata columns written by the
    extractor (strain/genotype/rnai/age_day/animal_id, contract_version>=3)
    > manifest.csv row > filename tokens. The CSV columns are authoritative
    because they are set explicitly in the extractor's dialog, never inferred;
    filename parsing and the manifest remain the fallback for older recordings
    that predate those columns, so nothing breaks for existing exports.

    `df` is the loaded recording (post `load_extracted`); pass None (or a
    frame without the metadata columns) to fall back to manifest/filename only.
    Always includes a `metadata_source` field. Never raises on a missing
    axis — returns None for that field instead."""
    name = path.name
    # filename fallback (also the base when a manifest row is partial)
    fn = wk.parse_metadata(name)
    meta = dict(genotype=fn["genotype"], age_day=fn["age_day"],
                rnai_target=fn["rnai_target"], is_control=fn["is_control"],
                quality=fn["quality_note"],
                magnetic_condition=parse_magnetic_condition(name),
                metadata_source="filename")

    if manifest is not None:
        row = manifest[manifest["filename"].astype(str) == name]
        if len(row) == 1:
            r = row.iloc[0].to_dict()
            for k in ("genotype", "age_day", "rnai_target",
                      "magnetic_condition", "quality"):
                if k in r and pd.notna(r[k]) and str(r[k]).strip() != "":
                    meta[k] = r[k]
            if "age_day" in meta and pd.notna(meta["age_day"]):
                try:
                    meta["age_day"] = int(meta["age_day"])
                except (ValueError, TypeError):
                    pass
            meta["manifest_animal_id"] = r.get("animal_id")
            meta["metadata_source"] = "manifest"
        elif len(row) > 1:
            meta["metadata_source"] = "manifest_DUPLICATE_ROWS"
        else:
            meta["metadata_source"] = "filename(no_manifest_row)"

    # ---- CSV metadata columns (Change 1): authoritative, ahead of both the
    # manifest and filename tokens. Applied per-field so a partially-tagged
    # CSV (e.g. old export re-saved with only some columns) still benefits.
    csv_fields_used = []
    if df is not None:
        if "genotype" in df.columns:
            v = df["genotype"].iloc[0]
            if pd.notna(v) and str(v).strip():
                meta["genotype"] = str(v).strip()
                csv_fields_used.append("genotype")
        if "rnai" in df.columns:
            v = df["rnai"].iloc[0]
            if pd.notna(v) and str(v).strip():
                meta["rnai_target"] = str(v).strip()
                csv_fields_used.append("rnai")
        if "age_day" in df.columns:
            v = df["age_day"].iloc[0]
            if pd.notna(v):
                try:
                    meta["age_day"] = int(v)
                    csv_fields_used.append("age_day")
                except (ValueError, TypeError):
                    pass
        if "animal_id" in df.columns:
            v = df["animal_id"].iloc[0]
            if pd.notna(v) and str(v).strip():
                meta["csv_animal_id"] = str(v).strip()
                csv_fields_used.append("animal_id")
        if "strain" in df.columns:
            v = df["strain"].iloc[0]
            if pd.notna(v) and str(v).strip():
                meta["strain"] = str(v).strip()
                csv_fields_used.append("strain")
    if csv_fields_used:
        meta["metadata_source"] = ("csv_columns"
            if {"genotype", "rnai", "age_day", "animal_id"}.issubset(csv_fields_used)
            else "csv_columns_partial")
        meta["csv_fields_used"] = sorted(csv_fields_used)
    return meta


def make_animal_id(path: Path, meta: dict, df: pd.DataFrame) -> str:
    """Unique animal id from recording + date + worm, so the worm is the unit
    of N. Prefers the extractor's own CSV `animal_id` column (Change 1,
    authoritative), then a manifest-provided id; else builds recording::worm
    and, if a date is discoverable (mtime), folds it in for cross-session
    uniqueness."""
    if meta.get("csv_animal_id"):
        return str(meta["csv_animal_id"])
    if meta.get("manifest_animal_id") and pd.notna(meta["manifest_animal_id"]):
        return str(meta["manifest_animal_id"])
    stem = Path(path).stem
    worm = str(df["worm_id"].iloc[0]) if "worm_id" in df and len(df) else "w1"
    # a stable short hash of the file path disambiguates same-named files in
    # different folders without depending on volatile mtimes
    h = hashlib.sha1(str(Path(path).resolve()).encode()).hexdigest()[:6]
    return f"{stem}::{worm}::{h}"


def load_manifest(csv_dir: Path) -> Optional[pd.DataFrame]:
    """Load metadata.csv from the batch directory if present."""
    for cand in ("metadata.csv", "manifest.csv"):
        p = Path(csv_dir) / cand
        if p.exists():
            m = read_table(p)
            missing = [c for c in ("filename",) if c not in m.columns]
            if missing:
                warnings.warn(f"manifest {p.name} lacks required column(s) {missing}; ignoring")
                return None
            return m
    return None


# --------------------------------------------------------------------------- #
# Batch config + result
# --------------------------------------------------------------------------- #
@dataclass
class BatchConfig:
    channel: wc.ChannelConfig = field(default_factory=wc.ChannelConfig)
    qc: wr.QCPolicy = field(default_factory=wr.QCPolicy)
    f0_percentile: float = 10.0
    drop_flagged_bad: bool = True          # exclude quality=='flagged_bad' by default
    min_duration_s: float = 20.0           # length-normalisation floor
    min_wave_coherence: float = 0.5        # wave metrics require coherence >= this
    confirmatory_only: bool = True         # aggregate confirmatory transients


@dataclass
class BatchResult:
    master_transients: pd.DataFrame        # one row per transient + metadata
    per_region: pd.DataFrame               # per (animal, region, metric)
    per_recording: pd.DataFrame            # one row per recording + metadata
    waves: pd.DataFrame                    # per (animal) wave metrics
    animal_summary: pd.DataFrame           # per-animal aggregates (unit of N)
    parse_log: pd.DataFrame                # metadata parse result per file
    inclusion: dict                        # counts included/excluded + reasons
    config: dict


# --------------------------------------------------------------------------- #
# Batch driver
# --------------------------------------------------------------------------- #
def run_batch(csv_dir: str | Path, cfg: BatchConfig = BatchConfig()) -> BatchResult:
    csv_dir = Path(csv_dir)
    manifest = load_manifest(csv_dir)
    files = sorted(p for p in csv_dir.glob("*.csv")
                   if p.name not in ("metadata.csv", "manifest.csv"))

    parse_rows, incl, excl = [], [], []
    master, region_frames, rec_rows, wave_rows = [], [], [], []

    for path in files:
        raw = wr.load_extracted(path)
        raw["worm_id"] = path.stem                      # recording key as worm_id
        meta = metadata_for_file(path, manifest, raw)
        animal_id = make_animal_id(path, meta, raw)

        # duration / length normalisation inputs
        fps = float(raw["fps"].iloc[0]) if "fps" in raw else np.nan
        n_frames = int(raw["frame"].nunique())
        duration_s = n_frames / fps if fps else np.nan

        plog = dict(filename=path.name, animal_id=animal_id,
                    metadata_source=meta.get("metadata_source"),
                    genotype=meta.get("genotype"), age_day=meta.get("age_day"),
                    rnai_target=meta.get("rnai_target"),
                    magnetic_condition=meta.get("magnetic_condition"),
                    quality=meta.get("quality"), n_frames=n_frames,
                    duration_s=round(duration_s, 2) if duration_s==duration_s else None)

        # ---- exclusion decisions (reported, not silent) ----
        reasons = []
        if cfg.drop_flagged_bad and meta.get("quality") == "flagged_bad":
            reasons.append("flagged_bad")
        if duration_s == duration_s and duration_s < cfg.min_duration_s:
            reasons.append(f"duration<{cfg.min_duration_s}s")
        plog["excluded"] = bool(reasons)
        plog["exclusion_reason"] = ";".join(reasons)
        parse_rows.append(plog)
        if reasons:
            excl.append(dict(filename=path.name, animal_id=animal_id, reasons=reasons))
            continue
        incl.append(dict(filename=path.name, animal_id=animal_id))

        # ---- per-file pipeline: QC -> normalise -> head mask -> kinetics ----
        filt, qc_report = wr.qc_filter(raw, cfg.qc)
        norm, chan_report = wc.apply_normalisation(filt, cfg.channel)
        masked = wk.mask_head(norm)

        common = dict(animal_id=animal_id, recording=path.stem,
                      genotype=meta.get("genotype"), age_day=meta.get("age_day"),
                      rnai_target=meta.get("rnai_target"),
                      magnetic_condition=meta.get("magnetic_condition"),
                      quality=meta.get("quality"))

        rr = wk.release_reuptake(masked, worm_id=path.stem)
        for k, v in common.items():
            rr[k] = v
        rr["background_applied"] = chan_report["background_applied"]
        master.append(rr)

        rs = wk.region_split(masked)
        for k, v in common.items():
            rs[k] = v
        region_frames.append(rs)

        wv = dict(wk.wave_propagation(masked, path.stem))
        wv.update(common)
        wv["duration_s"] = duration_s
        wv["wave_usable"] = bool(wv.get("coherence", 0) >= cfg.min_wave_coherence)
        wave_rows.append(wv)

        rec = dict(common, n_frames=n_frames, duration_s=duration_s,
                   event_rate_hz=len(wk.clean_transients(rr, "confirmatory")) / duration_s
                   if duration_s else np.nan,
                   retention_frac=qc_report.get("retention_frac"),
                   background_applied=chan_report["background_applied"],
                   n_transients=len(rr),
                   n_confirmatory=len(wk.clean_transients(rr, "confirmatory")))
        rec_rows.append(rec)

    master_df = pd.concat(master, ignore_index=True) if master else pd.DataFrame()
    region_df = pd.concat(region_frames, ignore_index=True) if region_frames else pd.DataFrame()
    rec_df = pd.DataFrame(rec_rows)
    wave_df = pd.DataFrame(wave_rows)
    parse_df = pd.DataFrame(parse_rows)

    animal_df = _aggregate_to_animal(master_df, rec_df, cfg)

    inclusion = dict(n_files=len(files), n_included=len(incl), n_excluded=len(excl),
                     included=incl, excluded=excl,
                     group_inference_ok=_group_inference_ok(rec_df))
    return BatchResult(master_transients=master_df, per_region=region_df,
                       per_recording=rec_df, waves=wave_df,
                       animal_summary=animal_df, parse_log=parse_df,
                       inclusion=inclusion, config=_config_dict(cfg))


def _aggregate_to_animal(master: pd.DataFrame, rec: pd.DataFrame,
                         cfg: BatchConfig) -> pd.DataFrame:
    """Per-animal, per-region kinetic summary — the unit of N for stats.
    Transients are aggregated (median) WITHIN each animal before any group test."""
    if master.empty:
        return pd.DataFrame()
    m = wk.clean_transients(master, "confirmatory") if cfg.confirmatory_only else master
    # exclude sub-resolution decays from tau/fall summaries (Fix-3 lesson)
    if "decay_subresolution" in m.columns:
        m_tau = m[~m["decay_subresolution"].astype(bool)]
    else:
        m_tau = m
    keys = ["animal_id", "genotype", "age_day", "rnai_target",
            "magnetic_condition", "region"]
    keys = [k for k in keys if k in m.columns]
    agg = (m.groupby(keys, dropna=False)
             .agg(n_transients=("peak_dff", "size"),
                  median_amp_dff=("amp_dff", "median"),
                  median_rise_s=("rise_time_s", "median"),
                  median_peak_dff=("peak_dff", "median"))
             .reset_index())
    tau = (m_tau.groupby(keys, dropna=False)
                .agg(median_decay_tau_s=("decay_tau_s", "median"),
                     median_fall_1090_s=("fall_1090_s", "median"))
                .reset_index())
    out = agg.merge(tau, on=keys, how="left")
    # attach per-recording event rate (animal-level) if 1 recording/animal
    if not rec.empty and "animal_id" in rec.columns:
        er = rec.groupby("animal_id")["event_rate_hz"].mean().reset_index()
        out = out.merge(er, on="animal_id", how="left")
    return out


def _group_inference_ok(rec: pd.DataFrame, min_animals_per_level: int = 2) -> dict:
    """Guardrail: a grouping AXIS is usable for inference only if it has >=2
    levels, each backed by >=min_animals_per_level distinct animals. Checks
    every experimental axis the user compares on (genotype, age, RNAi target,
    magnetic condition). Otherwise per-recording description only.

    Returns ok=True if AT LEAST ONE axis is usable, and reports each axis."""
    if rec.empty:
        return dict(ok=False, reason="no included recordings", axes={})
    axis_cols = [c for c in ("genotype", "age_day", "rnai_target",
                             "magnetic_condition") if c in rec.columns]
    id_col = "animal_id" if "animal_id" in rec.columns else None
    axes = {}
    usable = []
    for c in axis_cols:
        sub = rec[rec[c].notna()]
        if sub.empty:
            axes[c] = "absent"
            continue
        if id_col:
            per = sub.groupby(c)[id_col].nunique()
        else:
            per = sub.groupby(c).size()
        good_levels = (per >= min_animals_per_level).sum()
        if per.size < 2:
            axes[c] = f"1 level only ({per.index.tolist()})"
        elif good_levels < 2:
            axes[c] = (f"{per.size} levels but <{min_animals_per_level} "
                       f"animals in some (n per level: {per.to_dict()})")
        else:
            axes[c] = f"USABLE ({good_levels} levels, n per level: {per.to_dict()})"
            usable.append(c)
    if usable:
        return dict(ok=True, usable_axes=usable, axes=axes,
                    reason=f"inference OK on: {', '.join(usable)}")
    return dict(ok=False, usable_axes=[], axes=axes,
                reason="no grouping axis has >=2 levels with "
                       f">={min_animals_per_level} animals each; "
                       "per-recording description only, no group inference")


def animal_level_stats(animal_summary: pd.DataFrame, axis: str,
                       metrics: Sequence[str] = ("median_peak_dff",
                                                 "median_amp_dff",
                                                 "median_rise_s",
                                                 "median_decay_tau_s",
                                                 "median_fall_1090_s",
                                                 "event_rate_hz"),
                       region: Optional[str] = None) -> pd.DataFrame:
    """Compare metrics ACROSS ANIMALS on one grouping axis (worm = unit of N).

    Two-level axis -> Mann-Whitney U (rank-biserial effect size).
    >2 levels     -> Kruskal-Wallis.
    Each animal contributes ONE value per metric (already aggregated), so
    transients/segments are never treated as independent replicates.
    """
    from scipy import stats
    df = animal_summary.copy()
    if region is not None and "region" in df.columns:
        df = df[df["region"] == region]
    # collapse regions -> one row per animal per axis level if region not fixed
    if region is None and "region" in df.columns:
        gcols = [c for c in ("animal_id", axis) if c in df.columns]
        df = df.groupby(gcols, dropna=False)[list(metrics)].median().reset_index()
    rows = []
    levels = [lv for lv in df[axis].dropna().unique()]
    for metric in metrics:
        if metric not in df.columns:
            continue
        groups = [df.loc[df[axis] == lv, metric].dropna().values for lv in levels]
        groups = [(lv, g) for lv, g in zip(levels, groups) if len(g) > 0]
        if len(groups) < 2:
            continue
        ns = {lv: len(g) for lv, g in groups}
        if len(groups) == 2:
            (l1, g1), (l2, g2) = groups
            if len(g1) < 1 or len(g2) < 1:
                continue
            U, p = stats.mannwhitneyu(g1, g2, alternative="two-sided")
            rb = 1 - 2 * U / (len(g1) * len(g2))   # rank-biserial
            rows.append(dict(metric=metric, axis=axis, test="Mann-Whitney",
                             level_1=l1, level_2=l2, n=ns,
                             median_1=float(np.median(g1)), median_2=float(np.median(g2)),
                             effect_rank_biserial=float(rb), p_value=float(p)))
        else:
            H, p = stats.kruskal(*[g for _, g in groups])
            rows.append(dict(metric=metric, axis=axis, test="Kruskal-Wallis",
                             levels=[lv for lv, _ in groups], n=ns,
                             statistic=float(H), p_value=float(p)))
    return pd.DataFrame(rows)


def _config_dict(cfg: BatchConfig) -> dict:
    d = dict(f0_percentile=cfg.f0_percentile, drop_flagged_bad=cfg.drop_flagged_bad,
             min_duration_s=cfg.min_duration_s, min_wave_coherence=cfg.min_wave_coherence,
             confirmatory_only=cfg.confirmatory_only,
             channel_roles=cfg.channel.roles,
             reference_channel=cfg.channel.reference_channel)
    return d
