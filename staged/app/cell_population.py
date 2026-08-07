"""Declared fields, flat-field correction and censoring for cultured cells.

Spec 2 of the cultured cell population spec. Everything here exists to make a
population number either defensible or withheld, never quietly wrong.

THREE THINGS ARE DECLARED, NOT INFERRED, because each one decides which cells
end up in the sample and none of them can be recovered from the pixels:

    segmentation_channel  which channel the outlines came from
    segmentation_source   which FRAME or PROJECTION they were drawn on
    stimulus_onset_frame  where the pre-stimulus window ends

Each is proposed where a sensible proposal exists, confirmed by a person
always, and recorded with its consequence. Silent never.
"""
from __future__ import annotations

import numpy as np

# --------------------------------------------------------------- sources --
# WHICH FRAME THE OUTLINES CAME FROM IS A SAMPLING DECISION. Every option
# below finds a different subset of the cells present, and the difference is
# correlated with the thing being measured.
SEGMENTATION_SOURCES = {
    "pre_stimulus_mean": (
        "Mean of the frames before stimulus onset. Biases towards WELL-LOADED "
        "cells: a cell that took up little dye is dim at rest and may be "
        "missed, so between-cell comparisons are conditional on loading. It "
        "does NOT bias towards responders, which is why it is the default "
        "proposal for a stimulation series."),
    "max_projection": (
        "Maximum across frames. Biases towards RESPONDERS: a cell is found "
        "BECAUSE it got bright, so responding fraction is inflated by "
        "construction - the denominator is built from the numerator. Use only "
        "where responding fraction is not being reported."),
    "std_projection": (
        "Standard deviation across frames. Biases towards RESPONDERS for the "
        "same reason as the maximum: a cell that never changed contributes no "
        "variance and is not found."),
    "mean_projection": (
        "Mean across all frames, stimulation included. Biases towards "
        "well-loaded cells AND, more weakly, towards responders, since a "
        "responding cell raises its own mean."),
    "single_frame": (
        "One nominated frame. Whatever that frame favours, the sample "
        "favours; state which frame and why."),
    "separate_channel": (
        "A channel independent of the probe - DIC, or a nuclear stain. The "
        "only option with no response or loading bias."),
}

DEFAULT_SOURCE_FOR_SERIES = "pre_stimulus_mean"


def describe_source(name):
    """The sampling consequence of a segmentation source, or a refusal."""
    if name not in SEGMENTATION_SOURCES:
        raise ValueError(
            f"Unknown segmentation source {name!r}. Declare one of: "
            + ", ".join(sorted(SEGMENTATION_SOURCES)))
    return SEGMENTATION_SOURCES[name]


def propose_source(n_frames, has_separate_channel=False):
    """What to offer, and why. OFFERED, never applied silently."""
    if has_separate_channel:
        return "separate_channel", (
            "A channel independent of the probe is available, which is the "
            "only source with neither a loading nor a response bias.")
    if n_frames > 1:
        return DEFAULT_SOURCE_FOR_SERIES, (
            "This is a series, so outlines can be drawn on the frames BEFORE "
            "the stimulus. That avoids finding cells because they responded, "
            "which would build the responding fraction out of its own "
            "numerator. Confirm to accept.")
    return "single_frame", (
        "Only one frame exists, so it is the only possible source.")


# ------------------------------------------------------------ flat field --
def flat_field(frame, illumination=None):
    """Remove uneven illumination for SEGMENTATION ONLY.

    Returns (corrected, factor, record). `factor` is the per-pixel gain that
    was applied, so a per-cell correction factor can be reported alongside
    any measurement.

    SPATIAL, NEVER TEMPORAL. A temporal median over a stimulation series
    would contain the cells: adherent cells do not move at all, so they sit
    in their own median and subtracting it removes the signal. The same
    mistake was made once on the worm side, where a crawling animal covers a
    quarter of a body length per second and still barely leaves its own
    outline - see acquisition_probe._illumination, which this reuses.

    THE KERNEL MUST BE MUCH WIDER THAN A CELL. Anything narrower treats the
    cell as illumination and erases it.
    """
    import acquisition_probe

    data = np.asarray(frame, dtype=np.float32)
    if illumination is None:
        # SCALED AGAINST THE BACKGROUND, NOT AGAINST THE CELLS. The obvious
        # 0.5/99.9 percentile scaling puts the bright cells at the top of the
        # range, which squeezes the whole background gradient into a handful
        # of grey levels; the corners then round to near zero and dividing by
        # them multiplies the corners instead of flattening them. Measured on
        # a synthetic vignette: corner/centre went 0.56 to 20.69, an
        # inversion, not a correction.
        #
        # The 90th percentile is above the background everywhere and below
        # the cells, so the gradient spans the range and the cells simply
        # clip - which the MEDIAN blur ignores by construction, since that is
        # what a median is for.
        lo = float(np.percentile(data, 1))
        hi = float(np.percentile(data, 90))
        span = max(hi - lo, 1e-6)
        scaled = np.clip((data - lo) / span * 255, 0, 255).astype(np.uint8)
        blurred = acquisition_probe._illumination(scaled).astype(np.float32)
        # Back into the data's own units before forming a gain, or the gain
        # is a ratio of grey levels rather than of intensities.
        illumination = blurred / 255.0 * span + lo
        illumination = illumination / max(float(illumination.mean()), 1e-6)
        method = "spatial median blur (acquisition_probe._illumination)"
        scale = (f"kernel {min(data.shape[:2]) // 10 | 1} px, capped 9-61; "
                 f"scaled against the 1st-90th percentile so cells clip "
                 f"rather than compress the background")
    else:
        illumination = np.asarray(illumination, dtype=np.float32)
        method = "caller-supplied illumination field"
        scale = "supplied"
    illumination = np.maximum(illumination, 1e-3)
    corrected = data / illumination
    record = {
        "method": method,
        "scale": scale,
        "applies_to": "segmentation only; measurement uses RAW pixels",
        "gain_min": float(1.0 / illumination.max()),
        "gain_max": float(1.0 / illumination.min()),
    }
    return corrected, 1.0 / illumination, record


def correction_factor_for(factor_map, mask):
    """The mean gain applied over one cell, for export beside its numbers."""
    mask = np.asarray(mask, bool)
    if not mask.any():
        return None
    return float(np.asarray(factor_map, dtype=np.float32)[mask].mean())


# -------------------------------------------------------------- clipping --
def saturation_level(bit_depth):
    return float((1 << int(bit_depth)) - 1)


# CENSORED WHERE A CELL SATURATES, PER CELL. A series maximum of 255 does not
# censor the whole recording - it censors the cells that reached it. Cells
# that never approached the ceiling are unaffected and their numbers stand.
CENSORED_BY_SATURATION = (
    "peak_amplitude", "auc", "soce", "fwhm", "decay_tau",
    # TIME TO PEAK DOES NOT SURVIVE CLIPPING, though it looks as if it
    # should. For a saturated cell the recorded peak is the first frame that
    # reached the ceiling, so the measure becomes time-to-ceiling: a lower
    # bound, and a BIASED one. A stronger responder reaches the ceiling
    # sooner, so the bias runs opposite to the effect and shrinks exactly the
    # cells with the largest true response.
    "time_to_peak",
)

# What survives, because it depends on crossing a level rather than on where
# the trace ended up.
ROBUST_TO_SATURATION = ("responding_fraction", "onset_time",
                        "threshold_crossing")


def flag_saturated(traces, bit_depth=8, tolerance=0):
    """Per-cell saturation flags. One entry per trace, never one per series."""
    ceiling = saturation_level(bit_depth) - float(tolerance)
    flags = []
    for trace in np.atleast_2d(np.asarray(traces, dtype=float)):
        touched = trace >= ceiling
        flags.append({
            "saturated": bool(touched.any()),
            "n_frames_at_ceiling": int(touched.sum()),
            "first_ceiling_frame": (int(np.argmax(touched))
                                    if touched.any() else None),
            "censored_measures": (list(CENSORED_BY_SATURATION)
                                  if touched.any() else []),
        })
    return flags


# ------------------------------------------------------- stimulus onset ---
def propose_stimulus_onset(population_trace, min_pre_frames=5):
    """Where the stimulus appears to start, PROPOSED for a human to confirm.

    Found as the first sustained departure from the pre-stimulus level, using
    a robust baseline so one bright frame cannot move it. Returns
    (frame, why) with frame None when nothing convincing is present - an
    absent stimulus is a finding, not a reason to pick the largest jump.
    """
    trace = np.asarray(population_trace, dtype=float)
    if trace.size < min_pre_frames * 3:
        return None, (f"Only {trace.size} frames; too few to separate a "
                      f"pre-stimulus window from a response.")
    head = trace[:max(min_pre_frames, trace.size // 10)]
    baseline = float(np.median(head))
    spread = float(np.median(np.abs(head - baseline))) or 1e-9
    # Six robust deviations, sustained over three consecutive frames, so a
    # single bright frame or a cosmic ray cannot define the onset.
    threshold = baseline + 6.0 * spread
    above = trace > threshold
    for index in range(len(above) - 2):
        if above[index] and above[index + 1] and above[index + 2]:
            return int(index), (
                f"First of three consecutive frames above {threshold:.1f} "
                f"(baseline {baseline:.1f} + 6 robust deviations). The "
                f"pre-stimulus window is frames 0-{index - 1} and every "
                f"timing measure is referenced to this frame. Confirm or "
                f"correct it.")
    return None, (
        "No sustained rise found. Either the stimulus is not in this series, "
        "or the population did not respond - both are findings, and neither "
        "is a reason to nominate the largest single jump.")


# ------------------------------------------------------- outline reuse ---
# SEGMENT ONCE PER ACQUISITION, THEN PROPAGATE. Re-detecting per frame made
# the cell count swing 14-24 across frames of the SAME field, where the true
# count is fixed: cells enter and leave detection as they respond, which is
# max-projection circularity arriving one frame at a time. So outlines are
# drawn once on the declared segmentation_source and reused for every frame.
SEGMENT_ONCE = True
PER_FRAME_REDETECTION = False
REDETECTION_EXCLUDED_BECAUSE = (
    "Per-frame re-detection was measured at 14-24 cells across frames of one "
    "field whose true cell count is fixed. A cell entering detection because "
    "it responded makes the responding fraction partly a detection artefact.")

# Above this, outlines drawn on the source no longer describe the later
# frames. Half a small cell's diameter: cells here run ~15-30 px across, so
# an 8 px shift moves an outline off a small cell entirely.
MAX_DRIFT_PX = 8.0


def drift_offset(reference, frame):
    """Translation between two frames, by phase correlation, in pixels.

    GATES OUTLINE REUSE. Outlines drawn once are only valid while the field
    has not moved; a knocked stage or a focus adjustment invalidates every
    one of them, and nothing in the numbers would show it - the cells would
    simply appear to change shape and brightness together.
    """
    import cv2
    a = np.asarray(reference, dtype=np.float32)
    b = np.asarray(frame, dtype=np.float32)
    if a.shape != b.shape:
        raise ValueError(f"Frame shapes differ: {a.shape} vs {b.shape}.")
    window = cv2.createHanningWindow((a.shape[1], a.shape[0]), cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(a * window, b * window)
    return float(np.hypot(dx, dy)), {"dx": float(dx), "dy": float(dy),
                                     "response": float(response)}


def check_drift(reference, late_frames, max_px=MAX_DRIFT_PX):
    """Raise when the field moved enough to invalidate reused outlines.

    Fails LOUDLY and names the measured offset, because the alternative is
    per-cell traces quietly sampling the wrong pixels.
    """
    worst, detail, worst_index = 0.0, {}, None
    for index, frame in enumerate(late_frames):
        offset, info = drift_offset(reference, frame)
        if offset > worst:
            worst, detail, worst_index = offset, info, index
    if worst > max_px:
        raise ValueError(
            f"The field drifted {worst:.1f} px (dx={detail.get('dx', 0):.1f}, "
            f"dy={detail.get('dy', 0):.1f}) by late frame {worst_index}, "
            f"against a limit of {max_px:.0f} px. Outlines drawn on the "
            f"segmentation source no longer describe these frames, and reusing "
            f"them would sample the wrong pixels for every cell without "
            f"changing anything that looks wrong. Re-segment, or restrict the "
            f"analysis to the frames before the drift.")
    return {"max_drift_px": worst, "limit_px": float(max_px), **detail}


# Provenance values for the append-only correction log. A hand-ADDED cell is
# distinguished from a hand-corrected one: it was invisible to the detector,
# so the set of added cells measures the detector's miss rate directly, and
# it is also the material a future model would need most.
CORRECTION_PROVENANCE = (
    "auto_proposed",      # the detector drew it, nobody touched it
    "human_added",        # the detector MISSED it entirely
    "human_removed",      # the detector drew something that is not a cell
    "human_split",        # one proposal covering two cells
    "human_merged",       # two proposals covering one cell
    "human_reshaped",     # boundary corrected, identity unchanged
)
