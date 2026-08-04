"""
worm_kinetics_foraging_dampening.py
===================================
Two Stage-3a kinematic summaries to paste into worm_kinetics.py, next to
undulation_descriptors() and locomotion_summary():

  foraging_descriptors  head-swing amplitude and frequency, from the per-frame
                        head_bend_deg column the kinematics extractor emits.
                        The head is deliberately OUTSIDE the body-wave
                        segmentation (it forages, it does not undulate), so this
                        cannot reuse the body envelope; it is the one metric
                        that needs its own column.

  posterior_dampening   anterior-to-posterior fall in body-bend amplitude,
                        computed as a SPATIAL fit over wave_propagation()'s
                        seg_envelope (the per-segment Hilbert amplitude of the
                        band-passed curvature). No second estimator: it reuses
                        the wave fit, so it stays consistent with
                        undulation_descriptors and locomotion_summary.

Both follow the module's honesty convention: when the underlying wave (or the
head-bend column) is absent or unresolved, every derived number is NaN and
resolved=False with a reason, never a fabricated amplitude or space constant.

PASTE-IN: these reference wave_propagation, np, pd, and scipy.signal directly,
matching the rest of worm_kinetics.py. If you keep them in a separate module
instead, `import worm_kinetics as wk` and prefix wk.wave_propagation.

Cannot execute here without the pipeline's data; review and run in the venv.
"""
import numpy as np
import pandas as pd
from scipy import signal

# wave_propagation() lives in worm_kinetics.py. These functions were written to
# be pasted in beside it, where it is already in scope - so imported as a
# standalone module they raised NameError on the first call to
# posterior_dampening(). run_one_kinematics.py papers over that by assigning
# _fd.wave_propagation before grafting the functions onto wk, which works but
# makes the module silently dependent on its caller: any other importer gets the
# NameError instead.
#
# Resolving it here makes the module stand on its own and turns that graft into
# a convenience rather than a requirement. Both usages still work: when this
# file IS pasted into worm_kinetics.py the import fails harmlessly and the local
# definition is used.
try:                                    # standalone module
    from worm_kinetics import wave_propagation
except Exception:                       # pasted into worm_kinetics.py
    pass


# --------------------------------------------------------------------------- #
# Foraging (head swing) — needs the per-frame head_bend_deg column
# --------------------------------------------------------------------------- #
def foraging_descriptors(df: pd.DataFrame, worm_id: str,
                         head_col: str = "head_bend_deg",
                         band_hz: tuple = (0.3, 6.0)) -> dict:
    """Head-swing amplitude and frequency from the per-frame head-bend angle.

    head_bend_deg is written once per frame by the kinematics extractor (the
    head-tip deflection relative to the neck body axis), so it is collapsed to
    one value per frame here before analysis. Foraging is a HEAD behaviour and
    the head is excluded from the muscle segmentation, which is exactly why this
    uses its own column rather than the body-wave envelope.

    Amplitude is reported two ways: rms_deg (root-mean-square of the
    mean-subtracted swing) and p2p_deg (peak-to-peak). Frequency is the
    band-limited spectral peak (Welch), cross-checked by the median Hilbert
    instantaneous frequency of the band-passed swing; the two agreeing is the
    signal that the estimate is real.

    Nyquist honesty: the usable band is clipped to 0.95 * fps/2. If that clip
    removes the foraging band (fps too low, e.g. 5 Hz can see at most ~2.4 Hz),
    frequency is returned NaN with undersampled=True — foraging near 4–10 Hz is
    simply not observable at that rate, and a low number here would be an
    aliasing artefact, not a slow forage.
    """
    d = df[df["worm_id"] == worm_id]
    if head_col not in d.columns:
        return dict(worm_id=worm_id, resolved=False,
                    reason=f"no '{head_col}' column: re-export with the "
                           f"kinematics extractor (adds the per-frame head bend)",
                    rms_deg=np.nan, p2p_deg=np.nan, dominant_freq_hz=np.nan,
                    hilbert_freq_hz=np.nan, band_power_frac=np.nan,
                    undersampled=None, n_frames=0)

    fps = float(d["fps"].iloc[0])
    # collapse to one value per frame (the column repeats across segments/sides)
    s = (d.groupby("frame")[head_col].first().sort_index())
    y = s.to_numpy(dtype=float)
    finite = np.isfinite(y)
    n = int(finite.sum())
    if n < 16:
        return dict(worm_id=worm_id, resolved=False,
                    reason=f"too few valid head-bend frames ({n})",
                    rms_deg=np.nan, p2p_deg=np.nan, dominant_freq_hz=np.nan,
                    hilbert_freq_hz=np.nan, band_power_frac=np.nan,
                    undersampled=None, n_frames=n)

    # interpolate short gaps so the spectral tools see a continuous series
    y = pd.Series(y).interpolate(limit_direction="both").to_numpy()
    y0 = y - np.nanmean(y)
    rms = float(np.sqrt(np.mean(y0 ** 2)))
    p2p = float(np.nanmax(y) - np.nanmin(y))

    nyq = fps / 2.0
    lo, hi = band_hz
    hi = min(hi, 0.95 * nyq)
    undersampled = hi <= lo
    if undersampled:
        return dict(worm_id=worm_id, resolved=False,
                    reason=f"fps={fps:g} Hz cannot resolve the foraging band "
                           f"(Nyquist {nyq:g} Hz below {lo:g} Hz); amplitude is "
                           f"still valid, frequency is not",
                    rms_deg=rms, p2p_deg=p2p, dominant_freq_hz=np.nan,
                    hilbert_freq_hz=np.nan, band_power_frac=np.nan,
                    undersampled=True, n_frames=n)

    # Welch spectral peak inside the foraging band
    f, p = signal.welch(y0, fs=fps, nperseg=min(128, y0.size))
    band = (f >= lo) & (f <= hi)
    if band.any() and p[band].sum() > 0:
        f0 = float(f[band][np.argmax(p[band])])
        band_power_frac = float(p[band].sum() / (p.sum() + 1e-12))
    else:
        f0 = np.nan
        band_power_frac = np.nan

    # Hilbert instantaneous-frequency cross-check on the band-passed swing
    hilbert_freq = np.nan
    if np.isfinite(f0) and f0 > 0:
        blo, bhi = max(0.05, f0 * 0.5), min(nyq - 0.01, f0 * 1.8)
        if bhi > blo:
            sos = signal.butter(2, [blo, bhi], btype="band", fs=fps, output="sos")
            yb = signal.sosfiltfilt(sos, y0)
            phase = np.unwrap(np.angle(signal.hilbert(yb)))
            inst = np.diff(phase) / (2 * np.pi) * fps
            inst = inst[np.isfinite(inst)]
            if inst.size:
                hilbert_freq = float(np.median(inst))

    resolved = bool(np.isfinite(f0))
    return dict(worm_id=worm_id, resolved=resolved,
                rms_deg=rms, p2p_deg=p2p,
                dominant_freq_hz=f0, hilbert_freq_hz=hilbert_freq,
                band_power_frac=band_power_frac,
                undersampled=False, n_frames=n,
                reason="" if resolved else "no spectral peak in the foraging band")


# --------------------------------------------------------------------------- #
# Posterior dampening — spatial fit over the body-wave envelope
# --------------------------------------------------------------------------- #
def posterior_dampening(df: pd.DataFrame, worm_id: str,
                        curv_col: str = "seg_curv_deg") -> dict:
    """Anterior-to-posterior attenuation of body-bend amplitude.

    Reuses wave_propagation(value=curv_col, head_segments=()) so the amplitude
    is the SAME per-segment Hilbert envelope that drives undulation_descriptors
    and locomotion_summary — one wave, three readouts, never a parallel
    estimator. Per-segment amplitude is the time-median of that envelope; body
    position is the segment index normalised to [0, 1] head->tail.

    Three views of the same fall, because different papers report different
    ones:
      slope_per_bodylen : linear-fit slope of amplitude vs position
                          (deg-amplitude per unit body length; negative = the
                          wave attenuates posteriorly, the expected sign)
      norm_slope        : slope divided by mean amplitude (relative dampening
                          per body length; comparable across worms of different
                          absolute bend)
      space_constant    : lambda from a log-linear fit A(s)=A0*exp(-s/lambda),
                          in body-length units, only when the fall is genuinely
                          exponential (monotone decay, decent fit); else NaN
      pa_ratio          : posterior-third / anterior-third mean amplitude
                          (<1 = damped, >1 = amplified posteriorly)

    Honesty guard: if wave_propagation cannot fit a coherent body wave
    (seg_envelope is None), everything is NaN and resolved=False — a dampening
    slope over an envelope that does not exist would be noise dressed as a
    result. Requires wave_propagation defined in the same module (Stage 3a).
    """
    wp = wave_propagation(df, worm_id, value=curv_col, head_segments=())
    env = wp.get("seg_envelope")
    seg_axis = wp.get("seg_axis")
    resolved_wave = env is not None and seg_axis is not None and wp.get("direction") != "undetermined"
    if not resolved_wave:
        return dict(worm_id=worm_id, resolved=False,
                    reason="no coherent body wave (see wave_propagation "
                           "coherence/direction); dampening undefined",
                    slope_per_bodylen=np.nan, norm_slope=np.nan,
                    space_constant=np.nan, pa_ratio=np.nan, fit_r2=np.nan,
                    coherence=wp.get("coherence", np.nan),
                    seg_positions=None, seg_amplitudes=None)

    amp = np.median(np.asarray(env, dtype=float), axis=1)   # per-segment amplitude
    seg_axis = np.asarray(seg_axis, dtype=float)

    # normalise segment index to body fraction over the FULL segment count so
    # the position axis means the same thing across recordings
    nseg_total = int(df["segment"].max()) + 1 if "segment" in df.columns else int(seg_axis.max()) + 1
    pos = seg_axis / max(1, (nseg_total - 1))

    ok = np.isfinite(amp) & np.isfinite(pos)
    if ok.sum() < 4:
        return dict(worm_id=worm_id, resolved=False,
                    reason=f"too few segments with a finite envelope ({int(ok.sum())})",
                    slope_per_bodylen=np.nan, norm_slope=np.nan,
                    space_constant=np.nan, pa_ratio=np.nan, fit_r2=np.nan,
                    coherence=wp.get("coherence", np.nan),
                    seg_positions=pos.tolist(), seg_amplitudes=amp.tolist())

    x, a = pos[ok], amp[ok]

    # linear fit
    A = np.polyfit(x, a, 1)
    slope = float(A[0])
    yhat = np.polyval(A, x)
    r2 = float(1 - np.sum((a - yhat) ** 2) / (np.sum((a - a.mean()) ** 2) + 1e-12))
    mean_amp = float(np.mean(a))
    norm_slope = slope / mean_amp if mean_amp > 1e-9 else np.nan

    # exponential space constant, only where a decay is meaningful
    space_constant = np.nan
    pos_a = a > 1e-9
    if pos_a.sum() >= 4:
        L = np.polyfit(x[pos_a], np.log(a[pos_a]), 1)
        m = float(L[0])
        if m < 0:                       # amplitude actually falls posteriorly
            space_constant = float(-1.0 / m)

    # posterior/anterior third ratio, in segment order (x already head->tail)
    order = np.argsort(x)
    a_sorted = a[order]
    t = max(1, a_sorted.size // 3)
    ant = np.mean(a_sorted[:t])
    post = np.mean(a_sorted[-t:])
    pa_ratio = float(post / ant) if ant > 1e-9 else np.nan

    return dict(worm_id=worm_id, resolved=True,
                slope_per_bodylen=slope, norm_slope=norm_slope,
                space_constant=space_constant, pa_ratio=pa_ratio, fit_r2=r2,
                coherence=wp.get("coherence", np.nan),
                dominant_freq_hz=wp.get("dominant_freq_hz", np.nan),
                n_segments=int(ok.sum()),
                seg_positions=x.tolist(), seg_amplitudes=a.tolist(),
                reason="")


# --------------------------------------------------------------------------- #
# WIRING NOTES (no code change needed to the two functions above)
# --------------------------------------------------------------------------- #
# run_one.py — alongside the existing undulation_descriptors / locomotion_summary
# calls (around line 180), add:
#     _try("foraging_descriptors", lambda: wk.foraging_descriptors(masked, worm_id))
#     _try("posterior_dampening",  lambda: wk.posterior_dampening(masked, worm_id))
# `masked` already carries head_bend_deg through untouched (the head mask NaNs
# calcium, not geometry), so no change to the masking step is required.
#
# results_browser.py — mirror the undulation_descriptors view block (around line
# 291) for two new scalar views keyed "foraging_descriptors" and
# "posterior_dampening", each gated is_valid=_validity_fn("resolved_flag", ...).
#
# worm_batch.py — if you want these at the animal-as-N level, append their
# resolved rows into the per-recording table the same way wave_propagation is
# aggregated (around line 264), then let animal_level_stats pick them up.
