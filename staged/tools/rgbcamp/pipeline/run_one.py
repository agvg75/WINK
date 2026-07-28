"""
run_one.py
==========
Analyse ONE exported recording CSV: load -> QC -> channel normalisation
(background + dF/F0) -> head mask -> kinetics. Writes tables and figures to
an output folder created BESIDE the input file -- no batch/glob path, no
folder of other recordings required.

    python run_one.py path/to/recording.csv

Writes <recording_stem>_output/ next to the input, containing:
  qc_report.json             QC log + channel-normalisation report
  Per active channel (green/red/blue; Stage 2a/2b), suffixed _<channel>:
    region_split, dorsal_ventral, resting_calcium, contraction_state,
    release_reuptake, wave_propagation, curvature_phase_lag,
    cycle_average_anterior/posterior
    fig_kymograph, fig_release_reuptake, fig_cycle_average
  Coupling (Stage 2b): interchannel_timing.csv (sub-frame, green_vs_blue and
    green_vs_red -- replaces the retired intersignal_timing), plus the
    unchanged green-implicit legacy views amplitude_coupling.csv and
    movement_coupling.csv
  Kinematics (Stage 3a), NOT head-masked -- posture is valid over the whole
    body: undulation_descriptors.csv (body-wave frequency/speed/direction/
    wavelength/bend amplitude), locomotion_summary.csv (forward/backward
    fraction, reversals, signed crawl speed, angular velocity, omega turns),
    fig_curvature_kymograph.png (full body, own colour scale)

Green and red are head-masked (segments 0-7 excluded); blue is not masked in
the head and so has a wider valid range there -- see worm_kinetics.py's
per-channel head_segments docs and mask_head(). Kinematics columns
(seg_curv_deg, axial_vel_px_s, angular_vel_deg_s, etc.) are untouched by that
mask and are read straight from `masked` -- see undulation_descriptors() /
locomotion_summary() docstrings.

This is the entry point behind run_one.bat (double-click launcher with a file
picker) -- see run_one.bat / run_one_launcher.py in this folder.

analyse_one() returns an AnalysisResult (tables, figure paths, qc/channel
reports) so this is also the ONE computation path shared with the results
browser (results_browser.py / Browse_Recording_Results.bat) -- the browser
never re-implements the analysis, only reads this object.
"""
from __future__ import annotations

import json
import sys
import os
import traceback
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import worm_rgbcamp_analysis as wa
import worm_channels as wc
import worm_kinetics as wk


@dataclass
class AnalysisResult:
    """Everything one call to analyse_one() computed, in memory. This is the
    single computation path shared by the CLI/launcher (run_one.bat) and the
    results browser (Browse_Recording_Results.bat) -- neither re-implements
    the analysis; both just read this object (or the files it also writes)."""
    csv_path: Path
    out_dir: Path
    worm_id: str
    qc_report: dict
    channel_report: dict
    tables: dict           # name -> DataFrame (present only if computed without error)
    figures: dict           # name -> Path (present only if the figure was actually written)
    log: list = field(default_factory=list)


def analyse_one(csv_path: str | Path, out_dir: str | Path | None = None) -> AnalysisResult:
    csv_path = Path(csv_path)
    out_dir = Path(out_dir) if out_dir is not None else csv_path.parent / f"{csv_path.stem}_output"
    out_dir.mkdir(parents=True, exist_ok=True)

    log = [f"Loading {csv_path.name}"]
    raw = wa.load_extracted(csv_path)
    worm_id = str(raw["worm_id"].iloc[0])

    filt, qc_report = wa.qc_filter(raw)
    log.append(f"QC: kept {qc_report['n_rows_kept']}/{qc_report['n_rows_in']} rows "
               f"(retention {qc_report['retention_frac']:.2f})")

    # Unlike the batch's DMD default (green-only), a single-recording sanity check
    # should surface all three channels so inter-channel kinetics (intersignal_timing,
    # amplitude_coupling) work out of the box on a normal 3-channel RGBCaMP export.
    chan_cfg = wc.ChannelConfig(roles={"green": wc.ROLE_ACTIVITY, "red": wc.ROLE_ACTIVITY,
                                       "blue": wc.ROLE_ACTIVITY})
    norm, chan_report = wc.apply_normalisation(filt, chan_cfg)
    log.append(f"Channel normalisation: background_applied={chan_report['background_applied']}, "
               f"reference_channel={chan_report['reference_channel']}")

    masked = wk.mask_head(norm)
    log.append(f"Head mask applied (segments {wk.HEAD_SEGMENTS})")

    def _write_qc():
        (out_dir / "qc_report.json").write_text(json.dumps(
            dict(qc_report=qc_report, channel_report=chan_report, worm_id=worm_id, log=log),
            indent=2, default=str))
    _write_qc()

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

    # ---- calcium, per active channel (Stage 2a) ----
    # ONE loop over active channels, not copied per-channel code paths. Green
    # and red stay head-masked (HEAD_SEGMENTS); blue is not masked there (see
    # mask_head / worm_kinetics per-channel docs), so it gets head_segments=()
    # and keeps a wider valid range. curvature_phase_lag joins this loop
    # (Stage 2b: the phase upgrade of amplitude_coupling, computed per channel
    # like the rest of calcium). amplitude_coupling and movement_coupling stay
    # green-implicit, unchanged, kept as the legacy correlation-only views.
    active_channels = chan_cfg.activity_channels
    log.append(f"Per-channel calcium loop: {active_channels}")

    def _head_segments_for(ch):
        return () if ch == "blue" else wk.HEAD_SEGMENTS

    for ch in active_channels:
        hs = _head_segments_for(ch)
        val = f"{ch}_dff"
        bgsub_val = f"{ch}_bgsub"

        _try(f"region_split_{ch}",
            lambda val=val, hs=hs: wk.region_split(masked, value=val, head_segments=hs))
        _try(f"dorsal_ventral_{ch}",
            lambda val=val: wk.dorsal_ventral_split(masked, value=val))
        _try(f"resting_calcium_{ch}",
            lambda bgsub_val=bgsub_val, hs=hs: wk.resting_calcium(masked, value=bgsub_val, head_segments=hs))
        _try(f"contraction_state_{ch}",
            lambda val=val, hs=hs: wk.contraction_state(masked, value=val, head_segments=hs))
        _try(f"release_reuptake_{ch}",
            lambda val=val, hs=hs: wk.release_reuptake(masked, worm_id, value=val, head_segments=hs))
        _try(f"wave_propagation_{ch}",
            lambda val=val, hs=hs: wk.wave_propagation(masked, worm_id, value=val, head_segments=hs))
        _try(f"curvature_phase_lag_{ch}",
            lambda val=val, hs=hs: wk.curvature_phase_lag(masked, worm_id, value=val, head_segments=hs))
        # Stage 3c: bending vs propulsion, side by side, for this channel --
        # reuses curvature_phase_lag (bending half) plus a per-channel
        # calcium-vs-translation correlation (propulsion half).
        _try(f"calcium_output_decomposition_{ch}",
            lambda val=val, hs=hs: wk.calcium_output_decomposition(masked, worm_id, value=val, head_segments=hs))

        for region in ("anterior", "posterior"):
            def _cycle(region=region, val=val, hs=hs):
                d = wk.cycle_average(masked, worm_id, region=region, value=val, head_segments=hs)
                if d.get("n_cycles", 0) == 0:
                    return pd.DataFrame([{"region": region, "n_cycles": 0}])
                return pd.DataFrame({
                    "region": region, "phase_rad": d["phase"],
                    "ca_mean": d["ca_mean"], "ca_sem": d["ca_sem"],
                    "curv_mean": d["curv_mean"],
                })
            _try(f"cycle_average_{region}_{ch}", _cycle)

    # ---- kinematics (Stage 3a) ----
    # Posture/velocity only -- NOT head-masked (posture is valid over the
    # whole body 0-23; the head mask exists only for green/red calcium
    # bleed-through). Gate on midline-tracking quality instead, which these
    # two functions do internally (eigen_fit_quality, self_approach_flag,
    # partial_flag). `masked` is safe to reuse here unchanged: mask_head()
    # only NaNs columns starting with green/red or containing RG/GB/RB, none
    # of which match seg_curv_deg/axial_vel_px_s/angular_vel_deg_s/etc.
    _try("undulation_descriptors", lambda: wk.undulation_descriptors(masked, worm_id))
    _try("locomotion_summary", lambda: wk.locomotion_summary(masked, worm_id))

    # ---- coupling ----
    # intersignal_timing is RETIRED (Stage 2b): its plugin_lag_ms and
    # integer-frame xcorr_lag_s were not sub-frame capable and are no longer
    # computed or reported here. interchannel_timing replaces it.
    _try("interchannel_timing", lambda: wk.interchannel_timing(masked, worm_id))
    _try("amplitude_coupling", lambda: wk.amplitude_coupling(masked, worm_id))
    _try("movement_coupling", lambda: wk.movement_coupling(masked, worm_id))

    # ---- neuromechanical chain (Stage 3c): calcium -> curvature -> ----
    # ---- translation. Not head-masked (posture-derived), like Stage 3a. ----
    _try("curvature_to_translation", lambda: wk.curvature_to_translation(masked, worm_id))
    _try("propulsion_efficiency", lambda: wk.propulsion_efficiency(masked, worm_id))

    for name, df in tables.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)

    figures = _make_figures(masked, worm_id, active_channels, tables, out_dir, log)

    _write_qc()
    print("\n".join(log))
    print(f"Wrote {len(tables)} table(s) + figures to {out_dir}")
    return AnalysisResult(csv_path=csv_path, out_dir=out_dir, worm_id=worm_id,
                          qc_report=qc_report, channel_report=chan_report,
                          tables=tables, figures=figures, log=log)


def _make_figures(masked: pd.DataFrame, worm_id: str, active_channels: list, tables: dict,
                  out_dir: Path, log: list) -> dict:
    figures: dict[str, Path] = {}
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # --- curvature kymograph (Stage 3a kinematics) ---
    # Full body (0-23), NOT head-masked -- posture is valid there. Its own
    # color scale (nanmin/nanmax of this array only), never shared with a
    # calcium kymograph's scale.
    try:
        Mc, seg_axis_c, frames_c = wa.kymograph(masked, worm_id, value="seg_curv_deg")
        if np.isfinite(Mc).any():
            vmin_c, vmax_c = float(np.nanmin(Mc)), float(np.nanmax(Mc))
        else:
            vmin_c, vmax_c = None, None
        fig, ax = plt.subplots(figsize=(7, 4))
        im = ax.imshow(Mc, aspect="auto", origin="lower",
                       extent=[frames_c.min(), frames_c.max(), seg_axis_c.min(), seg_axis_c.max()],
                       cmap="RdBu_r", vmin=vmin_c, vmax=vmax_c)
        ax.set_xlabel("frame"); ax.set_ylabel("segment (0=head)")
        ax.set_title(f"{worm_id}: body curvature kymograph (full body, not head-masked)")
        fig.colorbar(im, ax=ax, label="curvature (deg)")
        fig.tight_layout()
        p = out_dir / "fig_curvature_kymograph.png"
        fig.savefig(p, dpi=150)
        plt.close(fig)
        figures["fig_curvature_kymograph"] = p
        log.append("  fig_curvature_kymograph.png written")
    except Exception as e:
        log.append(f"  fig_curvature_kymograph.png FAILED ({e})")

    for ch in active_channels:
        val = f"{ch}_dff"
        hs = () if ch == "blue" else wk.HEAD_SEGMENTS

        # --- kymograph ---
        # Colour scale fix: vmin/vmax are computed explicitly from THIS array
        # (nanmin/nanmax), i.e. only the masked data actually plotted here --
        # never the whole unmasked frame. For green/red this already excludes
        # the head (NaN there); for blue the head is real, valid data and is
        # included on its own terms, not stretched against a discarded value
        # elsewhere.
        try:
            M, seg_axis, frames = wa.kymograph(masked, worm_id, value=val)
            if np.isfinite(M).any():
                vmin, vmax = float(np.nanmin(M)), float(np.nanmax(M))
            else:
                vmin, vmax = None, None
            fig, ax = plt.subplots(figsize=(7, 4))
            im = ax.imshow(M, aspect="auto", origin="lower",
                           extent=[frames.min(), frames.max(), seg_axis.min(), seg_axis.max()],
                           cmap="viridis", vmin=vmin, vmax=vmax)
            ax.set_xlabel("frame"); ax.set_ylabel("segment (0=head)")
            ax.set_title(f"{worm_id}: {ch} dF/F0 kymograph")
            fig.colorbar(im, ax=ax, label="dF/F0")
            fig.tight_layout()
            p = out_dir / f"fig_kymograph_{ch}.png"
            fig.savefig(p, dpi=150)
            plt.close(fig)
            figures[f"fig_kymograph_{ch}"] = p
            log.append(f"  fig_kymograph_{ch}.png written")
        except Exception as e:
            log.append(f"  fig_kymograph_{ch}.png FAILED ({e})")

        # --- release/reuptake summary ---
        try:
            rr = tables.get(f"release_reuptake_{ch}")
            if rr is not None and len(rr) and "rise_time_s" in rr.columns:
                fig, ax = plt.subplots(figsize=(5, 5))
                conf = rr.get("confirmatory", pd.Series([False] * len(rr)))
                ax.scatter(rr["rise_time_s"], rr["fall_1090_s"], c=np.where(conf, "#2166ac", "#bbb"),
                          s=25, label=None)
                lim = np.nanmax([rr["rise_time_s"].max(), rr["fall_1090_s"].max(), 0.1]) * 1.1
                ax.plot([0, lim], [0, lim], ls=":", color="#999")
                ax.set_xlabel("10-90% rise time (s)"); ax.set_ylabel("10-90% fall time (s)")
                ax.set_title(f"{worm_id}: {ch} release vs reuptake (blue dots=confirmatory)")
                fig.tight_layout()
                p = out_dir / f"fig_release_reuptake_{ch}.png"
                fig.savefig(p, dpi=150)
                plt.close(fig)
                figures[f"fig_release_reuptake_{ch}"] = p
                log.append(f"  fig_release_reuptake_{ch}.png written")
        except Exception as e:
            log.append(f"  fig_release_reuptake_{ch}.png FAILED ({e})")

        # --- cycle average waveform ---
        try:
            fig, axes = plt.subplots(1, 2, figsize=(9, 3.5), sharey=True)
            any_drawn = False
            for ax, region in zip(axes, ("anterior", "posterior")):
                df = tables.get(f"cycle_average_{region}_{ch}")
                if df is not None and "ca_mean" in df.columns:
                    ax.plot(df["phase_rad"], df["ca_mean"], color="#2166ac")
                    ax.fill_between(df["phase_rad"], df["ca_mean"] - df["ca_sem"],
                                    df["ca_mean"] + df["ca_sem"], color="#2166ac", alpha=0.2)
                    any_drawn = True
                ax.set_title(region); ax.set_xlabel("phase (rad)")
            axes[0].set_ylabel(f"{ch} dF/F0 (phase-locked mean)")
            fig.tight_layout()
            if any_drawn:
                p = out_dir / f"fig_cycle_average_{ch}.png"
                fig.savefig(p, dpi=150)
                figures[f"fig_cycle_average_{ch}"] = p
                log.append(f"  fig_cycle_average_{ch}.png written")
            plt.close(fig)
        except Exception as e:
            log.append(f"  fig_cycle_average_{ch}.png FAILED ({e})")

        # --- neuromechanical overlay, time axis (Stage 3c) ---
        # Calcium + curvature + velocity on a shared time axis, annotated
        # with the bending/propulsion lags from calcium_output_decomposition
        # (the SAME numbers reported in that table, not re-derived here).
        # Whole reliable body for this channel (hs), not head-masked segments
        # excluded the same way every other per-channel view already is.
        try:
            d = masked[(masked["worm_id"] == worm_id) & (~masked["segment"].isin(hs))]
            per_frame = d.groupby("frame").agg(
                ca=(val, "mean"),
                curv=("seg_curv_deg", lambda s: np.nanmean(np.abs(s))),
                vel=("axial_vel_px_s", lambda s: np.nanmean(np.abs(s))),
                time_s=("time_s", "first"),
            ).reset_index().sort_values("frame")
            if len(per_frame) > 1:
                cod = tables.get(f"calcium_output_decomposition_{ch}")
                bend_lag = (float(cod["bending_lag_s"].iloc[0])
                           if cod is not None and len(cod) and bool(cod["bending_resolved"].iloc[0])
                           else None)
                prop_lag = (float(cod["propulsion_lag_s"].iloc[0])
                           if cod is not None and len(cod) and bool(cod["propulsion_resolved"].iloc[0])
                           else None)
                fig, axes = plt.subplots(3, 1, figsize=(9, 6), sharex=True)
                t = per_frame["time_s"].to_numpy()
                axes[0].plot(t, per_frame["ca"], color="#2166ac")
                axes[0].set_ylabel(f"{ch} dF/F0")
                axes[1].plot(t, per_frame["curv"], color="#b2182b")
                axes[1].set_ylabel("|curvature| (deg)")
                axes[2].plot(t, per_frame["vel"], color="#1a9850")
                axes[2].set_ylabel("|axial vel| (px/s)")
                axes[2].set_xlabel("time (s)")
                lag_txt = (f"calcium->curvature lag_s={bend_lag:.2f}" if bend_lag is not None
                          else "calcium->curvature lag: unresolved") + "; " + \
                         (f"calcium->translation lag_s={prop_lag:.2f}" if prop_lag is not None
                          else "calcium->translation lag: unresolved")
                axes[0].set_title(f"{worm_id}: {ch} neuromechanical chain (calcium -> curvature -> "
                                  f"translation)\n{lag_txt}", fontsize=9)
                fig.tight_layout()
                p = out_dir / f"fig_neuromech_overlay_{ch}.png"
                fig.savefig(p, dpi=150)
                figures[f"fig_neuromech_overlay_{ch}"] = p
                log.append(f"  fig_neuromech_overlay_{ch}.png written")
                plt.close(fig)
        except Exception as e:
            log.append(f"  fig_neuromech_overlay_{ch}.png FAILED ({e})")

        # --- neuromechanical overlay, phase axis (Stage 3c) ---
        # Reuses cycle_average()'s phase-locked averaging (extended with
        # vel_col in Stage 3c) rather than reimplementing cycle detection --
        # robust MAGNITUDE form only. Bend-to-thrust PHASE-RESOLVED timing
        # (exactly when in the stroke thrust peaks) is explicitly deferred to
        # a higher frame rate and is NOT claimed by this plot -- stated on
        # the figure itself, not just in code, so it can't be silently
        # mistaken for a resolved sub-cycle timing result.
        try:
            fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharex=True)
            any_drawn = False
            for ax, region in zip(axes, ("anterior", "posterior")):
                d3c = wk.cycle_average(masked, worm_id, region=region, value=val,
                                       vel_col="axial_vel_px_s", head_segments=hs)
                if d3c.get("n_cycles", 0) == 0 or "ca_mean" not in d3c:
                    ax.set_title(f"{region} (no resolved cycles)")
                    continue
                ax.plot(d3c["phase"], d3c["ca_mean"], color="#2166ac", label="calcium")
                ax2 = ax.twinx()
                ax2.plot(d3c["phase"], d3c["curv_mean"], color="#b2182b", label="|curvature|")
                if "vel_mean" in d3c:
                    ax3 = ax.twinx()
                    ax3.spines["right"].set_position(("axes", 1.18))
                    ax3.plot(d3c["phase"], d3c["vel_mean"], color="#1a9850", label="|velocity|")
                ax.set_title(region); ax.set_xlabel("phase (rad)")
                any_drawn = True
            axes[0].set_ylabel(f"{ch} dF/F0", color="#2166ac")
            fig.suptitle(f"{worm_id}: {ch} phase-locked overlay (robust magnitude form only -- "
                        "bend-to-thrust PHASE-RESOLVED timing deferred to higher frame rate, "
                        "not shown here)", fontsize=8.5)
            fig.tight_layout(rect=[0, 0, 1, 0.94])
            if any_drawn:
                p = out_dir / f"fig_neuromech_phase_{ch}.png"
                fig.savefig(p, dpi=150)
                figures[f"fig_neuromech_phase_{ch}"] = p
                log.append(f"  fig_neuromech_phase_{ch}.png written")
            plt.close(fig)
        except Exception as e:
            log.append(f"  fig_neuromech_phase_{ch}.png FAILED ({e})")

    return figures


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    csv_path = Path(sys.argv[1])
    if not csv_path.exists():
        print(f"ERROR: {csv_path} does not exist"); sys.exit(1)
    out_dir = sys.argv[2] if len(sys.argv) > 2 else None
    try:
        analyse_one(csv_path, out_dir)
    except Exception:
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
