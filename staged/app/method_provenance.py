"""Who contributed each method: the literature, Andres, or the assistant.

WHY THIS EXISTS. Andres asked that the manual distinguish "the methods that came
from literature, the ones Claude devised, and the ones I contributed - what I
did, what we adopted, and what the AI derived." That is a reasonable thing to
want and a difficult thing to reconstruct afterwards: by the time a tool works,
the commit history has interleaved an observation, an implementation and a
citation into something that reads as though it arrived whole.

So attribution is recorded HERE, next to the code, at the time the method is
written - not inferred later from a diff.

THE HONEST DEFAULT IS `joint`, AND MOST ENTRIES ARE. Almost nothing here has a
single author. The usual shape is that Andres names something true about the
animal, the assistant turns it into a measurement, and the literature supplies
the statistics or the vocabulary. `contribution` therefore records what EACH
party actually did rather than assigning a winner, and `origin` names only where
the decisive idea came from.

A note on what "the AI derived" honestly means. Where an entry is marked
`claude`, the contribution is the measurement design - choosing what to compute
so that a stated fact becomes separable from its confounds. It does not mean the
biology was discovered here, and entries should not be written as though it was.
"""
from __future__ import annotations

ORIGINS = ("andres", "claude", "literature", "joint")

# Each entry: what the method is, where the decisive idea came from, and what
# each party contributed. `verified` records how we know it works.
METHODS = {

    # ---- body-wall myocyte boundaries -----------------------------------
    "longitudinal_boundary_geometry": dict(
        title="Myocyte boundaries run longitudinally, not transversely",
        module="tools/fibre_orientation.py", origin="andres",
        contribution={
            "andres": ("Hand-marked the boundaries in two fields. Measuring "
                       "his ink showed 99% of it within 30 degrees of the body "
                       "axis, against an initial implementation that searched "
                       "transversely - a ~90 degree error, not a tuning miss."),
            "claude": "Measured the marks and rebuilt the search direction.",
        },
        verified="83.5% held-out recall at midbody, 57.9% at head."),

    "valley_operator": dict(
        title="A dim seam is found with the second derivative, not a gradient",
        module="tools/fibre_orientation.py", origin="claude",
        contribution={
            "claude": ("Gradient magnitude is ZERO at the centre of a dark "
                       "line, so it cannot localise the feature it is looking "
                       "for. d2I/dy2 is the operator that peaks there."),
            "literature": "Standard ridge/valley detection.",
        },
        verified="Cue power 0.915 for valley against 0.788 for gradient."),

    "per_cell_brightness_signature": dict(
        title="Each myocyte has its own brightness signature",
        module="tools/fibre_orientation.py", origin="andres",
        contribution={
            "andres": ("Phalloidin penetrates each cell individually, so "
                       "brightness differs cell to cell. This corrected an "
                       "opening claim that the boundary was not an intensity "
                       "feature at all."),
            "claude": ("Combined it with orientation as an independent cue - "
                       "gradient DIRECTION is invariant to intensity scaling, "
                       "which is what makes the two independent."),
        }),

    "junction_splitting": dict(
        title="Split traced fibres at junctions before measuring",
        module="tools/fibre_trace.py", origin="claude",
        contribution={"claude": "Sato ridge filter, skeletonise, split at "
                                "junctions so a fibre is not merged with its "
                                "neighbour across a crossing."},
        verified="Convergence voting reaches boundary evidence 0.849."),

    # ---- pharynx ---------------------------------------------------------
    "pharynx_damage_features": dict(
        title="What degeneration looks like in the pharynx",
        module="tools/pharynx_continuity.py", origin="andres",
        contribution={
            "andres": ("Named four things from marked images: interior holes "
                       "with an intact perimeter, extra-bright scar tissue, "
                       "detached filaments that coil and lose axial "
                       "orientation, and loss of radial congruence - all "
                       "concentrated in the CORTEX, because the centre holds "
                       "the lumen and is intrinsically non-radial."),
            "claude": "Turned each into a measure and validated three.",
        },
        verified="disrupted_fibres: bending 0.849, congruence 0.827."),

    "cortex_only_measurement": dict(
        title="Measure radial organisation in the cortex only",
        module="tools/pharynx_continuity.py", origin="andres",
        contribution={
            "andres": "\"The center has the lumen so it is intrinsically "
                      "non radial.\"",
            "claude": ("A first version measured coiling across 53% of fibre "
                       "area by scoring the core, where radial was never the "
                       "expectation."),
        }),

    "unroll_about_lumen": dict(
        title="Unroll about the lumen so continuity is bending-invariant",
        module="tools/pharynx_continuity.py", origin="claude",
        contribution={"claude": "Measuring continuity in unrolled coordinates "
                                "makes it invariant to how the organ is bent "
                                "by construction, rather than by correction."}),

    # ---- damage scoring --------------------------------------------------
    "splitter_not_lumper": dict(
        title="Score each damage parameter separately, never as one index",
        module="tools/pharynx_continuity.py", origin="literature",
        contribution={
            "literature": ("A 2023 ischaemic skeletal muscle scheme scores "
                           "inflammation, fibrosis, necrosis, adipocyte "
                           "infiltration and degeneration separately, 4-5 "
                           "levels each, validated by Kendall's W."),
            "andres": ("Independently described the same shape - categories "
                       "with a gradient inside each."),
        },
        verified="A single index makes 30% scarring and one detached muscle "
                 "numerically equal."),

    "continuous_not_categorical": dict(
        title="Measure continuously; bin only at the end",
        module="tools/pharynx_continuity.py", origin="literature",
        contribution={"literature": ("ISHLT cardiac allograft rejection "
                                     "grading was revised in 2004 to fix "
                                     "reproducibility and did not - "
                                     "disagreement persists AT GRADE "
                                     "BOUNDARIES, which continuous measures "
                                     "do not have.")}),

    "ordinal_guard": dict(
        title="Never average an ordinal grade",
        module="app/event_rhythm.py", origin="literature",
        contribution={"literature": ("Averaging ordinal grades assumes equal "
                                     "spacing no scheme guarantees; ~70% of "
                                     "papers do it anyway. Median, IQR, full "
                                     "distribution, non-parametric tests.")}),

    "function_anchored_severity": dict(
        title="Anchor damage severity to measured function",
        module="app/event_rhythm.py", origin="joint",
        contribution={
            "literature": ("Histopathology scales are usually validated "
                           "against expert consensus, which is circular."),
            "andres": ("This lab measures pumping, bends and swimming on the "
                       "same animals."),
            "claude": ("It also tests the detection confound - an artefact "
                       "will not track locomotor decline; real damage should."),
        }),

    # ---- rhythm and cycles ----------------------------------------------
    "cardiac_rhythm_vocabulary": dict(
        title="RMSSD, SDNN and Poincare descriptors for pharyngeal pumping",
        module="app/event_rhythm.py", origin="literature",
        contribution={
            "literature": "Cardiology's validated beat-to-beat vocabulary.",
            "andres": ("The pharynx is closer to cardiac than skeletal - "
                       "myogenic, sharing most ion channels that define "
                       "cardiac physiology. And: because the tool detects "
                       "EACH pumping event, the full interval series is "
                       "available, so every beat-to-beat measure is "
                       "computable where a mean rate gives none."),
        }),

    "cycle_shape_variability": dict(
        title="Cycle-to-cycle spread of rise, relaxation and excursion",
        module="app/cycle_analysis.py", origin="andres",
        contribution={
            "andres": ("Proposed that variability in time-to-peak, "
                       "time-to-relaxation and excursion is a dimension "
                       "separate from the mean, and underreported."),
            "literature": ("Partly confirms it: gon-2/gtl-1 knockdown raises "
                           "defecation cycle variability with NO change in "
                           "mean period. Variability of PERIOD is "
                           "established; variability of waveform SHAPE is "
                           "not."),
            "claude": ("The measure, and the quantisation floor - a timing "
                       "fraction cannot be measured finer than one frame, so "
                       "below step/sqrt(12) the report is of the camera."),
        }),

    "confidence_spans_never_concatenated": dict(
        title="Analyse within confidence spans; never join them",
        module="app/confidence_gate.py", origin="joint",
        contribution={
            "andres": ("Asked for a selectable confidence level so a "
                       "recording with good and bad stretches yields a "
                       "high-confidence output."),
            "claude": ("A cycle or interval spanning a join is an invention - "
                       "its period describes the gap, not the animal - so "
                       "spans are analysed separately and the RESULTS pooled."),
        }),

    # ---- body axis identity ---------------------------------------------
    "taper_shape": dict(
        title="Head and tail are told apart by taper SHAPE, not width",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("Both ends taper. The tail taper is long and shallow "
                       "and comes to a point; the head taper is short, steep "
                       "and round."),
            "claude": ("Replaced a terminal-width comparison, which a steep "
                       "head taper defeats, with taper length and tip "
                       "bluntness."),
        }),

    "pharynx_confinement": dict(
        title="The pharynx is found by CONFINEMENT, not texture",
        module="tools/head_tail.py", origin="joint",
        contribution={
            "andres": ("The pharynx is visible in DIC and makes the head read "
                       "LIGHTER than the region behind it; the tail matches "
                       "the body. Also suggested the confocal pharynx work "
                       "would help here."),
            "claude": ("What transferred was the length scale, not the lumen "
                       "and bulb detectors, which need a magnification these "
                       "movies lack. Measuring both features confined to one "
                       "pharynx length and comparing with the length behind "
                       "makes debris and gut contents cancel."),
        },
        verified="Smeared texture scores -0.02 against 0.30 for a pharynx."),

    "ventral_excursion_depth": dict(
        title="Ventral excursions are deeper, which identifies the side",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("The dorsoventral asymmetry during movement, clearest "
                       "in swimming. Also that failure means the movie could "
                       "not resolve it - a REVERSED mutant would be "
                       "extraordinary."),
            "claude": ("Depth from the 95th percentile rather than the mean, "
                       "and the prior encoded as a raised threshold outside "
                       "swimming rather than a refusal."),
        }),

    "vulval_gap": dict(
        title="The vulval myocyte gap marks the ventral side locally",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("Building the vulva required myocyte apoptosis, so an "
                       "adult hermaphrodite bends differently ventrally than "
                       "dorsally at precisely that one spot."),
            "claude": ("Difference in differences. A first version compared "
                       "each bending sense with its own flanks and scored a "
                       "worm with NO notch at -0.99, reading positional "
                       "curvature bias."),
        },
        verified="Corrected measure scores -0.001 on the no-notch control."),

    "head_error_from_cohort_disagreement": dict(
        title="A dorsoventral disagreement diagnoses a head error",
        module="tools/head_tail.py", origin="joint",
        contribution={
            "andres": ("A reversed animal would be extraordinary, so "
                       "disagreement is a processing fault."),
            "claude": ("A wrong head call inverts the dorsoventral sign "
                       "exactly, so the redundancy becomes an error detector. "
                       "Flags, never corrects - auto-flipping would make a "
                       "genuine reversal permanently invisible."),
        }),

    "human_override_propagates": dict(
        title="A hand-corrected head applies to the whole track",
        module="tools/head_tail.py", origin="andres",
        contribution={
            "andres": ("Asked that head/tail be correctable and that the "
                       "correction propagate to successive frames, which it "
                       "did not in at least one tool."),
            "claude": ("The call is per-track, so a correction cannot reach "
                       "the frame on screen and leave the rest behind; and it "
                       "propagates sideways too, since flipping the head "
                       "inverts dorsal and ventral."),
        }),

    # ---- infrastructure --------------------------------------------------
    "noisy_or_combination": dict(
        title="Independent agreeing cues combine by noisy-OR",
        module="tools/head_tail.py", origin="literature",
        contribution={
            "literature": "Standard combination of independent evidence.",
            "claude": ("Averaging made two agreeing cues score BELOW the "
                       "stronger alone. Deliberately not used for the head "
                       "cues, which read the same end's anatomy and fail "
                       "together."),
        }),

    "coerce_numeric_from_data": dict(
        title="Decide column types from data, not from column names",
        module="app/table_io.py", origin="claude",
        contribution={"claude": ("A first version matched column NAMES and "
                                 "would have turned fps_source='declared' "
                                 "into NaN, destroying provenance. Caught by "
                                 "surveying real CSVs before trusting it.")}),
}


class ProvenanceError(Exception):
    """Refusals that name the consequence."""


def check_registry(methods=None):
    """Validate the registry; a wrong attribution is worse than none."""
    methods = METHODS if methods is None else methods
    problems = []
    for key, m in methods.items():
        if m.get("origin") not in ORIGINS:
            problems.append(f"{key}: origin {m.get('origin')!r} not in {ORIGINS}")
        contrib = m.get("contribution") or {}
        if not contrib:
            problems.append(f"{key}: no contribution recorded")
        for who in contrib:
            if who not in ("andres", "claude", "literature"):
                problems.append(f"{key}: unknown contributor {who!r}")
        origin = m.get("origin")
        if origin in ("andres", "claude", "literature") and origin not in contrib:
            problems.append(
                f"{key}: origin is {origin!r} but {origin!r} contributed nothing")
        if origin == "joint" and len(contrib) < 2:
            problems.append(f"{key}: marked joint but has one contributor")
    return problems


def attribution_summary(methods=None):
    """Counts by origin, and how many methods each party contributed to.

    The two are different and both belong in the manual: `by_origin` says where
    the decisive idea came from, `contributed_to` says who was involved at all.
    Reporting only the first would erase everyone but the originator; reporting
    only the second would make every party look equally decisive.
    """
    methods = METHODS if methods is None else methods
    by_origin, contributed = {o: 0 for o in ORIGINS}, {}
    for m in methods.values():
        by_origin[m["origin"]] = by_origin.get(m["origin"], 0) + 1
        for who in (m.get("contribution") or {}):
            contributed[who] = contributed.get(who, 0) + 1
    return {
        "n_methods": len(methods),
        "by_origin": by_origin,
        "contributed_to": contributed,
        "note": ("`by_origin` is where the decisive idea came from; "
                 "`contributed_to` is who was involved at all. Most methods "
                 "here have more than one contributor, which is why both are "
                 "reported."),
    }


LABELS = {"andres": "Andres Vidal-Gadea", "claude": "assistant (Claude)",
          "literature": "published literature"}


def methods_section(keys=None, methods=None, heading="## Methods"):
    """Render the manual's methods section with attribution per method."""
    methods = METHODS if methods is None else methods
    keys = list(methods) if keys is None else list(keys)
    missing = [k for k in keys if k not in methods]
    if missing:
        raise ProvenanceError(
            f"No provenance recorded for {missing}. Add an entry rather than "
            f"publishing a method with no attribution - an unattributed method "
            f"reads as though it came from nowhere, and by the time anyone "
            f"asks, the history has blurred.")

    lines = [heading, ""]
    for k in keys:
        m = methods[k]
        lines.append(f"### {m['title']}")
        lines.append("")
        lines.append(f"*Origin: {LABELS.get(m['origin'], m['origin'])}"
                     f"{' (joint)' if m['origin'] == 'joint' else ''}* — "
                     f"`{m['module']}`")
        lines.append("")
        for who, what in (m.get("contribution") or {}).items():
            lines.append(f"- **{LABELS.get(who, who)}:** {what}")
        if m.get("verified"):
            lines.append(f"- *Verified:* {m['verified']}")
        lines.append("")
    s = attribution_summary(methods)
    lines += [
        "### Attribution summary", "",
        f"{s['n_methods']} methods. Decisive idea: "
        + ", ".join(f"{v} {k}" for k, v in s["by_origin"].items() if v),
        "",
        "Contributed to: "
        + ", ".join(f"{LABELS.get(k, k)} {v}"
                    for k, v in sorted(s["contributed_to"].items())),
        "", s["note"], "",
    ]
    return "\n".join(lines)
