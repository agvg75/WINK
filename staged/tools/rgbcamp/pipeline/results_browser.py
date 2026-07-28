"""
results_browser.py
===================
Single Recording Results Browser (Stage 1).

A desktop window to select, view, copy, and export one recording's results,
with honest labeling. Reuses run_one.analyse_one() for ALL computation --
this module never re-implements or re-derives an analysis, it only presents
what run_one already computed (one analysis path, not two).

Scope (Stage 1, per RGBCaMP Single Recording Results Browser handoff):
  - Descriptive and WITHIN-ANIMAL results only, from one recording.
  - No between-animal, genotype, or isoform comparison anywhere. An operator
    looking for one gets a clear deferral message (see GROUP_DEFERRAL_TEXT);
    that surface is a separate "group tool" activated only by labeled
    multi-animal data, and is out of scope here by design.
  - Views are grouped under Calcium / Kinematics / Coupling. Only views with
    actually-computed, valid data are listed -- an empty or all-placeholder
    result is never shown as if it were clean.
  - Kinematics (Stage 3a): posture/velocity views, NOT head-masked (posture
    is valid over the whole body) -- undulation descriptors, locomotion
    summary (forward/backward/reversals/turns), full-body curvature
    kymograph. See build_kinematics_views() and worm_kinetics.py's
    undulation_descriptors()/locomotion_summary() docstrings.

Launch: double-click Browse_Recording_Results.bat at the tracker root (opens
a file picker, then this window, via the pinned venv, no terminal). Can also
be run directly for testing: `python results_browser.py <csv_path>`.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd

import run_one

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from PIL import Image, ImageTk

GROUP_DEFERRAL_TEXT = (
    "Group, genotype, and isoform comparisons are not available here.\n\n"
    "This browser shows ONE recording. Between-animal statistics require "
    "labeled multi-animal data (genotype, age, RNAi target per animal) and "
    "live in the separate group tool, which only activates once that "
    "labeled data exists.\n\n"
    "Nothing computed for a single recording can honestly answer a group "
    "question, so this tool does not show one."
)

CI_Z = 1.96  # normal-approximation 95% CI


# --------------------------------------------------------------------------- #
# View catalog: maps each run_one table/figure to a domain, a validity check,
# and the caveat banner text shown at the top whenever the view is rendered.
# --------------------------------------------------------------------------- #
@dataclass
class ViewDef:
    key: str                      # name in result.tables or result.figures
    label: str                    # tree label
    domain: str                   # "Calcium" | "Kinematics" | "Coupling"
    kind: str                     # "table" | "figure"
    caveat: str                   # validity banner text
    n_label: str = ""             # what a row/n represents, for table views
    metric_cols: Optional[list] = None   # numeric columns to summarise; None = all numeric
    is_valid: Callable[["run_one.AnalysisResult"], bool] = None
    channel: Optional[str] = None  # "green"/"red"/"blue" for per-channel Calcium views; else None


def _has_rows(result, key):
    df = result.tables.get(key)
    return df is not None and len(df) > 0


def _has_col_nonnull(result, key, col):
    df = result.tables.get(key)
    return df is not None and len(df) > 0 and col in df.columns and df[col].notna().any()


def _has_flag(result, key, col="valid"):
    df = result.tables.get(key)
    return (df is not None and len(df) > 0 and col in df.columns
            and df[col].astype(bool).any())


def _has_valid_flag(result, key):
    return _has_flag(result, key, "valid")


def _has_figure(result, key):
    return result.figures.get(key) is not None


# --------------------------------------------------------------------------- #
# Per-channel reporter identity (Stage 2a). This is set by the PI, not guessed
# here -- use it verbatim. Any channel not in this dict falls back to an
# explicit "identity to confirm" caveat rather than assuming muscle calcium.
# --------------------------------------------------------------------------- #
CHANNEL_DISPLAY = {"green": "Green", "red": "Red", "blue": "Blue"}

CHANNEL_REPORTER = {
    "green": "Green is cytosolic GCaMP, the primary muscle calcium readout.",
    "red": ("Red is a mitochondrial calcium reporter: it reflects mitochondrial calcium, "
           "a different compartment from cytosolic calcium, and must not be read as "
           "muscle activation."),
    "blue": ("Blue is an ER calcium indicator (BlueCaMP-X), reporting ER store calcium, "
            "which can move opposite to cytosolic calcium in phase -- this is not a "
            "muscle activation signal."),
}
CHANNEL_REPORTER_FALLBACK = ("Reporter identity to confirm for this channel -- do not "
                            "assume muscle calcium without PI confirmation.")

CHANNEL_HEAD_NOTE = {
    "green": "Head-masked (segments 0-7 excluded).",
    "red": "Head-masked (segments 0-7 excluded; pharyngeal there, which is why it is masked).",
    "blue": "NOT head-masked: carries valid data in segments 0-7 where green/red do not.",
}


def channel_caveat(ch: str) -> str:
    reporter = CHANNEL_REPORTER.get(ch, CHANNEL_REPORTER_FALLBACK)
    head = CHANNEL_HEAD_NOTE.get(ch, "Head-masking status for this channel: confirm before "
                                     "interpreting segments 0-7.")
    return f"{reporter} {head}"


# --------------------------------------------------------------------------- #
# Per-channel calcium view templates (Stage 2a). Expanded into one ViewDef per
# active channel by build_view_catalog() below -- one definition, not three
# copy-pasted per-channel blocks, mirroring the per-channel loop in run_one.py.
# --------------------------------------------------------------------------- #
@dataclass
class _CalciumTemplate:
    key_base: str
    label_base: str
    kind: str
    caveat_fragment: str
    n_label: str = ""
    metric_cols: Optional[list] = None
    validity: str = "rows"   # "rows" | "valid_flag" | "col:<name>" | "figure"


CALCIUM_TEMPLATES = [
    _CalciumTemplate(
        key_base="release_reuptake", label_base="Release & reuptake kinetics",
        kind="table", n_label="per transient",
        metric_cols=["rise_time_s", "time_to_peak_s", "decay_tau_s", "fall_1090_s",
                    "amp_dff", "peak_dff", "reuptake_over_release", "decay_r2",
                    "confirmatory", "decay_subresolution", "decay_incomplete",
                    "tau_extrapolated", "onset_at_boundary"],
        caveat_fragment=("Per-transient rise/decay kinetics. Decay below ~1.5 sampling "
                         "intervals is flagged decay_subresolution -- the frame rate "
                         "cannot resolve it, filter to confirmatory before trusting a "
                         "tau value. Descriptive, within this recording only; n is "
                         "transients, not animals."),
    ),
    _CalciumTemplate(
        key_base="region_split", label_base="Region comparison (anterior vs posterior)",
        kind="table", n_label="per region (segments pooled within region)",
        metric_cols=["mean", "p95", "active_frac", "n"],
        caveat_fragment=("Anterior vs posterior within THIS recording only -- not a "
                         "between-animal or genotype comparison."),
    ),
    _CalciumTemplate(
        key_base="dorsal_ventral", label_base="Region comparison (dorsal vs ventral)",
        kind="table", n_label="per hemisegment (segments pooled)",
        metric_cols=["mean", "p95", "active_frac", "n"],
        caveat_fragment=("Dorsal vs ventral within THIS recording only. Dorsal and "
                         "ventral body-wall muscle alternate in antiphase during "
                         "undulation, so a real signal is expected to be reciprocal, "
                         "not equal. Only shown when the extractor resolved true "
                         "dorsal/ventral identity, not the generic L/R fallback."),
    ),
    _CalciumTemplate(
        key_base="resting_calcium", label_base="Resting calcium",
        kind="table", n_label="per region", validity="valid_flag",
        metric_cols=["resting_value", "n"],
        caveat_fragment=("Resting level from the background-subtracted baseline (10th "
                         "percentile over time) or the resting ratio when a "
                         "calcium-insensitive reference is designated -- NEVER from "
                         "dF/F0, which sets the baseline to zero by construction and so "
                         "cannot show a resting shift. 8-bit source and no "
                         "calcium-insensitive reference in the current construct: "
                         "absolute resting levels are less comparable across recordings, "
                         "pending an mCherry reference -- not fully cross-comparable."),
    ),
    _CalciumTemplate(
        key_base="contraction_state", label_base="Contraction state (Mann-Whitney)",
        kind="table", n_label="per hemisegment (n_con/n_rel = segment-frames)",
        metric_cols=["contracted_mean", "relaxed_mean", "diff", "rank_biserial", "p",
                    "n_con", "n_rel"],
        caveat_fragment=("Within-recording Mann-Whitney U comparing calcium in "
                         "contracted vs relaxed segment-frames (top/bottom curvature "
                         "tercile), pooled across reliable segments -- a within-animal "
                         "test, not a between-animal one."),
    ),
    _CalciumTemplate(
        key_base="wave_propagation", label_base="Calcium wave propagation",
        kind="table", n_label="one summary per recording (n_frames)", validity="col:coherence",
        metric_cols=["dominant_freq_hz", "wave_speed_seg_per_s", "coherence", "n_frames"],
        caveat_fragment=("Wave direction reflects the worm's locomotion heading, not a "
                         "fixed anatomical frame. Speed and direction are only "
                         "meaningful when coherence is high (roughly >=0.5); low "
                         "coherence means the pattern is not wave-organised in this "
                         "clip, not that the wave is slow."),
    ),
    _CalciumTemplate(
        key_base="fig_kymograph", label_base="Kymograph", kind="figure", validity="figure",
        caveat_fragment=("Colour scale is rescaled to the masked data actually shown "
                         "here, per channel -- never the full unmasked range, so "
                         "discarded (or, for blue, legitimately-included) head "
                         "brightness elsewhere cannot wash out the body signal."),
    ),
    _CalciumTemplate(
        key_base="fig_release_reuptake", label_base="Release vs reuptake plot",
        kind="figure", validity="figure",
        caveat_fragment=("Same data as the Release & reuptake kinetics table. Blue "
                         "points are confirmatory transients (R^2>=0.7, in-window, no "
                         "boundary flag); grey points are exploratory only -- do not "
                         "read them as equally trustworthy."),
    ),
    _CalciumTemplate(
        key_base="fig_cycle_average", label_base="Cycle-average waveform",
        kind="figure", validity="figure",
        caveat_fragment=("Phase-locked average over body-bend cycles (curvature "
                         "oscillation defines cycle boundaries). Shown as a figure, "
                         "not a flattened table, because averaging across phase bins "
                         "would erase the waveform shape that is the point of this "
                         "view. Within this recording's cycles only."),
    ),
]


def _validity_fn(validity: str, key: str) -> Callable:
    if validity == "figure":
        return lambda r, key=key: _has_figure(r, key)
    if validity == "valid_flag":
        return lambda r, key=key: _has_flag(r, key, "valid")
    if validity == "resolved_flag":
        return lambda r, key=key: _has_flag(r, key, "resolved")
    if validity.startswith("col:"):
        col = validity.split(":", 1)[1]
        return lambda r, key=key, col=col: _has_col_nonnull(r, key, col)
    return lambda r, key=key: _has_rows(r, key)


def build_calcium_views(channels=("green", "red", "blue")) -> list:
    views = []
    for ch in channels:
        cav = channel_caveat(ch)
        for t in CALCIUM_TEMPLATES:
            key = f"{t.key_base}_{ch}"
            views.append(ViewDef(
                key=key, label=t.label_base, domain="Calcium", kind=t.kind,
                caveat=f"{cav} {t.caveat_fragment}", n_label=t.n_label,
                metric_cols=t.metric_cols, is_valid=_validity_fn(t.validity, key),
                channel=ch,
            ))
    return views


KINEMATICS_CAVEAT_PREFIX = (
    "Posture-only: NOT head-masked. The calcium head mask exists only because "
    "green/red bleed through the pharynx there -- posture is valid over the "
    "whole body (segments 0-23) and is gated on midline-tracking quality "
    "instead (eigen_fit_quality, partial_flag, length flags, "
    "self_approach_flag), never on head segment."
)


# --------------------------------------------------------------------------- #
# Kinematics (Stage 3a). Posture/velocity only, not head-masked -- see
# undulation_descriptors() / locomotion_summary() in worm_kinetics.py.
# --------------------------------------------------------------------------- #
def build_kinematics_views() -> list:
    views = []

    views.append(ViewDef(
        key="undulation_descriptors", label="Undulation descriptors (body wave)",
        domain="Kinematics", kind="table",
        n_label="one summary per recording (n_frames)",
        metric_cols=["dominant_freq_hz", "wave_speed_seg_per_s", "wavelength_segments",
                    "bend_amplitude_deg", "direction", "coherence"],
        caveat=(f"{KINEMATICS_CAVEAT_PREFIX} Body-bend wave frequency, speed, direction, "
               "wavelength, and amplitude, from the SAME phase-gradient estimator as the "
               "calcium wave (wave_propagation), applied to curvature instead of dF/F0. "
               "wavelength_segments comes directly from the fitted phase slope, not by "
               "dividing speed by a possibly near-zero frequency. Honesty guard: if no "
               "coherent body wave is detected (resolved=False), every descriptor here is "
               "NaN, never a fabricated wavelength or amplitude from a wave that wasn't "
               "actually found -- check resolved and coherence before trusting a value."),
        is_valid=_validity_fn("resolved_flag", "undulation_descriptors"),
    ))

    views.append(ViewDef(
        key="locomotion_summary", label="Locomotion summary (forward/backward, reversals, turns)",
        domain="Kinematics", kind="table",
        n_label="one summary per recording (n_frames)",
        metric_cols=["frac_forward", "frac_backward", "frac_unresolved", "n_reversals",
                    "crawl_speed_px_s", "mean_signed_speed_px_s", "angular_vel_deg_s_mean_abs",
                    "n_omega_turns", "self_approach_frac", "eigen_fit_quality_mean"],
        caveat=(f"{KINEMATICS_CAVEAT_PREFIX} Forward/backward and reversals are derived from "
               "the SIGN OF THE BODY-WAVE DIRECTION per frame (anterior->posterior = forward, "
               "posterior->anterior = backward -- the biological convention), gated on that "
               "frame's own wave-fit quality (r2>0.5) -- NEVER from axial_vel_px_s's own sign, "
               "which is a per-segment local quantity with no guaranteed whole-body sign "
               "convention. Wave direction here IS the locomotion signal being measured, not a "
               "confound to caveat around (contrast with the Coupling views, where locomotion "
               "state is an unresolved confound on calcium-curvature lag). Frames where the "
               "wave fit isn't coherent are 'unresolved', never silently forced into forward or "
               "backward -- see frac_unresolved. Omega turns are counted two ways and reported "
               "separately (n_omega_turns_self_approach, n_omega_turns_turn_angle) so you can "
               "see which signal drove each count. self_approach_frac and "
               "eigen_fit_quality_mean are concrete numbers on every row, not a vague caveat: "
               "a high self_approach_frac means curvature-derived direction is suspect for a "
               "large fraction of this clip."),
        is_valid=_validity_fn("resolved_flag", "locomotion_summary"),
    ))

    views.append(ViewDef(
        key="fig_curvature_kymograph", label="Curvature kymograph (full body)",
        domain="Kinematics", kind="figure",
        caveat=(f"{KINEMATICS_CAVEAT_PREFIX} Full body (segments 0-23), its own colour scale "
               "(rescaled to this array's own min/max, never shared with a calcium "
               "kymograph's scale). This is the spatial view the undulation descriptors and "
               "locomotion summary above are both computed from."),
        is_valid=_validity_fn("figure", "fig_curvature_kymograph"),
    ))

    return views


# --------------------------------------------------------------------------- #
# Coupling (Stage 2b). curvature_phase_lag is looped per channel (like
# calcium) but listed under Coupling per the handoff; interchannel_timing
# replaces the retired intersignal_timing; amplitude_coupling stays as the
# explicitly-labeled legacy correlation view; movement_coupling is unchanged.
# --------------------------------------------------------------------------- #
def build_coupling_views(channels=("green", "red", "blue")) -> list:
    views = []

    for ch in channels:
        cav = channel_caveat(ch)
        key = f"curvature_phase_lag_{ch}"
        disp = CHANNEL_DISPLAY.get(ch, ch.capitalize())
        views.append(ViewDef(
            key=key, label=f"Calcium-to-curvature phase lag ({disp})",
            domain="Coupling", kind="table",
            n_label="per segment-hemisegment (self_approach_frac shown per row)",
            metric_cols=["lag_s", "lag_uncertainty_s", "coherence", "self_approach_frac"],
            caveat=(f"{cav} SIGN CONVENTION: positive lag_s means calcium PRECEDES "
                   "(leads) the bend; negative means calcium follows. Phase method "
                   "(Hilbert, band-passed around the dominant undulation frequency), "
                   "gated on wave coherence -- never a raw integer-frame argmax, which "
                   "returns 0 whenever the true lag is under one frame. Reliable body "
                   "only, per-channel masked. Suspect when self_approach_flag fires "
                   "heavily (~62% was seen on one pilot animal; self_approach_frac is "
                   "shown per row) -- self-approach folds the body near itself, "
                   "confounding curvature. Depends on forward vs backward locomotion "
                   "and is not a fixed muscle property -- not resolved here, so treat "
                   "this recording's lag as tied to whatever it was doing during this clip."),
            is_valid=_validity_fn("resolved_flag", key), channel=ch,
        ))

    views.append(ViewDef(
        key="interchannel_timing", label="Inter-channel timing (green vs blue, green vs red)",
        domain="Coupling", kind="table",
        n_label="per compartment pair, one row per recording (n_seg = segments contributing)",
        metric_cols=["lag_s", "lag_uncertainty_s", "direction_agreement", "n_seg", "coherence"],
        caveat=(f"{channel_caveat('green')} {CHANNEL_REPORTER['blue']} {CHANNEL_REPORTER['red']} "
               "SIGN CONVENTION: positive lag_s means the SECOND-named channel lags "
               "the first (green leads in both pairs here). Sub-frame capable only: "
               "Hilbert phase difference when the recording is coherently rhythmic, "
               "cross-correlation with parabolic peak interpolation otherwise -- never "
               "the integer-frame argmax, which returned exactly 0 and an implausible "
               "~-3 s plugin lag in the pilot (retired, not reported). "
               "green_vs_blue (cytosolic vs ER) is store release/refill, not a simple "
               "delay -- ER calcium can move OPPOSITE to cytosolic (see "
               "direction_agreement, negative = moved opposite). green_vs_red "
               "(cytosolic vs mitochondrial) is uptake -- mitochondrial calcium is "
               "expected to FOLLOW the cytosolic rise. A pair reads NaN and "
               "resolved=False, never zero, when its lag isn't distinguishable from "
               "noise."),
        is_valid=_validity_fn("resolved_flag", "interchannel_timing"),
    ))

    views.append(ViewDef(
        key="amplitude_coupling", label="Amplitude correlation (legacy: zero-lag + argmax)",
        domain="Coupling", kind="table", n_label="per segment-hemisegment",
        metric_cols=["r_zero_lag", "ca_leads_angle_s", "xcorr_peak"],
        caveat=(f"{channel_caveat('green')} SUPERSEDED for lead/lag questions by "
               "Calcium-to-curvature phase lag (phase-based, gated on coherence); "
               "kept here as the correlation-only legacy view so it is not confused "
               "with that one. ca_leads_angle_s is an integer-frame cross-correlation "
               "argmax and is frequently 0 at this frame rate -- do not read a 0 here "
               "as \"no lag\". Contraction amplitude (seg_angle_deg) is gated on "
               "midline quality upstream (eigen_fit_quality, partial/length flags). "
               "Within-recording only."),
        is_valid=lambda r: _has_rows(r, "amplitude_coupling"),
    ))

    views.append(ViewDef(
        key="movement_coupling", label="Movement coupling (calcium vs velocity)",
        domain="Coupling", kind="table", n_label="one summary per recording (n = frames)",
        metric_cols=["r_zero_lag", "ca_leads_move_s", "xcorr_peak", "n"],
        caveat=(f"{channel_caveat('green')} Whole-body axial velocity vs body-mean "
               "calcium. Kinematics gated on midline quality upstream "
               "(eigen_fit_quality, partial/length flags). A single within-recording "
               "correlation -- n here is frames, never animals."),
        is_valid=lambda r: _has_col_nonnull(r, "movement_coupling", "r_zero_lag"),
    ))

    # ----------------------------------------------------------------- #
    # Neuromechanical chain (Stage 3c): calcium -> curvature -> translation.
    # Robust MAGNITUDE form only; the phase-resolved (bend-to-thrust timing)
    # form is DEFERRED to a higher frame rate -- marked as such below, not
    # silently approximated.
    # ----------------------------------------------------------------- #
    NEUROMECH_PREFIX = (
        "Neuromechanical chain (calcium -> curvature -> translation), robust "
        "MAGNITUDE form only. The phase-resolved bend-to-thrust timing form "
        "(exactly when in the stroke thrust is produced) is DEFERRED to a "
        "higher frame rate (this recording is ~5 Hz) -- not built or "
        "approximated here."
    )

    for ch in channels:
        cav = channel_caveat(ch)
        disp = CHANNEL_DISPLAY.get(ch, ch.capitalize())

        views.append(ViewDef(
            key=f"calcium_output_decomposition_{ch}",
            label=f"Calcium output: bending vs propulsion ({disp})",
            domain="Coupling", kind="table",
            n_label="one summary per recording",
            metric_cols=["bending_lag_s", "bending_coherence", "propulsion_r_zero_lag",
                        "propulsion_lag_s", "self_approach_frac", "eigen_fit_quality_mean"],
            caveat=(f"{cav} Side-by-side split of this channel's mechanical output: "
                   "bending_* reuses Calcium-to-curvature phase lag (median across "
                   "resolved segments); propulsion_* is this channel's whole-body "
                   "calcium vs whole-body |axial velocity| (sub-frame cross-correlation "
                   "lag, parabolic interpolation -- never an integer-frame argmax). "
                   "Each half has its OWN resolved flag -- one can be resolved while "
                   "the other is not. See Propulsion efficiency (spatial breakdown) "
                   "and Curvature-to-translation link for the rest of this chain."),
            is_valid=lambda r, ch=ch: (_has_flag(r, f"calcium_output_decomposition_{ch}", "bending_resolved")
                                      or _has_flag(r, f"calcium_output_decomposition_{ch}", "propulsion_resolved")),
            channel=ch,
        ))

        views.append(ViewDef(
            key=f"fig_neuromech_overlay_{ch}", label=f"Neuromechanical overlay, time axis ({disp})",
            domain="Coupling", kind="figure",
            caveat=(f"{cav} {NEUROMECH_PREFIX} Calcium, |curvature|, and |axial velocity| on a "
                   "shared time axis, annotated with the calcium->curvature and "
                   "calcium->translation lags (same numbers as the tables above/below)."),
            is_valid=_validity_fn("figure", f"fig_neuromech_overlay_{ch}"), channel=ch,
        ))

        views.append(ViewDef(
            key=f"fig_neuromech_phase_{ch}", label=f"Neuromechanical overlay, phase axis ({disp})",
            domain="Coupling", kind="figure",
            caveat=(f"{cav} {NEUROMECH_PREFIX} Calcium, |curvature|, and |axial velocity| "
                   "phase-locked to the bend cycle (anterior/posterior), reusing the same "
                   "phase-averaging machinery as Cycle-average waveform -- this is the "
                   "magnitude envelope over one cycle, NOT a resolved bend-to-thrust "
                   "timing result; do not read peak positions here as sub-frame timing."),
            is_valid=_validity_fn("figure", f"fig_neuromech_phase_{ch}"), channel=ch,
        ))

    views.append(ViewDef(
        key="curvature_to_translation", label="Curvature-to-translation link",
        domain="Coupling", kind="table", n_label="one summary per recording (n = frames)",
        metric_cols=["r_zero_lag", "lag_s", "xcorr_peak", "self_approach_frac", "n"],
        caveat=(f"{KINEMATICS_CAVEAT_PREFIX} {NEUROMECH_PREFIX} The missing MIDDLE link "
               "in the chain: whole-body |curvature| vs whole-body |axial velocity| -- "
               "completes calcium->curvature (Calcium-to-curvature phase lag) and "
               "calcium->translation (Calcium output: bending vs propulsion) at this "
               "middle step. SIGN CONVENTION: positive lag_s means TRANSLATION lags "
               "CURVATURE (bending leads propulsion, the causally-expected order); "
               "sub-frame cross-correlation lag (parabolic interpolation), never an "
               "integer-frame argmax. Unresolved (insufficient samples or no variation) "
               "reads NaN and resolved=False, never zero."),
        is_valid=_validity_fn("resolved_flag", "curvature_to_translation"),
    ))

    views.append(ViewDef(
        key="propulsion_efficiency", label="Propulsion efficiency (spatial breakdown)",
        domain="Coupling", kind="table",
        n_label="whole-body + per-region + per-segment rows",
        metric_cols=["level", "region", "segment", "propulsion_efficiency_bl_s_per_rad",
                    "crawl_speed_bodylengths_per_s", "bend_amplitude_rad",
                    "dominant_direction", "resolved"],
        caveat=(f"{KINEMATICS_CAVEAT_PREFIX} {NEUROMECH_PREFIX} Forward speed per unit "
               "bending amplitude, in body-lengths/s per radian, normalized by this "
               "recording's own midline length so it is comparable across recordings "
               "even though um_per_px==0 here (uncalibrated pixel size cancels in the "
               "ratio -- see calibrated_length). Uses SPEED MAGNITUDE (|axial_vel_px_s|): "
               "both forward and backward travel count as propulsion, so bending without "
               "net displacement (thrashing in place) reads low regardless of direction; "
               "dominant_direction (from Locomotion summary) is carried alongside for "
               "context, not folded into the ratio's sign. Rows span whole_body, region "
               "(anterior/posterior), and segment (0-23) -- the spatial map of where "
               "bending actually converts to propulsion vs where it only deforms. "
               "Per-segment bend amplitude reuses the ONE whole-body wave fit's "
               "per-segment envelope, not a separate per-segment wave refit (a "
               "phase-gradient wave needs multiple segments to fit at all). Honesty "
               "guard: when bend amplitude is below the resolution floor, efficiency is "
               "NaN with resolved=False on that row -- a near-zero denominator never "
               "manufactures an inflated value, and one row failing this does not force "
               "others to NaN. Robust MAGNITUDE form only -- see caveat above on the "
               "deferred phase-resolved form."),
        is_valid=lambda r: _has_flag(r, "propulsion_efficiency", "resolved"),
    ))

    return views


def build_view_catalog(channels=("green", "red", "blue")) -> list:
    return (build_calcium_views(channels) + build_kinematics_views()
           + build_coupling_views(channels))


VIEW_CATALOG = build_view_catalog()


def summarize_table(df: pd.DataFrame, metric_cols: Optional[list], n_label: str) -> pd.DataFrame:
    """Descriptive summary per numeric metric: mean, median, 95% CI, n.
    n is the number of non-null observations for that metric -- labeled with
    n_label so it is never mistaken for a per-animal count. Boolean/flag
    columns are treated as 0/1 (mean = proportion True)."""
    cols = metric_cols if metric_cols is not None else list(df.columns)
    rows = []
    for col in cols:
        if col not in df.columns:
            continue
        s = df[col]
        if pd.api.types.is_bool_dtype(s):
            vals = s.dropna().astype(float).to_numpy()
        elif pd.api.types.is_numeric_dtype(s):
            vals = s.dropna().astype(float).to_numpy()
        else:
            continue
        n = vals.size
        if n == 0:
            continue
        mean = float(np.mean(vals))
        median = float(np.median(vals))
        if n >= 2:
            sem = float(np.std(vals, ddof=1) / np.sqrt(n))
            ci_low, ci_high = mean - CI_Z * sem, mean + CI_Z * sem
        else:
            ci_low, ci_high = np.nan, np.nan
        rows.append(dict(metric=col, mean=mean, median=median,
                         ci95_low=ci_low, ci95_high=ci_high, n=n))
    out = pd.DataFrame(rows)
    out.attrs["n_label"] = n_label
    return out


class ResultsBrowser(tk.Tk):
    def __init__(self, csv_path: Path):
        super().__init__()
        self.title(f"RGBCaMP Results Browser -- {Path(csv_path).name}")
        self.geometry("1150x720")

        self._current_view: Optional[ViewDef] = None
        self._current_table_full: Optional[pd.DataFrame] = None
        self._current_image_path: Optional[Path] = None
        self._tk_image = None  # keep a reference so it isn't garbage-collected

        try:
            self.result = run_one.analyse_one(csv_path)
        except Exception:
            messagebox.showerror("RGBCaMP Results Browser -- load failed",
                                 f"Could not analyse:\n{csv_path}\n\n{traceback.format_exc()[-1500:]}")
            self.destroy()
            return

        # Build the catalog from the channels THIS recording actually activated
        # (channel_report["activity_channels"]), not a hardcoded assumption --
        # a recording configured for fewer channels lists fewer per-channel views.
        active = self.result.channel_report.get("activity_channels") or ["green", "red", "blue"]
        self.view_catalog = build_view_catalog(tuple(active))

        self._build_layout()
        self._build_tree()

    # ---------------------------------------------------------------- layout
    def _build_layout(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(paned, width=300)
        paned.add(left, weight=1)
        ttk.Label(left, text="Views", font=("Segoe UI", 10, "bold")).pack(anchor="w", padx=6, pady=(6, 0))
        self.tree = ttk.Treeview(left, show="tree")
        self.tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        right = ttk.Frame(paned)
        paned.add(right, weight=4)

        self.banner = tk.Label(right, text="", wraplength=780, justify="left",
                               bg="#fff3cd", fg="#664d03", anchor="w",
                               padx=10, pady=8, font=("Segoe UI", 9))
        self.banner.pack(fill=tk.X, side=tk.TOP)

        btnbar = ttk.Frame(right)
        btnbar.pack(fill=tk.X, side=tk.TOP, pady=4)
        self.copy_btn = ttk.Button(btnbar, text="Copy", command=self._copy, state="disabled")
        self.copy_btn.pack(side=tk.LEFT, padx=6)
        self.export_btn = ttk.Button(btnbar, text="Export...", command=self._export, state="disabled")
        self.export_btn.pack(side=tk.LEFT, padx=6)

        self.content = ttk.Frame(right)
        self.content.pack(fill=tk.BOTH, expand=True)

    # ------------------------------------------------------------------ tree
    def _build_tree(self):
        domains = {}
        for domain in ("Calcium", "Kinematics", "Coupling"):
            domains[domain] = self.tree.insert("", "end", text=domain, open=True,
                                               tags=("domain",))

        # Calcium views are grouped one level deeper, by channel, since Stage 2a
        # multiplies each analysis by every active channel (green/red/blue) --
        # a flat list would be an unreadable wall of near-duplicate labels.
        channel_nodes = {}

        def _node_for(v):
            if v.domain == "Calcium" and v.channel:
                if v.channel not in channel_nodes:
                    disp = CHANNEL_DISPLAY.get(v.channel, v.channel.capitalize())
                    channel_nodes[v.channel] = self.tree.insert(
                        domains["Calcium"], "end", text=disp, open=False, tags=("channel",))
                return channel_nodes[v.channel]
            return domains[v.domain]

        any_shown = {d: False for d in domains}
        for v in self.view_catalog:
            try:
                ok = v.is_valid(self.result)
            except Exception:
                ok = False
            if not ok:
                continue
            self.tree.insert(_node_for(v), "end", text=v.label, tags=("view", v.key))
            any_shown[v.domain] = True

        if not any_shown["Kinematics"]:
            self.tree.insert(domains["Kinematics"], "end",
                             text="(no kinematics-only views in this stage -- see Stage 3)",
                             tags=("placeholder",))

        for domain, node in domains.items():
            if not any_shown[domain] and domain != "Kinematics":
                self.tree.insert(node, "end", text="(nothing valid for this recording)",
                                 tags=("placeholder",))

        self.tree.insert("", "end", text="Group / Genotype Comparison", tags=("group",))
        self.tree.tag_configure("placeholder", foreground="#888")
        self.tree.tag_configure("group", foreground="#8a3b00")
        self.tree.tag_configure("channel", font=("Segoe UI", 9, "italic"))

    def _view_by_key(self, key) -> Optional[ViewDef]:
        for v in self.view_catalog:
            if v.key == key:
                return v
        return None

    def _on_select(self, _event):
        sel = self.tree.selection()
        if not sel:
            return
        item = self.tree.item(sel[0])
        tags = item["tags"]
        if "group" in tags:
            self._render_group_deferral()
        elif "view" in tags:
            key = tags[1]
            v = self._view_by_key(key)
            if v is not None:
                self._render_view(v)
        else:
            self._clear_content()
            self.banner.config(text="")
            self.copy_btn.config(state="disabled")
            self.export_btn.config(state="disabled")

    # --------------------------------------------------------------- render
    def _clear_content(self):
        for w in self.content.winfo_children():
            w.destroy()

    def _render_group_deferral(self):
        self._current_view = None
        self._current_table_full = None
        self._current_image_path = None
        self._clear_content()
        self.banner.config(text="Not available in this tool -- see message.",
                           bg="#f8d7da", fg="#58151c")
        self.copy_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        lbl = tk.Label(self.content, text=GROUP_DEFERRAL_TEXT, justify="left",
                      wraplength=780, padx=20, pady=20, font=("Segoe UI", 10))
        lbl.pack(anchor="nw")

    def _render_view(self, v: ViewDef):
        self._current_view = v
        self._clear_content()
        self.banner.config(text=v.caveat, bg="#fff3cd", fg="#664d03")

        if v.kind == "figure":
            path = self.result.figures.get(v.key)
            self._current_image_path = path
            self._current_table_full = None
            img = Image.open(path)
            img.thumbnail((1000, 700))
            self._tk_image = ImageTk.PhotoImage(img)
            tk.Label(self.content, image=self._tk_image).pack(padx=10, pady=10)
            self.copy_btn.config(state="normal")
            self.export_btn.config(state="normal")
            return

        # table view: summary stats on top, full underlying data below
        df = self.result.tables.get(v.key)
        self._current_table_full = df
        self._current_image_path = None

        summary = summarize_table(df, v.metric_cols, v.n_label)
        ttk.Label(self.content, text=f"Summary (n = {v.n_label})",
                 font=("Segoe UI", 9, "italic")).pack(anchor="w", padx=8, pady=(6, 0))
        self._make_treeview(self.content, summary, height=min(8, max(2, len(summary))), fmt=True)

        ttk.Separator(self.content, orient="horizontal").pack(fill=tk.X, padx=8, pady=6)
        ttk.Label(self.content, text=f"Full data ({len(df)} rows, {v.n_label})",
                 font=("Segoe UI", 9, "italic")).pack(anchor="w", padx=8)
        self._make_treeview(self.content, df, height=16, fmt=True)

        self.copy_btn.config(state="normal")
        self.export_btn.config(state="normal")

    def _make_treeview(self, parent, df: pd.DataFrame, height: int, fmt: bool):
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        cols = list(df.columns)
        tv = ttk.Treeview(frame, columns=cols, show="headings", height=height)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=tv.yview)
        hsb = ttk.Scrollbar(frame, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        for c in cols:
            tv.heading(c, text=c)
            tv.column(c, width=110, anchor="center")
        for _, row in df.iterrows():
            vals = [self._fmt_cell(row[c]) if fmt else row[c] for c in cols]
            tv.insert("", "end", values=vals)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    @staticmethod
    def _fmt_cell(v):
        if isinstance(v, float):
            if np.isnan(v):
                return "—"   # em dash for NaN / not meaningful
            return f"{v:.4g}"
        return str(v)

    # ----------------------------------------------------------- copy/export
    def _copy(self):
        if self._current_image_path is not None:
            try:
                _copy_image_to_clipboard(self._current_image_path)
            except Exception as e:
                messagebox.showerror("Copy failed", f"Could not copy image to clipboard:\n{e}")
            return
        if self._current_table_full is not None:
            tsv = self._current_table_full.to_csv(sep="\t", index=False)
            self.clipboard_clear()
            self.clipboard_append(tsv)

    def _export(self):
        if self._current_image_path is not None:
            dest = filedialog.asksaveasfilename(defaultextension=".png",
                                                filetypes=[("PNG image", "*.png")],
                                                initialfile=self._current_image_path.name)
            if dest:
                shutil.copy(self._current_image_path, dest)
            return
        if self._current_table_full is not None:
            default = f"{self._current_view.key}.csv" if self._current_view else "table.csv"
            dest = filedialog.asksaveasfilename(defaultextension=".csv",
                                                filetypes=[("CSV", "*.csv")],
                                                initialfile=default)
            if dest:
                self._current_table_full.to_csv(dest, index=False)


def _copy_image_to_clipboard(path: Path):
    import win32clipboard
    image = Image.open(path).convert("RGB")
    buf = io.BytesIO()
    image.save(buf, "BMP")
    data = buf.getvalue()[14:]   # strip the 14-byte BMP file header; keep the DIB
    buf.close()
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32clipboard.CF_DIB, data)
    finally:
        win32clipboard.CloseClipboard()


def main():
    if len(sys.argv) < 2:
        print("Usage: python results_browser.py <recording_csv>")
        sys.exit(1)
    app = ResultsBrowser(Path(sys.argv[1]))
    app.mainloop()


if __name__ == "__main__":
    main()
