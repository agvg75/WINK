# Pre-registration: depth cohesion as a myocyte boundary cue

**Registered 8 Aug 2026, from Andrés. No data have been looked at.**

This file exists so the prediction is on record before the measurement. If it
were written afterwards it would be a description, not a prediction, and the
result would not be able to surprise anyone.

---

## The prediction (Andrés, stated in advance)

On the per-(x,y) **depth-of-max-fibrous-energy** map:

1. **Tile-like domains** appear, **matching myocyte size and the staggered-pair
   arrangement** of bodywall muscle.
2. **Between-cell depth steps EXCEED within-cell roughness.**

Point 2 is the whole test. Domains that are visible but whose steps do not
exceed within-cell roughness are not a usable boundary cue, however convincing
the picture looks.

---

## Method

- **~5 calibrated head stacks.**
- Compute the per-(x,y) depth-of-max-fibrous-energy map — **the same
  computation `bodywall_flattening_SPEC.md` §5 exports as its QC record.** One
  implementation, not a second one written for this test.
- **Measure both numbers**: between-cell depth step, and within-cell
  roughness. Both, with units, per stack.
- **Report the map images**, not only the statistics. The prediction is partly
  about spatial arrangement, which a scalar cannot confirm or refute.

## Decision rule, fixed now

**If confirmed:** depth discontinuity **joins orientation and phase as the
third boundary cue** in the composite proposer, **and the measured step size
is recorded as its derivation** — so the constant enters the code already
carrying its provenance, instead of becoming another underived literal for the
conformance scanner to find later.

**If not confirmed:** it does not enter the proposer, and this file records
that it was tried.

## Status

Not yet run. Queued behind the publish revert system, fix A, and the archive
navigator; it depends on no code that is not already written.
