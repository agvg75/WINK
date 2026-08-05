"""One document describing the state of the work, for a reader who was not here.

Andres asked whether the work could be put somewhere Claude can see it and
opine on. Most of it already is - method_provenance has been accumulating what
each method computes, where the idea came from, how it was validated, what was
tried and rejected with numbers, and what remains unsolved. This assembles that
into a single file to attach to a Claude Project or a Claude Science workspace.

WHY NOT JUST POINT AT THE REPOSITORY. The repository is the truth but it is a
poor briefing: forty thousand lines in which the important facts - that the
head-region recall is 57.9%, that fibre spacing scored highest and was rejected
anyway, that the median turned out no better than the mean on real data - are
distributed across commit messages, docstrings and test names. A reader would
have to reconstruct them, and would mostly reconstruct the code instead.

WHAT MAKES THIS USEFUL RATHER THAN FLATTERING. It leads with what is NOT known:
the open problems, the rejected approaches with the numbers that killed them,
the claims that failed verification, and the places where a measurement was
made on one animal. An export that lists achievements invites agreement; one
that leads with its own gaps invites the thing actually wanted, which is
someone finding a mistake or a better way.
"""
from __future__ import annotations

from pathlib import Path


def build(include_contributions=True):
    import method_provenance as mp

    L = ["# WINK: state of the work",
         "",
         "A C. elegans image-analysis toolset built in the Vidal-Gadea lab, "
         "Illinois State University. This document is generated from the "
         "code's own provenance registry, so it cannot drift from what the "
         "tools actually do.",
         "",
         "**Read the last three sections first.** They are what is wrong, "
         "unfinished, or unverified, and they are where an outside reading is "
         "worth most.",
         ""]

    a = mp.contribution_audit()
    L += ["## At a glance", "",
          f"- {a['methods_total']} methods with recorded attribution and "
          f"validation",
          f"- {a['open_problems']} stated open problems",
          f"- {a['rejected_alternatives']} approaches tried, measured and "
          f"rejected, with numbers",
          f"- {len(mp.REFERENCES)} external sources, all retrieved from origin",
          ""]

    L += ["## Methods in use", ""]
    for k, m in mp.METHODS.items():
        L.append(f"### {m['title']}")
        L.append(f"`{m['module']}`  ")
        if m.get("verified"):
            L.append(f"**Validated:** {m['verified']}  ")
        if m.get("known_limits"):
            L.append(f"**Known limits:** {m['known_limits']}  ")
        for who, what in (m.get("contribution") or {}).items():
            L.append(f"- *{mp.LABELS.get(who, who)}:* {what}")
        L.append("")

    L += ["", "---", "",
          "## What is NOT solved", "",
          "*Each names the suspected cause, what a solution would have to "
          "show, and the data to work from.*", ""]
    for k, p in mp.OPEN_PROBLEMS.items():
        L += [f"### {k}",
              f"{p['problem']}  ",
              f"**Suspected:** {p['suspected']}  ",
              f"**A solution would show:** {p['would_resolve']}  ",
              f"**Data:** {p['data']}", ""]

    L += ["---", "",
          "## What was tried and rejected", "",
          "*Several of these WON on the metric anyone would reach for first "
          "and were rejected anyway. Before proposing one, read why.*", ""]
    for k, r in mp.REJECTED.items():
        L += [f"- **{r['alternative']}** (considered instead of "
              f"`{r['instead_of']}`) — {r['why']} *Numbers:* {r['numbers']}", ""]

    unconfirmed = {k: v.get("unconfirmed") for k, v in mp.REFERENCES.items()
                   if v.get("unconfirmed")}
    if unconfirmed:
        L += ["---", "",
              "## Claims that did not survive checking", "",
              "*Statements made during development that the cited source does "
              "not actually support. Recorded rather than deleted, so they are "
              "not re-derived.*", ""]
        for k, note in unconfirmed.items():
            L += [f"- **[{k}]** {note}", ""]

    if include_contributions:
        L += ["---", "", mp.contribution_statement(heading="## Contributions")]

    L += ["---", "", "## References", ""]
    for k, r in mp.REFERENCES.items():
        line = f"- **[{k}]** {r['citation']}"
        if r.get("url"):
            line += f" <{r['url']}>"
        L += [line, f"  *Supports:* {r['supports']}"]
        if r.get("check"):
            L.append(f"  *Still to verify:* {r['check']}")
    L.append("")
    return "\n".join(L)


def write(path=None):
    p = Path(path or (Path(__file__).resolve().parents[1] / "docs"
                      / "WINK_state_of_work.md"))
    p.parent.mkdir(parents=True, exist_ok=True)
    text = build()
    p.write_text(text, encoding="utf-8")
    return p, text


if __name__ == "__main__":                                # pragma: no cover
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    p, text = write()
    print(f"{p}  ({len(text.splitlines())} lines, {len(text)} characters)")
