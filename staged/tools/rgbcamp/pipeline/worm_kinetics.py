"""
worm_kinetics.py
================
Kinetics + comparison layer on top of `worm_rgbcamp_analysis.py`.

Adds the analyses requested for the DMD program that go beyond per-worm
summaries:

  region_split          anterior vs posterior (reliable body segments)
  dorsal_ventral_split  dorsal vs ventral (true hemisegment identity only)
  resting_calcium       resting level from the bg-subtracted baseline, per region
  contraction_state     contracted vs relaxed frames (from curvature)
  release_reuptake      per-transient rise (release) + decay tau (reuptake)
  curvature_phase_lag   calcium-to-curvature phase lag, per channel (Stage 2b)
  interchannel_timing   sub-frame timing, green-vs-blue and green-vs-red (Stage 2b)
  amplitude_coupling    segment angle (contraction) vs calcium, zero-lag + argmax
                        (legacy correlation view; curvature_phase_lag supersedes
                        it for lead/lag questions -- see that function's docstring)
  movement_coupling     worm axial velocity (displacement) vs calcium, lag
  wave_propagation      A->P wave speed, direction, frequency from kymograph
  cycle_average         phase-locked average contractile cycle per region
  intersignal_timing    RETIRED (Stage 2b) -- see interchannel_timing

HEAD MASK (user spec): myocytes 1-8 sit over the pharynx (mCherry) and a head
GFP neuron, so RED and GREEN are unreliable in segments 0-7. `mask_head()` NaNs
green+red (and their dF/F0 / dF/dt) there while keeping BLUE.

PER-CHANNEL (Stage 2a): region_split, dorsal_ventral_split, resting_calcium,
contraction_state, release_reuptake, wave_propagation, and cycle_average all
accept a `head_segments` override (default HEAD_SEGMENTS) so callers can pass
head_segments=() for blue, which is not masked in the head and so has a wider
valid range there than green/red. Callers (run_one.py) loop this over every
active channel -- these functions don't hardcode "green" anywhere except in
their default `value=` argument for direct/manual use.
intersignal_timing, amplitude_coupling, and movement_coupling are unchanged
(Coupling domain, Stage 2b) and still operate on HEAD_SEGMENTS unconditionally.

METADATA FROM FILENAME (user spec): genotype (WT vs dystrophic), age
(day1 vs day5), and RNAi target are encoded in the file name, not the CSV.
`parse_metadata()` reads them; see its docstring for the token grammar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import signal, stats
from scipy.optimize import curve_fit

import worm_rgbcamp_analysis as wa

# Segments whose red+green are contaminated by pharyngeal mCherry / head GFP.
# Muscle i (1-based, user's language) ~ segment i-1 (0-based plugin index), so
# "myocytes 1-8" -> segments 0-7.
HEAD_SEGMENTS = tuple(range(8))
RG_CHANNELS = ("green", "red")          # unreliable in the head
KEEP_IN_HEAD = ("blue",)                # ER indicator stays usable


# --------------------------------------------------------------------------- #
# Head mask
# --------------------------------------------------------------------------- #
def mask_head(df: pd.DataFrame, head_segments=HEAD_SEGMENTS) -> pd.DataFrame:
    """Return a copy with green+red columns NaN'd inside the head segments.

    Blue is preserved. Every derived green/red column (mean/min/max, _dff,
    _dF_dt) and the ratios that involve red or green (RG, GB, RB) are masked,
    because none of them are trustworthy where the pharynx bleeds through.
    """
    out = df.copy()
    head = out["segment"].isin(head_segments)
    patt = []
    for ch in RG_CHANNELS:
        patt += [c for c in out.columns if c.startswith(ch)]
    # ratios / lags that mix in a masked channel
    for c in out.columns:
        if re.search(r"(RG|GB|RB)", c):
            patt.append(c)
    patt = sorted(set(patt))
    out.loc[head, patt] = np.nan
    out.attrs["head_masked"] = True
    out.attrs["head_segments"] = tuple(head_segments)
    return out


# --------------------------------------------------------------------------- #
# Metadata from filename
# --------------------------------------------------------------------------- #
def parse_metadata(name: str) -> dict:
    """Parse genotype / age / RNAi target from a file name.

    Token grammar (case-insensitive, tokens split on _ - space or camelCase):
      genotype : 'wt' | 'n2'                       -> 'wildtype'
                 'dmd' | 'dys1' | 'dys-1' | 'dystrophic' -> 'dystrophic'
      age      : 'day1'|'d1' -> 1 ,  'day5'|'d5' -> 5   (any dayN / dN)
      rnai     : 'l4440'                           -> empty-vector control
                 otherwise first non-keyword token -> RNAi target label
      quality  : 'bad'|'bad2' present              -> 'flagged_bad'
    Unspecified axes come back as None so grouping code can skip them.
    """
    stem = re.sub(r"\.csv$", "", name, flags=re.I)
    stem = re.sub(r"WormRGBCaMP_extracted_?", "", stem, flags=re.I)
    toks = re.split(r"[ _\-]+", stem.strip())
    low = [t.lower() for t in toks if t]

    genotype = None
    for t in low:
        if t in ("wt", "n2"):
            genotype = "wildtype"
        elif t in ("dmd", "dys1", "dys-1", "dystrophic", "dys"):
            genotype = "dystrophic"

    age_day = None
    for t in low:
        m = re.fullmatch(r"(?:day|d)(\d+)", t)
        if m:
            age_day = int(m.group(1))

    quality = "flagged_bad" if any(re.fullmatch(r"bad\d*", t) for t in low) else "good"

    is_control = any(t == "l4440" for t in low)
    rnai = None
    KEYWORDS = {"wt", "n2", "dmd", "dys1", "dys-1", "dys", "dystrophic",
                "1g", "extracted", "wormrgbcamp"}
    for t in low:
        if t == "l4440":
            rnai = "L4440(empty_vector)"
            break
        if re.fullmatch(r"(?:day|d)\d+", t) or re.fullmatch(r"bad\d*", t):
            continue
        if t in KEYWORDS:
            continue
        rnai = t
        break

    return dict(genotype=genotype, age_day=age_day, rnai_target=rnai,
                is_control=is_control, quality_note=quality)


# --------------------------------------------------------------------------- #
# Region split (anterior vs posterior, reliable body only)
# --------------------------------------------------------------------------- #
def region_of(segment: int, head_segments=HEAD_SEGMENTS) -> str:
    """Label a segment anterior / posterior over the reliable (non-head) body.

    Head segments are excluded from the green/red regional comparison. The
    reliable body (8..23) is split at its midpoint: anterior = 8-15,
    posterior = 16-23.

    head_segments=() (blue -- kept in the head, see mask_head) splits the
    FULL body 0..23 at its midpoint instead, since there is no head to
    exclude for that channel.
    """
    if segment in head_segments:
        return "head"
    lo = (max(head_segments) + 1) if head_segments else 0
    hi = 23
    mid = (lo + hi) / 2
    return "anterior" if segment <= mid else "posterior"


def region_split(df: pd.DataFrame, value: str = "green_dff",
                 head_segments=HEAD_SEGMENTS) -> pd.DataFrame:
    """Per-worm anterior vs posterior comparison of a calcium metric.

    Uses reliable segments only (head excluded for green/red; pass
    head_segments=() for blue, which is kept in the head -- see mask_head).
    Returns one row per worm x region with mean, p95 dF/F0, and active
    fraction.
    """
    d = df.copy()
    d["region"] = d["segment"].map(lambda s: region_of(s, head_segments))
    d = d[d["region"] != "head"]
    rows = []
    for (w, reg), g in d.groupby(["worm_id", "region"]):
        v = g[value].to_numpy()
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        rows.append(dict(worm_id=w, region=reg, n=v.size,
                         mean=float(np.mean(v)),
                         p95=float(np.percentile(v, 95)),
                         active_frac=float(np.mean(v > 0.25))))
    return pd.DataFrame(rows)


def dorsal_ventral_split(df: pd.DataFrame, value: str = "green_dff",
                         require_dorsal_known: bool = True) -> pd.DataFrame:
    """Per-worm dorsal vs ventral comparison of a calcium metric -- the same
    shape as region_split, but cutting by hemisegment identity instead of
    anterior/posterior position.

    Only meaningful where the extractor resolved true dorsal/ventral identity
    (hemisegment values 'dorsal'/'ventral', from the vulva-notch detector) --
    NOT the generic 'L'/'R' fallback used when that detector didn't fire. By
    default also requires dorsal_known==1 (if that column is present), so an
    unreliable per-frame guess doesn't quietly count as a settled hemisegment
    label. Returns an empty frame (not zeros) if neither is available for
    this recording -- that is the honest "not computable" result, not a bug.

    Dorsal and ventral body-wall muscle alternate in antiphase during
    undulation, so a real signal here is expected to be reciprocal (one high
    while the other is low), not equal.
    """
    d = df.copy()
    if require_dorsal_known and "dorsal_known" in d.columns:
        d = d[d["dorsal_known"] == 1]
    d = d[d["hemisegment"].isin(["dorsal", "ventral"])]
    rows = []
    for (w, hemi), g in d.groupby(["worm_id", "hemisegment"]):
        v = g[value].to_numpy()
        v = v[np.isfinite(v)]
        if v.size == 0:
            continue
        rows.append(dict(worm_id=w, hemisegment=hemi, n=v.size,
                         mean=float(np.mean(v)),
                         p95=float(np.percentile(v, 95)),
                         active_frac=float(np.mean(v > 0.25))))
    return pd.DataFrame(rows)


def resting_calcium(df: pd.DataFrame, value: str = "green_bgsub",
                    percentile: float = 10.0,
                    head_segments=HEAD_SEGMENTS) -> pd.DataFrame:
    """Resting calcium level per region, from the BACKGROUND-SUBTRACTED signal
    (worm_channels.apply_normalisation's `<ch>_bgsub`, or a `<ch>_refdiv`
    ratio when a calcium-insensitive reference channel is designated) -- never
    from dF/F0, which subtracts its own baseline by construction and so
    cannot report a resting shift by definition.

    Returns one row per region with the low-`percentile` value of `value` as
    the resting level. If `value` is absent from `df` (channel off, or a
    refdiv ratio that was never computed because no reference channel was
    configured), returns a single explicitly-invalid row -- NaN and flagged,
    never a silent zero. Same if a region has no valid samples.
    """
    if value not in df.columns:
        return pd.DataFrame([dict(region="ALL", source_col=value, resting_value=np.nan,
                                  n=0, valid=False,
                                  reason=f"column '{value}' not present (channel off, or "
                                         f"no reference channel configured for a refdiv)")])
    d = df.copy()
    d["region"] = d["segment"].map(lambda s: region_of(s, head_segments))
    rows = []
    for reg, g in d.groupby("region"):
        v = g[value].to_numpy()
        v = v[np.isfinite(v)]
        if v.size == 0:
            rows.append(dict(region=reg, source_col=value, resting_value=np.nan,
                             n=0, valid=False, reason="no valid (non-NaN) samples in this region"))
            continue
        rows.append(dict(region=reg, source_col=value,
                         resting_value=float(np.percentile(v, percentile)),
                         n=v.size, valid=True, reason=""))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Contracted vs relaxed
# --------------------------------------------------------------------------- #
def contraction_state(df: pd.DataFrame, value: str = "green_dff",
                      curv_col: str = "seg_curv_deg",
                      quantile: float = 0.33,
                      head_segments=HEAD_SEGMENTS) -> pd.DataFrame:
    """Compare calcium in contracted vs relaxed segment-frames.

    For a hemisegment, contraction is read from local curvature magnitude:
    frames in the top `quantile` of |curv| for that segment are 'contracted',
    the bottom `quantile` are 'relaxed'. Compares `value` between the two,
    per worm x hemisegment, and returns the paired difference and a
    within-worm Mann-Whitney across pooled reliable segments.

    head_segments=() (blue) includes the head, since blue is kept there.
    """
    d = df.copy()
    d = d[~d["segment"].isin(head_segments)]
    d["absc"] = d[curv_col].abs()
    rows = []
    for (w, hemi), g in d.groupby(["worm_id", "hemisegment"]):
        hi = g["absc"].quantile(1 - quantile)
        lo = g["absc"].quantile(quantile)
        con = g.loc[g["absc"] >= hi, value].to_numpy()
        rel = g.loc[g["absc"] <= lo, value].to_numpy()
        con = con[np.isfinite(con)]; rel = rel[np.isfinite(rel)]
        if con.size < 10 or rel.size < 10:
            continue
        try:
            U, p = stats.mannwhitneyu(con, rel, alternative="two-sided")
            rb = 2 * U / (con.size * rel.size) - 1     # rank-biserial
        except ValueError:
            p, rb = np.nan, np.nan
        rows.append(dict(worm_id=w, hemisegment=hemi,
                         contracted_mean=float(np.mean(con)),
                         relaxed_mean=float(np.mean(rel)),
                         diff=float(np.mean(con) - np.mean(rel)),
                         rank_biserial=float(rb), p=float(p),
                         n_con=con.size, n_rel=rel.size))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Release vs reuptake kinetics (per calcium transient)
# --------------------------------------------------------------------------- #
def _mono_decay(t, a, tau, c):
    return a * np.exp(-t / tau) + c


def _crossing_time(y, i0, i1, level, fps):
    """First sample index in [i0,i1] at/above `level`, linearly interpolated to
    sub-frame time (seconds, relative to i0). Returns None if never reached."""
    for i in range(i0, i1 + 1):
        if y[i] >= level:
            if i == i0:
                return 0.0
            # interpolate between i-1 (below) and i (at/above)
            y0, y1 = y[i - 1], y[i]
            frac = 0.0 if y1 == y0 else (level - y0) / (y1 - y0)
            return ((i - 1) + frac - i0) / fps
    return None


@dataclass
class KineticsConfig:
    """Parameters for release/reuptake detection (spec: RGBCaMP fixes)."""
    min_amp: float = 0.25          # dF/F0 floor for a real transient
    n_mad: float = 4.0             # SNR floor in MAD units
    pre_window_s: float = 2.0      # pre-peak search when there is no prior peak
    max_decay_s: float = 10.0      # cap on the observed decay window
    decay_frac: float = 1.0 / np.e  # completion criterion: fall to 37% of amp
    r2_floor_explore: float = 0.5  # keep as exploratory
    r2_floor_confirm: float = 0.7  # confirmatory tau set (spec Fix 2)


def release_reuptake(df: pd.DataFrame, worm_id: str, value: str = "green_dff",
                     fps: float | None = None,
                     cfg: KineticsConfig = KineticsConfig(),
                     head_segments=HEAD_SEGMENTS) -> pd.DataFrame:
    """Per-transient release (rise) and reuptake (decay) kinetics — corrected.

    FIX 1 (onset / rise). The backward onset search is bounded so it cannot
    cross the previous detected peak: the search floor is the local MINIMUM
    between the previous peak and this one (or a fixed pre-peak window when
    there is no previous peak). The local baseline is that bounded minimum, not
    a whole-trace statistic. Rise time is measured 10%->90% of peak amplitude
    ABOVE the local baseline, inside the bounded interval; time-to-peak (onset
    at 10% -> peak) is reported separately. If the 10% crossing is not found
    inside the bounded interval the onset hit a boundary: `onset_at_boundary`
    is flagged and rise_time is left NaN rather than censored.

    FIX 2 (decay window / bound). The decay is observed from the peak to the
    next local minimum, capped at `max_decay_s`; the exponential tau upper
    bound equals that observed window length, so tau is never extrapolated past
    what was seen. `tau_extrapolated` flags tau within 5% of the window cap;
    `decay_incomplete` flags transients that never fall to `decay_frac` (1/e)
    of peak amplitude within the window. The R^2 gate is retained and reported;
    `confirmatory` marks fits with R^2 >= r2_floor_confirm (0.7).

    Returns ONE ROW PER TRANSIENT with explicit flags — nothing is silently
    dropped. Downstream summaries should filter on the flags (see
    `clean_transients`).
    """
    if fps is None:
        fps = float(df["fps"].iloc[0])
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(head_segments))]
    pre_n = int(round(cfg.pre_window_s * fps))
    max_decay_n = int(round(cfg.max_decay_s * fps))
    rows = []
    for (seg, hemi), g in d.groupby(["segment", "hemisegment"]):
        g = g.sort_values("frame")
        y = g[value].to_numpy(dtype=float)
        if np.isfinite(y).sum() < 20:
            continue
        y = pd.Series(y).interpolate(limit_direction="both").to_numpy()
        noise = 1.4826 * np.median(np.abs(y - np.median(y))) + 1e-9
        peaks, _ = signal.find_peaks(y, height=max(cfg.min_amp, cfg.n_mad * noise),
                                     distance=int(round(fps)))
        for j, pk in enumerate(peaks):
            peak_val = float(y[pk])
            # ---- Fix 1: bounded backward search ----
            prev_pk = peaks[j - 1] if j > 0 else None
            if prev_pk is not None:
                floor_idx = prev_pk + 1
            else:
                floor_idx = max(0, pk - pre_n)
            if pk - floor_idx < 1:
                continue
            local_min_idx = floor_idx + int(np.argmin(y[floor_idx:pk + 1]))
            baseline = float(y[local_min_idx])
            amp = peak_val - baseline
            if amp <= max(cfg.min_amp, cfg.n_mad * noise):
                continue
            lvl10 = baseline + 0.10 * amp
            lvl90 = baseline + 0.90 * amp
            # crossings within [local_min_idx, pk]
            t10 = _crossing_time(y, local_min_idx, pk, lvl10, fps)
            t90 = _crossing_time(y, local_min_idx, pk, lvl90, fps)
            # onset hits boundary if 10% level never reached after the bounded min,
            # i.e. the trace never dropped to baseline+10% inside the interval
            no_prev = prev_pk is None
            onset_at_boundary = (t10 is None) or (
                no_prev and local_min_idx == floor_idx and floor_idx == pk - pre_n
                and y[floor_idx] > lvl10)
            if t10 is not None and t90 is not None and t90 >= t10:
                rise_time = t90 - t10
            else:
                rise_time = np.nan
            time_to_peak = (pk - (local_min_idx)) / fps  # bounded-min -> peak

            # ---- Fix 2: decay observed to the NEXT local minimum, capped ----
            cap = min(pk + max_decay_n, len(y) - 1)
            seg_full = y[pk:cap + 1]
            # first local minimum = first index where the trace turns back up
            # (a rise-back of > noise), i.e. the onset of the following event.
            first_min_rel = len(seg_full) - 1
            for i in range(1, len(seg_full) - 1):
                if seg_full[i] < seg_full[i - 1] and seg_full[i + 1] > seg_full[i] + noise:
                    first_min_rel = i
                    break
            end = pk + max(first_min_rel, 2)
            seg_decay = y[pk:end + 1]
            if seg_decay.size < 4:
                continue
            window_dur = (seg_decay.size - 1) / fps
            t = np.arange(seg_decay.size) / fps
            # completion: does it fall to decay_frac of amplitude within window?
            decay_target = baseline + cfg.decay_frac * amp
            decay_incomplete = bool(np.min(seg_decay) > decay_target)
            tau, ss = np.nan, np.nan
            try:
                a0 = peak_val - seg_decay[-1]
                popt, _ = curve_fit(
                    _mono_decay, t, seg_decay,
                    p0=[max(a0, 1e-3), min(0.5, window_dur / 2), seg_decay[-1]],
                    maxfev=10000,
                    bounds=([0, 0.05, -np.inf], [np.inf, window_dur, np.inf]))
                tau = float(popt[1])
                fit = _mono_decay(t, *popt)
                ss = 1 - np.sum((seg_decay - fit) ** 2) / (
                    np.sum((seg_decay - seg_decay.mean()) ** 2) + 1e-12)
            except (RuntimeError, ValueError):
                tau, ss = np.nan, np.nan
            tau_extrapolated = bool(np.isfinite(tau) and tau >= 0.95 * window_dur)
            # Sub-resolution decay: tau below ~1.5 sampling intervals means the
            # reuptake completes within 1-2 frames and tau is quantized by the
            # frame period, not physiology. Flag (do not drop): at higher fps
            # these would resolve. `decay_subresolution` is the resolution floor.
            dt = 1.0 / fps
            decay_subresolution = bool(np.isfinite(tau) and tau < 1.5 * dt)
            # Like-for-like reuptake vs release: convert the mono-exponential
            # decay tau to a 10-90% FALL time (tau * ln 9) so it is directly
            # comparable to the 10-90% rise time. reuptake_over_release keeps the
            # raw tau/rise ratio for backward compatibility.
            fall_1090 = float(tau * np.log(9.0)) if np.isfinite(tau) else np.nan
            rise_faster_than_fall = (bool(rise_time < fall_1090)
                                     if (np.isfinite(rise_time) and np.isfinite(fall_1090))
                                     else None)

            rr = (float(tau / rise_time) if (np.isfinite(tau) and
                  np.isfinite(rise_time) and rise_time > 0) else np.nan)
            rows.append(dict(
                worm_id=worm_id, segment=int(seg), hemisegment=hemi,
                region=region_of(int(seg), head_segments), peak_dff=peak_val, baseline_dff=baseline,
                amp_dff=float(amp),
                rise_time_s=float(rise_time) if np.isfinite(rise_time) else np.nan,
                time_to_peak_s=float(time_to_peak),
                decay_tau_s=float(tau) if np.isfinite(tau) else np.nan,
                fall_1090_s=fall_1090,
                decay_window_s=float(window_dur),
                reuptake_over_release=rr,
                rise_faster_than_fall=rise_faster_than_fall,
                decay_r2=float(ss) if np.isfinite(ss) else np.nan,
                onset_at_boundary=bool(onset_at_boundary),
                decay_incomplete=decay_incomplete,
                tau_extrapolated=tau_extrapolated,
                decay_subresolution=decay_subresolution,
                confirmatory=bool(np.isfinite(ss) and ss >= cfg.r2_floor_confirm
                                  and not decay_incomplete and not tau_extrapolated
                                  and not onset_at_boundary),
            ))
    return pd.DataFrame(rows)


def clean_transients(rr: pd.DataFrame, level: str = "confirmatory") -> pd.DataFrame:
    """Filter a release_reuptake table by quality tier.

    level='confirmatory' -> only clean, in-window, well-fit transients
    level='exploratory'  -> drop hard-invalid (boundary onset, incomplete decay,
                            extrapolated tau) but keep R^2>=0.5 fits
    """
    if rr.empty:
        return rr
    good = rr.copy()
    if level == "confirmatory":
        return good[good["confirmatory"]].copy()
    keep = (~good["onset_at_boundary"] & ~good["decay_incomplete"]
            & ~good["tau_extrapolated"] & (good["decay_r2"] >= 0.5))
    return good[keep].copy()


# --------------------------------------------------------------------------- #
# Inter-signal timing (between calcium channels)
# --------------------------------------------------------------------------- #
def _xcorr_lag(a, b, fps, maxlag_s=3.0):
    """Best lag (s) of b relative to a by normalised cross-correlation.
    Positive => b lags a (a leads)."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if a.size < 10:
        return np.nan, np.nan
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    n = a.size
    maxlag = int(round(maxlag_s * fps))
    xc = signal.correlate(b, a, mode="full") / n
    lags = signal.correlation_lags(n, n, mode="full")
    sel = np.abs(lags) <= maxlag
    xc, lags = xc[sel], lags[sel]
    k = int(np.argmax(xc))
    return lags[k] / fps, float(xc[k])


def intersignal_timing(df: pd.DataFrame, worm_id: str) -> pd.DataFrame:
    """RETIRED (Stage 2b) -- kept only so nothing importing this module breaks;
    run_one.py and the results browser no longer call it, and its output is
    not reported anywhere. Neither of its two readouts is sub-frame capable:
    plugin_lag_ms is the extractor's own frame-quantized lag (this pilot's
    5 Hz data produced an implausible ~-3 s value), and xcorr_lag_s is an
    INTEGER-SAMPLE cross-correlation argmax that is frequently exactly 0 at
    this frame rate -- indistinguishable from "no lag" when the true lag is
    just below one frame. Use `interchannel_timing()` instead, which is
    sub-frame capable (Hilbert phase difference, or cross-correlation with
    parabolic peak interpolation) and never reports the pilot's zero/implausible
    values.

    Two independent readouts:
      plugin_lag_ms : median of the plugin's own lag_XY_ms (only where
                      lag_resolved==1)
      xcorr_lag_s   : cross-correlation lag between channel dF/F0 traces
    Channel pairs use only pairs whose channels are both reliable in the body
    (green-red here; blue pairs kept but blue is ER, interpret separately).
    """
    fps = float(df["fps"].iloc[0])
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(HEAD_SEGMENTS))]
    pairs = [("green", "red", "RG"), ("green", "blue", "GB"), ("red", "blue", "RB")]
    rows = []
    for a, b, tag in pairs:
        # plugin lag
        lag_col = f"lag_{tag}_ms"
        plug = np.nan
        if lag_col in d and "lag_resolved" in d:
            sub = d.loc[d["lag_resolved"] == 1, lag_col]
            plug = float(sub.median()) if sub.notna().any() else np.nan
        # xcorr per segment-hemiseg, then median
        lags = []
        for _, g in d.groupby(["segment", "hemisegment"]):
            g = g.sort_values("frame")
            lag, peak = _xcorr_lag(g[f"{a}_dff"], g[f"{b}_dff"], fps)
            if np.isfinite(lag) and peak > 0.2:
                lags.append(lag)
        rows.append(dict(worm_id=worm_id, pair=tag,
                         lead_channel=a, lag_channel=b,
                         plugin_lag_ms=plug,
                         xcorr_lag_s=float(np.median(lags)) if lags else np.nan,
                         n_seg=len(lags)))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Contraction-amplitude vs calcium, and movement vs calcium
# --------------------------------------------------------------------------- #
def amplitude_coupling(df: pd.DataFrame, worm_id: str,
                       value: str = "green_dff",
                       amp_col: str = "seg_angle_deg") -> pd.DataFrame:
    """Segment contraction amplitude (angle) vs calcium, with lead/lag.

    Per reliable segment x hemisegment: zero-lag correlation and cross-corr
    lag between |seg_angle_deg| (contraction amplitude) and calcium dF/F0.
    Positive xcorr_lag_s => calcium leads angle (activation precedes bend).
    """
    fps = float(df["fps"].iloc[0])
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(HEAD_SEGMENTS))]
    rows = []
    for (seg, hemi), g in d.groupby(["segment", "hemisegment"]):
        g = g.sort_values("frame")
        amp = g[amp_col].abs().to_numpy()
        ca = g[value].to_numpy()
        m = np.isfinite(amp) & np.isfinite(ca)
        if m.sum() < 20:
            continue
        r = np.corrcoef(amp[m], ca[m])[0, 1]
        lag, peak = _xcorr_lag(ca[m], amp[m], fps)   # ca leads amp if >0
        rows.append(dict(worm_id=worm_id, segment=int(seg), hemisegment=hemi,
                         region=region_of(int(seg)),
                         r_zero_lag=float(r),
                         ca_leads_angle_s=float(lag), xcorr_peak=float(peak)))
    return pd.DataFrame(rows)


def movement_coupling(df: pd.DataFrame, worm_id: str,
                      value: str = "green_dff",
                      vel_col: str = "axial_vel_px_s") -> pd.DataFrame:
    """Whole-worm displacement (axial velocity) vs body-averaged calcium.

    Aggregates reliable-segment calcium to one body-mean trace per frame,
    correlates with |axial velocity|, and reports cross-corr lag
    (positive => calcium leads movement).
    """
    fps = float(df["fps"].iloc[0])
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(HEAD_SEGMENTS))]
    per_frame = d.groupby("frame").agg(ca=(value, "mean"),
                                       vel=(vel_col, "first")).reset_index()
    ca = per_frame["ca"].to_numpy()
    vel = per_frame["vel"].abs().to_numpy()
    m = np.isfinite(ca) & np.isfinite(vel)
    if m.sum() < 20:
        return pd.DataFrame([dict(worm_id=worm_id, r_zero_lag=np.nan,
                                  ca_leads_move_s=np.nan, n=int(m.sum()))])
    r = np.corrcoef(ca[m], vel[m])[0, 1]
    lag, peak = _xcorr_lag(ca[m], vel[m], fps)
    return pd.DataFrame([dict(worm_id=worm_id, r_zero_lag=float(r),
                              ca_leads_move_s=float(lag), xcorr_peak=float(peak),
                              n=int(m.sum()))])


# --------------------------------------------------------------------------- #
# Wave propagation
# --------------------------------------------------------------------------- #
def wave_propagation(df: pd.DataFrame, worm_id: str, value: str = "green_dff",
                     hemisegment: str = "mean", head_segments=HEAD_SEGMENTS) -> dict:
    """Anterior->posterior wave speed, direction, and frequency for `value`
    (calcium dF/F0 in Stages 2a/2b; seg_curv_deg for the Stage 3a kinematic
    body-wave, called with head_segments=() for the full body).

    Uses a PHASE-GRADIENT estimator, which is robust at the low frame rates
    (~5 Hz) of freely-moving worm imaging where adjacent-segment delays fall
    below one frame and pairwise cross-correlation collapses to 'standing'.

    Method: band-pass the kymograph around the dominant undulation frequency,
    take the Hilbert analytic phase of each segment's trace, unwrap phase
    along the body at each frame, and fit phase vs segment position. The
    slope (rad/segment) with the temporal frequency gives:
        wave_speed = 2*pi*f / slope        [segments/s]
    Sign of the slope gives direction (A->P if phase increases posteriorly).
    A coherence value (mean resultant length of per-frame phase-gradient fits)
    reports how wave-like the pattern is (1 = perfectly ordered, 0 = none).

    Also returns the PER-FRAME phase-gradient fit (frame_numbers, frame_slopes,
    frame_r2) so callers needing a frame-by-frame classification (Stage 3a's
    locomotion_summary: forward/backward per frame from the sign of the
    per-frame slope) reuse this same fit rather than re-deriving it. Existing
    callers that only want the whole-recording summary can ignore these keys.
    """
    M, seg_axis, frames = wa.kymograph(df, worm_id, value=value,
                                       hemisegment=hemisegment)
    fps = float(df["fps"].iloc[0])
    keep = (seg_axis >= max(head_segments) + 1) if head_segments else np.ones_like(seg_axis, dtype=bool)
    M, seg_axis = M[keep].astype(float), seg_axis[keep]
    # interpolate NaNs per segment
    for i in range(M.shape[0]):
        M[i] = pd.Series(M[i]).interpolate(limit_direction="both").to_numpy()
    M = np.nan_to_num(M)
    if M.shape[1] < 16 or M.shape[0] < 4:
        return dict(worm_id=worm_id, wave_speed_seg_per_s=np.nan,
                    direction="undetermined", coherence=np.nan,
                    dominant_freq_hz=np.nan, n_frames=int(M.shape[1]),
                    frame_numbers=frames, frame_slopes=np.full(M.shape[1], np.nan),
                    frame_r2=np.full(M.shape[1], np.nan),
                    seg_axis=seg_axis, seg_envelope=None)

    # dominant undulation frequency from body-mean signal
    body = M.mean(0)
    f, p = signal.welch(body - body.mean(), fs=fps, nperseg=min(64, body.size))
    # ignore DC/very-low drift: restrict to plausible undulation band 0.1-2 Hz
    band = (f >= 0.1) & (f <= 2.0)
    if band.any():
        f0 = float(f[band][np.argmax(p[band])])
    else:
        f0 = float(f[np.argmax(p)]) if f.size else np.nan

    # band-pass each segment around f0 then Hilbert phase
    if not np.isfinite(f0) or f0 <= 0:
        return dict(worm_id=worm_id, wave_speed_seg_per_s=np.nan,
                    direction="undetermined", coherence=np.nan,
                    dominant_freq_hz=f0, n_frames=int(M.shape[1]),
                    frame_numbers=frames, frame_slopes=np.full(M.shape[1], np.nan),
                    frame_r2=np.full(M.shape[1], np.nan),
                    seg_axis=seg_axis, seg_envelope=None)
    lo, hi = max(0.05, f0 * 0.5), min(fps / 2 - 0.01, f0 * 1.8)
    sos = signal.butter(2, [lo, hi], btype="band", fs=fps, output="sos")
    Mb = signal.sosfiltfilt(sos, M, axis=1)
    analytic = signal.hilbert(Mb, axis=1)          # per-segment analytic signal over time
    envelope = np.abs(analytic)                     # per-segment instantaneous amplitude
    phase = np.unwrap(np.angle(analytic), axis=0)  # along body

    x = seg_axis.astype(float)
    slopes, r2s = [], []
    for t in range(phase.shape[1]):
        y = phase[:, t]
        A = np.polyfit(x, y, 1)
        slope = A[0]
        yhat = np.polyval(A, x)
        ss = 1 - np.sum((y - yhat) ** 2) / (np.sum((y - y.mean()) ** 2) + 1e-12)
        slopes.append(slope); r2s.append(ss)
    slopes = np.array(slopes); r2s = np.array(r2s)
    good = r2s > 0.5
    if good.sum() < 5:
        med_slope = np.median(slopes)
        coherence = float(np.mean(r2s > 0.5))
    else:
        med_slope = float(np.median(slopes[good]))
        coherence = float(good.mean())

    speed = (2 * np.pi * f0 / abs(med_slope)
             if np.isfinite(med_slope) and med_slope != 0 else np.nan)
    direction = ("anterior->posterior" if med_slope > 0
                 else "posterior->anterior" if med_slope < 0 else "standing")
    return dict(worm_id=worm_id,
                dominant_freq_hz=f0,
                phase_slope_rad_per_seg=float(med_slope),
                wave_speed_seg_per_s=float(speed) if np.isfinite(speed) else np.nan,
                direction=direction,
                coherence=coherence,
                n_frames=int(M.shape[1]),
                frame_numbers=frames, frame_slopes=slopes, frame_r2=r2s,
                seg_axis=seg_axis, seg_envelope=envelope)


# --------------------------------------------------------------------------- #
# Kinematics (Stage 3a): posture/velocity descriptors, NOT head-masked.
# Posture is valid over the whole body (segments 0-23); the head mask exists
# only because green/red calcium bleeds through the pharynx there. Gate on
# midline-tracking quality instead (eigen_fit_quality, partial_flag, length
# flags, self_approach_flag), never on head_segments.
# --------------------------------------------------------------------------- #
def undulation_descriptors(df: pd.DataFrame, worm_id: str,
                          curv_col: str = "seg_curv_deg") -> dict:
    """Body-bend wave descriptors from posture alone: frequency, wave speed,
    direction, wavelength, and bend amplitude.

    Reuses wave_propagation()'s phase-gradient estimator on `curv_col` with
    head_segments=() (full body, no calcium head mask applies to posture) --
    one wave estimator shared with the calcium kymograph, not a second one
    reimplemented here.

    wavelength_segments is derived directly from the already-fitted phase
    slope (2*pi / |slope|), not by re-dividing wave speed by frequency, so it
    can't blow up from a near-zero frequency estimate that speed's own ratio
    already guards against.

    bend_amplitude_deg is the median Hilbert-envelope amplitude of the
    band-passed curvature kymograph (the same band-passed signal
    wave_propagation computes its phase from), body-wide.

    Honesty guard: if wave_propagation can't resolve a coherent body wave
    (direction=='undetermined' or no finite dominant frequency), every
    descriptor here is NaN and resolved=False -- never a fabricated
    wavelength or amplitude from a wave that wasn't actually detected.
    """
    wp = wave_propagation(df, worm_id, value=curv_col, head_segments=())
    f0 = wp.get("dominant_freq_hz", np.nan)
    resolved = bool(wp.get("direction") != "undetermined" and np.isfinite(f0))
    slope = wp.get("phase_slope_rad_per_seg", np.nan)
    wavelength = (2 * np.pi / abs(slope)
                 if resolved and np.isfinite(slope) and slope != 0 else np.nan)

    envelope = wp.get("seg_envelope")
    amp_mean = (float(np.median(np.median(envelope, axis=1)))
               if resolved and envelope is not None else np.nan)

    return dict(worm_id=worm_id,
                resolved=resolved,
                dominant_freq_hz=f0,
                coherence=wp.get("coherence", np.nan),
                wavelength_segments=wavelength,
                wave_speed_seg_per_s=wp.get("wave_speed_seg_per_s", np.nan),
                direction=wp.get("direction", "undetermined"),
                bend_amplitude_deg=amp_mean,
                n_frames=int(wp.get("n_frames", 0)),
                reason="" if resolved else "no coherent body wave detected "
                                            "(see coherence/direction above)")


def locomotion_summary(df: pd.DataFrame, worm_id: str,
                       curv_col: str = "seg_curv_deg") -> dict:
    """Whole-body locomotion classification: forward/backward fraction,
    reversals, signed crawl speed, angular velocity, and omega turns -- all
    from posture and the body-wave direction, none of it head-masked.

    Forward/backward and reversals are derived from the SIGN OF THE BODY-WAVE
    PROPAGATION DIRECTION per frame (wave_propagation's per-frame phase-
    gradient slope on `curv_col`, gated on that frame's own r2>0.5), which is
    the biological definition of crawl direction (anterior->posterior bending
    wave = forward; posterior->anterior = backward) -- NEVER from
    axial_vel_px_s's own sign, which is a per-segment local quantity with no
    guaranteed whole-body sign convention. axial_vel_px_s contributes only
    its magnitude: signed_speed = |mean axial_vel_px_s over the body| * (+1
    forward / -1 backward), re-signed by the wave classification.

    Honesty guards:
      - Frames whose per-frame wave fit is not coherent (r2<=0.5) are
        'unresolved', never silently folded into forward or backward.
      - Reversals count only resolved-to-resolved forward<->backward
        transitions in sequence; an unresolved frame between two same-
        direction frames does not itself manufacture a reversal.
      - self_approach_frac and eigen_fit_quality_mean (midline-tracking
        quality) are reported as concrete numbers on every summary, not a
        vague caveat.
      - Omega turns are counted two ways and reported separately:
        self_approach_flag firing, or cumulative |angular_vel_deg_s| over a
        ~1s window exceeding 135 degrees (a sharp reorientation the flag
        alone can miss) -- so a reader can see which signal drove each count.
      - If wave_propagation can't fit a body wave at all, the whole summary
        is resolved=False with NaN direction-derived fields; self_approach
        and eigen-fit numbers (not wave-dependent) are still reported.
    """
    d = df[df["worm_id"] == worm_id].copy()
    fps = float(d["fps"].iloc[0])
    wp = wave_propagation(d, worm_id, value=curv_col, head_segments=())

    self_approach_frac = (float(d["self_approach_flag"].mean())
                          if "self_approach_flag" in d.columns and len(d) else np.nan)
    eigen_fit_quality_mean = (float(d["eigen_fit_quality"].mean())
                              if "eigen_fit_quality" in d.columns and len(d) else np.nan)

    frame_body = d.groupby("frame").agg(
        axial_vel_px_s=("axial_vel_px_s", "mean"),
        angular_vel_deg_s=("angular_vel_deg_s", "mean"),
        self_approach_flag=("self_approach_flag", "max"),
    ).reset_index().sort_values("frame")

    fnums = wp.get("frame_numbers")
    fslopes = wp.get("frame_slopes")
    fr2 = wp.get("frame_r2")
    if fnums is None or fslopes is None or len(fnums) == 0:
        return dict(worm_id=worm_id, resolved=False,
                    reason="wave_propagation could not fit a body wave",
                    self_approach_frac=self_approach_frac,
                    eigen_fit_quality_mean=eigen_fit_quality_mean,
                    n_frames=int(len(frame_body)))

    fr2 = np.asarray(fr2, dtype=float)
    fslopes = np.asarray(fslopes, dtype=float)
    good = np.isfinite(fr2) & (fr2 > 0.5)
    cls = np.where(~good, "unresolved",
          np.where(fslopes > 0, "forward",
          np.where(fslopes < 0, "backward", "unresolved")))
    dirn = pd.DataFrame({"frame": np.asarray(fnums), "cls": cls})
    fb = frame_body.merge(dirn, on="frame", how="inner")
    n = len(fb)
    if n == 0:
        return dict(worm_id=worm_id, resolved=False,
                    reason="no frames overlap between kinematics and wave fit",
                    self_approach_frac=self_approach_frac,
                    eigen_fit_quality_mean=eigen_fit_quality_mean,
                    n_frames=0)

    sign = fb["cls"].map({"forward": 1.0, "backward": -1.0, "unresolved": np.nan})
    fb["signed_speed_px_s"] = fb["axial_vel_px_s"].abs() * sign

    frac_forward = float((fb["cls"] == "forward").mean())
    frac_backward = float((fb["cls"] == "backward").mean())
    frac_unresolved = float((fb["cls"] == "unresolved").mean())

    resolved_seq = fb.loc[fb["cls"] != "unresolved", "cls"].to_numpy()
    n_reversals = (int(np.sum(resolved_seq[1:] != resolved_seq[:-1]))
                  if resolved_seq.size > 1 else 0)

    signed_speed = fb["signed_speed_px_s"].to_numpy(dtype=float)
    finite_speed = signed_speed[np.isfinite(signed_speed)]
    crawl_speed_px_s = float(np.mean(np.abs(finite_speed))) if finite_speed.size else np.nan
    mean_signed_speed_px_s = float(np.mean(finite_speed)) if finite_speed.size else np.nan

    ang = fb["angular_vel_deg_s"].to_numpy(dtype=float)
    ang_finite = ang[np.isfinite(ang)]
    ang_mean_abs = float(np.mean(np.abs(ang_finite))) if ang_finite.size else np.nan
    ang_p95_abs = float(np.percentile(np.abs(ang_finite), 95)) if ang_finite.size else np.nan

    # omega turns: self-approach flag OR cumulative |angular_vel_deg_s| turned
    # through the body over a ~1s sliding window exceeding 135 deg.
    win = max(1, int(round(fps)))
    dt = 1.0 / fps
    cum_turn = pd.Series(ang).rolling(win, min_periods=win).apply(
        lambda w: abs(np.nansum(w) * dt) if np.isfinite(w).any() else np.nan, raw=True
    ).to_numpy()
    turn_angle_hit = np.isfinite(cum_turn) & (cum_turn > 135.0)
    self_approach_hit = fb["self_approach_flag"].fillna(0).astype(bool).to_numpy()
    n_omega_self_approach = int(np.sum(self_approach_hit))
    n_omega_turn_angle = int(np.sum(turn_angle_hit & ~self_approach_hit))
    n_omega_turns = int(np.sum(self_approach_hit | turn_angle_hit))

    return dict(worm_id=worm_id,
                resolved=True,
                n_frames=n,
                frac_forward=frac_forward,
                frac_backward=frac_backward,
                frac_unresolved=frac_unresolved,
                n_reversals=n_reversals,
                crawl_speed_px_s=crawl_speed_px_s,
                mean_signed_speed_px_s=mean_signed_speed_px_s,
                angular_vel_deg_s_mean_abs=ang_mean_abs,
                angular_vel_deg_s_p95_abs=ang_p95_abs,
                n_omega_turns=n_omega_turns,
                n_omega_turns_self_approach=n_omega_self_approach,
                n_omega_turns_turn_angle=n_omega_turn_angle,
                self_approach_frac=self_approach_frac,
                eigen_fit_quality_mean=eigen_fit_quality_mean,
                wave_coherence=wp.get("coherence", np.nan),
                reason="")


# --------------------------------------------------------------------------- #
# Calcium-to-curvature phase lag (Stage 2b: phase upgrade of amplitude_coupling)
# --------------------------------------------------------------------------- #
def _band_hilbert_phase(y: np.ndarray, f0: float, fps: float) -> np.ndarray:
    """Band-pass `y` around f0 (same proportional window wave_propagation
    uses) and return its unwrapped Hilbert analytic phase."""
    lo, hi = max(0.05, f0 * 0.5), min(fps / 2 - 0.01, f0 * 1.8)
    sos = signal.butter(2, [lo, hi], btype="band", fs=fps, output="sos")
    yb = signal.sosfiltfilt(sos, y)
    return np.unwrap(np.angle(signal.hilbert(yb)))


def _phase_lag_seconds(phase_lead: np.ndarray, phase_lag: np.ndarray, f0: float) -> np.ndarray:
    """Per-sample time lag (s) implied by two instantaneous phases at a shared
    dominant frequency f0. Positive => the FIRST argument (phase_lead) leads
    (precedes) the second. Wraps the phase difference to (-pi, pi] before
    converting, so accumulated multi-cycle unwrap drift can't inflate it."""
    dphi = np.angle(np.exp(1j * (phase_lead - phase_lag)))
    return dphi / (2 * np.pi * f0)


def curvature_phase_lag(df: pd.DataFrame, worm_id: str, value: str = "green_dff",
                        curv_col: str = "seg_curv_deg", head_segments=HEAD_SEGMENTS,
                        min_coherence: float = 0.5, min_samples: int = 20) -> pd.DataFrame:
    """Calcium-to-curvature phase lag, per segment x hemisegment -- the phase
    upgrade of amplitude_coupling's zero-lag correlation + integer-frame
    cross-correlation argmax, which returns 0 whenever the true lag is below
    one frame (routine at ~5 Hz -- this was the pilot's failure mode).

    SIGN CONVENTION (fixed here; don't re-derive it elsewhere):
        lag_s > 0  =>  CALCIUM PRECEDES (leads) the bend.
        lag_s < 0  =>  calcium FOLLOWS the bend.
    lag_s is calcium's Hilbert phase minus curvature's, converted from radians
    to seconds at the recording's dominant undulation frequency.

    Method: reuses wave_propagation()'s dominant frequency and coherence (the
    same Hilbert-phase machinery applied there spatially across segments, and
    here temporally within one segment) to band-pass both `value` and
    `curv_col` around that frequency, then takes each signal's own analytic
    phase and converts their difference to a time lag. Reported only when
    coherence >= min_coherence, i.e. the animal is genuinely undulating
    rhythmically body-wide -- never from a raw integer-frame argmax.

    Honesty guards:
      - Unresolved (coherence too low, no dominant frequency, or insufficient
        valid samples) => lag_s is NaN and resolved=False. Never zero.
      - lag_uncertainty_s is the SEM of the per-frame lag estimate within the
        segment; if |lag_s| < lag_uncertainty_s (not distinguishable from zero
        given the noise), lag_s is also NaN'd and resolved=False.
      - self_approach_frac is carried on every row: curvature is suspect when
        self-approach fires heavily (~62% was seen on one pilot animal), and
        this number lets a reader judge that directly.
      - Locomotor confound (forward vs backward) is NOT resolved from any
        column here and is stated as a caveat by the caller (results_browser)
        instead of guessed at.
    """
    fps = float(df["fps"].iloc[0])
    wp = wave_propagation(df, worm_id, value=value, head_segments=head_segments)
    f0, coherence = wp["dominant_freq_hz"], wp["coherence"]
    gate_ok = bool(np.isfinite(f0) and f0 > 0 and np.isfinite(coherence) and coherence >= min_coherence)

    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(head_segments))]
    self_approach_frac = (float(d["self_approach_flag"].mean())
                          if "self_approach_flag" in d.columns and len(d) else np.nan)

    rows = []
    for (seg, hemi), g in d.groupby(["segment", "hemisegment"]):
        g = g.sort_values("frame")
        ca = g[value].to_numpy(dtype=float)
        cv = g[curv_col].to_numpy(dtype=float)
        base = dict(segment=int(seg), hemisegment=hemi, region=region_of(int(seg), head_segments),
                   dominant_freq_hz=f0, coherence=coherence, self_approach_frac=self_approach_frac)
        if not gate_ok:
            rows.append(dict(base, lag_s=np.nan, lag_uncertainty_s=np.nan, resolved=False,
                             reason=f"wave not coherent enough (coherence<{min_coherence:.2f} "
                                    f"or no dominant frequency)"))
            continue
        if np.isfinite(ca).sum() < min_samples or np.isfinite(cv).sum() < min_samples:
            rows.append(dict(base, lag_s=np.nan, lag_uncertainty_s=np.nan, resolved=False,
                             reason="insufficient valid samples"))
            continue
        ca_i = pd.Series(ca).interpolate(limit_direction="both").to_numpy()
        cv_i = pd.Series(cv).interpolate(limit_direction="both").to_numpy()
        if not (np.isfinite(ca_i).all() and np.isfinite(cv_i).all()):
            rows.append(dict(base, lag_s=np.nan, lag_uncertainty_s=np.nan, resolved=False,
                             reason="unfillable gaps in calcium or curvature trace"))
            continue
        try:
            phase_ca = _band_hilbert_phase(ca_i, f0, fps)
            phase_cv = _band_hilbert_phase(cv_i, f0, fps)
        except Exception as e:
            rows.append(dict(base, lag_s=np.nan, lag_uncertainty_s=np.nan, resolved=False,
                             reason=f"band-pass/Hilbert failed: {e}"))
            continue
        lag_series = _phase_lag_seconds(phase_ca, phase_cv, f0)
        lag_s = float(np.median(lag_series))
        lag_uncertainty_s = float(np.std(lag_series) / np.sqrt(lag_series.size))
        resolved = bool(np.isfinite(lag_s) and lag_uncertainty_s > 0 and abs(lag_s) >= lag_uncertainty_s)
        rows.append(dict(base,
                         lag_s=lag_s if resolved else np.nan,
                         lag_uncertainty_s=lag_uncertainty_s,
                         resolved=resolved,
                         reason="" if resolved else "lag not distinguishable from zero given estimate noise"))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Sub-frame inter-channel timing (Stage 2b: replaces intersignal_timing)
# --------------------------------------------------------------------------- #
def _xcorr_lag_parabolic(a: np.ndarray, b: np.ndarray, fps: float, maxlag_s: float = 3.0):
    """Cross-correlation lag of b relative to a, refined to sub-sample
    precision by parabolic interpolation around the discrete argmax -- NEVER
    the bare integer-frame argmax, which is exactly the pilot's failure mode
    (returns exactly 0 whenever the true lag is under one frame).
    Positive => b lags a (a leads). Returns (lag_s, peak_corr), (nan, nan) if
    there isn't enough data."""
    a = np.asarray(a, float); b = np.asarray(b, float)
    m = np.isfinite(a) & np.isfinite(b)
    a, b = a[m], b[m]
    if a.size < 10:
        return np.nan, np.nan
    a = (a - a.mean()) / (a.std() + 1e-9)
    b = (b - b.mean()) / (b.std() + 1e-9)
    n = a.size
    maxlag = int(round(maxlag_s * fps))
    xc = signal.correlate(b, a, mode="full") / n
    lags = signal.correlation_lags(n, n, mode="full")
    sel = np.abs(lags) <= maxlag
    xc, lags = xc[sel], lags[sel]
    k = int(np.argmax(xc))
    if 0 < k < len(xc) - 1:
        y0, y1, y2 = xc[k - 1], xc[k], xc[k + 1]
        denom = y0 - 2 * y1 + y2
        frac = float(np.clip(0.5 * (y0 - y2) / denom, -1.0, 1.0)) if denom != 0 else 0.0
    else:
        frac = 0.0   # peak at the search-window edge: no interpolation possible
    return float(lags[k] + frac) / fps, float(xc[k])


# Cytosolic (green) is the shared reference channel for both pairs; each pair
# is labeled with the biology its sign requires for correct reading (spec).
_INTERCHANNEL_PAIRS = [
    ("green", "blue", "green_vs_blue",
    "Cytosolic (green, GCaMP) vs ER (blue, BlueCaMP-X): store release/refill, "
    "not a simple delay. ER calcium can move OPPOSITE to cytosolic -- see "
    "direction_agreement (negative = moved opposite)."),
    ("green", "red", "green_vs_red",
    "Cytosolic (green, GCaMP) vs mitochondrial (red): uptake. Mitochondrial "
    "calcium is expected to FOLLOW the cytosolic rise (positive lag_s is the "
    "default physiological expectation)."),
]


def interchannel_timing(df: pd.DataFrame, worm_id: str, head_segments=HEAD_SEGMENTS,
                        min_coherence: float = 0.5, min_samples: int = 20) -> pd.DataFrame:
    """Sub-frame timing between calcium compartments, reported per recording.
    Replaces `intersignal_timing` (Stage 2b): that function's plugin_lag_ms
    was frame-quantized (an implausible ~-3 s on this pilot's data) and its
    xcorr_lag_s used an integer-sample argmax that is frequently exactly 0 at
    ~5 Hz -- neither is reported here, and neither is sub-frame capable.

    SIGN CONVENTION: positive lag_s means the SECOND-named channel lags the
    first (first channel leads) -- e.g. for green_vs_blue, positive lag_s
    means blue lags green.

    Method, in priority order:
      1. Hilbert phase difference (same machinery as curvature_phase_lag /
         wave_propagation) when the recording is coherently rhythmic (gated
         on wave_propagation's coherence for the green channel).
      2. Cross-correlation with parabolic peak interpolation otherwise --
         still sub-frame capable, just without a shared undulation frequency
         to phase-lock to.
    Both are sub-frame capable; the bare integer-frame argmax is never used.

    direction_agreement is the zero-lag correlation between the two channels'
    dF/F0 traces: positive means they moved the same way, negative means
    opposite (expected for the ER pair some of the time).

    Unresolved (no usable segment, or an estimate not distinguishable from
    zero given its noise) => lag_s is NaN and resolved=False, never zero.
    """
    fps = float(df["fps"].iloc[0])
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(head_segments))]
    wp = wave_propagation(df, worm_id, value="green_dff", head_segments=head_segments)
    f0, coherence = wp["dominant_freq_hz"], wp["coherence"]
    phase_gate_ok = bool(np.isfinite(f0) and f0 > 0 and np.isfinite(coherence) and coherence >= min_coherence)

    rows = []
    for a, b, tag, biology in _INTERCHANNEL_PAIRS:
        cola, colb = f"{a}_dff", f"{b}_dff"
        if cola not in d.columns or colb not in d.columns:
            rows.append(dict(pair=tag, lead_channel=a, lag_channel=b, method="none",
                             lag_s=np.nan, lag_uncertainty_s=np.nan, resolved=False,
                             direction_agreement=np.nan, n_seg=0, coherence=coherence,
                             biology=biology, reason=f"missing column {cola} or {colb}"))
            continue

        lags_phase, lags_xcorr, dir_agree = [], [], []
        for _, g in d.groupby(["segment", "hemisegment"]):
            g = g.sort_values("frame")
            ca, cb = g[cola].to_numpy(dtype=float), g[colb].to_numpy(dtype=float)
            m = np.isfinite(ca) & np.isfinite(cb)
            if m.sum() < min_samples:
                continue
            r = np.corrcoef(ca[m], cb[m])[0, 1]
            if np.isfinite(r):
                dir_agree.append(r)
            if phase_gate_ok:
                ca_i = pd.Series(ca).interpolate(limit_direction="both").to_numpy()
                cb_i = pd.Series(cb).interpolate(limit_direction="both").to_numpy()
                if np.isfinite(ca_i).all() and np.isfinite(cb_i).all():
                    try:
                        phase_a = _band_hilbert_phase(ca_i, f0, fps)
                        phase_b = _band_hilbert_phase(cb_i, f0, fps)
                        lags_phase.append(_phase_lag_seconds(phase_a, phase_b, f0))
                    except Exception:
                        pass
            lag_xc, peak = _xcorr_lag_parabolic(ca, cb, fps)
            if np.isfinite(lag_xc) and peak > 0.2:
                lags_xcorr.append(lag_xc)

        method, lag_s, lag_uncertainty_s, n_seg = "none", np.nan, np.nan, 0
        if lags_phase:
            all_lags = np.concatenate(lags_phase)
            lag_s = float(np.median(all_lags))
            lag_uncertainty_s = float(np.std(all_lags) / np.sqrt(all_lags.size))
            n_seg = len(lags_phase)
            method = "phase"
        elif lags_xcorr:
            lag_s = float(np.median(lags_xcorr))
            lag_uncertainty_s = (float(np.std(lags_xcorr) / np.sqrt(len(lags_xcorr)))
                                 if len(lags_xcorr) > 1 else np.nan)
            n_seg = len(lags_xcorr)
            method = "xcorr_parabolic"

        resolved = bool(np.isfinite(lag_s) and np.isfinite(lag_uncertainty_s)
                        and lag_uncertainty_s > 0 and abs(lag_s) >= lag_uncertainty_s)
        if method == "none":
            reason = "no segment produced a usable estimate"
        elif not resolved:
            reason = "lag not distinguishable from zero given estimate noise"
        else:
            reason = ""
        rows.append(dict(pair=tag, lead_channel=a, lag_channel=b, method=method,
                         lag_s=lag_s if resolved else np.nan,
                         lag_uncertainty_s=lag_uncertainty_s, resolved=resolved,
                         direction_agreement=float(np.median(dir_agree)) if dir_agree else np.nan,
                         n_seg=n_seg, coherence=coherence, biology=biology, reason=reason))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- #
# Phase-locked average contractile cycle
# --------------------------------------------------------------------------- #
def cycle_average(df: pd.DataFrame, worm_id: str, region: str = "anterior",
                  value: str = "green_dff", curv_ref: str = "seg_curv_deg",
                  vel_col: str | None = None,
                  n_phase: int = 24, head_segments=HEAD_SEGMENTS) -> dict:
    """Average contractile cycle for a body region.

    Cycles are defined from the body-bend oscillation (mean curvature of the
    region). Each cycle is resampled to `n_phase` phase bins (0..2pi), and the
    calcium dF/F0 and |curvature| are averaged across cycles => the mean
    contractile cycle waveform for that region/muscle group.

    head_segments=() (blue) includes the head, since blue is kept there.

    vel_col (Stage 3c, additive/optional -- default None preserves the exact
    prior return shape for every existing caller): when given, |vel_col| is
    ALSO phase-averaged the same way as calcium/curvature, adding vel_mean/
    vel_sem keys -- reused by the Stage 3c phase-axis neuromechanical overlay
    so it doesn't reimplement this phase-locked-averaging machinery a second
    time just to add a velocity trace.
    """
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(head_segments))].copy()
    d["region"] = d["segment"].map(lambda s: region_of(s, head_segments))
    d = d[d["region"] == region]
    if d.empty:
        return dict(worm_id=worm_id, region=region, n_cycles=0)
    fps = float(df["fps"].iloc[0])
    agg = {"curv": (curv_ref, "mean"), "ca": (value, "mean")}
    if vel_col is not None:
        agg["vel"] = (vel_col, lambda s: np.nanmean(np.abs(s)))
    per_frame = d.groupby("frame").agg(**agg).reset_index()
    curv = pd.Series(per_frame["curv"].to_numpy()).interpolate(
        limit_direction="both").to_numpy()
    ca = pd.Series(per_frame["ca"].to_numpy()).interpolate(
        limit_direction="both").to_numpy()
    vel = (pd.Series(per_frame["vel"].to_numpy()).interpolate(limit_direction="both").to_numpy()
          if vel_col is not None else None)
    # zero-crossings (neg->pos) of detrended curvature define cycle starts
    c = curv - np.nanmean(curv)
    zc = np.where((c[:-1] < 0) & (c[1:] >= 0))[0]
    if zc.size < 3:
        return dict(worm_id=worm_id, region=region, n_cycles=int(max(zc.size - 1, 0)))
    phase_ca, phase_cv, phase_vel = [], [], []
    for s, e in zip(zc[:-1], zc[1:]):
        if e - s < 3:
            continue
        xp = np.linspace(0, 1, e - s)
        grid = np.linspace(0, 1, n_phase)
        phase_ca.append(np.interp(grid, xp, ca[s:e]))
        phase_cv.append(np.interp(grid, xp, np.abs(c[s:e])))
        if vel is not None:
            phase_vel.append(np.interp(grid, xp, vel[s:e]))
    if not phase_ca:
        return dict(worm_id=worm_id, region=region, n_cycles=0)
    phase_ca = np.vstack(phase_ca); phase_cv = np.vstack(phase_cv)
    periods = np.diff(zc) / fps
    result = dict(worm_id=worm_id, region=region, n_cycles=phase_ca.shape[0],
                 mean_period_s=float(np.median(periods)),
                 phase=np.linspace(0, 2 * np.pi, n_phase),
                 ca_mean=phase_ca.mean(0), ca_sem=phase_ca.std(0) / np.sqrt(phase_ca.shape[0]),
                 curv_mean=phase_cv.mean(0),
                 ca_peak_phase=float(np.linspace(0, 2 * np.pi, n_phase)[phase_ca.mean(0).argmax()]))
    if vel is not None and phase_vel:
        phase_vel = np.vstack(phase_vel)
        result["vel_mean"] = phase_vel.mean(0)
        result["vel_sem"] = phase_vel.std(0) / np.sqrt(phase_vel.shape[0])
    return result


# --------------------------------------------------------------------------- #
# Neuromechanical chain (Stage 3c): calcium -> curvature -> translation.
# curvature_phase_lag (Stage 2b) is the first link (calcium->curvature).
# curvature_to_translation below is the missing second link (curvature->
# translation). propulsion_efficiency and calcium_output_decomposition
# combine both links into single-recording summaries. All robust MAGNITUDE
# form only -- a phase-resolved (bend-to-thrust timing) form is explicitly
# DEFERRED to higher frame rate, not approximated here.
# --------------------------------------------------------------------------- #
def curvature_to_translation(df: pd.DataFrame, worm_id: str,
                             curv_col: str = "seg_curv_deg",
                             vel_col: str = "axial_vel_px_s",
                             max_lag_s: float = 3.0) -> dict:
    """Second link in the neuromechanical chain: whole-body bending magnitude
    vs translation speed -- NOT head-masked (posture is valid over the whole
    body; see undulation_descriptors/locomotion_summary). Completes the chain
    alongside curvature_phase_lag (calcium->curvature, Stage 2b) and
    calcium_output_decomposition's propulsion half (calcium->translation),
    which were computed separately but never joined at this middle link.

    Per frame: whole-body mean |curvature| vs whole-body mean |axial
    velocity|. Zero-lag correlation plus a sub-frame cross-correlation lag
    (parabolic interpolation around the discrete argmax, the SAME estimator
    interchannel_timing uses) -- never an integer-frame argmax, which is
    frequently exactly 0 at this frame rate.

    SIGN CONVENTION: positive lag_s means TRANSLATION lags CURVATURE (bending
    leads propulsion) -- the causally-expected order (a segment bends, then
    the body moves); negative would mean translation precedes bending.

    Robust MAGNITUDE form only (Stage 3c). A phase-resolved bend-to-thrust
    timing form (exactly where in the bend cycle thrust peaks) needs a higher
    frame rate than this recording's ~5 Hz to resolve reliably -- DEFERRED,
    not silently approximated here.

    Honesty guard: unresolved (insufficient samples or no variation in either
    signal) => every numeric field is NaN and resolved=False, never zero.
    """
    d = df[df["worm_id"] == worm_id].copy()
    fps = float(d["fps"].iloc[0])
    per_frame = d.groupby("frame").agg(
        curv=(curv_col, lambda s: np.nanmean(np.abs(s))),
        vel=(vel_col, lambda s: np.nanmean(np.abs(s))),
    ).reset_index()
    curv = per_frame["curv"].to_numpy(dtype=float)
    vel = per_frame["vel"].to_numpy(dtype=float)
    ok = np.isfinite(curv) & np.isfinite(vel)
    n = int(ok.sum())

    self_approach_frac = (float(d["self_approach_flag"].mean())
                          if "self_approach_flag" in d.columns and len(d) else np.nan)
    eigen_fit_quality_mean = (float(d["eigen_fit_quality"].mean())
                             if "eigen_fit_quality" in d.columns and len(d) else np.nan)

    if n < 20 or np.nanstd(curv[ok]) == 0 or np.nanstd(vel[ok]) == 0:
        return dict(worm_id=worm_id, resolved=False, n=n,
                    r_zero_lag=np.nan, lag_s=np.nan, xcorr_peak=np.nan,
                    self_approach_frac=self_approach_frac,
                    eigen_fit_quality_mean=eigen_fit_quality_mean,
                    reason="insufficient valid samples or no variation in curvature/velocity")

    cu, ve = curv[ok], vel[ok]
    r0 = float(np.corrcoef(cu, ve)[0, 1])
    lag_s, xcorr_peak = _xcorr_lag_parabolic(cu, ve, fps, maxlag_s=max_lag_s)
    return dict(worm_id=worm_id, resolved=True, n=n,
                r_zero_lag=r0, lag_s=lag_s, xcorr_peak=xcorr_peak,
                self_approach_frac=self_approach_frac,
                eigen_fit_quality_mean=eigen_fit_quality_mean,
                reason="")


def propulsion_efficiency(df: pd.DataFrame, worm_id: str,
                          curv_col: str = "seg_curv_deg",
                          vel_col: str = "axial_vel_px_s",
                          midline_col: str = "midline_len_px",
                          min_bend_rad: float = 0.01) -> pd.DataFrame:
    """Robust MAGNITUDE-form propulsion efficiency: forward travel speed,
    normalized to body length, per unit of normalized bending amplitude --
    whole-body, per region (anterior/posterior), AND per segment (the spatial
    breakdown of where calcium-driven bending actually converts to
    propulsion versus where it only deforms).

        propulsion_efficiency = crawl_speed_bodylengths_per_s / bend_amplitude_rad

    Speed uses |axial_vel_px_s| (magnitude): both forward and backward travel
    count as propulsion, while bending without net displacement reads low
    regardless of which direction it would have been. dominant_direction
    (forward/backward/even/undetermined) is reported alongside on every row,
    reused from locomotion_summary() rather than re-derived here.

    Whole-body and regional rows reuse undulation_descriptors()'s
    Hilbert-envelope bend amplitude (deg->rad) on that group's segments.
    Per-segment rows reuse the SAME single whole-body wave_propagation fit's
    per-segment envelope (seg_envelope/seg_axis, Stage 3a) rather than fitting
    a new phase-gradient wave on one segment alone -- a wave estimator needs
    multiple segments to fit a spatial phase gradient at all.

    crawl_speed_bodylengths_per_s normalizes each group's mean |axial_vel_px_s|
    (px/s) by this recording's whole-body mean midline_len_px (px) -- a
    body-lengths/s speed even when um_per_px==0 (uncalibrated pixel size),
    since the ratio of two pixel quantities is unit-independent; um_per_px
    and whether it's calibrated (>0) are carried in the output for reference.
    The SAME whole-body midline length normalizes every row (segment, region,
    or whole-body), since "body lengths" means the animal's own length, not a
    fictional per-region length.

    Honesty guard: if a group's bend_amplitude_rad is unresolved or below
    min_bend_rad, its propulsion_efficiency is NaN with resolved=False and a
    stated reason PER ROW -- a near-zero bending denominator must NEVER
    manufacture an inflated or fabricated efficiency value, and one group
    failing this guard does not force the others to NaN.

    DEFERRED (Stage 3c, not built here): a phase-resolved form (efficiency as
    a function of bend-cycle phase -- exactly when in the stroke thrust is
    produced) needs a higher frame rate than this recording's ~5 Hz to
    resolve sub-cycle timing reliably. Only the whole-recording robust
    magnitude form, per region and per segment, is reported here.
    """
    d_all = df[df["worm_id"] == worm_id].copy()
    um_per_px = (float(d_all["um_per_px"].iloc[0])
                if "um_per_px" in d_all.columns and len(d_all) else np.nan)
    calibrated = bool(np.isfinite(um_per_px) and um_per_px > 0)

    # whole-body midline normalization: the SAME denominator for every row.
    per_frame_ml = d_all.groupby("frame").agg(
        midline_len_px=(midline_col, "mean")).reset_index()
    ml = per_frame_ml["midline_len_px"].to_numpy(dtype=float)
    ml_ok = np.isfinite(ml) & (ml > 0)
    mean_midline_px = float(np.mean(ml[ml_ok])) if ml_ok.any() else np.nan

    # dominant travel direction, reused from locomotion_summary (Stage 3a) --
    # not re-derived by a second wave-direction classification here.
    ls = locomotion_summary(d_all, worm_id, curv_col=curv_col)
    if ls.get("resolved"):
        ff, fb = ls["frac_forward"], ls["frac_backward"]
        dominant_direction = ("forward" if ff > fb else
                              "backward" if fb > ff else "even")
    else:
        dominant_direction = "undetermined"

    # single whole-body wave fit, reused for every per-segment amplitude
    # (Stage 3a's additive seg_axis/seg_envelope keys) -- not refit per segment.
    wp = wave_propagation(d_all, worm_id, value=curv_col, head_segments=())
    seg_axis = wp.get("seg_axis")
    envelope = wp.get("seg_envelope")
    wave_resolved = bool(wp.get("direction") != "undetermined"
                        and np.isfinite(wp.get("dominant_freq_hz", np.nan))
                        and envelope is not None)

    rows = []

    def _row(level, region, segment, seg_filter, bend_amp_rad):
        if seg_filter is not None:
            dd = d_all[d_all["segment"].isin(seg_filter)]
        else:
            dd = d_all
        if dd.empty:
            crawl_bl_s, n, resolved, reason = np.nan, 0, False, "no data for this group"
        else:
            pf = dd.groupby("frame").agg(
                vel=(vel_col, lambda s: np.nanmean(np.abs(s)))).reset_index()
            vel = pf["vel"].to_numpy(dtype=float)
            ok = np.isfinite(vel)
            n = int(ok.sum())
            crawl_speed_px_s = float(np.mean(vel[ok])) if ok.any() else np.nan
            crawl_bl_s = (crawl_speed_px_s / mean_midline_px
                         if np.isfinite(crawl_speed_px_s) and np.isfinite(mean_midline_px)
                         and mean_midline_px > 0 else np.nan)
            bend_ok = bool(bend_amp_rad is not None and np.isfinite(bend_amp_rad)
                          and bend_amp_rad >= min_bend_rad)
            resolved = bool(bend_ok and np.isfinite(crawl_bl_s))
            reason = ("" if resolved else
                     ("insufficient valid speed samples" if not np.isfinite(crawl_bl_s)
                      else f"bend amplitude below resolution floor or unresolved "
                           f"(min_bend_rad={min_bend_rad})"))
        efficiency = (crawl_bl_s / bend_amp_rad
                     if resolved and bend_amp_rad else np.nan)
        rows.append(dict(worm_id=worm_id, level=level, region=region, segment=segment,
                         resolved=resolved,
                         propulsion_efficiency_bl_s_per_rad=efficiency,
                         crawl_speed_bodylengths_per_s=crawl_bl_s,
                         bend_amplitude_rad=(float(bend_amp_rad)
                                             if bend_amp_rad is not None and np.isfinite(bend_amp_rad)
                                             else np.nan),
                         mean_midline_len_px=mean_midline_px,
                         um_per_px=um_per_px, calibrated_length=calibrated,
                         dominant_direction=dominant_direction,
                         n_frames=n, reason=reason))

    # whole body
    ud_whole = undulation_descriptors(d_all, worm_id, curv_col=curv_col)
    bend_whole = (np.deg2rad(ud_whole["bend_amplitude_deg"])
                 if ud_whole.get("resolved") else np.nan)
    _row("whole_body", "whole_body", None, None, bend_whole)

    # region (anterior/posterior) -- kinematics full body, head_segments=()
    for region in ("anterior", "posterior"):
        dd = d_all.copy()
        dd["region"] = dd["segment"].map(lambda s: region_of(s, ()))
        segs_r = sorted(dd.loc[dd["region"] == region, "segment"].unique().tolist())
        if not segs_r:
            _row("region", region, None, [], None)
            continue
        ud_r = undulation_descriptors(dd[dd["region"] == region], worm_id, curv_col=curv_col)
        bend_r = np.deg2rad(ud_r["bend_amplitude_deg"]) if ud_r.get("resolved") else np.nan
        _row("region", region, None, segs_r, bend_r)

    # per segment, reusing the single whole-body wave fit's per-segment
    # envelope -- never a per-segment-only wave refit (see docstring).
    all_segments = sorted(d_all["segment"].unique().tolist())
    env_by_seg = ({int(s): np.median(e) for s, e in zip(seg_axis, envelope)}
                 if wave_resolved else {})
    for seg in all_segments:
        seg = int(seg)
        reg = region_of(seg, ())
        bend_seg = (float(np.deg2rad(env_by_seg[seg])) if seg in env_by_seg else np.nan)
        _row("segment", reg, seg, [seg], bend_seg)

    return pd.DataFrame(rows)


def calcium_output_decomposition(df: pd.DataFrame, worm_id: str, value: str = "green_dff",
                                 curv_col: str = "seg_curv_deg",
                                 vel_col: str = "axial_vel_px_s",
                                 head_segments=HEAD_SEGMENTS) -> dict:
    """Side-by-side decomposition of one calcium channel's coupling to the
    two downstream mechanical outputs in the chain: bending (curvature) and
    net propulsion (translation speed) -- both links for the SAME channel in
    one row, so bending vs propulsion can be compared directly for that
    channel.

    bending_lag_s / bending_coherence: reuses curvature_phase_lag() entirely
    (median lag_s across its resolved per-segment rows; coherence is a
    whole-recording number from wave_propagation, same for every segment) --
    not a second bending-coupling estimator.
    propulsion_r_zero_lag / propulsion_lag_s: whole-body channel calcium
    (reliable-body mean) vs whole-body |axial velocity|, sub-frame
    cross-correlation lag via the same parabolic-interpolation estimator
    curvature_to_translation/interchannel_timing use.

    Honesty guards: bending and propulsion each carry their own resolved
    flag -- a channel unresolved for one is not forced to look unresolved
    for the other. self_approach_frac and eigen_fit_quality_mean are
    reported as concrete numbers, not a vague caveat.
    """
    cpl = curvature_phase_lag(df, worm_id, value=value, curv_col=curv_col, head_segments=head_segments)
    resolved_rows = cpl[cpl["resolved"]] if len(cpl) else cpl
    bending_resolved = bool(len(resolved_rows))
    bending_lag_s = float(resolved_rows["lag_s"].median()) if bending_resolved else np.nan
    bending_coherence = (float(cpl["coherence"].iloc[0])
                        if len(cpl) and np.isfinite(cpl["coherence"].iloc[0]) else np.nan)

    fps = float(df["fps"].iloc[0])
    d = df[(df["worm_id"] == worm_id) & (~df["segment"].isin(head_segments))]
    per_frame = d.groupby("frame").agg(
        ca=(value, "mean"),
        vel=(vel_col, lambda s: np.nanmean(np.abs(s))),
    ).reset_index()
    ca = per_frame["ca"].to_numpy(dtype=float)
    vel = per_frame["vel"].to_numpy(dtype=float)
    m = np.isfinite(ca) & np.isfinite(vel)
    propulsion_resolved = bool(m.sum() >= 20 and np.nanstd(ca[m]) > 0 and np.nanstd(vel[m]) > 0)
    if propulsion_resolved:
        propulsion_r0 = float(np.corrcoef(ca[m], vel[m])[0, 1])
        propulsion_lag_s, _ = _xcorr_lag_parabolic(ca[m], vel[m], fps)
    else:
        propulsion_r0, propulsion_lag_s = np.nan, np.nan

    self_approach_frac = (float(d["self_approach_flag"].mean())
                          if "self_approach_flag" in d.columns and len(d) else np.nan)
    eigen_fit_quality_mean = (float(d["eigen_fit_quality"].mean())
                             if "eigen_fit_quality" in d.columns and len(d) else np.nan)

    return dict(worm_id=worm_id,
                bending_resolved=bending_resolved, bending_lag_s=bending_lag_s,
                bending_coherence=bending_coherence,
                propulsion_resolved=propulsion_resolved,
                propulsion_r_zero_lag=propulsion_r0, propulsion_lag_s=propulsion_lag_s,
                self_approach_frac=self_approach_frac,
                eigen_fit_quality_mean=eigen_fit_quality_mean)
