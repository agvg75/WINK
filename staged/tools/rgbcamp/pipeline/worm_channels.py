"""
worm_channels.py — configurable channel roles + background normalisation.

Implements the "Channel configuration and background normalisation" section of
RGBCaMP_fixes_batch_spec.docx.

Validated default for this preparation: BACKGROUND-SUBTRACTED GCaMP dF/F0.
A reference channel (blue ER, or a future mCherry body-wall reporter) is an
OPTIONAL refinement, not a requirement (per the PNAS-supplement equivalence of
background-normalised GCaMP with mCherry normalisation).

Normalisation order is fixed and explicit:
  1. subtract a per-frame background (measured outside the worm) from each
     channel  ->  <ch>_bgsub
  2. dF/F0 on the background-subtracted signal                  ->  <ch>_dff
  3. ONLY if a reference channel is designated: divide the activity channel by
     the reference                                              ->  <ch>_refdiv

The background value lives in the extractor. Since extractor contract_version
3, the CSV carries a PER-CHANNEL background column per frame (bg_blue,
bg_green, bg_red — each channel's own outside-worm measurement); step 1 uses
those when present. Older exports that carry only one shared background
column (BACKGROUND_COL_CANDIDATES) still work via that fallback. If neither
is present, step 1 is a no-op and the report flags `background_applied=False`.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from typing import Optional, Sequence

import numpy as np
import pandas as pd
from scipy import signal

CHANNELS = ("blue", "green", "red")

ROLE_ACTIVITY = "activity"      # GCaMP — the Ca readout
ROLE_REFERENCE = "reference"    # Ca-insensitive, used for ratiometric motion correction
ROLE_OFF = "off"                # ignore this channel

# Candidate names the extractor might use for the per-frame outside-worm value.
# The subtraction stays auditable: we record which column was used.
BACKGROUND_COL_CANDIDATES = ("background_mean", "bg_mean", "background",
                             "outside_mean", "bkg_mean")


@dataclass
class ChannelConfig:
    """User-selectable channel roles + normalisation switches.

    roles maps channel name -> ROLE_ACTIVITY | ROLE_REFERENCE | ROLE_OFF.
    At most one reference channel is allowed. Roles are set per batch and may be
    overridden per file via the manifest (mixed folders).
    """
    roles: dict = field(default_factory=lambda: {
        "green": ROLE_ACTIVITY,   # cytoplasmic GCaMP — primary Ca readout
        "red": ROLE_OFF,          # mito RCaMP / pharynx mCherry — off by default
        "blue": ROLE_OFF,         # ER indicator — off by default (reference-eligible)
    })
    f0_percentile: float = 10.0
    group_cols: Sequence[str] = ("worm_id", "segment", "hemisegment")
    background_col: Optional[str] = None   # None -> auto-detect from candidates
    # Guardrail: a reference must be STATIC. If it shows calcium-like transients
    # (fraction of frames above this SNR), refuse the ratiometric division.
    reference_max_transient_frac: float = 0.02
    reference_snr_mad: float = 4.0

    def __post_init__(self):
        refs = [c for c, r in self.roles.items() if r == ROLE_REFERENCE]
        if len(refs) > 1:
            raise ValueError(f"at most one reference channel allowed, got {refs}")

    @property
    def activity_channels(self):
        return [c for c, r in self.roles.items() if r == ROLE_ACTIVITY]

    @property
    def reference_channel(self):
        refs = [c for c, r in self.roles.items() if r == ROLE_REFERENCE]
        return refs[0] if refs else None


def _detect_background_col(df: pd.DataFrame, cfg: ChannelConfig) -> Optional[str]:
    """Detect a single SHARED background column (fallback path, older CSVs)."""
    if cfg.background_col is not None:
        return cfg.background_col if cfg.background_col in df.columns else None
    for cand in BACKGROUND_COL_CANDIDATES:
        if cand in df.columns:
            return cand
    return None


def _detect_per_channel_bg_col(ch: str, df: pd.DataFrame) -> Optional[str]:
    """Detect a PER-CHANNEL background column (extractor contract_version>=3
    writes bg_blue/bg_green/bg_red). Preferred over the shared-column fallback
    because it uses each channel's own outside-worm measurement."""
    cand = f"bg_{ch}"
    return cand if cand in df.columns else None


def _looks_like_calcium(y: np.ndarray, snr_mad: float, max_frac: float) -> bool:
    """Does a would-be reference channel carry calcium-like transients?
    Fraction of frames that are positive SNR peaks above `snr_mad` MADs."""
    y = np.asarray(y, float)
    y = y[np.isfinite(y)]
    if y.size < 10:
        return False
    noise = 1.4826 * np.median(np.abs(y - np.median(y))) + 1e-9
    peaks, _ = signal.find_peaks(y, height=np.median(y) + snr_mad * noise)
    return (len(peaks) / y.size) > max_frac


def apply_normalisation(df: pd.DataFrame, cfg: ChannelConfig = ChannelConfig()
                        ) -> tuple[pd.DataFrame, dict]:
    """Run the fixed normalisation order and return (df, report).

    Adds columns:
      <ch>_bgsub  background-subtracted channel mean (== mean if no background)
      <ch>_f0     per-group low-percentile baseline of bgsub
      <ch>_dff    dF/F0 on the background-subtracted signal
      <act>_refdiv   activity/reference ratio (only if a valid static reference)

    report keys: background_applied, background_col (shared-column fallback
      name, or None if per-channel columns were used), background_per_channel
      (bool), background_cols_used (sorted list of the actual column(s)
      applied, e.g. ['bg_blue','bg_green','bg_red']), reference_channel,
      reference_is_static, ratiometric_applied, notes (list).
    """
    out = df.sort_values(list(cfg.group_cols) + ["frame"]).copy()
    notes: list[str] = []
    active = [c for c in cfg.roles if cfg.roles[c] != ROLE_OFF and f"{c}_mean" in out.columns]

    # ---- step 1: background subtraction (per frame, per channel) ----
    # Preferred: a PER-CHANNEL background column (bg_<ch>) -- this is what the
    # extractor actually writes (contract_version>=3: bg_blue/bg_green/bg_red),
    # using each channel's own outside-worm measurement. Fall back to a single
    # SHARED background column (BACKGROUND_COL_CANDIDATES) for older CSVs that
    # only carry one. Decided per channel, so a partially-tagged CSV still
    # benefits on whichever channels have their own column.
    shared_bg_col = _detect_background_col(out, cfg)
    bg_col_for = {}          # ch -> column actually used (or None)
    used_per_channel = False
    for ch in active:
        per_ch = _detect_per_channel_bg_col(ch, out)
        if per_ch is not None:
            bg_col_for[ch] = per_ch
            used_per_channel = True
        else:
            bg_col_for[ch] = shared_bg_col

    bg_cols_used = sorted({c for c in bg_col_for.values() if c is not None})
    background_applied = bool(bg_cols_used)
    for ch in active:
        mean_col = f"{ch}_mean"
        bg_col = bg_col_for[ch]
        if bg_col is not None:
            out[f"{ch}_bgsub"] = out[mean_col] - out[bg_col]
        else:
            out[f"{ch}_bgsub"] = out[mean_col]
    if used_per_channel:
        notes.append(f"background subtracted per channel using columns: {bg_cols_used}")
    elif background_applied:
        notes.append(f"background subtracted using shared column '{shared_bg_col}'")
    else:
        notes.append("NO background column found: background subtraction NOT "
                     "applied (pilot state). dF/F0 computed on raw channel mean; "
                     "motion/shading uncorrected.")

    # ---- step 2: dF/F0 on the background-subtracted signal ----
    for ch in active:
        b = f"{ch}_bgsub"
        f0 = out.groupby(list(cfg.group_cols))[b].transform(
            lambda x: np.nanpercentile(x, cfg.f0_percentile) if x.notna().any() else np.nan)
        f0 = f0.replace(0, np.nan)
        out[f"{ch}_f0"] = f0
        out[f"{ch}_dff"] = (out[b] - f0) / f0

    # ---- step 3: optional ratiometric division by a STATIC reference ----
    ref = cfg.reference_channel
    reference_is_static = None
    ratiometric_applied = False
    if ref is not None and f"{ref}_dff" in out.columns:
        # is the reference genuinely static, or does it carry Ca transients?
        looks_ca = _looks_like_calcium(out[f"{ref}_dff"].to_numpy(),
                                       cfg.reference_snr_mad,
                                       cfg.reference_max_transient_frac)
        reference_is_static = not looks_ca
        if reference_is_static:
            ref_sig = out[f"{ref}_bgsub"].replace(0, np.nan)
            for ch in cfg.activity_channels:
                out[f"{ch}_refdiv"] = out[f"{ch}_bgsub"] / ref_sig
            ratiometric_applied = True
            notes.append(f"ratiometric division by static reference '{ref}'")
        else:
            warnings.warn(f"reference channel '{ref}' shows calcium-like "
                          f"transients; refusing ratiometric division. "
                          f"Falling back to background-subtracted dF/F0.")
            notes.append(f"reference '{ref}' NOT static (shows transients): "
                         f"ratiometric division REFUSED; using dF/F0 only.")
    elif ref is None:
        notes.append("no reference channel set: using background-subtracted "
                     "dF/F0 (validated default); motion uncorrected (information, "
                     "not error).")

    report = dict(background_applied=background_applied,
                  background_col=shared_bg_col if not used_per_channel else None,
                  background_per_channel=used_per_channel,
                  background_cols_used=bg_cols_used,
                  reference_channel=ref, reference_is_static=reference_is_static,
                  ratiometric_applied=ratiometric_applied,
                  activity_channels=cfg.activity_channels, notes=notes)
    return out, report
