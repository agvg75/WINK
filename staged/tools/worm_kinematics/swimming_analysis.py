"""Single-worm swimming analysis from the DIC tracker's long-format CSV.

Never interpolates across unusable frames. Frequency is estimated separately
inside contiguous usable runs and all gates/reasons are exported.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"app"))
from acquisition import AcquisitionMetadata

REQUIRED = {"worm_id", "frame", "time_s", "segment", "seg_curv_deg",
            "body_length_px", "fps", "needs_help"}


def _truthy(s):
    return s.astype(str).str.lower().isin({"true", "1", "yes"})


def _frequency(t, y, lo=0.2, hi=5.0):
    good = np.isfinite(t) & np.isfinite(y)
    t, y = np.asarray(t)[good], np.asarray(y)[good]
    if len(t) < 8 or t[-1] - t[0] < 2.0:
        return np.nan
    dt = np.median(np.diff(t))
    y = y - np.mean(y)
    f = np.fft.rfftfreq(len(y), dt)
    p = np.abs(np.fft.rfft(y * np.hanning(len(y)))) ** 2
    band = (f >= lo) & (f <= min(hi, 0.45 / dt))
    return float(f[band][np.argmax(p[band])]) if np.any(band) else np.nan


def analyze_csv(csv_path, output_dir=None, amplitude_threshold_deg=8.0,
                length_floor_fraction=0.80, max_gap_frames=1,
                start_frame=None, end_frame=None):
    path = Path(csv_path)
    df = pd.read_csv(path)
    missing = REQUIRED - set(df.columns)
    if missing:
        raise ValueError("Swimming analysis requires columns: " + ", ".join(sorted(missing)))
    mode = str(df.get("assay_mode", pd.Series(["unknown"])).iloc[0]).lower()
    if mode not in {"swimming", "unknown", "nan"}:
        raise ValueError(f"This recording is marked assay_mode={mode!r}, not swimming.")
    for c in ["frame", "time_s", "segment", "seg_curv_deg", "body_length_px", "fps"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    source_min=int(df.frame.min());source_max=int(df.frame.max())
    selected_start=source_min if start_frame is None else int(start_frame)
    selected_end=source_max if end_frame is None else int(end_frame)
    if selected_end<selected_start:raise ValueError("End frame must be at or after start frame.")
    df=df[(df.frame>=selected_start)&(df.frame<=selected_end)].copy()
    if df.empty:raise ValueError("The selected frame range contains no tracker rows.")
    exposure = pd.to_numeric(df.get("exposure_ms", pd.Series([np.nan])), errors="coerce").median()
    acquisition=AcquisitionMetadata(float(df.fps.median()),str(df.get("fps_source",pd.Series(["declared"])).iloc[0]),
        float(pd.to_numeric(df.get("um_per_px",pd.Series([np.nan])),errors="coerce").median()),
        str(df.get("um_per_px_source",pd.Series(["declared"])).iloc[0]),
        None if pd.isna(exposure) else float(exposure),
        "not_applicable" if pd.isna(exposure) else str(df.get("exposure_source",pd.Series(["declared"])).iloc[0])).validate()
    frames = df.groupby("frame", as_index=False).agg(
        time_s=("time_s", "median"), body_length_px=("body_length_px", "median"),
        needs_help=("needs_help", lambda x: bool(_truthy(x).any())),
        curvature_rms_deg=("seg_curv_deg", lambda x: float(np.sqrt(np.nanmean(np.square(x))))))
    ref_len = float(np.nanmax(frames.body_length_px))
    frames["length_fraction"] = frames.body_length_px / ref_len
    frames["usable"] = (~frames.needs_help) & (frames.length_fraction >= length_floor_fraction)
    frames["qc_reason"] = np.where(frames.needs_help, "tracker_needs_help",
                           np.where(frames.length_fraction < length_floor_fraction,
                                    "possible_truncation", "usable"))
    frames["swimming"] = frames.usable & (frames.curvature_rms_deg >= amplitude_threshold_deg)
    # Contiguous run IDs; gaps and unusable frames split runs.
    gap = frames.frame.diff().fillna(1).gt(max_gap_frames)
    frames["run_id"] = ((~frames.usable) | gap | (~frames.usable).shift(fill_value=True)).cumsum()
    segs = sorted(df.segment.dropna().unique())
    mid = segs[len(segs)//3: max(len(segs)//3 + 1, 2*len(segs)//3)]
    run_rows = []
    for rid, fg in frames[frames.usable].groupby("run_id"):
        d = df[df.frame.isin(fg.frame) & df.segment.isin(mid)]
        sig = d.groupby("time_s").seg_curv_deg.mean().reset_index()
        run_rows.append({"run_id": int(rid), "start_s": float(fg.time_s.min()),
                         "end_s": float(fg.time_s.max()), "duration_s": float(fg.time_s.max()-fg.time_s.min()),
                         "frequency_hz": _frequency(sig.time_s.values, sig.seg_curv_deg.values)})
    runs = pd.DataFrame(run_rows)
    usable_df = df[df.frame.isin(frames.loc[frames.usable, "frame"])]
    amp = usable_df.groupby("segment").seg_curv_deg.apply(
        lambda x: float(np.sqrt(np.nanmean(np.square(x))))).rename("curvature_rms_deg").reset_index()
    thirds = max(1, len(segs)//3)
    ant = amp[amp.segment.isin(segs[:thirds])].curvature_rms_deg.mean()
    post = amp[amp.segment.isin(segs[-thirds:])].curvature_rms_deg.mean()
    # Circular phase from the dominant-frequency Fourier coefficient.
    phase_deg = stability = np.nan
    valid_freq = runs.frequency_hz.dropna() if not runs.empty else pd.Series(dtype=float)
    freq = float(np.average(valid_freq, weights=runs.loc[valid_freq.index, "duration_s"])) if len(valid_freq) else np.nan
    if np.isfinite(freq) and len(segs) >= 2:
        wide = usable_df.pivot_table(index="time_s", columns="segment", values="seg_curv_deg")
        if len(wide) >= 8:
            t = wide.index.to_numpy(); a = wide[segs[:thirds]].mean(axis=1).to_numpy(); p = wide[segs[-thirds:]].mean(axis=1).to_numpy()
            ca = np.nansum((a-np.nanmean(a))*np.exp(-2j*np.pi*freq*t)); cp = np.nansum((p-np.nanmean(p))*np.exp(-2j*np.pi*freq*t))
            phase_deg = float(np.angle(cp/ca, deg=True)); stability = float(min(abs(ca), abs(cp))/max(abs(ca), abs(cp))) if max(abs(ca), abs(cp)) else np.nan
    summary = {
        "recording": path.name, "worm_id": str(df.worm_id.iloc[0]), "assay_mode": mode,
        **acquisition.as_columns(),
        "usable_fraction": float(frames.usable.mean()), "swimming_fraction_of_usable": float(frames.loc[frames.usable, "swimming"].mean()) if frames.usable.any() else None,
        "frequency_hz": None if not np.isfinite(freq) else freq,
        "frequency_sd_hz": float(valid_freq.std(ddof=1)) if len(valid_freq) > 1 else None,
        "posterior_anterior_amplitude_ratio": None if not np.isfinite(ant) or ant == 0 else float(post/ant),
        "head_tail_phase_deg": None if not np.isfinite(phase_deg) else phase_deg,
        "phase_strength_balance": None if not np.isfinite(stability) else stability,
        "dv_outputs_supported": bool(pd.notna(exposure) and exposure <= 5.0),
        "dv_gate_reason": "supported_by_declared_exposure" if pd.notna(exposure) and exposure <= 5.0 else "exposure_missing_or_above_5_ms",
        "amplitude_threshold_deg": float(amplitude_threshold_deg), "length_floor_fraction": float(length_floor_fraction),
        "source_frame_start":source_min,"source_frame_end":source_max,
        "selected_frame_start":selected_start,"selected_frame_end":selected_end,
        "note": "Swimming occupancy is the fraction of usable frames above the declared curvature-amplitude threshold; it is not inferred during unusable frames."
    }
    out = Path(output_dir) if output_dir else path.parent / f"{path.stem}_swimming_results"
    out.mkdir(parents=True, exist_ok=True)
    frames.to_csv(out / "frame_qc_and_state.csv", index=False)
    runs.to_csv(out / "contiguous_run_frequency.csv", index=False)
    amp.to_csv(out / "segment_amplitude_profile.csv", index=False)
    (out / "swimming_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    pd.DataFrame([summary]).to_csv(out / "swimming_summary.csv", index=False)
    return summary, out
