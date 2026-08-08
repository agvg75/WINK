"""Does this recording support the measurements you intend to make?

`acquisition_advisor` plans a recording before it is made. This checks one
afterwards, or a proposed setting before filming, and answers per measurement
rather than in general - because a recording can be entirely adequate for
speed and useless for body orientation, and a single verdict hides that.

WRITTEN FROM A RECORDING THAT FAILED. An archived magnetotaxis movie was
re-tracked in full: 1 fps, 20.1 px/mm, worms 1.14 mm long, so about 23 px per
animal. The detector worked and the trajectories were still a random walk -
turning angle 70-95 degrees where uncorrelated is 90, RISING as the sampling
interval lengthened, displacement scaling as the square root of time. Neither
per-frame linking nor heavy smoothing fixed it, because the problem was the
recording rather than the analysis.

TWO FLOORS DID IT, and both are computable in advance:

  THE BODY WAVE ALIASES. A crawling animal undulates at roughly 0.3-0.5 Hz, so
  its centroid oscillates at that rate independently of where it is going.
  Sampling at 1 fps is at Nyquist for a 0.5 Hz wave and below it for anything
  faster, and the aliased wobble is indistinguishable from real turning.

  THE ANIMAL IS TOO SMALL. At 23 px long, the centroid of a bending worm moves
  by a noticeable fraction of a body length as it bends. If that is comparable
  to how far the animal actually travels between samples, heading is noise.

NEITHER APPEARS IN A PIXEL-LENGTH TABLE, which is why this exists alongside the
advisor rather than inside it. The advisor asks "is the worm big enough to
see"; this asks "is it big enough, and sampled often enough, for the specific
thing you want to measure".

FAILURES NAME THE FIX, and the fix is usually acquisition. There is no
analysis that recovers an aliased body wave.
"""
from __future__ import annotations

import math

# WHY THE PUMPING FLOOR IS NOT 16 fps.
#
# Every locomotion row below is governed by samples per undulation, because a
# crawling or swimming body is approximately sinusoidal and the question is
# whether the waveform can be reconstructed. Applying that rule to pumping
# gives 4 samples x 4-5 Hz = 16-20 fps, and it is WRONG, because pumping is
# not a sinusoid. It is a brief discrete event - a grinder contraction of
# roughly 100-200 ms - separated by longer intervals. The measurement is
# counting individual transients without merging or missing them, which is set
# by how long one pump LASTS, not by how often pumps arrive.
#
#   at 16 fps a 150 ms pump spans 2.4 frames, and one falling between frames
#             is not attenuated, it is ABSENT
#   at 20 fps it spans 3.0 frames, still marginal
#   at 30 fps it spans 4.5 frames, which survives a missed frame and a pump
#             landing anywhere in the cycle
#
# This note sits next to the number because the number looks like it
# disagrees with the table below, and the obvious "correction" - apply Nyquist
# like everything else - reintroduces an undercount that looks entirely
# plausible in the output. A 10 fps recording does not fail loudly; it returns
# a pump rate that is simply too low, which is the same failure shape as the
# fake calcium dose-response.
PUMP_EVENT_S = 0.15
PUMP_MIN_FRAMES_PER_EVENT = 4.0
# 4 frames / 0.15 s = 26.7, rounded up to a frame rate a camera actually
# offers.
PUMP_MIN_FPS = 30.0

# THERE IS NO COMFORTABLE TIER FOR PUMPING, AND PRETENDING OTHERWISE GAVE
# ADVICE NOBODY COULD FOLLOW. This used to read
#
#     PUMP_COMFORTABLE_FRAMES_PER_EVENT = 6.0
#     PUMP_COMFORTABLE_FPS = 40.0            # 6 / 0.15
#
# which is arithmetically fine and physically impossible: EVERY RIG IN THIS
# LAB TOPS OUT AT 30 fps (Andres, 7 Aug 2026). So the acquisition standard
# told Mackenzie to prefer a frame rate her camera cannot reach, and the
# warning below fired on every recording the lab will ever own - at the 30 fps
# ceiling a 150 ms pump spans 4.5 frames against a 6-frame "comfort"
# threshold. A warning that can never be cleared is noise, and noise trains
# people to ignore warnings that matter.
#
# The honest statement is that the countable floor EQUALS the hardware
# ceiling. Pumping is filmed with zero margin, and the only way to gain any
# is a faster camera - not a different setting.
CAMERA_MAX_FPS = 30.0

# BELOW THE COUNTABLE FLOOR, PUMPING IS STILL VISIBLE - just not countable.
# Andres scores pumping by eye at 15 fps, and what he detects is not the
# contraction shape but that the grinder moving one way in one frame moves
# the other way in the next. That needs two samples inside the event, not
# four: 2 / 0.15 s = 13.3, rounded to a rate cameras offer.
#
# So a recording between 15 and 30 fps is PRESENT-BUT-NOT-COUNTABLE. Given
# defecation and crawling are often filmed below 30, that category is
# expected to be well populated, and that is an acquisition constraint rather
# than a failure of any detector.
PUMP_PRESENT_FRAMES_PER_EVENT = 2.0
PUMP_PRESENT_FPS = 15.0

# THE SPATIAL FLOOR IS A DIAMETER, NOT AN AXIAL LENGTH. A pump is a
# contraction ACROSS the bulb, so what has to be resolved is how many pixels
# lie across it. Taking the pharynx as a fraction of body LENGTH - about 1/20,
# giving 25 px on a 500 px animal - measures the wrong axis and overestimates
# detectability roughly twofold.
#
# A recording whose bulb lands between the floor and comfortable belongs in
# MARGINAL and should be routed to human review rather than passing silently.
# The marginal category is expected to be populated; it is not a rounding
# error to be tidied away.
#
# THE WORKED EXAMPLE THAT USED TO SIT HERE HAS BEEN DELETED. It read "at
# about 0.45 px/um from an 1100 um day 1 adult, the terminal bulb is 14-16 px
# across" - and 0.45 px/um was RETRACTED on 6 Aug 2026, having come from a
# 495 px body length that was itself the median of a frame containing two
# animals. The constants below never depended on it: they come from anatomy,
# a 33 um bulb on an 1100 um adult. Only the illustration was stale, and an
# illustration in retracted units teaches the retracted number.
GRINDER_MIN_PX = 10
GRINDER_COMFORTABLE_PX = 25
# The fraction the pixel floors above are derived FROM. Motion signature spec
# v3 section 6.1 requires spatial thresholds be expressed as fractions of
# measured body length rather than as pixels, because magnification metadata
# across the archive is unreliable. This is the diameter fraction: a 1100 um
# day 1 adult has a terminal bulb about 33 um across, so about 1/33 of body
# LENGTH resolves to bulb DIAMETER. Revision 2 used 1/20 and took the result
# as an axial length, which measures the wrong axis.
PHARYNX_BULB_DIAMETER_FRACTION = 1.0 / 33.0


def grinder_px_for(body_length_px,
                   fraction=PHARYNX_BULB_DIAMETER_FRACTION):
    """Bulb DIAMETER in pixels implied by a measured body length.

    The spec forbids pixel thresholds precisely so this conversion happens per
    recording, from a body length MEASURED in that recording - which is also
    why this takes body length in pixels rather than a micrometre scale.
    Magnification metadata across this archive is unreliable, and spec 6.1
    chose body-length fractions to avoid depending on it.

    (An instruction to make these constants micrometre-based and gate them on
    a calibrated scale was raised and WITHDRAWN on 7 Aug 2026: with um_per_px
    still unset for most of the archive it would have reported "unavailable"
    for nearly every recording. The example that used to sit here quoted a
    495 px animal, a retracted figure; it is gone rather than restated.)
    """
    if not body_length_px:
        return None
    return float(body_length_px) * float(fraction)


def pump_sampling_margin(fps, event_s=PUMP_EVENT_S):
    """Frames per pump event - reported instead of a bare pass.

    A recording that scrapes the floor and one with room to spare are not the
    same recording, and a boolean cannot say so.
    """
    return float(fps) * float(event_s)


# What each measurement actually needs. `needs_spine` connects to
# tractability.py: a centroid gives direction of travel, a spine gives
# orientation of the body, and they are not the same measurement.
MEASUREMENTS = {
    "position": {
        "label": "Position and dispersal",
        "min_body_px": 5, "samples_per_undulation": 0, "needs_spine": False,
        "why": "A blob that can be found at all has a centre of mass.",
    },
    "speed": {
        "label": "Speed and distance travelled",
        "min_body_px": 10, "samples_per_undulation": 2, "needs_spine": False,
        "why": ("Displacement between samples must exceed how far the centroid "
                "wanders as the body bends."),
    },
    "track_direction": {
        "label": "Direction of travel",
        "min_body_px": 20, "samples_per_undulation": 4, "needs_spine": False,
        "why": ("Heading is the angle of a displacement, so the displacement "
                "has to be larger than the noise on it."),
    },
    "turning": {
        "label": "Turning rate and reorientation",
        "min_body_px": 25, "samples_per_undulation": 6, "needs_spine": False,
        "why": ("A turn must be distinguishable from the body wave, which "
                "means resolving the wave rather than aliasing it."),
    },
    "body_orientation": {
        "label": "Body orientation relative to a stimulus",
        "min_body_px": 40, "samples_per_undulation": 6, "needs_spine": True,
        "why": ("Needs the midline, not the centroid. An animal can point one "
                "way and travel another - during a reversal it always does."),
    },
    "curvature": {
        "label": "Body curvature and bend depth",
        "min_body_px": 60, "samples_per_undulation": 8, "needs_spine": True,
        "why": ("Curvature is measured along the midline, so the body needs "
                "enough pixels across to fit one and enough samples to follow "
                "the wave."),
    },
    "omega_turns": {
        "label": "Omega turns and escape manoeuvres",
        "min_body_px": 60, "samples_per_undulation": 10, "needs_spine": True,
        "why": ("An omega is a shape change over about one undulation period; "
                "sampling it a few times per period misses its structure."),
    },
    # NOT A NYQUIST CALCULATION. Read the note below before changing 30.
    "pumping": {
        "label": "Pharyngeal pumping rate",
        "min_body_px": 0, "samples_per_undulation": 0, "needs_spine": False,
        "min_fps": PUMP_MIN_FPS,
        # DIAMETER, not axial length. Bulb detectability is set by how many
        # pixels lie across the structure, because that is what a contraction
        # changes. An axial-length fraction overestimates it roughly twofold
        # and would call a marginal recording comfortable.
        "min_grinder_px": GRINDER_MIN_PX,
        "comfortable_grinder_px": GRINDER_COMFORTABLE_PX,
        "why": ("A pump is a discrete event, not a waveform. The measurement "
                "is counting individual transients without merging or missing "
                "them, and that is set by how long one pump LASTS, not by how "
                "often pumps arrive."),
    },
}

# Crawling undulates around 0.3-0.5 Hz; swimming is far faster, 1-3 Hz. The
# default is the crawling case because it is the forgiving one, and a swim
# recording planned against it will be badly undersampled.
UNDULATION_HZ = {"crawl": 0.5, "swim": 2.0}


class AcquisitionError(Exception):
    """Refusals that name the consequence."""


def check(*, fps, um_per_px, body_length_um=1140.0, wants=(),
          gait="crawl", undulation_hz=None, tier="centroid", grinder_px=None):
    """Per-measurement verdicts for one recording or one proposed setting.

    `body_length_um` defaults to 1.14 mm, the figure Andres gave for the
    animals in these recordings.
    """
    if not fps or float(fps) <= 0:
        raise AcquisitionError(
            "A frame rate is required. Every temporal check here is a ratio "
            "against it, and assuming one would make every verdict a guess "
            "wearing a number.")
    if not um_per_px or float(um_per_px) <= 0:
        raise AcquisitionError(
            "A spatial scale is required. Without it the animal's size in "
            "pixels is unknown, and that is what decides whether a midline "
            "can be fitted at all.")
    fps = float(fps)
    hz = float(undulation_hz) if undulation_hz else UNDULATION_HZ.get(
        gait, UNDULATION_HZ["crawl"])
    body_px = float(body_length_um) / float(um_per_px)
    samples_per_cycle = fps / hz

    wanted = list(wants) or list(MEASUREMENTS)
    out = {
        "fps": fps, "um_per_px": float(um_per_px),
        "body_length_px": round(body_px, 1),
        "gait": gait, "undulation_hz": hz,
        "samples_per_undulation": round(samples_per_cycle, 2),
        "nyquist_fps": round(2 * hz, 2),
        "measurements": {}, "warnings": [],
    }

    # NYQUIST IS NOT A USABLE THRESHOLD, and this warning was written at 2
    # before being tested against the recording that motivated the module.
    # That recording sampled the wave exactly 2.0 times per cycle - at
    # Nyquist, so the warning stayed silent - and it aliased badly enough that
    # the trajectories were a random walk. Nyquist is the floor for perfectly
    # reconstructing a bandlimited signal with unlimited precision; a noisy
    # centroid on a not-quite-sinusoidal body wave needs several times that.
    if samples_per_cycle < 4:
        severity = ("ALIASES outright" if samples_per_cycle < 2
                    else "is at or barely above Nyquist and will alias in "
                         "practice")
        out["warnings"].append(
            f"At {fps:g} fps the {hz:g} Hz body wave is sampled "
            f"{samples_per_cycle:.1f} times per cycle, so it {severity}. The "
            f"centroid then appears to move at random and no analysis "
            f"recovers it. Measured on a real recording at exactly 2.0 "
            f"samples per cycle: turning angle rose toward 90 degrees - pure "
            f"randomness - as the sampling interval lengthened, and neither "
            f"per-frame linking nor smoothing fixed it. Four samples per "
            f"cycle is the practical floor; six or more for turning.")

    for key in wanted:
        spec = MEASUREMENTS.get(key)
        if spec is None:
            raise AcquisitionError(
                f"Unknown measurement {key!r}. Known: {sorted(MEASUREMENTS)}.")
        fails = []
        if body_px < spec["min_body_px"]:
            fails.append(
                f"the animal is {body_px:.0f} px long against a floor of "
                f"{spec['min_body_px']} px")
        need = spec["samples_per_undulation"]
        if need and samples_per_cycle < need:
            fails.append(
                f"the body wave is sampled {samples_per_cycle:.1f} times per "
                f"cycle against a floor of {need}")
        if spec["needs_spine"] and tier != "spine":
            fails.append(
                "it needs a midline and this recording gives centroids only")
        # An event-rate floor, for readouts that count transients rather than
        # reconstruct a waveform. Kept separate from samples_per_undulation
        # on purpose: the two are not the same quantity and collapsing them
        # is how the pumping floor gets "corrected" down to Nyquist.
        record = {
            "label": spec["label"], "supported": None, "why": spec["why"],
            "fails": fails, "fix": None,
        }
        floor_fps = spec.get("min_fps")
        if floor_fps:
            margin = pump_sampling_margin(fps)
            record["frames_per_event"] = round(margin, 2)
            record["present_fps"] = PUMP_PRESENT_FPS
            record["camera_max_fps"] = CAMERA_MAX_FPS
            if fps < PUMP_PRESENT_FPS:
                fails.append(
                    f"the frame rate is {fps:g} fps against a floor of "
                    f"{floor_fps:g}, so a {PUMP_EVENT_S * 1000:.0f} ms pump "
                    f"spans only {margin:.1f} frames and one falling between "
                    f"frames is missed entirely, not merely attenuated")
            elif fps < floor_fps:
                # PRESENT BUT NOT COUNTABLE. Enough to see that pumping is
                # happening, not enough to count pumps without undercounting.
                # Reported as its own outcome rather than as a failure,
                # because the recording is fine and the camera is the limit.
                fails.append(
                    f"the frame rate is {fps:g} fps, above the "
                    f"{PUMP_PRESENT_FPS:g} fps at which pumping is still "
                    f"VISIBLE but below the {floor_fps:g} fps needed to COUNT "
                    f"it: a {PUMP_EVENT_S * 1000:.0f} ms pump spans "
                    f"{margin:.1f} frames, so presence can be scored and rate "
                    f"cannot")
                record["pumping_presence"] = "present but not countable"
            elif fps >= floor_fps:
                # The floor and the hardware ceiling are the same number, so
                # clearing the floor is as good as this ever gets. Say so
                # once, as a fact about the rig, rather than warning about a
                # margin that cannot be improved.
                record["pumping_presence"] = "countable"
                record["at_camera_ceiling"] = fps >= CAMERA_MAX_FPS
                if fps >= CAMERA_MAX_FPS:
                    record["margin_note"] = (
                        f"{margin:.1f} frames per pump at the "
                        f"{CAMERA_MAX_FPS:g} fps camera maximum. This is the "
                        f"most margin the hardware can give; only a faster "
                        f"camera would add any.")
        grinder_floor = spec.get("min_grinder_px")
        if grinder_floor:
            if grinder_px is None:
                # Abstain rather than guess: for pumping the head is framed,
                # not the whole animal, so body length does not imply the
                # grinder size and inferring one from the other would be a
                # number wearing a measurement's clothes.
                record["spatial_unverified"] = (
                    f"needs the grinder resolved at {grinder_floor}+ px; not "
                    f"checked because no grinder_px was supplied and body "
                    f"length does not imply it - a pumping recording frames "
                    f"the head, not the animal")
            elif float(grinder_px) < grinder_floor:
                fails.append(
                    f"the grinder is {float(grinder_px):.0f} px across "
                    f"against a floor of {grinder_floor} px")
            else:
                comfortable = spec.get("comfortable_grinder_px") or 0
                record["grinder_px"] = float(grinder_px)
                record["spatial_margin"] = round(
                    float(grinder_px) / grinder_floor, 2)
                if float(grinder_px) < comfortable:
                    record["spatial_verdict"] = "marginal"
                    out["warnings"].append(
                        f"The grinder is {float(grinder_px):.0f} px across, "
                        f"above the {grinder_floor} px floor but below "
                        f"{comfortable} px. MARGINAL: route to human review "
                        f"rather than treating the result as established.")
                else:
                    record["spatial_verdict"] = "recoverable"
        record["supported"] = not fails
        record["fix"] = (_fix(fails, spec, fps, hz, um_per_px, body_length_um)
                         if fails else None)
        out["measurements"][key] = record
    out["n_supported"] = sum(1 for m in out["measurements"].values()
                             if m["supported"])
    out["n_unsupported"] = len(out["measurements"]) - out["n_supported"]
    return out


def _fix(fails, spec, fps, hz, um_per_px, body_um):
    """What to change, in the units of the microscope rather than the analysis."""
    parts = []
    if any("px long" in f for f in fails):
        need_um_per_px = float(body_um) / spec["min_body_px"]
        parts.append(
            f"magnify until the scale is {need_um_per_px:.1f} um/px or finer "
            f"(currently {float(um_per_px):.1f})")
    if any("per cycle" in f for f in fails):
        parts.append(
            f"film at {spec['samples_per_undulation'] * hz:.0f} fps or faster "
            f"(currently {fps:g})")
    if any("midline" in f for f in fails):
        parts.append(
            "and extract spines rather than centroids - see tractability.py, "
            "which decides from a traced frame whether that is possible")
    if any(("floor of" in f or "needed to COUNT" in f) and "fps" in f
           for f in fails):
        # NOT "or faster". The floor equals the camera maximum, so 30 fps is
        # the instruction and there is nothing above it to reach for.
        parts.append(
            f"film at {spec['min_fps']:g} fps (currently {fps:g}), which is "
            f"also the camera maximum - this floor comes from how long a pump "
            f"LASTS, not from the pump rate, so do not recompute it from "
            f"Nyquist. Below {PUMP_PRESENT_FPS:g} fps pumping cannot even be "
            f"scored as present")
    if any("grinder" in f for f in fails):
        parts.append(
            f"magnify until the grinder covers {spec['min_grinder_px']}+ px")
    return "; ".join(parts) or None


def recommend(*, wants, gait="crawl", body_length_um=1140.0,
              undulation_hz=None):
    """The loosest settings that support everything asked for.

    Deliberately the loosest, not the best: a recommendation nobody can meet
    is one everybody ignores, and the floors are already floors.
    """
    hz = float(undulation_hz) if undulation_hz else UNDULATION_HZ.get(
        gait, UNDULATION_HZ["crawl"])
    specs = [MEASUREMENTS[w] for w in wants]
    if not specs:
        raise AcquisitionError(
            "Nothing was asked for, so there is nothing to recommend. State "
            "the measurements first - the settings follow from them, not the "
            "other way round.")
    need_px = max(s["min_body_px"] for s in specs)
    need_samples = max(s["samples_per_undulation"] for s in specs)
    needs_spine = any(s["needs_spine"] for s in specs)
    fps = max(need_samples * hz, 2 * hz)
    # An event-duration floor is not comparable to an undulation floor, so it
    # is taken as a separate maximum rather than folded into the arithmetic.
    event_floor = max((s.get("min_fps") or 0) for s in specs)
    fps = max(fps, event_floor)
    # A RECOMMENDATION NO RIG CAN MEET MUST SAY SO. Returning a bare number
    # above the ceiling is how the 40 fps "comfortable" pumping tier came to
    # sit in the acquisition standard, telling a student to film faster than
    # her camera can.
    unreachable = (f"{round(fps, 1):g} fps exceeds the {CAMERA_MAX_FPS:g} fps "
                   f"maximum of every rig in this lab. This combination of "
                   f"readouts cannot be acquired here - drop one, film the "
                   f"slower gait, or use a faster camera."
                   if fps > CAMERA_MAX_FPS else "")
    return {
        "min_fps": round(fps, 1),
        "camera_max_fps": CAMERA_MAX_FPS,
        "exceeds_camera": unreachable,
        # An event-duration readout has no body-length floor - pumping frames
        # the head, not the animal - so there is no scale it implies. None
        # rather than a number, because a 0 here would read as "any scale".
        "max_um_per_px": (round(float(body_length_um) / need_px, 2)
                          if need_px else None),
        "min_body_px": need_px,
        "needs_spine": needs_spine,
        "gait": gait, "undulation_hz": hz,
        "why": (f"{need_px} px of animal and {need_samples} samples per "
                f"undulation are the strictest floors among the measurements "
                f"asked for. At {hz:g} Hz that is {fps:.0f} fps."
                + (" Spines are required, so the animals must also be "
                   "separable - a pile cannot be segmented at any frame rate."
                   if needs_spine else "")),
        "caveat": ("These are floors for the measurement to mean anything, "
                   "not targets for a good recording. Meeting them exactly "
                   "leaves no margin for a worm that swims faster than "
                   "expected or a frame that goes out of focus."),
    }
