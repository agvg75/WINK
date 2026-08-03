# WINK Lab Tools v11.123 — in-tool help, and fibres get the same editing power as animal tracks

## Step-by-step help inside the tool

Every cockpit tool gains a **`?  help`** button. It shows guidance for the step
you are actually on — what to do next and *why it matters* — in the hood, and
only when you ask for it, so it never adds noise to the process log.

Myocyte morphometry registers help for all five stages: boundary, sampling
line, sarcomere ticks, fibres, save. The other twelve cockpit tools inherit the
button now and show a clear placeholder until their own text is written.

This answers what the single definitive manual cannot without a student leaving
the tool to go and find the right page.

Completes fibre editing in Myocyte morphometry. The population tracker lets you
split, trim, delete and add points to an animal's track over time; a traced
fibre now gets the same, applied to a single frame.

## The full set

| Action | How | Use it when |
|---|---|---|
| **Relabel** | click a fibre | the straight / wavy / low-confidence call is wrong |
| **Delete** | right-click a fibre | the trace jumped between two different real fibres |
| **Cut in two** | click where to cut | one trace covers a genuinely straight stretch *and* a wavy one |
| **Extend** | click the end, then trace on | the tracer stopped short of the fibre's real end |
| **Draw by hand** | click along it | the tracer missed the fibre entirely |
| **Retry tracing** | adjust link distance | the tracer keeps hopping to a neighbouring fibre |

New in this release: **cut** and **extend**. The rest shipped in v11.122.

## Details that matter

**Cut conserves the traced points exactly** — nothing is invented or lost, and
both halves inherit the original's label so you can relabel just the half that
needs it. A cut that would leave a stub under ten points is **refused**, because
`classify_fiber_wavy` cannot classify one; the message says so and points at
deleting the fibre instead.

**Extend fills the new stretch at traced spacing** (~2 px), not as one sparse
jump. The waviness classifier counts *points*, so a sparsely clicked extension
would be weighted wrongly against the rest of the fibre.

**An edited fibre's wavy length fraction is re-derived** from its own arc length
against the cell's Feret. The automatic value described the original trace and
stops describing an edited one. Cut and extended fibres are marked `corrected`,
so `wave_n_relabelled` reflects human judgement rather than the automatic first
pass.

## Still not built

Marking a branch point *within* a fibre and assigning identity per segment
rather than per fibre. Cutting at the branch point and labelling each half is
the current way to express that.
