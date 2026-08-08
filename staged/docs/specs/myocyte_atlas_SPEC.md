# WINK: Myocyte atlas from outlines
## Build specification — not built yet

Recorded 8 Aug 2026 from Andrés. **Sequenced AFTER the muscle-layer
extractor** — it consumes the flattened layer, so it cannot start earlier.

---

## 1. Outlining UI

Runs **on the flattened layer** (`bodywall_flattening_SPEC.md`), not on raw
stacks. Outlines are drawn in **body-axis + quadrant coordinates**, so a cell
is located by where it sits on the animal rather than by where it landed on
the slide — the same coordinates the flattening module already exports, and
the reason the orientation-on-slide export exists.

Records in the **correction-log format** already used for sarcomere peaks,
neurite traces, and the planned flattening corrections. One schema, extended;
not a fourth log with its own shape.

## 2. Source material

**The 17-animal head/mid/tail pairing pool. Wild type first.**

Wild type first because the priors below are meant to describe the normal
arrangement; fitting them on a mixed pool would bake the phenotype into the
baseline the phenotype is supposed to be measured against.

## 3. The priors fitted from the outlines

Per region and per quadrant:

| prior | |
|---|---|
| count | |
| area | |
| aspect | |
| orientation vs. axis | |
| staggered-pair offsets | |

**The prior operates FLAG-NOT-FORCE, stratified by strain.** It never edits a
proposal into agreement with itself. **Deviations are reported as findings** —
which is the only way a prior can be present without deciding in advance that
the unusual animal is wrong. A forcing prior applied to a mutant would erase
precisely the difference the experiment exists to detect.

## 4. The outlines have two further uses

- **(a) HITL fine-tuning set.** Threshold **100–200 ROIs**, per the Cellpose
  2.0 evidence on how much human-in-the-loop correction a fine-tune needs.
- **(b) Golden ground truth for proposer validation.**

### Flag, raised once and not blocking

**(a) and (b) are the same outlines, and that is the "spent as evidence"
problem** stated in `VALIDATION_PLAN_v1.md` V5(ii): data used to fit a model
cannot also serve as an independent check on it. A proposer fine-tuned on
these outlines will score well against them for reasons that have nothing to
do with being right.

The cheap fix, if wanted: **split the pool before either use** — outline all
17 animals, reserve a named subset that the fine-tune never sees, and validate
only there. It costs nothing at this stage and cannot be added afterwards,
because once a set has been trained on there is no way to un-see it.

**Recorded as instructed either way; this is a note, not a refusal.** Related:
the DAPI subset queued in `confocal_census_2026-08-07.md` §7 is an
*independent* validation bridge and does not have this problem — it is held
back by construction.
