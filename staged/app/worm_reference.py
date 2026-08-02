"""Published reference ranges for C. elegans size and locomotion, and the
plausibility checks that use them.

WHY THIS EXISTS
---------------
Frame rate and micrometres-per-pixel are entered by hand in every WINK module
and are recorded as "declared" - nothing verifies them. Both propagate
linearly into reported physical quantities:

    speed      = pixels/frame x fps x um_per_px      (linear in BOTH)
    frequency  = cycles/frame x fps                  (linear in fps)

so a declared value that is wrong by a factor of four makes every reported
number wrong by a factor of four, silently and consistently. A real case: a
recording captured at 7.5 fps but written with a 30 fps header, analysed with a
scale of 2.0 um/px when the true value was about 10, reported 1.17 Hz and
124 um/s for crawling animals. The correct figures were near 0.29 Hz and
155 um/s. Nothing in the toolset objected, even though the module had already
measured the animals at 100 px long - which at the declared scale means 200 um,
the size of an L1, not the adults on the plate.

These checks turn measurements the modules already make into a question at the
point where a person can still answer it.

HOW TO READ THE NUMBERS
-----------------------
The ranges are deliberately WIDE. They exist to catch order-of-magnitude
mistakes - a scale off by 5x, a frame rate off by 4x - not to police biology. A
value outside a range is a prompt to check a declared parameter, never a
statement that the animals are abnormal.

Body lengths are for N2 at 20 C and vary with strain, temperature, food and
crowding. Locomotion figures vary with substrate, food, and assay. Mutants and
stressed animals legitimately fall outside these ranges, which is exactly why
every check is a warning and never a correction.

Sources: WormAtlas handbook growth data (Altun & Hall) for stage lengths;
standard locomotion assay literature for speed and undulation frequency. Treat
them as approximate.

LAB OVERRIDES
-------------
The lab can replace or extend any of this without editing code by writing
``~/.wink/worm_reference.json`` with the same structure. Anything present there
wins; anything absent falls back to the values below.
"""
from __future__ import annotations

import json
from pathlib import Path

USER_OVERRIDE = Path.home() / ".wink" / "worm_reference.json"

# Body length in micrometres: (typical, plausible_low, plausible_high).
# Adult day numbering: AD1 is the first day of adulthood. Adults continue to
# grow, which is why the later stages are included - some assays deliberately
# use older, larger animals.
STAGE_LENGTH_UM = {
    "L1":  (250,  180,   350),
    "L2":  (380,  300,   480),
    "L3":  (550,  430,   700),
    "L4":  (650,  520,   850),
    "AD1": (1150, 850,  1500),
    "AD2": (1250, 950,  1600),
    "AD3": (1350, 1000, 1750),
    "AD4": (1400, 1050, 1850),
    "AD5": (1450, 1050, 1950),
}

STAGE_ORDER = ["L1", "L2", "L3", "L4", "AD1", "AD2", "AD3", "AD4", "AD5"]

STAGE_LABELS = {
    "L1": "L1 larva", "L2": "L2 larva", "L3": "L3 larva", "L4": "L4 larva",
    "AD1": "Adult day 1", "AD2": "Adult day 2", "AD3": "Adult day 3",
    "AD4": "Adult day 4", "AD5": "Adult day 5",
}

# Locomotion, as (low, high) over the whole assay type. Wide on purpose.
LOCOMOTION = {
    "crawling": {
        "speed_um_s": (40, 350),
        "undulation_hz": (0.15, 0.9),
        "note": "on agar; slower on food than off it",
    },
    "swimming": {
        "speed_um_s": (100, 900),
        "undulation_hz": (0.8, 3.0),
        "note": "in liquid; thrashing is several times faster than crawling",
    },
    "burrowing": {
        "speed_um_s": (10, 200),
        "undulation_hz": (0.1, 0.8),
        "note": "in gel or agar matrix; typically the slowest of the three",
    },
}


# --------------------------------------------------------------------------
# Standard culture vessels
# --------------------------------------------------------------------------
# If the recording contains a whole well or dish, the vessel is a ruler of
# known size sitting in the frame. It is a coarse check - what the camera sees
# may be the outer wall, the inner wall, or the agar meniscus, and those differ
# by several percent - but it is more than good enough to catch a scale that is
# wrong by a factor of five.
#
# (nominal_mm, inner_mm, note). `inner_mm` is the usable/agar diameter, which
# is what a top-down camera usually images; `nominal_mm` is what the vessel is
# called. Where they differ, both are offered because which edge is visible
# depends on the rig.
VESSELS = {
    "well_96":   (6.4,  6.4,  "96-well plate, flat bottom"),
    "well_48":   (11.1, 11.1, "48-well plate"),
    "well_24":   (15.6, 15.6, "24-well plate"),
    "well_12":   (22.1, 22.1, "12-well plate"),
    "well_6":    (34.8, 34.8, "6-well plate"),
    "dish_35":   (35.0, 34.0, "3 cm Petri dish"),
    "dish_50":   (50.0, 48.0, "5 cm Petri dish"),
    "dish_60":   (60.0, 52.0, "6 cm Petri dish"),
    "dish_100":  (100.0, 86.0, "10 cm Petri dish"),
}

VESSEL_ORDER = ["well_96", "well_48", "well_24", "well_12", "well_6",
                "dish_35", "dish_50", "dish_60", "dish_100"]

VESSEL_LABELS = {
    "well_96": "96-well plate (6.4 mm well)",
    "well_48": "48-well plate (11.1 mm well)",
    "well_24": "24-well plate (15.6 mm well)",
    "well_12": "12-well plate (22.1 mm well)",
    "well_6":  "6-well plate (34.8 mm well)",
    "dish_35": "3 cm Petri dish (35 mm)",
    "dish_50": "5 cm Petri dish (50 mm)",
    "dish_60": "6 cm Petri dish (60 mm)",
    "dish_100": "10 cm Petri dish (100 mm)",
}


def vessel_diameter_mm(vessel, edge="inner"):
    data = _load_overrides().get("VESSELS", {})
    entry = data.get(vessel) or VESSELS.get(vessel)
    if not entry:
        raise KeyError(f"unknown vessel: {vessel}")
    nominal, inner = float(entry[0]), float(entry[1])
    return inner if edge == "inner" else nominal


def scale_from_vessel(diameter_px, vessel, edge="inner"):
    """um/pixel implied by a standard vessel spanning `diameter_px`."""
    if diameter_px <= 0:
        raise ValueError("Measured diameter must be greater than zero.")
    return vessel_diameter_mm(vessel, edge) * 1000.0 / float(diameter_px)


def check_vessel_scale(declared_um_per_px, diameter_px, vessel, tolerance=0.20):
    """Cross-check a declared scale against a vessel of known size."""
    if not declared_um_per_px or not diameter_px or vessel not in VESSELS:
        return None
    inner = scale_from_vessel(diameter_px, vessel, "inner")
    outer = scale_from_vessel(diameter_px, vessel, "outer")
    lo, hi = min(inner, outer), max(inner, outer)
    # Accept anything consistent with either edge, plus the tolerance.
    if lo * (1 - tolerance) <= declared_um_per_px <= hi * (1 + tolerance):
        return None
    ratio = ((inner + outer) / 2.0) / float(declared_um_per_px)
    return Warning_(
        "vessel scale",
        f"{declared_um_per_px:.3f} um/px declared",
        f"{lo:.2f}-{hi:.2f} um/px from a {VESSEL_LABELS.get(vessel, vessel)} "
        f"measured at {diameter_px:,.0f} px",
        (f"A {VESSEL_LABELS.get(vessel, vessel)} spanning {diameter_px:,.0f} "
         f"pixels implies about {ratio:.1f}x the declared scale. Vessel "
         f"diameters are standard, so this is usually the fastest way to catch "
         f"a scale that is simply wrong - though it assumes the measured circle "
         f"is the vessel and not, say, a lid reflection or the illuminated "
         f"field."),
        ["scale_um_per_px", "vessel"])


def circle_from_points(points):
    """Least-squares circle through 3 or more points -> (cx, cy, radius).

    The vessel is often larger than the field of view, so only an arc of the
    rim is visible and no whole circle can be detected. An arc still determines
    the circle: three points are enough, more are better. Solved algebraically
    (Kasa), which is exact for clean points and stable for a well-spread arc.

    Accuracy degrades sharply as the arc gets shorter and straighter - a nearly
    flat arc barely constrains the radius - so callers should report the
    subtended angle alongside the result and treat a small one with suspicion.
    """
    try:
        import numpy as np
    except Exception:
        return None
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) < 3:
        return None
    x, y = pts[:, 0], pts[:, 1]
    # x^2 + y^2 + D x + E y + F = 0  ->  centre (-D/2, -E/2)
    A = np.column_stack([x, y, np.ones(len(pts))])
    b = -(x ** 2 + y ** 2)
    try:
        sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    except Exception:
        return None
    D, E, F = sol
    cx, cy = -D / 2.0, -E / 2.0
    inside = cx ** 2 + cy ** 2 - F
    if inside <= 0:
        return None
    return float(cx), float(cy), float(np.sqrt(inside))


def arc_span_degrees(points, centre):
    """How much of the circle the clicked points actually cover.

    A short arc constrains the radius weakly; this is what tells a caller
    whether to trust the fit.
    """
    try:
        import numpy as np
    except Exception:
        return None
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    angles = np.degrees(np.arctan2(pts[:, 1] - centre[1], pts[:, 0] - centre[0]))
    angles = np.sort(np.mod(angles, 360.0))
    if len(angles) < 2:
        return 0.0
    gaps = np.diff(np.concatenate([angles, angles[:1] + 360.0]))
    return float(360.0 - gaps.max())      # the span not covered by the largest gap


def scale_from_arc(points, vessel, edge="inner", image_scale=1.0):
    """um/pixel from points clicked along a partially visible vessel rim.

    Returns (um_per_px, diameter_px, arc_degrees, confidence) where confidence
    is 'good', 'weak' or 'poor' based on how much of the rim was covered.
    """
    fit = circle_from_points(points)
    if fit is None:
        return None
    cx, cy, radius = fit
    diameter_px = 2.0 * radius / float(image_scale or 1.0)
    # Round before grading: a span computed as 89.9999 and one computed as
    # 90.0001 describe the same arc and must not get different verdicts.
    span = round(arc_span_degrees(points, (cx, cy)) or 0.0, 3)
    confidence = "good" if span >= 89.99 else "weak" if span >= 39.99 else "poor"
    return (vessel_diameter_mm(vessel, edge) * 1000.0 / diameter_px,
            diameter_px, span, confidence)


def detect_vessel_diameter_px(image, scale=1.0):
    """Largest circular feature in a frame, in SOURCE pixels, or None.

    `scale` is the proxy factor the image was measured at, so the result is
    returned in source pixels regardless of what it was detected on. Coarse by
    design: it finds the dominant circle, which is normally the vessel rim, but
    a lid edge or a vignette can also be circular. Always show the student what
    was found rather than applying it silently.
    """
    try:
        import cv2
        import numpy as np
    except Exception:
        return None
    img = np.asarray(image)
    if img.ndim == 3:
        img = img[..., :3].mean(axis=2)
    img = np.clip(img, 0, 255).astype("uint8")
    height, width = img.shape
    blurred = cv2.GaussianBlur(img, (9, 9), 0)
    circles = cv2.HoughCircles(
        blurred, cv2.HOUGH_GRADIENT, dp=1.5, minDist=max(width, height),
        param1=120, param2=60,
        minRadius=int(min(width, height) * 0.20),
        maxRadius=int(max(width, height) * 0.75))
    if circles is None:
        return None
    best = max(circles[0], key=lambda c: c[2])
    return float(2.0 * best[2]) / float(scale or 1.0)


# --------------------------------------------------------------------------
# The lab's own measurements
# --------------------------------------------------------------------------
# Published ranges are broad because they span strains, temperatures and rigs.
# A given lab, on a given setup, occupies a much narrower band - so its own
# accumulated measurements make a sharper check than the literature ever can.
#
# The hazard is obvious and worth stating plainly: a library built from runs
# whose declared parameters were wrong will encode those mistakes as normal.
# The run that started all this would have taught it that adults are 200 um
# long and crawl at 1.17 Hz. So an observation only counts toward a range once
# a person has CONFIRMED the run's calibration; everything else is stored but
# excluded, and remains visible for audit.
MEASUREMENT_LOG = Path.home() / ".wink" / "worm_measurements.jsonl"
SHARED_LOG_KEY = "SHARED_MEASUREMENT_LOG"   # optional path in the override file
MIN_OBSERVATIONS = 5        # below this, published ranges are used
EMPIRICAL_LOW_PCT, EMPIRICAL_HIGH_PCT = 5, 95


def _measurement_logs():
    """User log first, then a shared lab log if one is configured."""
    paths = [MEASUREMENT_LOG]
    shared = _load_overrides().get(SHARED_LOG_KEY)
    if shared:
        paths.append(Path(shared))
    return paths


def record_observation(*, module, run_id, stage=None, mode=None,
                       length_px=None, um_per_px=None, speed_um_s=None,
                       freq_hz=None, declared_fps=None, confirmed=False,
                       warnings=None, path=None):
    """Append one run's measurements to the lab library.

    ``confirmed`` must be True for the observation to influence any range. Pass
    True only when a person has looked at the calibration and accepted it.
    """
    import datetime
    entry = {
        "recorded_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "module": module, "run_id": str(run_id),
        "stage": stage, "mode": mode,
        "length_px": None if length_px is None else float(length_px),
        "um_per_px": None if um_per_px is None else float(um_per_px),
        "implied_length_um": (None if (length_px is None or um_per_px is None)
                              else float(length_px) * float(um_per_px)),
        "speed_um_s": None if speed_um_s is None else float(speed_um_s),
        "freq_hz": None if freq_hz is None else float(freq_hz),
        "declared_fps": None if declared_fps is None else float(declared_fps),
        "confirmed": bool(confirmed),
        "warnings_at_record": [w.subject for w in (warnings or [])],
    }
    target = Path(path) if path else MEASUREMENT_LOG
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def load_observations(confirmed_only=True, paths=None):
    rows = []
    for p in (paths or _measurement_logs()):
        try:
            if not Path(p).exists():
                continue
            for line in Path(p).read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                if confirmed_only and not entry.get("confirmed"):
                    continue
                rows.append(entry)
        except Exception:
            continue
    return rows


def _percentile(values, pct):
    values = sorted(values)
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    k = (len(values) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def empirical_range(field, *, stage=None, mode=None, module=None, paths=None):
    """(low, high, n) from the lab's confirmed observations, or None.

    ``field`` is one of implied_length_um, speed_um_s, freq_hz.
    """
    rows = load_observations(confirmed_only=True, paths=paths)
    vals = [r.get(field) for r in rows
            if (stage is None or r.get("stage") == stage)
            and (mode is None or r.get("mode") == mode)
            and (module is None or r.get("module") == module)
            and isinstance(r.get(field), (int, float))]
    if len(vals) < MIN_OBSERVATIONS:
        return None
    return (_percentile(vals, EMPIRICAL_LOW_PCT),
            _percentile(vals, EMPIRICAL_HIGH_PCT), len(vals))


def _load_overrides():
    try:
        if USER_OVERRIDE.exists():
            return json.loads(USER_OVERRIDE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def stage_length_um(stage):
    """(typical, low, high) body length for a stage, honouring lab overrides."""
    data = _load_overrides().get("STAGE_LENGTH_UM", {})
    if stage in data:
        v = data[stage]
        return tuple(float(x) for x in (v if len(v) == 3 else (v[0], v[0], v[0])))
    return tuple(float(x) for x in STAGE_LENGTH_UM[stage])


def locomotion_range(mode, key):
    data = _load_overrides().get("LOCOMOTION", {})
    entry = data.get(mode) or LOCOMOTION.get(mode) or {}
    span = entry.get(key)
    if not span:
        return None
    return float(span[0]), float(span[1])


def scale_from_trace(path_length_px, stage):
    """um/pixel implied by tracing one animal of a known stage, head to tail.

    ``path_length_px`` is the traced path length in SOURCE pixels.
    """
    typical, _, _ = stage_length_um(stage)
    if path_length_px <= 0:
        raise ValueError("Traced length must be greater than zero.")
    return float(typical) / float(path_length_px)


class Warning_:
    """A plausibility concern, phrased as a question rather than a correction."""

    def __init__(self, subject, observed, expected, message, suspects):
        self.subject = subject
        self.observed = observed
        self.expected = expected
        self.message = message
        self.suspects = suspects          # declared parameters that could explain it

    def as_dict(self):
        return {"subject": self.subject, "observed": self.observed,
                "expected": self.expected, "message": self.message,
                "likely_declared_causes": list(self.suspects)}

    def __repr__(self):
        return f"<{self.subject}: {self.message}>"


def _fmt(value, unit):
    return f"{value:,.0f} {unit}" if abs(value) >= 10 else f"{value:.2f} {unit}"


def check_worm_length(length_px, um_per_px, stage, *, paths=None):
    """Does the declared scale imply a body length consistent with the stage?"""
    if not length_px or not um_per_px or stage not in STAGE_LENGTH_UM:
        return None
    implied = float(length_px) * float(um_per_px)
    typical, pub_low, pub_high = stage_length_um(stage)
    low, high, source = _band("implied_length_um", (pub_low, pub_high),
                              stage=stage, paths=paths)
    if low <= implied <= high:
        return None
    factor = implied / typical
    nearest = min(STAGE_ORDER,
                  key=lambda s: abs(stage_length_um(s)[0] - implied))
    return Warning_(
        "body length",
        f"{implied:,.0f} um ({length_px:,.0f} px at {um_per_px:.3f} um/px)",
        f"{low:,.0f}-{high:,.0f} um for {STAGE_LABELS.get(stage, stage)} ({source})",
        (f"The declared scale implies animals {implied:,.0f} um long, which is "
         f"{factor:.1f}x the typical {typical:,.0f} um for "
         f"{STAGE_LABELS.get(stage, stage)} and closest to "
         f"{STAGE_LABELS.get(nearest, nearest)}. Either the stage or the "
         f"micrometres-per-pixel is not what the recording contains."),
        ["scale_um_per_px", "stage"])


def _band(field, published, *, stage=None, mode=None, module=None, paths=None):
    """Prefer the lab's own confirmed range once there is enough of it.

    Returns (low, high, source_text). The lab's band is narrower and therefore
    a sharper check, but it only exists for conditions the lab has actually
    measured and confirmed - so published values remain the fallback.
    """
    lab = empirical_range(field, stage=stage, mode=mode, module=module, paths=paths)
    if lab:
        low, high, n = lab
        return low, high, f"this lab's own range from {n} confirmed run(s)"
    if published:
        return published[0], published[1], "the published range"
    return None, None, None


def check_speed(speed_um_s, mode="crawling", *, stage=None, paths=None):
    if speed_um_s is None:
        return None
    low, high, source = _band("speed_um_s", locomotion_range(mode, "speed_um_s"),
                              stage=stage, mode=mode, paths=paths)
    if low is None or low <= speed_um_s <= high:
        return None
    return Warning_(
        "speed",
        _fmt(float(speed_um_s), "um/s"),
        f"{low:,.0f}-{high:,.0f} um/s for {mode} ({source})",
        (f"Median speed of {speed_um_s:,.0f} um/s falls outside "
         f"{source} for {mode}. Speed scales with BOTH declared frame rate and "
         f"declared micrometres-per-pixel, so a mistake in either moves it "
         f"proportionally."),
        ["declared_fps", "scale_um_per_px"])


def check_frequency(freq_hz, mode="crawling", *, stage=None, paths=None):
    if freq_hz is None:
        return None
    low, high, source = _band("freq_hz", locomotion_range(mode, "undulation_hz"),
                              stage=stage, mode=mode, paths=paths)
    if low is None or low <= freq_hz <= high:
        return None
    factor = freq_hz / high if freq_hz > high else freq_hz / max(low, 1e-9)
    return Warning_(
        "undulation frequency",
        f"{freq_hz:.2f} Hz",
        f"{low:.2f}-{high:.2f} Hz for {mode} ({source})",
        (f"Undulation frequency of {freq_hz:.2f} Hz is {abs(factor):.1f}x "
         f"outside {source} for {mode}. Frequency scales with the declared "
         f"frame rate ALONE, so it is the most direct indicator that the frame "
         f"rate is not what the recording was captured at."),
        ["declared_fps"])


def check_frame_rate(declared_fps, container_fps, tolerance=0.15):
    """Does the declared rate match what the file's own header reports?"""
    if not declared_fps or not container_fps:
        return None
    ratio = float(declared_fps) / float(container_fps)
    if abs(ratio - 1.0) <= tolerance:
        return None
    return Warning_(
        "frame rate",
        f"{declared_fps:g} fps declared",
        f"{container_fps:.3g} fps in the file header",
        (f"The declared frame rate is {ratio:.2f}x the rate written in the "
         f"file. The header is not authoritative - a camera can be recorded "
         f"with the wrong nominal rate - but the two disagreeing is worth "
         f"resolving, because every frequency and speed scales with whichever "
         f"is correct."),
        ["declared_fps"])


def check_scale_agreement(declared_um_per_px, worm_um_per_px, tolerance=0.25,
                          declared_source="declared"):
    """Cross-check a stated magnification against a traced animal.

    WINK can arrive at um/pixel three independent ways: an optical estimate
    from scope, zoom and camera; a scale bar drawn on a frame; and a traced
    animal of known stage. The animal is the weakest of the three in precision
    - body length varies - but it is measured on the actual recording, so it is
    the one that catches an optical estimate built from the wrong objective,
    zoom or adapter factor, or a value carried over from another rig.
    """
    if not declared_um_per_px or not worm_um_per_px:
        return None
    ratio = float(worm_um_per_px) / float(declared_um_per_px)
    if abs(ratio - 1.0) <= tolerance:
        return None
    return Warning_(
        "scale agreement",
        f"{declared_um_per_px:.3f} um/px {declared_source}",
        f"{worm_um_per_px:.3f} um/px from the traced animal",
        (f"The traced animal implies a scale {ratio:.2f}x the {declared_source} "
         f"value. A traced worm is the less precise method, but it is measured "
         f"on this recording - so a large disagreement usually means the "
         f"optical path (objective, zoom, C-mount adapter) or a carried-over "
         f"calibration is wrong, rather than the animal being unusual. A scale "
         f"bar on a frame settles it."),
        ["scale_um_per_px", "objective", "zoom", "c_mount_factor"])


def scale_from_plate(diameter_px, dish_mm):
    """um/pixel implied by a culture dish of known size filling `diameter_px`.

    A fourth, coarse cross-check: dish diameters are standard and the rim is
    usually the most visible circle in the frame.
    """
    if diameter_px <= 0 or dish_mm <= 0:
        raise ValueError("Diameter and dish size must be greater than zero.")
    return float(dish_mm) * 1000.0 / float(diameter_px)


def review(length_px=None, um_per_px=None, stage=None, speed_um_s=None,
           freq_hz=None, mode="crawling", declared_fps=None,
           container_fps=None, paths=None):
    """Run every applicable check. Returns a list of warnings, possibly empty."""
    found = [
        check_frame_rate(declared_fps, container_fps),
        check_worm_length(length_px, um_per_px, stage, paths=paths),
        check_frequency(freq_hz, mode, stage=stage, paths=paths),
        check_speed(speed_um_s, mode, stage=stage, paths=paths),
    ]
    return [w for w in found if w is not None]


def calibration_provenance(*, declared_um_per_px=None, declared_fps=None,
                           container_fps=None, stage=None, vessel=None,
                           estimates=None, warnings=None, confirmed=False,
                           substrate=None, notes=None):
    """Everything that was inferred about a recording, for storage with it.

    Written whether or not any of it was acted on. The point is that someone
    returning to this dataset in a year can see which scale routes were
    available, what each one implied, which was actually used, what looked odd
    at the time, and whether a person ever confirmed it. A value that was
    inferred and ignored is still evidence; discarding it makes the dataset
    harder to re-examine later, not cleaner.

    `estimates` is a list of dicts, each at minimum
    ``{"route": ..., "um_per_px": ..., "confidence": ...}``.
    """
    estimates = list(estimates or [])
    used = declared_um_per_px
    spread = None
    values = [e.get("um_per_px") for e in estimates
              if isinstance(e.get("um_per_px"), (int, float))]
    if len(values) >= 2:
        spread = {"min": min(values), "max": max(values),
                  "ratio_max_over_min": max(values) / max(min(values), 1e-9)}
    return {
        "schema": "wink.calibration_provenance/1",
        "declared": {"um_per_px": declared_um_per_px, "fps": declared_fps,
                     "stage": stage, "vessel": vessel},
        "container_fps": container_fps,
        "independent_scale_estimates": estimates,
        "estimate_spread": spread,
        "scale_actually_used_um_per_px": used,
        "plausibility_warnings": [w.as_dict() for w in (warnings or [])],
        "confirmed_by_user": bool(confirmed),
        "substrate": substrate,
        "notes": notes or "",
        "interpretation_note": (
            "Estimates are recorded whether or not they were used. Declared "
            "values are what the analysis actually ran with. A warning here "
            "does not mean the data are wrong - it means a declared parameter "
            "and a measurement disagreed, and nobody had resolved it at the "
            "time of the run."),
    }


def library_summary(paths=None):
    """What the lab library currently knows, for display and for auditing."""
    all_rows = load_observations(confirmed_only=False, paths=paths)
    confirmed = [r for r in all_rows if r.get("confirmed")]
    by_stage = {}
    for row in confirmed:
        by_stage.setdefault(row.get("stage") or "(unstated)", []).append(row)
    out = {"observations_total": len(all_rows),
           "observations_confirmed": len(confirmed),
           "observations_excluded": len(all_rows) - len(confirmed),
           "minimum_for_a_range": MIN_OBSERVATIONS, "stages": {}}
    for stage, rows in sorted(by_stage.items()):
        entry = {"n": len(rows)}
        for field in ("implied_length_um", "speed_um_s", "freq_hz"):
            span = empirical_range(field, stage=None if stage == "(unstated)" else stage,
                                   paths=paths)
            if span:
                entry[field] = {"low": round(span[0], 3), "high": round(span[1], 3),
                                "n": span[2]}
        out["stages"][stage] = entry
    return out


def rescale_report(speed_um_s=None, freq_hz=None, old_fps=None, new_fps=None,
                   old_um_per_px=None, new_um_per_px=None):
    """What reported values become under corrected declared parameters.

    Exact for speed and frequency, which are linear in these parameters. It does
    NOT re-derive anything that used a frequency THRESHOLD - modality proposals
    in particular must be reclassified, not rescaled.
    """
    fps_factor = (float(new_fps) / float(old_fps)) if old_fps and new_fps else 1.0
    scale_factor = ((float(new_um_per_px) / float(old_um_per_px))
                    if old_um_per_px and new_um_per_px else 1.0)
    out = {"fps_factor": fps_factor, "scale_factor": scale_factor,
           "speed_factor": fps_factor * scale_factor,
           "frequency_factor": fps_factor}
    if speed_um_s is not None:
        out["speed_um_s"] = float(speed_um_s) * fps_factor * scale_factor
    if freq_hz is not None:
        out["frequency_hz"] = float(freq_hz) * fps_factor
    out["caveat"] = ("Speed and frequency rescale exactly. Anything that "
                     "compared a frequency against a threshold - modality "
                     "proposals, eligibility gates - must be recomputed from "
                     "the saved detections, not rescaled.")
    return out
