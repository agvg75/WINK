# The Reference Registry — SPEC, draft v1

Status: **draft. Not built.** Recorded 7 Aug 2026.

---

## What it is, in one paragraph

Every constant in this codebase is one of two things: a number somebody
measured, or a number somebody guessed. Today they look identical. The
Reference Registry is where measurements accumulate so that constants can be
*replaced by queries against them* — `min_area` stops being `40` and becomes
"the 5th percentile of established worm areas for this strain, this assay,
this rig, n=312". A guess and a measurement then look different, because one
of them can tell you its n.

This is the layer that turns a tool into a lab that remembers.

---

## 1. What it holds

Per **quantity**, per **stratum**, a distribution of established values.

**Stratum = strain × assay × rig × module version.** All four, always. A worm
area from a 4K plate rig is not the same quantity as one from a 20× dissecting
scope, and a value measured by a module that has since changed is a value from
a different instrument.

Each entry carries **provenance** — which recording, which session, who
established it — and the running **n**.

## 2. The four hard rules

**(1) It learns from ESTABLISHED values only, never from proposals.**

A detector's output is a proposal until a person accepts it. If proposals fed
the registry, the registry would learn the detector's biases and then be used
to justify them — a machine agreeing with itself, at scale, with an n beside
it to make it look like evidence. **The correction log is the source, and the
correction log records who accepted what.**

**(2) Measurement-quantity expectations may GATE. Biological-quantity
expectations may only ANNOTATE.**

This is the load-bearing distinction and the easiest one to erode.

A *measurement* quantity is a property of the instrument and the pipeline:
pixels across a bulb, mask area against a reference, frames per event. When a
new value falls far outside its stratum, something is probably wrong with the
measurement, and the registry may **withhold** the result.

A *biological* quantity is the thing being studied: pump rate, speed, body
length, calcium amplitude. When one of those falls outside expectation, that
may be **the finding**. A registry that gates on biology would suppress every
phenotype the lab exists to discover — including, precisely, the dystrophic
animals that are supposed to look different.

**Gating on biology is how a lab stops being able to be surprised.**

**(3) Flagged items remain recorded. Nothing is silently dropped.**

An outlier is annotated, never removed. The registry's value depends on it
being a record of what was measured, not a record of what was expected.

**(4) Held-out datasets are excluded BY CONSTRUCTION, not by convention.**

The legacy human-scored sets, and anything else reserved for validation,
cannot enter the registry at all. Not "should not" — the ingest path must not
have a route for them. A validation set that has been learned from has
stopped being one, and nobody would be able to tell afterwards.

## 3. How constants graduate

A constant moves through three states, and its state is visible:

| state | looks like | example |
|---|---|---|
| **guessed** | a literal with a truthful waiver | `min_px=12` — "guess, predates working viewer" |
| **derived** | a literal with its derivation beside it | `PUMP_MIN_FPS = 30` — 4 frames per 150 ms event |
| **registry** | a query | `registry.percentile("cell_area", stratum, 5)` |

A registry query returns **value, stratum, percentile and n**. A query with
n=3 is not the same claim as one with n=300, and the caller can see which it
got. **No query silently falls back to a literal**; a stratum with too little
data returns *unavailable*, and the caller withholds — the same discipline as
a missing frame rate or an undeclared segmentation channel.

## 4. Entry #1: the taper cue

`tools/head_tail.taper_cue(widths, thresh=0.85)`. Nobody knows where 0.85
came from.

The derivation is already specified: run the cue over curated RGBCaMP and
animal-tracker ground truth, take the distribution of the cue at **true
heads** versus **true tails**, and state the criterion **before looking**.
Then either document 0.85 against it, or replace it with the derived value —
and if it moves, that is a finding, not an embarrassment.

That work produces exactly the shape the registry stores: a quantity, a
stratum, a distribution, an n, and a provenance. **It is the registry's first
entry and its proof of concept in one job.**

## 5. Why this is the grant's spine

The proposal's claim is a pipeline that produces defensible measurements
across a 16 TB archive. Defensible means two things, and only two:

**A number can say where it came from.** Provenance, per value, to the
recording and the person.

**A number can say what it is being compared against, and on what n.** Not
"the threshold is 40" but "the 5th percentile of 312 established values from
this strain on this rig".

Everything else in the system — the conformance scanner, the repro corpus, the
published anchors, the correction logs — produces evidence. **The registry is
where evidence accumulates into expectation, and expectation is what lets a
tool say "this recording is unlike the others" instead of silently returning a
number.**

It is the difference between a tool that measures and a lab that knows what it
usually measures. That is the "PI in the box": not a system that decides, but
one that can say *this is unusual, and here is how unusual, and here is what
usual looks like* — which is the thing a PI does that no threshold can.

---

## 6. What must not happen

- **No learning from proposals.** See rule 1. This is the failure that would
  make everything downstream worthless while looking like progress.
- **No gating on biology.** See rule 2.
- **No silent fallback to a literal** when a stratum is thin. Unavailable is
  an answer.
- **No held-out data in the registry**, by construction rather than by care.
- **No registry value quoted without its n and stratum.** A percentile with
  no n is a guess wearing a measurement's clothes, which is the thing this
  whole layer exists to abolish.

---

## 7. Extension: the "published" provenance class

A registry entry may come from the literature as well as from the bench. Such
an entry carries **DOI, values, AND CONDITIONS** — all three, and the third is
not optional.

**The pezo-1 food-density lesson is why.** A pumping rate or a speed means
nothing without the food condition it was measured under; comparing a lab
value on a thin lawn to a published value on a thick one measures the lawn.
So:

**Comparisons must be condition-matched or REFUSE.** An unmatched comparison
is not a weak result, it is a different question answered by accident.

**Divergence is a reportable finding in BOTH directions.** If the lab differs
from the literature, either the lab's pipeline is wrong or the published value
does not hold under these conditions — and the second is a result. A registry
that treats the literature as ground truth would silently tune the lab into
agreement, which is the anchor-fitting error from the validation plan wearing
a different hat.

**Every literature entry is human-established before use.** Nothing enters
from a PDF without a person reading it and saying so, because a mis-typed
published value is indistinguishable from a measured one once it is in the
table.

## 8. Extension: joint distributions, not marginals

Per stratum the registry holds the **joint** distribution, not a set of
independent marginals.

Anomaly scoring runs against the **correlation structure**, and the case that
matters most gets its own flag: **marginal-pass / joint-fail** — every
quantity individually ordinary, the combination not. A worm of normal length
and normal area, whose length and area are wrong *for each other*, is invisible
to any per-quantity check and obvious to a joint one. That is the shape of
most segmentation failures.

> **Note for the grant narrative: this layer and the R15 covariance claim are
> the same computation.** The registry's joint distribution over quantities
> within a stratum IS the covariance structure the proposal argues for. They
> are not two pieces of work that resemble each other; building either one
> builds the other. The spec should be read that way, and the proposal can
> quote it directly.

## 9. Extension: the husbandry join

WINK measurements carry strain and date. ReagentHub carries `StrainThaw`
records. Joining them yields **generations since thaw**, and drift flags
surface with that number attached.

A drift flag on its own says "something changed". With generations-since-thaw
beside it, it says something a person can act on.

### 9.1 Diagnostic checklist: anomaly shape maps to a question

| anomaly shape | proposed question |
|---|---|
| **gradual, across all users** | culture age — how many generations since thaw? |
| **step change, one date** | rig or protocol — what changed that day? |
| **confined to one user** | technique — what is being done differently? |

This is a checklist for a person, not a classifier. The shape suggests where
to look; it does not diagnose.

### 9.2 All diagnostics ANNOTATE. None gate.

Every flag in sections 7–9 attaches to a result and travels with it. **None of
them withholds a measurement.** The gating rule from section 2 is unchanged
and unextended: only measurement-quantity expectations may gate, and a
husbandry or literature or joint-distribution flag is not one.

A tool that refused a measurement because the culture was old would be
deciding a biological question by suppression. The flag says *this animal is
14 generations from thaw, and the values from this stratum drift after 10* —
and a person decides what that means.
