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

### 4.1 RULING (Andrés, 8 Aug 2026): partition before outlining

Using the same outlines for (a) and (b) would be the **"spent as evidence"**
problem of `VALIDATION_PLAN_v1.md` V5(ii) — a proposer fine-tuned on these
outlines scores well against them for reasons unrelated to being right. The
ruling:

**PARTITION BEFORE ANY OUTLINING.**

| | |
|---|---|
| **when** | before the first outline is drawn — **not** after |
| **grain** | **animal level** |
| **split** | **~70 / 30**, release pool / sealed set |
| **record** | the **sealed set is NAMED IN THE CATALOG** |
| **use** | **training and the atlas come from the RELEASE POOL ONLY** |

**Before, because a partition cannot be made afterwards.** Once outlines exist
and someone has looked at them, no subsequent split is blind — the choice of
which animals to seal is made by a person who already knows what is in them.

**Animal level, because outlines within one animal are not independent.** The
same fixation, the same mounting, the same imaging session, the same
staining. Splitting at the ROI level would put cells from one animal on both
sides of the line, and the sealed set would be scoring a proposer on animals
it had already been trained on — leakage that looks like accuracy.

**Named in the catalog, because a sealed set that is not written down is not
sealed.** It becomes whatever is left over at the end, chosen by whoever is
assembling the figure.

At 17 animals this is roughly **12 release / 5 sealed**, wild type first.

**Related and independent:** the DAPI subset queued in
`confocal_census_2026-08-07.md` §7 is held back by construction and is a
second, differently-sourced bridge — nuclei-seeded segmentation there never
sees the stain-free features at all.
