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

THE SAME CULTURES ARE IMAGED WITH SEVERAL KINDS OF PROBE, and the kind decides
what can be measured. Andres: Fura-2 sometimes and Fluo-4 as well, plus
mitochondrial oxidation indicators which may or may not be ratiometric, plus
antibody staining in these same cultures. A single boolean for "ratiometric"
cannot express that, so probes are registered here and three independent axes
are checked separately:

  LOADING-INDEPENDENT?  can two cells be compared on the raw signal? A
                        ratiometric dye (Fura-2, Indo-1, roGFP2, HyPer7)
                        cancels loading, so yes. A single-wavelength dye
                        (Fluo-4, GCaMP, TMRM, MitoSOX) does not: its F0
                        depends on how much dye a cell took up, so dF/F0 is
                        comparable but raw F is not. Conflating these is the
                        standard way a calcium comparison goes wrong, and it
                        is why the DMD literature uses ratiometric dyes for
                        the resting-calcium claim.

  REVERSIBLE?           does the signal come back down? Calcium dyes and the
                        genetically-encoded redox sensors do. MitoSOX and
                        CM-H2DCFDA do NOT - their oxidised product accumulates
                        and stays. For those, a rate of accumulation is
                        defensible and a decay constant, an FWHM or an event
                        frequency are not, however cleanly they fit. This axis
                        is the one a boolean flag cannot see at all.

  LIVE?                 antibody staining is a fixed sample. There is no time
                        in it, so there are no kinetics in it either - not
                        slow ones, not noisy ones, none. Abundance and
                        localisation are what it supports.

BASELINE IS THE HARDEST MEASUREMENT HERE, not the easiest. A transient is
self-referencing: F0 comes from the same cell moments earlier, so illumination,
loading and focus all cancel. A resting level has nothing to cancel against,
so every one of those becomes an error term. That is why the module asks more
of a baseline claim than of a kinetic one.
"""
from __future__ import annotations

import math

import numpy as np

# Probes registered by what they can support, not by what they are called.
# Three axes, because they fail independently: whether the raw signal is
# comparable between cells, whether the signal comes back down, and whether
# there is any time in the sample at all.
PROBES = {
    "fura-2": {
        "readout": "calcium", "ratiometric": "excitation",
        "loading_independent": True, "reversible": True, "live": True,
        "note": ("The 340/380 ratio is not a calcium concentration until it is "
                 "calibrated (Rmin, Rmax, Kd) on this rig with these settings. "
                 "Uncalibrated ratios compare conditions within a rig; they do "
                 "not compare against a number from a paper."),
    },
    "indo-1": {
        "readout": "calcium", "ratiometric": "emission",
        "loading_independent": True, "reversible": True, "live": True,
        "note": ("Ratiometric in emission, so it needs one excitation and two "
                 "detectors - the opposite hardware demand from Fura-2."),
    },
    "fluo-4": {
        "readout": "calcium", "ratiometric": None,
        "loading_independent": False, "reversible": True, "live": True,
        "note": ("F0 depends on how much dye each cell took up, so dF/F0 "
                 "compares between cells and raw F does not. A resting-calcium "
                 "claim needs Fura-2 or an internal reference in the field."),
    },
    "fluo-3": {
        "readout": "calcium", "ratiometric": None,
        "loading_independent": False, "reversible": True, "live": True,
        "note": "As Fluo-4, with lower brightness and more bleaching.",
    },
    "cal-520": {
        "readout": "calcium", "ratiometric": None,
        "loading_independent": False, "reversible": True, "live": True,
        "note": ("Better cytosolic retention than Fluo-4, same loading "
                 "dependence."),
    },
    "gcamp": {
        "readout": "calcium", "ratiometric": None,
        "loading_independent": False, "reversible": True, "live": True,
        "note": ("Expression level varies between cells and drifts with "
                 "passage, so the loading caveat applies and does not wash "
                 "out with time. The indicator also buffers calcium, which "
                 "slows the decay it is being used to measure."),
    },
    "rhod-2": {
        "readout": "calcium", "ratiometric": None,
        "loading_independent": False, "reversible": True, "live": True,
        "note": ("Cationic, so it partitions into mitochondria - but "
                 "incompletely. Cytosolic signal contaminates the "
                 "mitochondrial one unless loading is cold/warm cycled."),
    },
    "grx1-rogfp2": {
        "readout": "redox", "ratiometric": "excitation",
        "loading_independent": True, "reversible": True, "live": True,
        "note": ("Reports glutathione redox potential, ratiometric and "
                 "reversible. It is pH-sensitive: a treatment that acidifies "
                 "the cell moves the ratio without changing redox state, so a "
                 "pH control belongs in the design."),
    },
    "rogfp2": {
        "readout": "redox", "ratiometric": "excitation",
        "loading_independent": True, "reversible": True, "live": True,
        "note": ("As Grx1-roGFP2 but not coupled to glutaredoxin, so it "
                 "equilibrates more slowly and reports less specifically."),
    },
    "hyper7": {
        "readout": "redox", "ratiometric": "excitation",
        "loading_independent": True, "reversible": True, "live": True,
        "note": ("H2O2-specific and ratiometric. Also pH-sensitive; the "
                 "matched pH-control sensor (SypHer) exists for this reason."),
    },
    "mitosox": {
        "readout": "redox", "ratiometric": None,
        "loading_independent": False, "reversible": False, "live": True,
        "note": ("The oxidised product intercalates DNA and stays there. This "
                 "reports CUMULATIVE oxidation, so a rate of accumulation is "
                 "defensible and a decay constant, an FWHM or an event rate "
                 "are not - they will fit cleanly and mean nothing. Signal "
                 "also depends on mitochondrial membrane potential, which is "
                 "usually the other thing being manipulated."),
    },
    "cm-h2dcfda": {
        "readout": "redox", "ratiometric": None,
        "loading_independent": False, "reversible": False, "live": True,
        "note": ("Irreversible and not specific to any one oxidant. Reports "
                 "cumulative general oxidation, and is itself photo-oxidised "
                 "by the excitation light, so illumination must be identical "
                 "across conditions."),
    },
    "tmrm": {
        "readout": "membrane_potential", "ratiometric": None,
        "loading_independent": False, "reversible": True, "live": True,
        "note": ("The SIGN depends on the mode. In quench mode (high dye) a "
                 "depolarisation makes cells brighter; in non-quench mode "
                 "(low dye) it makes them dimmer. Record which was used, or "
                 "the direction of every result is ambiguous."),
    },
    "jc-1": {
        "readout": "membrane_potential", "ratiometric": "emission",
        "loading_independent": True, "reversible": True, "live": True,
        "note": ("Only quasi-ratiometric: the red/green ratio depends on dye "
                 "concentration as well as on potential, so loading is not "
                 "fully cancelled."),
    },
    "antibody": {
        "readout": "abundance", "ratiometric": None,
        "loading_independent": False, "reversible": False, "live": False,
        "note": ("A fixed sample. There is no time in it, so there are no "
                 "kinetics in it - not slow ones, not noisy ones, none. "
                 "Between-coverslip comparison is limited by staining batch, "
                 "so an internal reference in the same image is what makes "
                 "abundance comparable."),
    },
}

# Which measurements are even meaningful for each kind of readout. Asking a
# Fura-2 recording for an antibody expression level, or an antibody image for a
# decay constant, is a question that should not be scored at all.
PANELS = {
    "calcium": ["resting", "peak_amplitude", "time_to_peak", "decay_tau",
                "fwhm", "auc", "event_frequency", "responding_fraction",
                "store_content", "soce"],
    "redox": ["oxidation_ratio", "peak_amplitude", "time_to_peak", "decay_tau",
              "fwhm", "auc", "responding_fraction", "accumulation_rate"],
    "membrane_potential": ["resting", "peak_amplitude", "time_to_peak",
                           "decay_tau", "fwhm", "auc", "responding_fraction"],
    "abundance": ["expression_level"],
}

# What each measurement needs from the recording. Checked before anything is
# computed, because returning a number from data that cannot support it is
# worse than returning nothing.
REQUIREMENTS = {
    "resting": {
        "needs_timeseries": False,
        "needs_loading_independent": True,
        "needs_reversible": False,
        "needs_live": True,
        "min_frames": 1,
        "why": ("A resting level is a comparison between cells, so it needs a "
                "dye whose signal does not depend on how much dye each cell "
                "took up. With a single-wavelength dye, a 'higher baseline' "
                "is indistinguishable from a better-loaded cell."),
    },
    "peak_amplitude": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 20,
        "why": "dF/F0 is self-referencing, so dye loading cancels.",
    },
    "time_to_peak": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 30,
        "why": ("The rise must be sampled several times, or the peak is "
                "wherever the camera happened to look."),
    },
    "decay_tau": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 50,
        "why": ("An exponential fitted to a handful of points returns a "
                "number whatever the data does."),
    },
    "fwhm": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 30,
        "why": "Less model-dependent than tau, and needs the same sampling.",
    },
    "auc": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 20,
        "why": "Integrated load over the transient.",
    },
    "event_frequency": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 200,
        "why": ("A rate needs enough recording to see several events, or the "
                "answer is dominated by whether one happened to occur."),
    },
    "responding_fraction": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": False, "needs_live": True,
        "min_frames": 20,
        "why": ("The proportion of cells that answer a stimulus at all. It "
                "needs no reversibility, because a cell that started to "
                "respond has already declared itself."),
    },
    "store_content": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 50,
        "why": "Caffeine or thapsigargin-evoked release, measured as a peak.",
    },
    "soce": {
        "needs_timeseries": True, "needs_loading_independent": True,
        "needs_reversible": True, "needs_live": True,
        "min_frames": 100,
        "why": ("Store-operated entry is a slow rise compared between "
                "conditions, so it needs a loading-independent signal."),
    },
    "oxidation_ratio": {
        "needs_timeseries": False, "needs_loading_independent": True,
        "needs_reversible": False, "needs_live": True,
        "min_frames": 1,
        "why": ("The resting redox state, which is a between-cell comparison "
                "and so needs a ratiometric sensor for the same reason a "
                "resting calcium level does."),
    },
    "accumulation_rate": {
        "needs_timeseries": True, "needs_loading_independent": False,
        "needs_reversible": False, "needs_live": True,
        "min_frames": 30,
        "why": ("For a probe whose product does not come back, the slope of "
                "the rise is the only defensible number. It is the measure "
                "that REPLACES the kinetic panel rather than joining it."),
    },
    "expression_level": {
        "needs_timeseries": False, "needs_loading_independent": False,
        "needs_reversible": False, "needs_live": False,
        "min_frames": 1,
        "why": ("Per-cell abundance from a fixed, stained sample. Comparable "
                "within an image; between coverslips only against an internal "
                "reference, because staining batch varies."),
    },
}

# 8-bit ratiometry is the trap this dataset fell into.
MIN_RATIOMETRIC_BITS = 12
# Points after the peak needed before a decay fit means anything.
MIN_DECAY_POINTS = 8
MIN_SIGNAL_FOR_RATIO = 20.0


def normalise_probe(name):
    """Accept 'Fura-2', 'fura2', 'FURA 2' as the same probe."""
    key = str(name).strip().lower().replace(" ", "-").replace("_", "-")
    if key in PROBES:
        return key
    squashed = key.replace("-", "")
    for known in PROBES:
        if known.replace("-", "") == squashed:
            return known
    raise CalciumError(
        f"Unknown probe {name!r}. Registered: {sorted(PROBES)}. Add it to "
        f"PROBES with its readout, whether it is loading-independent, whether "
        f"it is reversible and whether it works in a live cell - guessing any "
        f"of those is how a measurement that cannot be made gets made.")


class CalciumError(Exception):
    """Refusals that name the consequence."""


def check_recording(*, n_frames, probe=None, ratiometric=None, bit_depth=8,
                    typical_signal=None, wants=()):
    """Can this recording support the measurements intended?

    Written after looking at the lab's pilot smooth-muscle images, which are
    single 8-bit frames using 47 of 256 grey levels. They cannot support any
    kinetic measure at all, and their dynamic range makes a ratio dominated by
    quantisation - one grey level moves a 3/2 ratio by 33%. Reading the Leica
    metadata on the confocal afterwards showed Resolution="8" on every channel,
    so the 8-bit was ACQUIRED and is not an export artefact: it is a scope
    setting to change, not a file to re-export.

    Give a `probe` name where possible. `ratiometric` alone is kept for callers
    written before the registry existed, but it cannot express irreversibility
    or a fixed sample, so it will happily green-light a decay constant on
    MitoSOX.
    """
    spec_probe = None
    if probe is not None:
        spec_probe = PROBES[normalise_probe(probe)]
        loading_independent = spec_probe["loading_independent"]
        reversible = spec_probe["reversible"]
        live = spec_probe["live"]
        is_ratio = spec_probe["ratiometric"] is not None
        readout = spec_probe["readout"]
    elif ratiometric is not None:
        loading_independent = is_ratio = bool(ratiometric)
        reversible = live = True
        readout = "calcium"
    else:
        raise CalciumError(
            "Give either a probe name or the legacy `ratiometric` flag. "
            "Without one of them there is nothing to check the measurements "
            "against.")
    if ratiometric is not None and spec_probe is not None:
        loading_independent = is_ratio = bool(ratiometric)

    wanted = list(wants) or list(PANELS.get(readout, list(REQUIREMENTS)))
    out = {"n_frames": int(n_frames), "probe": probe, "readout": readout,
           "ratiometric": is_ratio, "loading_independent": loading_independent,
           "reversible": reversible, "live": live,
           "bit_depth": int(bit_depth), "measurements": {}, "warnings": []}
    if spec_probe is not None:
        out["probe_note"] = spec_probe["note"]

    levels = 2 ** int(bit_depth)
    # Expressed in BIT DEPTH rather than in a level count. Written first as
    # "levels < 64 * 4", which is 256 - and 8-bit gives exactly 256, so the
    # warning stayed silent on the one case it exists for. Ratiometric calcium
    # wants 12-bit or better; that is the statement, so that is the test.
    if is_ratio and int(bit_depth) < MIN_RATIOMETRIC_BITS:
        out["warnings"].append(
            f"{bit_depth}-bit data has {levels} grey levels. A ratio of two "
            f"small integers moves in coarse jumps - at an intensity of 3 "
            f"over 2, one grey level changes the ratio by 33%. Ratiometric "
            f"calcium needs the depth and the exposure to put the signal well "
            f"up the range; 12- or 16-bit is the norm for this reason.")
    if typical_signal is not None and is_ratio and \
            typical_signal < MIN_SIGNAL_FOR_RATIO:
        out["warnings"].append(
            f"The typical signal is about {typical_signal:g} counts. Dividing "
            f"two numbers this small gives a ratio whose noise is larger than "
            f"the differences being looked for, however many cells are "
            f"measured - this is an exposure problem, and no analysis fixes "
            f"it.")
    if not reversible and n_frames > 1:
        out["warnings"].append(
            "This probe's signal does not come back down. Anything shaped "
            "like a transient - a decay constant, an FWHM, an event rate - "
            "will still FIT this data and will still mean nothing. Use the "
            "accumulation rate instead.")

    for key in wanted:
        spec = REQUIREMENTS.get(key)
        if spec is None:
            raise CalciumError(
                f"Unknown measurement {key!r}. Known: {sorted(REQUIREMENTS)}.")
        fails = []
        if spec["needs_live"] and not live:
            fails.append("the sample is fixed, so there is no time in it and "
                         "no kinetics in it")
        if spec["needs_timeseries"] and n_frames < 2:
            fails.append("this is a single frame and the measure needs a "
                         "time series")
        elif spec["needs_timeseries"] and n_frames < spec["min_frames"]:
            fails.append(f"{n_frames} frames against a floor of "
                         f"{spec['min_frames']}")
        if spec["needs_loading_independent"] and not loading_independent:
            fails.append("it compares between cells, which needs a signal "
                         "that does not depend on how much probe each cell "
                         "took up")
        if spec["needs_reversible"] and not reversible:
            fails.append("the probe does not return to baseline, so this "
                         "measure would describe the shape of an accumulation "
                         "rather than of a response")
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


# --------------------------------------------------------------------------- #
# Transfected against untransfected, in the same field
# --------------------------------------------------------------------------- #
# Andres: two signals, two channels - one is calcium, the other is mCherry
# showing which cells were transfected, and transfected vs non-transfected IS
# the experiment. shRNA against the long isoforms (Dp427), against all isoforms
# (Dp71), or scrambled control.
#
# THIS DESIGN IS MUCH STRONGER THAN IT LOOKS, and the reason is worth stating.
# The control cells sit in the SAME field as the treated ones: same coverslip,
# same dye loading, same passage, same illumination, same focus, same day.
# Every one of those is an error term for a resting-calcium claim made between
# dishes, and all of them cancel when the comparison is made within a field.
# That is why the paired analysis here uses the FIELD as the unit rather than
# pooling cells - pooling would throw away the pairing that makes the design
# good, and would also treat cells sharing a coverslip as independent.
#
# It brings three failure modes that a between-dish design does not have, and
# all three point the same way as the hypothesis, which is what makes them
# dangerous rather than merely annoying.
MARKER_BLEED_R = 0.4
MIN_CELLS_PER_CLASS = 3


def check_two_channel_design(*, signal_channel, marker_channel,
                             segmentation_channel=None, conditions=()):
    """Sanity of the layout before any cell is measured.

    The one that matters most is the segmentation channel. If cells are found
    by thresholding the calcium channel, then dim cells are missed, the sample
    is biased towards high calcium, and the bias need not be equal in the two
    groups - a knockdown that raises resting calcium would also make its cells
    easier to find, inflating the very difference being measured. Segment on
    something independent: transmitted light, or a nuclear stain.
    """
    notes, warnings = [], []
    if segmentation_channel is None:
        warnings.append(
            "No segmentation channel declared. Say which channel the cell "
            "outlines came from - it decides whether the cells measured are a "
            "fair sample of the cells present.")
    elif segmentation_channel == signal_channel:
        warnings.append(
            f"Cells were segmented on the measurement channel "
            f"({signal_channel}). Bright cells are then easier to find than "
            f"dim ones, so the sample is biased towards high signal - and if "
            f"the treatment shifts the signal, the bias differs between "
            f"groups and adds to the effect. Segment on transmitted light or "
            f"a nuclear stain instead. The lab's Leica exports carry a third "
            f"channel (ch02, LUT 'Gray') that was acquired for this and did "
            f"not get copied to the L: drive with the other two.")
    elif segmentation_channel == marker_channel:
        warnings.append(
            f"Cells were segmented on the marker channel ({marker_channel}), "
            f"so untransfected cells cannot be found at all - and they are "
            f"the internal control. Only transfected cells will be measured.")
    else:
        notes.append(
            f"Segmented on {segmentation_channel}, independent of both the "
            f"signal and the marker. This is the arrangement that lets the "
            f"untransfected cells act as controls.")

    conds = [str(c) for c in conditions]
    scrambles = [c for c in conds
                 if "scram" in c.lower() or "control" in c.lower()]
    if conds and not scrambles:
        warnings.append(
            "No scrambled/control condition listed. The scramble is what "
            "separates 'knockdown changed calcium' from 'transfection changed "
            "calcium' - without it a difference between marker-positive and "
            "marker-negative cells has two explanations and no way to choose.")
    return {"notes": notes, "warnings": warnings,
            "control_conditions": scrambles}


def classify_by_marker(marker_values, *, threshold=None, gap_frac=0.25):
    """Split cells into marker-positive, marker-negative, and ambiguous.

    Cells near the threshold are returned as AMBIGUOUS rather than pushed into
    one class. A graded marker means a graded knockdown, so the cells at the
    boundary are the ones whose class is least certain and whose calcium is
    most likely to sit between the two groups - forcing them either way drags
    the two distributions towards each other and buries a real effect, or
    invents one, depending on which side the noise falls.
    """
    x = np.asarray(marker_values, dtype=float)
    x = x[np.isfinite(x)]
    if x.size == 0:
        raise CalciumError("No marker values, so nothing can be classified.")
    if threshold is None:
        # Otsu on the marker histogram: the split that best separates two
        # groups, without assuming what fraction was transfected.
        lo, hi = float(x.min()), float(x.max())
        if hi <= lo:
            raise CalciumError(
                "Every cell has the same marker value, so no threshold "
                "separates transfected from untransfected. Check that the "
                "marker channel is the one that was read.")
        counts, edges = np.histogram(x, bins=64, range=(lo, hi))
        centres = (edges[:-1] + edges[1:]) / 2
        total = counts.sum()
        w0 = np.cumsum(counts) / total
        m0 = np.cumsum(counts * centres) / np.maximum(np.cumsum(counts), 1)
        m_all = float((counts * centres).sum() / total)
        with np.errstate(divide="ignore", invalid="ignore"):
            between = w0 * (1 - w0) * (m0 - (m_all - w0 * m0) /
                                       np.maximum(1 - w0, 1e-12)) ** 2
        # A well-transfected sample leaves an EMPTY GAP between the two
        # clusters, and every threshold inside that gap scores identically -
        # the between-class variance depends only on which cells fall each
        # side, and no cell falls inside the gap. argmax then returns the
        # lowest of them, which puts the boundary hard against the shoulder of
        # the untransfected cluster, and the exclusion band below eats into
        # real negatives. Take the middle of the tied plateau instead, which is
        # the middle of the gap.
        best = np.nanmax(between)
        plateau = np.nonzero(between >= best * 0.999)[0]
        threshold = float(centres[int(np.median(plateau))])

    band = gap_frac * abs(threshold) if threshold else 0.0
    positive = x > threshold + band
    negative = x < threshold - band
    ambiguous = ~(positive | negative)

    # Is the marker actually bimodal? Measured as Otsu's separability, the
    # fraction of the total variance that the split explains.
    #
    # NOT as the gap between the two classes in units of their spread: the
    # exclusion band above removes the cells nearest the threshold, which
    # widens that gap by construction. A single normal distribution cut in half
    # scored 7 standard deviations of "separation" that way, which would have
    # certified the least bimodal data there is.
    #
    # Separability has a known reference value instead. Splitting ONE normal
    # distribution at its mean explains 2/pi = 0.64 of the variance, so 0.64 is
    # what unimodal data looks like and anything near it is a warning.
    hi_all = x > threshold
    w1 = float(hi_all.mean())
    var_total = float(np.var(x))
    if 0 < w1 < 1 and var_total > 0:
        gap = float(x[hi_all].mean() - x[~hi_all].mean())
        separability = w1 * (1 - w1) * gap * gap / var_total
    else:
        separability = 0.0

    out = {
        "threshold": float(threshold),
        "n_positive": int(positive.sum()),
        "n_negative": int(negative.sum()),
        "n_ambiguous": int(ambiguous.sum()),
        "positive": positive, "negative": negative, "ambiguous": ambiguous,
        "separability": float(separability),
        "warnings": [],
    }
    if separability < 0.75:
        out["warnings"].append(
            f"The marker split explains {separability:.2f} of the variance, "
            f"against 0.64 for a single unimodal distribution cut in half. "
            f"The marker is therefore not clearly bimodal, the threshold is a "
            f"decision rather than a boundary, and moving it would move the "
            f"result - report the threshold, and check the result survives a "
            f"different one.")
    frac = out["n_positive"] / max(x.size, 1)
    if frac < 0.02:
        out["warnings"].append(
            f"Only {out['n_positive']} of {x.size} cells are marker-positive "
            f"({frac:.1%}). That is a transfection efficiency low enough that "
            f"a field contributes almost no paired information.")
    return out


def marker_bleedthrough(signal_values, marker_values, positive_mask):
    """Is the signal channel contaminated by the marker?

    This is the failure that manufactures the expected result. mCherry
    emission reaching the calcium detector makes transfected cells brighter in
    the calcium channel for a purely optical reason, in exactly the direction a
    knockdown that raises calcium would predict.

    The proper control is a marker-only sample with no calcium dye, imaged with
    the calcium settings. Absent that, this is the within-experiment proxy:
    among transfected cells, bleed-through scales with how much mCherry the
    cell has, whereas a knockdown effect should not - a cell either lost the
    protein or did not. So a positive correlation between marker brightness and
    calcium signal AMONG POSITIVE CELLS is the warning sign.
    """
    s = np.asarray(signal_values, dtype=float)
    m = np.asarray(marker_values, dtype=float)
    p = np.asarray(positive_mask, dtype=bool)
    if s.shape != m.shape or s.shape != p.shape:
        raise CalciumError(
            f"Signal, marker and mask must line up cell for cell; got "
            f"{s.shape}, {m.shape} and {p.shape}.")
    ok = p & np.isfinite(s) & np.isfinite(m)
    n = int(ok.sum())
    out = {"n_positive_cells": n, "r": None, "suspect": False, "warnings": []}
    if n < 5:
        out["warnings"].append(
            f"Only {n} marker-positive cells, too few to test for bleed-"
            f"through. This check is not a pass - it did not run.")
        return out
    r = float(np.corrcoef(m[ok], s[ok])[0, 1])
    out["r"] = r
    if r > MARKER_BLEED_R:
        out["suspect"] = True
        out["warnings"].append(
            f"Among transfected cells, the calcium signal rises with marker "
            f"brightness (r = {r:+.2f}). Knockdown is closer to all-or-none, "
            f"so this gradient looks like mCherry emission reaching the "
            f"calcium detector - which would raise transfected cells in "
            f"exactly the direction the hypothesis predicts. Image a marker-"
            f"only, dye-free sample with the calcium settings before "
            f"believing the difference.")
    return out


def paired_field_comparison(fields, *, min_cells=MIN_CELLS_PER_CLASS):
    """Transfected against untransfected within each field, then across fields.

    Each field yields ONE number: the difference between its transfected and
    untransfected cells. Those numbers are the replicates. Cells are not, and
    treating them as such is what turns a handful of coverslips into an n of
    several hundred.

    `fields` is a sequence of dicts with 'field', 'condition', 'signal' and
    'marker' - signal and marker being per-cell values in the same order.
    """
    per_field, skipped = [], []
    for f in fields:
        name = f.get("field", "?")
        sig = np.asarray(f["signal"], dtype=float)
        mark = np.asarray(f["marker"], dtype=float)
        if sig.shape != mark.shape:
            raise CalciumError(
                f"Field {name!r}: {sig.size} signal values against "
                f"{mark.size} marker values. They must be one per cell, in "
                f"the same order.")
        cls = classify_by_marker(mark, threshold=f.get("threshold"))
        pos, neg = sig[cls["positive"]], sig[cls["negative"]]
        if pos.size < min_cells or neg.size < min_cells:
            skipped.append(
                f"{name}: {pos.size} transfected and {neg.size} untransfected "
                f"cells, below the floor of {min_cells} each")
            continue
        bleed = marker_bleedthrough(sig, mark, cls["positive"])
        per_field.append({
            "field": name,
            "condition": f.get("condition", "?"),
            "n_positive": int(pos.size), "n_negative": int(neg.size),
            "median_positive": float(np.median(pos)),
            "median_negative": float(np.median(neg)),
            "ratio": (float(np.median(pos) / np.median(neg))
                      if np.median(neg) else None),
            "difference": float(np.median(pos) - np.median(neg)),
            "bleedthrough_r": bleed["r"],
            "warnings": cls["warnings"] + bleed["warnings"],
        })

    by_cond = {}
    for rec in per_field:
        by_cond.setdefault(rec["condition"], []).append(rec)

    summary = {}
    for cond, recs in by_cond.items():
        ratios = [r["ratio"] for r in recs if r["ratio"] is not None]
        summary[cond] = {
            "n_fields": len(recs),
            "n_cells": sum(r["n_positive"] + r["n_negative"] for r in recs),
            "median_ratio": float(np.median(ratios)) if ratios else None,
            "fields_above_1": sum(1 for r in ratios if r > 1),
        }

    out = {"per_field": per_field, "by_condition": summary,
           "skipped_fields": skipped, "warnings": []}
    if skipped:
        out["warnings"].append(
            f"{len(skipped)} field(s) contributed nothing because one class "
            f"was too small. They are listed rather than dropped silently, "
            f"because losing the low-efficiency fields is itself a selection "
            f"- they may be the ones where transfection went worst.")

    # The scramble is the internal validity check, and it is the reason this
    # design has a control at all. Marker-positive scramble cells received the
    # lipid, the plasmid and the mCherry, and no knockdown. If they still
    # differ from their neighbours, then being transfected changes calcium by
    # itself and every other condition inherits that difference.
    for cond, s in summary.items():
        if ("scram" in cond.lower() or "control" in cond.lower()) and \
                s["median_ratio"] is not None and abs(s["median_ratio"] - 1) > 0.15:
            out["warnings"].append(
                f"The {cond} control shows transfected cells at "
                f"{s['median_ratio']:.2f} times their untransfected "
                f"neighbours. Scrambled shRNA should knock nothing down, so "
                f"this is the transfection itself moving calcium - through "
                f"lipid stress, mCherry bleed-through, or the selection of "
                f"which cells take up plasmid. Whatever the knockdowns show "
                f"has to be read against this, not against 1.0.")

    n_units = sum(s["n_fields"] for s in summary.values())
    out["note"] = (
        f"The unit here is the field: {n_units} paired comparisons, not the "
        f"{sum(s['n_cells'] for s in summary.values())} cells behind them. "
        f"Cells in one field share a coverslip, a loading and a passage, so a "
        f"test over pooled cells would find significance a test over fields "
        f"would not. Pairing within field also cancels loading, illumination "
        f"and focus, which is what makes a single-wavelength dye usable for a "
        f"resting comparison at all.")
    return out


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
