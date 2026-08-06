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
}

# Crawling undulates around 0.3-0.5 Hz; swimming is far faster, 1-3 Hz. The
# default is the crawling case because it is the forgiving one, and a swim
# recording planned against it will be badly undersampled.
UNDULATION_HZ = {"crawl": 0.5, "swim": 2.0}


class AcquisitionError(Exception):
    """Refusals that name the consequence."""


def check(*, fps, um_per_px, body_length_um=1140.0, wants=(),
          gait="crawl", undulation_hz=None, tier="centroid"):
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
        out["measurements"][key] = {
            "label": spec["label"], "supported": not fails,
            "why": spec["why"],
            "fails": fails,
            "fix": _fix(fails, spec, fps, hz, um_per_px, body_length_um)
            if fails else None,
        }
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
    return {
        "min_fps": round(fps, 1),
        "max_um_per_px": round(float(body_length_um) / need_px, 2),
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
