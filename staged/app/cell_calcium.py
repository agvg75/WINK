"""Calcium in cultured muscle cells: baseline, kinetics, and store content.

Andres: measure calcium kinetics and baseline in cultured human cells, from
myoblasts to myofibres, striated and smooth, informed by the literature and by
what people in the field actually measure.

WHAT PEOPLE IN THE FIELD MEASURE, and why each one is here. In the muscular
dystrophy calcium literature the recurring claims are elevated RESTING
calcium, altered store content, and increased store-operated entry - so the
panel is built around those rather than around whatever is easy to compute.

  RESTING / BASELINE     the DMD claim that most often decides a paper
  PEAK AMPLITUDE         dF/F0, or a ratio change for ratiometric dyes
  TIME TO PEAK           how fast release happens
  DECAY TAU              how fast it is removed - SERCA and exchanger work
  FWHM                   transient duration, less model-dependent than tau
  AREA UNDER CURVE       integrated calcium load, what the cell actually saw
  EVENT FREQUENCY        spontaneous activity
  RESPONDING FRACTION    proportion of cells that answer a stimulus at all
  STORE CONTENT          caffeine or thapsigargin-evoked release
  SOCE                   store-operated entry after depletion

RATIOMETRIC AND SINGLE-WAVELENGTH ARE NOT INTERCHANGEABLE, and conflating them
is the standard way a calcium comparison goes wrong. A ratiometric dye
(Fura-2, Indo-1) reports a quantity that can be compared between cells and
between days, because dye loading cancels. A single-wavelength dye (Fluo-4,
GCaMP) does not: its F0 depends on how much dye a cell took up, so dF/F0 is
comparable but raw F is not. This module refuses to compare raw intensities
across cells for single-wavelength data, which is exactly the comparison a
resting-calcium claim needs - and it is why the DMD literature uses
ratiometric dyes for that claim.

BASELINE IS THE HARDEST MEASUREMENT HERE, not the easiest. A transient is
self-referencing: F0 comes from the same cell moments earlier, so illumination,
loading and focus all cancel. A resting level has nothing to cancel against,
so every one of those becomes an error term. That is why the module asks more
of a baseline claim than of a kinetic one.
"""
from __future__ import annotations

import math

import numpy as np

# What each measurement needs from the recording. Checked before anything is
# computed, because returning a number from data that cannot support it is
# worse than returning nothing.
REQUIREMENTS = {
    "resting": {
        "needs_timeseries": False,
        "needs_ratiometric": True,
        "min_frames": 1,
        "why": ("A resting level is a comparison between cells, so it needs a "
                "dye whose signal does not depend on how much dye each cell "
                "took up. With a single-wavelength dye, a 'higher baseline' "
                "is indistinguishable from a better-loaded cell."),
    },
    "peak_amplitude": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 20,
        "why": "dF/F0 is self-referencing, so dye loading cancels.",
    },
    "time_to_peak": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 30,
        "why": ("The rise must be sampled several times, or the peak is "
                "wherever the camera happened to look."),
    },
    "decay_tau": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 50,
        "why": ("An exponential fitted to a handful of points returns a "
                "number whatever the data does."),
    },
    "fwhm": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 30,
        "why": "Less model-dependent than tau, and needs the same sampling.",
    },
    "auc": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 20,
        "why": "Integrated load over the transient.",
    },
    "event_frequency": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 200,
        "why": ("A rate needs enough recording to see several events, or the "
                "answer is dominated by whether one happened to occur."),
    },
    "store_content": {
        "needs_timeseries": True, "needs_ratiometric": False,
        "min_frames": 50,
        "why": "Caffeine or thapsigargin-evoked release, measured as a peak.",
    },
    "soce": {
        "needs_timeseries": True, "needs_ratiometric": True,
        "min_frames": 100,
        "why": ("Store-operated entry is a slow rise compared between "
                "conditions, so it needs a loading-independent signal."),
    },
}

# 8-bit ratiometry is the trap this dataset fell into.
MIN_RATIOMETRIC_BITS = 12
# Points after the peak needed before a decay fit means anything.
MIN_DECAY_POINTS = 8
MIN_SIGNAL_FOR_RATIO = 20.0


class CalciumError(Exception):
    """Refusals that name the consequence."""


def check_recording(*, n_frames, ratiometric, bit_depth=8,
                    typical_signal=None, wants=()):
    """Can this recording support the measurements intended?

    Written after looking at the lab's pilot smooth-muscle images, which are
    single 8-bit frames using 47 of 256 grey levels. They cannot support any
    kinetic measure at all, and their dynamic range makes a ratio dominated by
    quantisation - one grey level moves a 3/2 ratio by 33%.
    """
    wanted = list(wants) or list(REQUIREMENTS)
    out = {"n_frames": int(n_frames), "ratiometric": bool(ratiometric),
           "bit_depth": int(bit_depth), "measurements": {}, "warnings": []}

    levels = 2 ** int(bit_depth)
    # Expressed in BIT DEPTH rather than in a level count. Written first as
    # "levels < 64 * 4", which is 256 - and 8-bit gives exactly 256, so the
    # warning stayed silent on the one case it exists for. Ratiometric calcium
    # wants 12-bit or better; that is the statement, so that is the test.
    if ratiometric and int(bit_depth) < MIN_RATIOMETRIC_BITS:
        out["warnings"].append(
            f"{bit_depth}-bit data has {levels} grey levels. A ratio of two "
            f"small integers moves in coarse jumps - at an intensity of 3 "
            f"over 2, one grey level changes the ratio by 33%. Ratiometric "
            f"calcium needs the depth and the exposure to put the signal well "
            f"up the range; 12- or 16-bit is the norm for this reason.")
    if typical_signal is not None and ratiometric and \
            typical_signal < MIN_SIGNAL_FOR_RATIO:
        out["warnings"].append(
            f"The typical signal is about {typical_signal:g} counts. Dividing "
            f"two numbers this small gives a ratio whose noise is larger than "
            f"the differences being looked for, however many cells are "
            f"measured - this is an exposure problem, and no analysis fixes "
            f"it.")

    for key in wanted:
        spec = REQUIREMENTS.get(key)
        if spec is None:
            raise CalciumError(
                f"Unknown measurement {key!r}. Known: {sorted(REQUIREMENTS)}.")
        fails = []
        if spec["needs_timeseries"] and n_frames < 2:
            fails.append("this is a single frame and the measure needs a "
                         "time series")
        elif n_frames < spec["min_frames"]:
            fails.append(f"{n_frames} frames against a floor of "
                         f"{spec['min_frames']}")
        if spec["needs_ratiometric"] and not ratiometric:
            fails.append("it compares between cells, which needs a "
                         "ratiometric dye")
        out["measurements"][key] = {
            "supported": not fails, "fails": fails, "why": spec["why"]}
    out["n_supported"] = sum(1 for m in out["measurements"].values()
                             if m["supported"])
    out["n_unsupported"] = len(out["measurements"]) - out["n_supported"]
    return out


# --------------------------------------------------------------------------- #
# Traces
# --------------------------------------------------------------------------- #
def baseline(trace, *, method="percentile", percentile=10, frames=None):
    """F0 for a trace. Percentile by default, not the first N frames.

    The first frames are the conventional choice and the fragile one: if the
    cell was already active, or the shutter was still settling, F0 is taken
    from exactly the part of the recording most likely to be wrong, and every
    dF/F0 afterwards inherits it. A low percentile of the whole trace is
    robust to both, at the cost of a small underestimate when the cell is
    quiet throughout.
    """
    x = np.asarray(trace, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        raise CalciumError("An empty trace has no baseline to take.")
    if method == "percentile":
        return float(np.percentile(x, percentile))
    if method == "first_frames":
        n = int(frames or max(3, len(x) // 20))
        return float(np.mean(x[:n]))
    if method == "mode":
        hist, edges = np.histogram(x, bins=min(64, max(8, x.size // 10)))
        i = int(np.argmax(hist))
        return float((edges[i] + edges[i + 1]) / 2)
    raise CalciumError("method must be 'percentile', 'first_frames' or 'mode'.")


def transient(trace, fps, *, f0=None, f0_method="percentile",
              min_prominence_frac=0.2):
    """The standard single-transient panel: amplitude, timing, decay, area."""
    x = np.asarray(trace, dtype=float)
    if x.size < 5:
        raise CalciumError(
            f"{x.size} points cannot describe a transient. Amplitude alone "
            f"might survive; timing and decay cannot.")
    if not fps or fps <= 0:
        raise CalciumError(
            "A frame rate is required. Every timing here is in seconds, and "
            "assuming one would silently rescale time to whatever the camera "
            "happened to do.")
    base = float(f0) if f0 is not None else baseline(x, method=f0_method)
    if base == 0:
        raise CalciumError(
            "The baseline is zero, so dF/F0 is undefined. For a single-"
            "wavelength dye this usually means background was over-subtracted.")
    dff = (x - base) / base
    i_peak = int(np.argmax(dff))
    amp = float(dff[i_peak])
    if amp < min_prominence_frac:
        return {"detected": False, "amplitude_dff": amp, "f0": base,
                "why": (f"The largest excursion is {amp:.2f} dF/F0, below the "
                        f"{min_prominence_frac} threshold. Reporting timing "
                        f"for an event this small would be describing "
                        f"noise.")}

    half = amp / 2.0
    rise = np.nonzero(dff[:i_peak + 1] >= half)[0]
    i_rise = int(rise[0]) if rise.size else i_peak
    after = np.nonzero(dff[i_peak:] <= half)[0]
    i_fall = int(i_peak + after[0]) if after.size else len(dff) - 1

    # Decay constant from a log-linear fit over the falling phase, which is
    # less brittle than a curve fit and does not need a starting guess.
    # A DECAY YOU HAVE NOT WATCHED DECAY CANNOT BE FITTED, and the count of
    # points is not enough to enforce that. Written first as "at least four
    # points after the peak", which passed on a truncated synthetic trace and
    # returned exactly the right tau - because four points determine an
    # exponential perfectly when there is no noise. On real data they would
    # not. So the trace must also have FALLEN, to below half amplitude, which
    # is about 0.7 tau of observed decay; otherwise the fit is extrapolating
    # from the top of the curve where every tau looks alike.
    tau = None
    tau_note = None
    seg = dff[i_peak:]
    pos = seg > max(amp * 0.05, 1e-9)
    fell_enough = seg.size > 0 and float(seg.min()) <= amp * 0.5
    if np.count_nonzero(pos) >= MIN_DECAY_POINTS and fell_enough:
        t = np.arange(len(seg))[pos] / float(fps)
        y = np.log(seg[pos])
        slope, _ = np.polyfit(t, y, 1)
        if slope < 0:
            tau = float(-1.0 / slope)
    elif not fell_enough:
        tau_note = (
            f"No decay constant: the trace only fell to "
            f"{float(seg.min()) / amp:.0%} of peak before it ended, so less "
            f"than half the decay was observed. A fit from the top of the "
            f"curve extrapolates rather than measures - every tau looks "
            f"alike there.")

    return {
        "detected": True,
        "f0": base,
        "amplitude_dff": amp,
        "time_to_peak_s": float(i_peak / fps),
        "rise_time_half_s": float((i_peak - i_rise) / fps),
        "fwhm_s": float((i_fall - i_rise) / fps),
        "decay_tau_s": tau,
        "auc_dff_s": float(np.trapezoid(np.clip(dff, 0, None)) / fps),
        "n_frames": int(x.size),
        "caveat": (None if tau is not None else
                   tau_note or
                   f"No decay constant: fewer than {MIN_DECAY_POINTS} usable "
                   f"points after the peak. A recording that ends during the "
                   f"decay cannot give tau."),
    }


def resting_ratio(ch_a, ch_b, mask=None, *, min_signal=MIN_SIGNAL_FOR_RATIO):
    """Ratiometric resting level - the measurement the DMD claim rests on.

    Computed as a ratio of SUMS over the cell rather than a mean of per-pixel
    ratios. A per-pixel ratio explodes wherever the denominator is near zero,
    and the dimmest pixels are the edges of the cell, so the mean of ratios is
    dominated by exactly the pixels carrying least signal.
    """
    a = np.asarray(ch_a, dtype=float)
    b = np.asarray(ch_b, dtype=float)
    if a.shape != b.shape:
        raise CalciumError(
            f"Channels differ in shape, {a.shape} against {b.shape}. A "
            f"ratio of misaligned images is a picture of the misalignment.")
    if mask is not None:
        m = np.asarray(mask, dtype=bool)
        a, b = a[m], b[m]
    if a.size == 0:
        raise CalciumError("The mask selected no pixels.")
    sa, sb = float(a.sum()), float(b.sum())
    if sb <= 0:
        raise CalciumError(
            "The denominator channel sums to zero over the cell, so no ratio "
            "exists. Check the channel order and the background subtraction.")
    ratio = sa / sb
    typical = float(np.median(np.concatenate([a, b])))
    out = {"ratio": ratio, "sum_a": sa, "sum_b": sb,
           "n_pixels": int(a.size), "typical_counts": typical,
           "warnings": []}
    if typical < min_signal:
        out["warnings"].append(
            f"Typical intensity over the cell is {typical:g} counts. At this "
            f"level a single grey level changes the ratio by roughly "
            f"{100.0 / max(typical, 1):.0f}%, which will be larger than the "
            f"difference between conditions. This is an exposure problem and "
            f"cannot be fixed downstream.")
    return out


def compare_conditions(by_condition, *, control=None, metric="value"):
    """Effect sizes between conditions, without pretending to a p-value.

    Reports the difference and its size relative to spread. A statistical test
    belongs downstream where the experimental unit is known: cells within a
    dish are not independent replicates, and treating them as such is the
    commonest way a calcium comparison overstates itself.
    """
    stats = {}
    for cond, values in by_condition.items():
        x = np.asarray([v for v in values
                        if v is not None and math.isfinite(float(v))],
                       dtype=float)
        if x.size == 0:
            continue
        med = float(np.median(x))
        mad = float(np.median(np.abs(x - med))) * 1.4826
        stats[cond] = {"n": int(x.size), "median": med, "mad": mad}
    if control and control not in stats:
        raise CalciumError(
            f"Control condition {control!r} has no values, so nothing can be "
            f"compared against it.")
    out = {"per_condition": stats, "control": control, "metric": metric}
    if control:
        ref = stats[control]
        for cond, s in stats.items():
            if cond == control:
                continue
            pooled = max((s["mad"] + ref["mad"]) / 2, 1e-12)
            s["vs_control_fold"] = (round(s["median"] / ref["median"], 3)
                                    if ref["median"] else None)
            s["vs_control_effect"] = round(
                (s["median"] - ref["median"]) / pooled, 2)
    out["note"] = (
        "Effect sizes only. Cells within one dish share a passage, a loading, "
        "a coverslip and a field of view, so they are not independent "
        "replicates - a test run over pooled cells will find significance "
        "that a test over dishes will not. The experimental unit belongs to "
        "whoever designed the experiment, not to this function.")
    return out
