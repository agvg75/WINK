"""A standing watch for published work that could improve WINK, and the rules
for testing it honestly against what we already have.

Andres asked for a weekly scan of preprints and literature for work bearing on
what is already in place, then evaluation of the promising ones - including
running them against previous data to see whether they would have improved
accuracy, speed, or both.

The scan is the easy half. The evaluation is where this can go quietly wrong,
and the reason is arithmetic rather than carelessness.

THE MULTIPLE-COMPARISONS TRAP, AND WHY IT IS BUILT IN HERE.
Every week this produces candidates. Each candidate gets measured against the
same held-out fixtures. Test twenty candidates against one held-out set and the
best of them beats the incumbent by a margin that means nothing - not because
anyone cheated, but because the best of twenty noisy draws is high by
construction. Do it for a year and the reported accuracy of WINK becomes a
record of how many things were tried, not of how well it works.

So the held-out data is treated as a budget that is SPENT, and this module
tracks the spending:

  - Screening and first evaluation run on DEVELOPMENT fixtures only.
  - A candidate reaches held-out data ONCE, after it has already won on
    development data, and the promotion is recorded.
  - The registered validation set (the published hand-measured swim/crawl
    confocal data) is never touched by this process at all. It exists to
    answer one question once, and a weekly loop would consume it.
  - A margin that would not survive the number of candidates already tested is
    reported as not established, however good it looks.

WHAT COUNTS AS AN IMPROVEMENT is stated per benchmark BEFORE anything is run,
because a threshold chosen after seeing the result is not a threshold. Speed
and accuracy are tracked separately: a method that is twice as fast and
slightly worse is a real option for whole-drive work and a bad one for a
figure, and collapsing them into a single score hides which it is.
"""
from __future__ import annotations

import math


class WatchError(Exception):
    """Refusals that name the consequence."""


# Topics to scan, tied to what they could change. Each names the METHODS or
# OPEN_PROBLEMS entry it bears on, so a hit arrives already attached to the
# thing it might replace.
WATCH_TOPICS = {
    "myocyte_boundary": dict(
        queries=["C. elegans body wall muscle cell boundary segmentation",
                 "myocyte boundary detection phalloidin confocal automated",
                 "ridge valley detection dim membrane seam microscopy"],
        bears_on=["longitudinal_boundary_geometry", "valley_operator",
                  "junction_splitting"],
        open_problems=["head_region_boundary_recall", "fibre_length_capture"]),

    "pharynx_damage": dict(
        queries=["C. elegans pharynx degeneration quantification",
                 "pharyngeal muscle damage dystrophy imaging metrics",
                 "radial muscle organisation disruption image analysis"],
        bears_on=["pharynx_damage_features", "cortex_only_measurement",
                  "unroll_about_lumen"],
        open_problems=["interior_voids_over_called", "bright_scar_unvalidated"]),

    "worm_pose_tracking": dict(
        queries=["C. elegans midline tracking head tail identification deep learning",
                 "worm posture eigenworm skeleton freely moving open source",
                 "nematode head tail disambiguation automated"],
        bears_on=["taper_shape", "pharynx_confinement",
                  "ventral_excursion_depth", "vulval_gap"],
        open_problems=["dv_untested_on_real_animals", "no_fiji_parity_check"]),

    "calcium_kinetics": dict(
        queries=["GCaMP transient kinetics rise decay quantification muscle",
                 "calcium imaging freely moving C. elegans body wall muscle",
                 "curvature calcium coupling nematode locomotion"],
        bears_on=["cycle_shape_variability",
                  "confidence_spans_never_concatenated"],
        open_problems=[]),

    "damage_scoring": dict(
        queries=["histopathology severity scoring reproducibility ordinal",
                 "muscle degeneration grading system validation",
                 "neurite damage quantification beading blebbing"],
        bears_on=["splitter_not_lumper", "continuous_not_categorical",
                  "ordinal_guard", "function_anchored_severity"],
        open_problems=[]),

    "rhythm_variability": dict(
        queries=["defecation motor program variability C. elegans",
                 "pharyngeal pumping rate variability mutant",
                 "heart rate variability methods short recordings"],
        bears_on=["cardiac_rhythm_vocabulary", "cycle_shape_variability"],
        open_problems=[]),
}

PREPRINT_SOURCES = ("bioRxiv", "arXiv q-bio", "PubMed (last 7 days)",
                    "micropublication.biology")


# What a candidate has to beat, and on what. Stated in advance. `dev_fixture`
# is where screening happens; `heldout_fixture` is spent at most once per
# candidate and only after a development win.
BENCHMARKS = {
    "myocyte_boundary_recall": dict(
        metric="held-out boundary recall",
        current="83.5% midbody, 57.9% head",
        dev_fixture="myocyte_marks_W1_midbody.npz",
        heldout_fixture="myocyte_marks_W1_ventral_head.npz",
        min_improvement=0.05,
        why_that_margin=("Below 5 percentage points the difference is within "
                         "the spread already seen between quadrants of the "
                         "same field - 84.2% between, 56.2% within - so a "
                         "smaller margin describes which field was scored."),
        also_track=["seconds per field"]),

    "fibre_length_capture": dict(
        metric="fraction of expected fibre length captured",
        current="57%, and increasing it has always HURT boundary evidence",
        dev_fixture="myocyte_vertices_midbody.npz",
        heldout_fixture="myocyte_vertices_head.npz",
        min_improvement=0.10,
        why_that_margin=("This one must improve length AND hold boundary "
                         "evidence; a length-only gain has already been shown "
                         "to be partly wrong length bridged across junctions."),
        also_track=["boundary evidence", "seconds per field"]),

    "pharynx_disruption": dict(
        metric="agreement with marked damage",
        current="bending 0.849, congruence 0.827",
        dev_fixture="pharynx_marks_W4_head.png",
        heldout_fixture="pharynx_marks_W2_head.png",
        min_improvement=0.05,
        why_that_margin="Two marked fields only; anything smaller is one mark.",
        also_track=["false interior voids (currently 23 against 1 marked)"]),

    "head_tail_accuracy": dict(
        metric="fraction of tracks with the head called correctly",
        current="synthetic only; never measured on real recordings",
        dev_fixture="synthetic worms in tests/test_head_tail.py",
        heldout_fixture="a real recording set, once one is scored by eye",
        min_improvement=0.05,
        why_that_margin=("There is no real-data baseline yet, so the first "
                         "measurement establishes one rather than beating it."),
        also_track=["seconds per track"]),
}

# The registered validation set is deliberately absent from BENCHMARKS.
PROTECTED_DATA = {
    "open_biology_validation_set": (
        "Published hand-measured swim and crawl confocal data, registered as "
        "HELD OUT. It answers one question once. A weekly candidate-testing "
        "loop would consume it within months, and no amount of care afterwards "
        "would restore it. Never used by this process."),
}


def screen(title, source, url, bears_on, claim, why_relevant):
    """Record a candidate paper, before any evaluation of it."""
    unknown = [b for b in bears_on if b not in _known_targets()]
    if unknown:
        raise WatchError(
            f"{unknown} is not a method or open problem in "
            f"method_provenance. A candidate that does not attach to something "
            f"we already do cannot be evaluated against anything, and would "
            f"become an interesting paper nobody ever acts on.")
    return {
        "title": title, "source": source, "url": url,
        "bears_on": list(bears_on), "claim": claim,
        "why_relevant": why_relevant,
        "stage": "screened", "tested_on_heldout": False,
    }


def _known_targets():
    try:
        import method_provenance as mp
    except ImportError:                                   # pragma: no cover
        return set()
    return set(mp.METHODS) | set(mp.OPEN_PROBLEMS)


def evaluation_plan(candidate, benchmark_key):
    """State what would count as an improvement, BEFORE running anything."""
    if benchmark_key not in BENCHMARKS:
        raise WatchError(f"No benchmark {benchmark_key!r}. Add one with a "
                         f"stated margin before evaluating against it - a "
                         f"threshold chosen after seeing the result is not a "
                         f"threshold.")
    b = BENCHMARKS[benchmark_key]
    return {
        "candidate": candidate["title"],
        "benchmark": benchmark_key,
        "metric": b["metric"],
        "must_beat": b["current"],
        "min_improvement": b["min_improvement"],
        "why_that_margin": b["why_that_margin"],
        "run_on": b["dev_fixture"],
        "heldout_reserved": b["heldout_fixture"],
        "also_track": b["also_track"],
        "speed_and_accuracy_separately": (
            "Report both. A method twice as fast and slightly worse is a good "
            "option for whole-drive work and a bad one for a figure; a single "
            "combined score hides which case you are in."),
        "protected": sorted(PROTECTED_DATA),
    }


def multiplicity_guard(observed_improvement, n_candidates_tested,
                       min_improvement, alpha=0.05):
    """Is this margin bigger than the best of N noisy draws would be anyway?

    A crude Bonferroni-style correction, and crude is the right level: the
    point is not a precise p-value but to stop the twentieth candidate of the
    year being promoted on a margin the first would not have been. The required
    margin grows with how many candidates have already been measured against
    the same fixture.
    """
    n = max(int(n_candidates_tested), 1)
    # Effective threshold scaled by sqrt(log N): the expected maximum of N
    # independent noise draws grows about that fast.
    inflation = math.sqrt(math.log(n + 1) / math.log(2))
    required = min_improvement * inflation
    passes = observed_improvement >= required
    return {
        "observed": round(float(observed_improvement), 5),
        "n_candidates_tested": n,
        "base_threshold": min_improvement,
        "required_now": round(float(required), 5),
        "established": bool(passes),
        "why": (f"{n} candidates have now been measured against this fixture. "
                f"The best of {n} noisy results is high by construction, so "
                f"the margin required rises from {min_improvement} to "
                f"{required:.3f}. "
                + ("This clears it." if passes else
                   "This does not clear it, however good it looks - report it "
                   "as not established and, if it still seems promising, get "
                   "more data rather than more candidates.")),
    }


def promote_to_heldout(candidate, benchmark_key, dev_result_beat_threshold):
    """Spend one held-out evaluation. Refuses if development did not win first."""
    if candidate.get("tested_on_heldout"):
        raise WatchError(
            f"{candidate['title']!r} has already been evaluated on held-out "
            f"data. Testing it again after a change is how a held-out set "
            f"becomes a training set - the second run is no longer held out, "
            f"and nothing afterwards can undo that.")
    if not dev_result_beat_threshold:
        raise WatchError(
            f"{candidate['title']!r} did not clear the development threshold. "
            f"Held-out data is spent, not borrowed; a candidate that has not "
            f"already won on development data has no claim on it.")
    out = dict(candidate)
    out.update({"stage": "promoted", "tested_on_heldout": True,
                "benchmark": benchmark_key,
                "note": ("One held-out evaluation. Whatever it returns is the "
                         "result for this candidate - there is no second run.")})
    return out


def weekly_brief(topics=None):
    """The searches to run, and what each hit would have to displace."""
    topics = list(WATCH_TOPICS) if topics is None else list(topics)
    lines = ["# WINK literature watch", "",
             "Sources: " + ", ".join(PREPRINT_SOURCES), "",
             "For each hit, record it with `screen()` so it arrives attached "
             "to the method or open problem it bears on. A paper that attaches "
             "to nothing becomes an interesting paper nobody acts on.", ""]
    for t in topics:
        w = WATCH_TOPICS[t]
        lines.append(f"## {t}")
        for q in w["queries"]:
            lines.append(f"- `{q}`")
        if w["bears_on"]:
            lines.append(f"  - *Could displace:* {', '.join(w['bears_on'])}")
        if w["open_problems"]:
            lines.append(f"  - *Could resolve:* {', '.join(w['open_problems'])}")
        lines.append("")
    lines += ["## Rules for evaluating a hit", "",
              "1. Screen and evaluate on DEVELOPMENT fixtures.",
              "2. Beat the stated margin there first.",
              "3. Then, and only then, spend ONE held-out evaluation.",
              "4. Apply `multiplicity_guard` - the margin required rises with "
              "the number of candidates already tested against that fixture.",
              "5. Report speed and accuracy separately.",
              "6. Never touch the registered validation set.", ""]
    for k, v in PROTECTED_DATA.items():
        lines.append(f"- **{k}**: {v}")
    return "\n".join(lines)
