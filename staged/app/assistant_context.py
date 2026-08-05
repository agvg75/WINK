"""What the assistant is allowed to know, so it explains WINK instead of guessing.

A help panel wired straight to a language model will answer every question
fluently, including the ones it has no information about. A student asking why
their worm was not detected would get plausible general advice about contrast
and focus, and never learn that the tool merges pumping events closer than five
seconds and their animal's cycle is shorter than that. Confident, irrelevant
help is worse than no help: it sends the student off to fix the wrong thing and
they have no way to tell.

So the assistant is given TWO grounded sources and told to answer from them or
say it does not know.

  ENVELOPES  the settings that bound what each tool can see, and what happens
             to a specimen that falls outside them. This is the parked
             "envelope advisor" in the form the assistant needs it - every
             entry is a real constant read out of the code, cited by module.

  METHODS    method_provenance, which knows what each measure computes, how it
             was validated, and what was tried and rejected.

WHAT GOES IN AN ENVELOPE ENTRY. Not "this tool uses a 5 second window" - that
is a fact about the code and means nothing to a student. It is "events closer
than 5 seconds are merged into one, so an animal with a shorter cycle is
undercounted and nothing warns you". The consequence is the part that helps.
"""
from __future__ import annotations

# Every limit below was read out of the named module. When one of these
# constants changes, this entry is wrong and a student will be told something
# false with the tool's authority - so they are cited by module and function.
ENVELOPES = {
    "defecation": dict(
        tool="Defecation / pBoc",
        module="tools/defecation/pboc_engine.py",
        limits=[
            dict(setting="Events closer than 5 s are merged (merge_distance = "
                         "5 * fps in candidate_events)",
                 consequence=("Two real pBoc events less than 5 s apart are "
                              "counted as ONE. An animal with a short "
                              "defecation cycle is undercounted, and nothing "
                              "warns you - the count simply comes out low."),
                 what_to_do=("If your genotype speeds the cycle up, check a "
                             "recording by eye before trusting the count.")),
            dict(setting="Recovery is only searched for 6 s after the peak",
                 consequence=("An animal that relaxes more slowly than that is "
                              "recorded as has_recovery = False, which reads "
                              "like a FAILED contraction rather than a slow "
                              "one."),
                 what_to_do=("A high rate of has_recovery = False in a slow "
                             "mutant is a limit of the tool, not a phenotype.")),
        ]),

    "rhythm": dict(
        tool="Rhythm and regularity statistics",
        module="app/event_rhythm.py",
        limits=[
            dict(setting="min_events counts INTERVALS, not events",
                 consequence=("Eight defecation intervals need about six "
                              "minutes of continuous qualifying recording; "
                              "eight pumping intervals need about two "
                              "seconds."),
                 what_to_do=("If it refuses, the recording is too short for "
                             "the rhythm you are measuring - it is not a "
                             "detection failure.")),
            dict(setting="Intervals are never formed across a confidence gap",
                 consequence=("Statistics are computed within good stretches "
                              "and pooled. You will not see a long interval "
                              "where the recording was simply unusable."),
                 what_to_do="Nothing - this is why no false pauses appear."),
        ]),

    "cycles": dict(
        tool="Per-cycle analysis and variability",
        module="app/cycle_analysis.py",
        limits=[
            dict(setting="Timing is quantised by the frame rate",
                 consequence=("Rise and relaxation timing cannot be measured "
                              "finer than one frame. At 30 fps a 5 Hz pump is "
                              "6 frames per cycle - about a 9% floor - which "
                              "would swamp any real shape variability."),
                 what_to_do=("If the report says variability is within the "
                             "quantisation floor, record faster. The number "
                             "you are seeing is the camera, not the animal.")),
            dict(setting="Cycles are never formed across a confidence gap",
                 consequence=("A cycle spanning a bad stretch would have a "
                              "period describing the gap rather than the "
                              "animal, so it is not produced at all."),
                 what_to_do="Expect fewer cycles from a patchy recording."),
        ]),

    "head_tail": dict(
        tool="Head/tail and dorsal/ventral identification",
        module="tools/head_tail.py",
        limits=[
            dict(setting="Dorsoventral cues are read off MOVEMENT",
                 consequence=("They are clearest in swimming. In crawling or "
                              "burrowing the asymmetry is expected to be too "
                              "subtle, so the confidence bar is raised rather "
                              "than a confident answer returned."),
                 what_to_do=("A low-confidence result on a crawling animal "
                             "means the asymmetry was not visible, NOT that "
                             "the animal lacks it.")),
            dict(setting="The vulval cue is adult hermaphrodites only",
                 consequence=("Larvae have not built a vulva and males never "
                              "do, so on either it measures nothing."),
                 what_to_do=("Do not assert adult_hermaphrodite for larvae or "
                             "males.")),
            dict(setting="The pharynx cue needs transmitted light",
                 consequence=("On fluorescence it refuses, because there it "
                              "would only score whichever end was brighter."),
                 what_to_do="Give it the DIC channel if you have one."),
            dict(setting="A wrong head call INVERTS dorsal and ventral",
                 consequence=("Not degrades - inverts. Segment 0 becomes the "
                              "tail, anterior-posterior gradients reverse, and "
                              "a head-to-tail calcium wave reads as "
                              "tail-to-head. All of it still looks plausible."),
                 what_to_do=("Correct the head by hand if it is wrong; the fix "
                             "applies to the whole track and flips "
                             "dorsal/ventral with it.")),
        ]),

    "myocyte": dict(
        tool="Myocyte boundary detection and morphometry",
        module="tools/morphology/myocyte_boundary_proposer.py",
        limits=[
            dict(setting="Detection scale assumes a magnification range "
                         "(DETECT_SCALE per region)",
                 consequence=("Head fields are assumed to be more zoomed in "
                              "than midbody. An unusual magnification is not "
                              "detected, it is simply handled badly."),
                 what_to_do="Tell the tool the region; do not let it guess."),
            dict(setting="Held-out recall is 83.5% at midbody, 57.9% at head",
                 consequence=("Roughly two in five head boundaries are missed. "
                              "This is a known open problem, not a fault in "
                              "your image."),
                 what_to_do=("Review and correct head fields; the review layer "
                             "exists for exactly this.")),
        ]),

    "confidence": dict(
        tool="Confidence gating",
        module="app/confidence_gate.py",
        limits=[
            dict(setting="Qualifying stretches are analysed separately and "
                         "the RESULTS pooled - spans are never joined",
                 consequence=("Raising the confidence level gives you less "
                              "data, not smoother data. Coverage is reported "
                              "so you can see what was dropped."),
                 what_to_do=("Use the sweep to see what each level would cost "
                             "before choosing one.")),
        ]),
}


SYSTEM_PROMPT = """You are the help panel inside WINK, a C. elegans analysis \
toolset used by students in the Vidal-Gadea lab at Illinois State University.

Answer ONLY from the grounding provided below. It contains the real operating \
limits of the tool the student is using, read out of its source code, and \
descriptions of what its measures compute and how they were validated.

If the grounding does not cover the question, say plainly that you do not have \
that information and suggest they ask Andres or check the tool's own output. \
Do NOT fall back on general microscopy or biology advice that sounds \
reasonable - a confident answer about the wrong thing sends a student off to \
fix something that was never the problem, and they have no way to tell.

When a limit in the grounding explains what the student is seeing, say so \
directly and name the number. "The tool merges pumping events closer than 5 \
seconds, so a faster cycle is undercounted" is useful. "Check your focus and \
contrast" is not.

Be brief. Two or three sentences is usually enough. These are students in the \
middle of an analysis, not readers of a manual."""


def build_grounding(tool_key, include_methods=True, max_methods=6):
    """Assemble the grounding text for one tool."""
    parts = []
    env = ENVELOPES.get(tool_key)
    if env:
        parts.append(f"## Operating limits of {env['tool']} ({env['module']})")
        for lim in env["limits"]:
            parts.append(f"- SETTING: {lim['setting']}\n"
                         f"  CONSEQUENCE: {lim['consequence']}\n"
                         f"  WHAT TO DO: {lim['what_to_do']}")
    else:
        parts.append(
            f"## No operating limits are recorded for '{tool_key}'.\n"
            f"Say so rather than inferring them. Known tools: "
            f"{', '.join(sorted(ENVELOPES))}.")

    if include_methods:
        try:
            import method_provenance as mp
        except ImportError:                                # pragma: no cover
            mp = None
        if mp is not None:
            rel = [m for k, m in mp.METHODS.items()
                   if tool_key in m.get("module", "")
                   or tool_key in k][:max_methods]
            if rel:
                parts.append("\n## What these measures compute")
                for m in rel:
                    line = f"- {m['title']} ({m['module']})"
                    if m.get("verified"):
                        line += f"\n  Validated: {m['verified']}"
                    parts.append(line)
    return "\n".join(parts)


def known_tools():
    return sorted(ENVELOPES)


def export_grounding(path=None):
    """Write the whole grounding as one document, for a Claude Project.

    WHY THIS EXISTS SEPARATELY FROM THE ENDPOINT. The endpoint is plumbing; the
    GROUNDING is the part that makes an assistant useful rather than fluent.
    A lab that already has a Claude account can attach this document to a
    Project and get most of the value today, with no API key, no server and no
    cost beyond the subscription it already pays for.

    What that route does NOT give you is the ledger - no record of what was
    asked, no answers accumulating for the next student, no repeated questions
    surfacing as a bug queue - and no per-student caps, because a subscription
    is flat. Those are the reasons to build the endpoint later, and they are
    better reasons once there is evidence students use it at all.
    """
    parts = [
        "# WINK: what the tools measure and what their settings hide",
        "",
        "Attach this to a Claude Project. It is the operating envelope of each "
        "tool - the settings that bound what it can detect and what happens to "
        "a specimen outside them - plus what each measure computes and how it "
        "was validated.",
        "",
        "**Answer from this document.** If it does not cover a question, say "
        "so and suggest asking Andres. General microscopy advice that sounds "
        "reasonable sends a student to fix something that was never the "
        "problem, and they have no way to tell.",
        "",
    ]
    for key in known_tools():
        env = ENVELOPES[key]
        parts += [f"## {env['tool']}  (`{key}`)", f"*Source: {env['module']}*", ""]
        for lim in env["limits"]:
            parts += [f"**Setting:** {lim['setting']}",
                      f"**Consequence:** {lim['consequence']}",
                      f"**What to do:** {lim['what_to_do']}", ""]

    try:
        import method_provenance as mp
        parts += ["## What the measures compute, and how they were validated", ""]
        for k, m in mp.METHODS.items():
            line = f"- **{m['title']}** (`{m['module']}`)"
            if m.get("verified"):
                line += f" — *validated:* {m['verified']}"
            if m.get("known_limits"):
                line += f" — *known limits:* {m['known_limits']}"
            parts.append(line)
        parts += ["", "## Things we have NOT solved", ""]
        for k, p in mp.OPEN_PROBLEMS.items():
            parts.append(f"- **{k}** — {p['problem']} A solution would show: "
                         f"{p['would_resolve']}")
        parts += ["", "## Approaches already tried and rejected", "",
                  "*Several scored better on the obvious metric and were "
                  "rejected anyway. If a student proposes one, this is why.*", ""]
        for k, r in mp.REJECTED.items():
            parts.append(f"- **{r['alternative']}** {r['why']} "
                         f"({r['numbers']})")
    except ImportError:                                    # pragma: no cover
        parts.append("*(method_provenance unavailable; envelopes only.)*")

    text = "\n".join(parts) + "\n"
    if path:
        from pathlib import Path
        Path(path).write_text(text, encoding="utf-8")
    return text


def envelope_notice(tool_key):
    """The short warning a tool can show BEFORE it runs, not only on failure.

    This is the half of the envelope idea that a help panel does not cover: it
    fires when everything goes right and the user still needs to know what was
    not measured.
    """
    env = ENVELOPES.get(tool_key)
    if not env:
        return None
    return {
        "tool": env["tool"], "module": env["module"],
        "limits": [f"{l['setting']} - {l['consequence']}" for l in env["limits"]],
        "why_shown_before_running": (
            "A refusal fires when something goes wrong. This fires when "
            "everything goes right and the result still does not mean what it "
            "appears to."),
    }
