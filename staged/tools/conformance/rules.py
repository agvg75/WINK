"""Conformance rules. APPEND-ONLY: add rules, never quietly weaken one.

Every rule here comes from an incident that actually happened in this
project. The incident is recorded with the rule because a rule whose reason
has been forgotten is one somebody deletes the first time it is inconvenient.

RANK decides what a finding does at publish time:

    measured-values   changes a number a person would report -> BLOCKS
    gating            changes what is eligible or offered -> reports
    cosmetic          confusing rather than wrong -> reports

WEAKENING A RULE IS AN EDIT WITH A REASON, NOT A DELETION. If a pattern is
wrong, add an exemption with a note saying why. If a rule is genuinely
retired, mark it retired and leave it in place: the record of what was once
required is the point.
"""
from __future__ import annotations

# Files that are ABOUT the failures rather than committing them. A spec
# documenting a retraction must be allowed to name the retracted number.
DOC_CONTEXT = (r"RETRACT", r"retracted", r"do not resurrect", r"WITHDRAWN",
               r"this used to", r"used to read", r"the bug this",
               r"incident", r"NOT the", r"never ", r"no longer")

# --------------------------------------------------------- structural --
# Some rules are about SHAPE, not text, and a regex cannot see shape. A rule
# may carry a `check(path, text) -> [(line_index, matched_text)]` instead of
# `patterns`; the scanner treats the results identically, including
# fingerprints, waivers and exemptions.


def except_name_imported_in_try(path, text):
    """`except X` where X is imported INSIDE the try it guards.

    If the import is what fails, the name is unbound when the handler runs,
    so the except clause raises NameError while handling the very error it
    was written to report. The handler is dead code that looks live, and it
    is only entered on the failure path - which is exactly where nobody
    looks until a student hits it.
    """
    import ast
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        bound = set()
        for statement in node.body:
            for inner in ast.walk(statement):
                if isinstance(inner, (ast.Import, ast.ImportFrom)):
                    for alias in inner.names:
                        bound.add((alias.asname or alias.name).split(".")[0])
        if not bound:
            continue
        for handler in node.handlers:
            if handler.type is None:
                continue
            for name in ast.walk(handler.type):
                if isinstance(name, ast.Name) and name.id in bound:
                    found.append((handler.lineno - 1, f"except {name.id}"))
                elif isinstance(name, ast.Attribute):
                    root = name
                    while isinstance(root, ast.Attribute):
                        root = root.value
                    if isinstance(root, ast.Name) and root.id in bound:
                        found.append(
                            (handler.lineno - 1, f"except {root.id}.*"))
    return found


RULES = [
    {
        "id": "withdrawn-numbers",
        "rank": "measured-values",
        "summary": "A number that was measured, then retracted, used as if live",
        "incident": (
            "0.45 px/um came from a 495 px body length that was itself the "
            "median of a frame containing two animals. Everything derived "
            "from it inherited the error, including a 14.9:1 aspect ratio. "
            "Retracted 6 Aug 2026; the retraction only holds if nothing "
            "keeps using the number."),
        "patterns": [r"0\.45\s*px\s*/?\s*um", r"\b495\s*px\b", r"14\.9\s*:\s*1"],
        "exempt_context": DOC_CONTEXT,
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "fps-established",
        "rank": "measured-values",
        "summary": "30 fps described as established rather than bracketed",
        "incident": (
            "I reported 30 fps as 'established, not assumed' from three "
            "tight folders. Across all 26 bracketed sessions the median only "
            "bounds the rate above ~16.7 fps, and drive-wide 99.7% of "
            "sessions are pinned by the camera ceiling rather than by the "
            "inter-session arithmetic. The claim needed narrowing twice."),
        "patterns": [r"30\s*fps[^.\n]{0,40}establish",
                     r"establish[^.\n]{0,40}30\s*fps"],
        "exempt_context": DOC_CONTEXT + (r"ceiling", r"protocol"),
        "files": ["app/*.py", "tools/**/*.py", "docs/specs/*.md"],
    },
    {
        "id": "underived-constant",
        "rank": "measured-values",
        "summary": "An absolute pixel/area/threshold with no derivation beside it",
        "incident": (
            "The tracker's acceptance band, 0.55 to 1.60 of a reference, has "
            "no derivation anywhere in the repository. It returned ZERO "
            "detections across 234 frames of a recording where the animal is "
            "plainly visible, because a texture mask is systematically "
            "smaller than the hand outline it was compared against."),
        "patterns": [
            r"(?<![\w.])(?:min|max)_(?:area|px|size)\s*=\s*\d{2,}",
            r"(?<![\w.])(?:threshold|thresh|cutoff)\s*=\s*\d+\.?\d*",
            r"\b0\.55\s*\*", r"\b1\.60\s*\*",
        ],
        "exempt_context": DOC_CONTEXT + (
            r"derived", r"derivation", r"measured", r"because",
            r"UNDERIVED", r"set from", r"per spec", r"spec \d",
            # alpha blends and colour weights are not thresholds
            r"rgb", r"alpha", r"blend", r"overlay",
            # TEXT THAT WARNS ABOUT A CONSTANT IS NOT THE CONSTANT.
            # The provisional-results notice in population_swimming
            # quotes the very gates it warns about, and the scanner
            # duly flagged the warning as the violation.
            r"notice", r"warning", r"defect", r"provisional",
            r"showwarning", r"do not adapt"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "declared-not-measured",
        "rank": "gating",
        "summary": "Bit depth, rate, scale or channel count taken on trust",
        "incident": (
            "check_recording answered from the typed 'Frames per cell' box, "
            "which defaults to 1. Pointed at a 224-frame Leica movie it "
            "reported that every kinetic measurement was impossible because "
            "the recording was a single frame. The data was in the file."),
        "patterns": [
            r"bit_depth\s*=\s*(?:8|16)\b(?!.*measur)",
            r"\bfps\s*=\s*\d+\.?\d*(?!.*(?:measur|read|header))",
            r"um_per_px\s*=\s*\d+\.?\d*(?!.*(?:measur|read))",
        ],
        "exempt_context": (r"default", r"fallback", r"test", r"fixture",
                           r"measured", r"read from", r"header",
                           r"declared", r"refuse"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "single-sample-statistic",
        "rank": "measured-values",
        "summary": "A directional or temporal property estimated from one frame",
        "incident": (
            "Single-frame azimuth inherits the animal's posture: 146 degrees "
            "at R=0.56 from one frame against 94 degrees at R=0.86 over 25. "
            "A direction from one frame is a posture, not an illumination "
            "geometry."),
        "patterns": [r"frames?\[0\][^\n]{0,60}(?:angle|azimuth|direction|"
                     r"orient|period|rate|interval)",
                     r"(?:azimuth|direction|orientation)[^\n]{0,40}frames?\[0\]"],
        "exempt_context": DOC_CONTEXT + (r"over frames", r"across frames"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "runtime-parity",
        "rank": "measured-values",
        "summary": "An import that can silently fall back to a different path",
        "incident": (
            "cv2 is in the lab runtime and not in the bundled one. A tool "
            "that quietly takes a different branch when it is missing "
            "returns different MEASURED VALUES from the same recording "
            "depending on which Python opened it, which is worse than "
            "refusing to start."),
        "patterns": [
            r"except\s+ImportError[^\n]*:\s*(?:\n\s+)?(?!.*raise)"
            r"(?:\s*[\w.]+\s*=|.*pass\b)",
            r"HAVE_\w+\s*=\s*have\(",
        ],
        "exempt_context": (r"raise", r"refuse", r"fail loudly", r"SystemExit",
                           r"probe", r"never break the tool"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "photometry-firewall",
        "rank": "measured-values",
        "summary": "Reported intensity computed on corrected or normalised pixels",
        "incident": (
            "Segmentation may define object extent only. An intensity read "
            "off a flat-field-corrected or contrast-stretched image carries "
            "the correction into the number, and nothing downstream can tell "
            "it was applied. segment on corrected, MEASURE ON RAW."),
        "patterns": [
            r"(?:mean|median|sum|intensity|amplitude|f0|dff)\s*\([^)]*"
            r"(?:corrected|normalised|normalized|stretched|scaled)",
            r"(?:corrected|normalised|normalized)\[[^\]]*\]\.(?:mean|sum)\(",
        ],
        "exempt_context": (r"display", r"segmentation only", r"for drawing",
                           r"overlay", r"preview"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "segmentation-trust",
        "rank": "gating",
        "summary": "A measurement consuming a mask with no overlay step in its lineage",
        "incident": (
            "Threshold+watershed on Naga's cells returned ONE region "
            "covering 65% of the frame - it had segmented the illumination "
            "vignette. The blob count alone looked like a detector working "
            "on a confluent sheet. Only the overlay showed it."),
        "patterns": [r"def\s+\w*(?:measure|quantif|analyse|analyz)\w*\s*\("
                     r"[^)]*mask"],
        "exempt_context": (r"overlay", r"reviewed", r"confirmed", r"proposal",
                           r"segmentation_review", r"accepted"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "reachability",
        "rank": "gating",
        "summary": "A capability with no route from a screen that needs it",
        "incident": (
            "Six reachability failures in one tool: the GCaMP commit control "
            "collapsed to 1px, the frame range not passed across a handoff, "
            "the segmentation workbench given a derived directory, a stale "
            "review session ending the tool, and a brightness dial that "
            "existed in five other tools and neither tracker screen."),
        "patterns": [r"imshow\([^)]*cmap\s*=\s*[\"']gray[\"']\s*\)"],
        "exempt_context": (r"vmin", r"clim", r"attach_sliders", r"display_range",
                           r"overlay", r"thumbnail", r"contact sheet"),
        "files": ["app/*.py", "tools/**/*.py"],
    },
    {
        "id": "handler-name-bound-in-try",
        "rank": "gating",
        "summary": "An except clause naming something imported inside its own try",
        "family": "error machinery must be fired to be trusted",
        "incident": (
            "segmentation_review_tool.py imported ContextError inside the "
            "try whose handler caught it. Had the import been the thing that "
            "failed, `except ContextError` would have raised NameError while "
            "handling the error it existed to report - and the original "
            "message would have been replaced by a traceback about a missing "
            "name. Written 8 Aug 2026 during fix A and caught by reading, "
            "not by running: the handler is only entered on the failure "
            "path, which is where nobody looks until a student gets there. "
            "Same family as the crash handler that filed a clean exit and "
            "the publish refusal that printed the word PASS - error "
            "machinery is not trustworthy until it has been fired."),
        "check": except_name_imported_in_try,
        "patterns": [],
        # DOC_CONTEXT only. An exemption on "fixture" or "deliberately" would
        # let any violation excuse itself by sitting near the word - the same
        # self-excusing trap that let `underived_gate` satisfy the
        # underived-constant rule by naming itself.
        "exempt_context": DOC_CONTEXT,
        "files": ["app/*.py", "tools/**/*.py"],
    },
]


def by_id(rule_id):
    for rule in RULES:
        if rule["id"] == rule_id:
            return rule
    raise KeyError(rule_id)


BLOCKING_RANK = "measured-values"


# ---------------------------------------------------------------- repro --
# A STATIC PATTERN SAYS A RULE MIGHT BE BROKEN. A REPRO SAYS IT IS.
#
# Each entry names frozen data and the failure signature IN NUMBERS. Prose
# signatures ("detection was poor") cannot be compared across modules, and
# comparing is the whole point: the propagation protocol below branches on
# whether another module fails the SAME way.
REPRO_CORPUS = r"L:\10_AGVG LAB\Lab Tools\repro_corpus"

REPROS = {
    "underived-constant": {
        "clip": "AVG6_frames_0_233",
        "extra": {"area_ref_px": 44232.0, "band": [0.55, 1.60]},
        "signature": {
            # Measured 7 Aug 2026. The rule finds the animal on every frame
            # and the band admits almost none of them.
            "frames": 234,
            "found_an_object": 234,
            "admitted_by_band": 3,
            "median_ratio": 0.300,
            "ratio_range": [0.228, 0.719],
        },
        "tolerance": {"median_ratio": 0.02, "admitted_by_band": 2},
        "why": ("The band, not the foreground rule, produces the zero. Any "
                "module comparing a mask area to a hand-drawn reference is a "
                "candidate for the same failure."),
    },
    "segmentation-trust": {
        "clip": "hCTM_ach_1",
        "extra": {"frame_index": 1654},
        "signature": {
            # Otsu without flat-field correction segments the vignette.
            "regions_without_flatfield": 1,
            "coverage_without_flatfield": 0.664,
            "regions_with_flatfield": 14,
            "coverage_with_flatfield": 0.009,
        },
        "tolerance": {"coverage_without_flatfield": 0.05,
                      "regions_with_flatfield": 6},
        "why": ("A detector that returns one enormous region looks like a "
                "confluent sheet in the numbers and like a failure in the "
                "overlay."),
    },
    "single-sample-statistic": {
        "clip": "AVG6_frames_0_233",
        "extra": {"single_frame": 528, "window": 25},
        "signature": {
            "single_frame_consistency": 0.56,
            "windowed_consistency": 0.86,
        },
        "tolerance": {"single_frame_consistency": 0.12,
                      "windowed_consistency": 0.12},
        "why": ("One frame reports the animal's posture; the window reports "
                "the illumination geometry."),
    },
}

# Clips the corpus must hold, seeded from the frozen development set.
REQUIRED_CLIPS = (
    "pezo1_frozen_six",          # the six frozen recordings
    "AVG6_frames_0_233",         # plus area_ref 44232 from the review session
    "AVG6_frame_528",
    "AVG6_frame_1728",           # the unambiguous coil
    "AVG6_frame_4499",
    "AVG6_frame_8549",           # animal immersed in lawn
    "hCTM_ach_1",                # Naga's cultured cells
)


# THE PROPAGATION PROTOCOL, ENFORCED RATHER THAN REMEMBERED.
#
# Before an incident-derived fix is applied to any module OTHER than the one
# it came from, the repro runs against that module UNFIXED. What happens next
# is decided by the signature, not by judgement:
PROPAGATION = {
    "same_signature": (
        "APPLY the fix, rerun the repro, confirm it now passes. The module "
        "was susceptible in the same way and the fix is the right fix."),
    "no_failure": (
        "DO NOT APPLY. Record 'not susceptible' with the run as evidence. A "
        "fix applied where nothing was broken is a change with no reason, "
        "and the next person cannot tell it from a change with one."),
    "different_signature": (
        "STOP. Report both signatures side by side and change NOTHING until "
        "the divergence is explained. Two modules failing differently under "
        "one repro means the shared cause is not yet understood, and applying "
        "a fix derived from the other one would be guessing."),
}
DIVERGENCE_RANK = "measured-values"     # a STOP blocks publish like any fail


# ----------------------------------------------------- published anchors --
# A TIER ABOVE THE REPRO CORPUS. A repro pins behaviour against ourselves;
# these pin it against NUMBERS THAT ARE ALREADY PUBLISHED, which is the only
# check that catches a whole pipeline drifting together.
#
# THE ONE-SHOT RULE, and it is the entire discipline: run once, report the
# result, and do not iterate against the target. Tolerance is stated BEFORE
# the run, taken from the spread the paper itself reports - never chosen
# afterwards to make an answer fit.
#
# Divergence is a finding to investigate. It is never a knob to turn. A
# pipeline tuned until it reproduces a published number has been fitted to
# that number and has stopped being evidence for anything.
PUBLISHED_ANCHORS = {
    # Seeded empty of values on purpose: filling these in requires reading
    # the papers, and a placeholder number would be indistinguishable from a
    # real one the moment it is committed.
    "pezo1_manuscript": {
        "doi": "TO BE FILLED FROM THE PAPER",
        "clip": "pezo1_frozen_six",
        "targets": {},          # published value -> numeric target
        "tolerance": {},        # PRE-STATED, from the paper's own spreads
        "tolerance_source": "the reported spread in the paper, not chosen here",
        "one_shot": True,
        "status": "awaiting the paper's reported values",
    },
    "affordable_tracker_micropub": {
        "doi": "TO BE FILLED FROM THE PAPER",
        "clip": "micropub_affordable_tracker",
        "targets": {},
        "tolerance": {},
        "tolerance_source": "the reported spread in the micropublication",
        "one_shot": True,
        "status": "awaiting the dataset location and the paper's values",
    },
}

ANCHOR_PROTOCOL = (
    "Run once. Report. Do not re-run against the target with anything "
    "changed. If the result diverges, that is a finding about the pipeline "
    "or about the paper, and it is investigated as one - not closed by "
    "adjusting a parameter until the numbers agree.")


# ------------------------------------------------------------- lore -----
# Incidents worth keeping that are not themselves patterns. A rule catches a
# shape in the code; these are shapes in how the work goes wrong.
LORE = [
    {
        "id": "act-before-verify",
        "date": "2026-08-07",
        "what": (
            "A scanner finding was acted on as an instruction before the "
            "source was read. The scanner flagged 0.45 px/um and 495 px in "
            "acquisition_check.py, a fix was ordered - make the grinder "
            "constants micrometre-based and gate them on a calibrated scale - "
            "and only the verification step revealed that the constants never "
            "depended on those numbers at all. They come from anatomy: a 33 um "
            "bulb on an 1100 um adult. The retracted figures appeared solely "
            "in an illustrative comment."),
        "cost_if_unchecked": (
            "The ordered fix would have routed pumping eligibility through "
            "um_per_px, which is unset for most of this archive, and reported "
            "'unavailable' for nearly every recording - a regression, to fix "
            "a defect that was in the prose."),
        "what_caught_it": (
            "The spot-verify-before-acting step. It was in the instruction "
            "and it earned its place on its first use."),
        "rule_or_not": (
            "NOT MECHANIZABLE as a pattern. A scanner cannot tell an "
            "illustration from a dependency; only reading can. The mechanism "
            "is the verification step itself, which is now standing practice: "
            "spot-verify every finding against source before acting, "
            "especially while the scanner is young."),
    },
    {
        "id": "generation-as-propagation-vector",
        "date": "2026-08-07",
        "what": (
            "The literal 1.60 appears in the tracker's identity band, the "
            "basal slowing gates, and defecation_feasibility. It was not "
            "copied by hand between them: the same model re-emitted it "
            "independently in three places."),
        "cost_if_unchecked": (
            "A constant spreads through a codebase with no edit that a review "
            "would catch, because there is no copy-paste to notice and each "
            "site looks locally reasonable."),
        "what_caught_it": "the conformance scanner's underived-constant rule",
        "rule_or_not": (
            "RULE, already present - underived-constant catches the literal "
            "wherever it lands. What is new is knowing the vector, which is "
            "why cross-module literal agreement is worth treating as evidence "
            "rather than coincidence."),
    },
]
