# External data catalog

The register called for by `docs/specs/VALIDATION_PLAN_v1.md` **V7(c)**: every
external dataset considered as a validation anchor, **with its license and
metadata completeness recorded per candidate**, and — the part that does the
real work — **what it may and may not be used for.**

**A dataset's usefulness is not a property of its quality.** The entries below
include excellent data that would be actively harmful for one purpose and
correct for another, and the distinction is recorded here rather than
rediscovered by whoever reaches for it next.

**Licenses marked *to verify* have not been checked.** They are not assumed
permissive; V7(c) requires the check before use, and recording a guess here
would defeat the register's purpose.

---

## Myocyte / anatomy

### ASR — Li et al. 2024, *Bioinformatics* btae324

| | |
|---|---|
| what | Atlas built on **464 annotated L1 stacks**; **97.7% BWM recognition** |
| kind | **position / nuclei ground truth** |
| license | *to verify* |
| metadata completeness | *to verify* |

**USE FOR:** the **atlas-prior layer** (`myocyte_atlas_SPEC.md` §3), and as
**code templates**.

**DO NOT USE FOR: texture-segmenter training.** Three disqualifiers, each
sufficient on its own — **L1** rather than adult, **nuclear labels** rather
than cell outlines, and **no phalloidin texture**. A texture segmenter trained
here would be learning a different stain on a different animal at a different
stage.

### Kainmueller 558-cell L1 benchmark

| | |
|---|---|
| what | **100 train / 200 test worms** |
| kind | **position / nuclei ground truth** |
| license | *to verify* |
| metadata completeness | *to verify* |

Same permission and same prohibition as ASR above, for the same reasons.

---

## Behaviour (from V7(c))

| candidate | offers | license |
|---|---|---|
| OpenWorm Movement Database (Zenodo) | WCON + Tierpsy features as **reference answers** | *to verify* |
| BBBC010 | live/dead **ground truth** → the paralysis tool | *to verify* |
| CC-BY micropublication video datasets (e.g. Wormtrails, DOI-addressed) | raw video | CC-BY, *to verify per deposit* |

**YouTube is excluded from validation** (V7(d)).

---

## The gap, and what follows from it

**No public adult phalloidin myocyte instance dataset exists.**

This is recorded as a finding, not a complaint: it is why the atlas work has
no external anchor to validate against, and why the DAPI subset queued in
`confocal_census_2026-08-07.md` §7 matters as much as it does — a held-back
independent bridge is the substitute for the public dataset that isn't there.

**Flag for the methods-paper outline: ours would be the first.**

### The sealed set (ruling, 8 Aug 2026)

The 17-animal pairing pool is **partitioned BEFORE any outlining**, at
**animal level**, roughly **70 / 30 release / sealed** — about 12 and 5.
**Training and the atlas use the release pool only.**

**The sealed animals are named here, in this catalog, and this section is
where they go.** A sealed set that is not written down is not sealed; it
becomes whatever happens to be left over, chosen by whoever assembles the
figure. See `docs/specs/myocyte_atlas_SPEC.md` §4.1.

> **Sealed animals: not yet chosen.** To be listed here by ID at partition
> time, before the first outline is drawn.

**Deliverable: a Figshare or Zenodo deposit — wild type + dystrophic.** Worth
planning as a deliverable rather than a by-product, because the deposit's
value depends on decisions made while the data are being produced (what is
recorded alongside each outline, which animals are held back, what the license
will be) and those cannot be retrofitted afterwards.
