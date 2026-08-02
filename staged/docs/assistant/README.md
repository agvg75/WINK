# WINK Assistant corpus

Documentation written **for the assistant to reason from**, not for a person to
read start to finish. It is loaded into the assistant's system prompt so it can
answer "what does this module do" and, when a run summary is attached, "why does
my result look like this".

## Layout

```
docs/assistant/
  README.md                 this file - conventions
  system_prompt.md          the versioned system prompt
  run_summary_schema.md     what a module writes for the assistant to read
  modules/
    population_tracking.md
    basal_slowing.md
```

## How to write a module file

Five sections, in this order:

1. **What it measures, and why** — the biological question, not the algorithm.
2. **What it expects** — inputs, and what a good recording looks like.
3. **Parameters** — what each controls, typical range, and *what units it is in*.
   Units are the single biggest source of misconfiguration: several WINK
   parameters are in **source pixels**, which means the right value depends on
   magnification, and a value copied from another rig is usually wrong.
4. **What normal output looks like** — actual numbers from real runs where
   possible, so the assistant can tell "unusual" from "broken".
5. **Troubleshooting** — the part the assistant leans on hardest.

## Writing the troubleshooting sections

Write **observation → explanation**, never observation → instruction.

The system prompt tells the assistant to lay out the factors that matter and let
the student do the diagnostic reasoning. It can only do that if the source
material is written that way. If an entry says "increase the size filter", the
assistant will say "increase the size filter", and the student learns nothing
about why their data looked like that.

Bad:

> Too few objects detected? Lower the minimum area.

Good:

> **Observation:** far fewer objects detected than animals visible on the plate.
> **What this usually means:** the area gates are in source pixels, so their
> correct value depends on magnification — on a 4K recording a worm is a few
> thousand pixels, not a few tens. A gate carried over from a lower-resolution
> rig will reject nearly everything.
> **Also worth considering:** animals that are not moving get absorbed into the
> background and become invisible to a difference-based detector, which is a
> property of the preparation rather than the settings.
> **What to check:** whether the marked worm's measured area falls inside the
> gates, and whether the missing animals were moving during the sampled frames.

Always include at least one **experimental or biological** possibility alongside
the software ones. The assistant is instructed not to assume a technical cause,
and it needs material that supports that.

## Keep it honest

- Say when a metric is a proxy. Say when it is a fallback.
- Record known limitations even when they are unflattering — the sampling rate
  of a measurement, the resolution below which something stops working.
- If a default is known to be wrong for a common rig, say so plainly.
- Cite real numbers from real runs. "Median bend frequency about 1.2 Hz on a
  swimming plate" is useful; "a reasonable value" is not.

## Maintenance

When a defect is found and fixed, ask whether it should become a troubleshooting
entry. The signature a user saw is usually more valuable than the fix, because
the same signature can have other causes. Entries derived from real incidents
are marked with the version in which the underlying cause was addressed.
