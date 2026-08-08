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

## Published anchors — our own deposits and papers

### Figshare 27341877 — our deposit (checked 8 Aug 2026)

| | |
|---|---|
| title | *Characterization of muscle growth and sarcomere branching in the striated musculature of* C. elegans |
| author | Andrés Vidal-Gadea | 
| DOI | **10.6084/m9.figshare.27341877.v1**, 30 Oct 2024 |
| **license** | **CC BY 4.0** — verified, not assumed |
| acquisition | Leica SP8, **63×**, **Lightning deconvolution**; freeze-crack cuticle removal; **phalloidin** f-actin, occasionally **WGA** |
| funding | 2R15AR068583-02 |

**Composition — 180 file entries** (the article record says 217; the files
endpoint enumerates 180, and the discrepancy is recorded rather than resolved
in favour of the more convenient number):

| count | kind |
|---|---|
| 164 | `.jpg` snapshots |
| 12 | `Thumbs.db` — Windows cache files, accidentally deposited |
| 2 | `..._LUT_Blue.png` — a colour lookup applied, not an annotation |
| **1** | `.tif` — `Series001Snapshot1_RAW_ch00.tif` |
| 1 | `Database description.xlsx` — the **FILE MASTER LIST** |

**ARE ANY IMAGES LABELLED OR ANNOTATED? No.** No filename contains label,
annot, mask, outline, trace, ROI or measured; the two PNGs are LUT
renderings. Everything is an **unlabelled projection**. Region information
lives in the *filenames* (`W1_Series001_mid_anterior-left...`) — useful
metadata for atlas region assignment, but not drawn annotation.

**RULE (Andrés, 8 Aug 2026), and it now has almost no exceptions:**

> **Deposited JPGs are valid for OUTLINE TRACING and ATLAS INPUT, and NEVER
> for intensity measurement. Measurement happens on the matched raw stacks.**

JPEG is lossy and the snapshots carry a display LUT; an intensity read from
one measures the export settings as much as the specimen. Geometry survives
that, photometry does not. The single `RAW_ch00.tif` is still a **snapshot**,
not the raw stack, and is not an exception to the rule.

### Deposit ↔ raw source links

The `Database description.xlsx` **names its source `.lif` acquisitions
directly**, so matching needed no filename inference.

| | |
|---|---|
| acquisitions named in the manifest | **38** |
| **matched to raw `.lif` on L / scope share** | **38 of 38** |
| held in more than one place | 13 |
| **held in exactly ONE place** | **25** |
| raw bytes behind the deposit | **0.37 TB** |

Per-file links: **`docs/deposit_27341877_raw_sources.csv`**, with
`identity_basis` recorded per row per navigator spec §6.

**Two things worth acting on:** 25 of the 38 raw sources behind a *published*
deposit exist in only one place; and the deposit contains 12 `Thumbs.db`
files, which are junk that also leaks local folder structure.

**Name collisions here too:** the deposit holds repeated filenames at
different byte sizes (e.g. `W2_Series002_tailSnapshot1_ch00.jpg` twice). Same
lesson as navigator spec §6.1 — a name is not an identity.

### Fazyl et al., *Biology Open* — reproduction targets

**10.1242/bio.062371**, preprint 10.1101/2024.08.30.610496 (v1 Aug 2024, v3
Nov 2025). Fazyl A., Anbu A., Kollbaum S., Vidal-Gadea A. G. —
*Activity-dependent remodeling of muscle architecture during distinct
locomotor behaviours in* C. elegans.

**This is the paper the deposit cites as its accompanying preprint**, so the
"muscle growth / branching" dataset and this paper are **one body of work, not
two independent anchors.** Recorded that way rather than double-counted.

**The version history proves it rather than merely suggesting it** — v1 of the
preprint carried *the deposit's exact title*:

| version | date | title | authors |
|---|---|---|---|
| **v1** | 30 Aug 2024 | *Characterization of muscle growth and sarcomere branching in the striated musculature of* C. elegans | Fazyl, Anbu, Kollbaum, **Conklin, Schroeder**, Vidal-Gadea |
| v2 | 14 May 2025 | *Activity-Dependent Sarcomere Remodeling in* C. elegans *Muscle Correlates with Mechanical Vulnerability in Dystrophy* | same |
| v3 | 18 Nov 2025 | *Activity-dependent remodeling of muscle architecture during distinct locomotor behaviours* | Fazyl, Anbu, Kollbaum, Vidal-Gadea |

Two things to carry: **the author list changed** (Conklin and Schroeder appear
on v1–v2, not on v3 or the published paper), and **v2 framed the work around
dystrophy** — directly relevant to the wt + dystrophic deposit planned in this
catalog. **Counting the deposit and the paper as two anchors would have
double-counted one dataset.**

Full text of v1 and v2 was not retrievable: bioRxiv returned HTTP 429 to every
attempt, including direct PDF download. So **whether the reported values moved
between versions is unverified** — worth knowing, since a number that changed
across versions is a weaker anchor than one that did not.

**Pre-stated reproduction targets** — crawl → swim. **Every value below was
read from the published PDF, not from a summary.** See the correction note
after the table; it matters.

**Spread is mean ± s.e.m. throughout** (stated in the paper). **`n` counts
MYOCYTES, not animals** — the study analysed **97 animals (52 crawl, 45 swim)
yielding 215 myocytes before outlier removal** (112 crawl, 103 swim), and
reports **N = 96–103 animals** per panel.

**Myocyte counts per region:** head **C=12, S=10**; mid **C=16, S=20**; tail
**C=25, S=15**.

| measure | region | crawl | swim | P |
|---|---|---|---|---|
| **cell area (µm²)** | **mid** | **1217 ± 243** | **1063 ± 207** | 0.032 |
| cell area | head, tail | *unaffected* | | |
| length, Feret (µm) | head | 118.2 ± 12.1 | 134.6 ± 8.5 | 0.0006 |
| length | mid | 127.1 | 136.3 | 0.014 |
| length | posterior | 117.0 | 129.8 | 0.0006 |
| width, MinFeret (µm) | mid | 16.0 | 12.8 | <1×10⁻⁶ |
| width | head, tail | *unchanged* | | |
| sarcomere length (µm) | head | 1.62 | 1.43 | 0.003 |
| sarcomere length | mid | 1.85 | 1.49 | <10⁻⁹ |
| sarcomere length | tail | 1.57 | 1.36 | 7×10⁻⁵ |
| sarcomere number | head | **+0.77 per myocyte** | | |
| sarcomere number | mid | **+0.65 per myocyte** | | |
| sarcomere density (µm⁻²) | mid | 0.0066 | 0.0080 | 0.010 |
| area↔sarcomere correlation | anterior | r²=0.33, n=22 | | 0.005 |
| | mid | r²=0.05, n=31 | | ns |
| | posterior | r²=0.10, n=36 | | ns |
| | pooled | crawl r²=0.57, n=52; swim r²=0.36, n=37 | | <0.0003 / <0.0007 |

Headline: **cell area −13%** in mid-body swimmers, with global elongation and
selective mid-body thinning; sarcomere length −0.19 µm head, −0.35 µm mid,
−0.20 µm tail.

**NO BRANCHING TARGET EXISTS.** "Sarcomere branching" appears in the deposit
title and in the preprint's v1 title, but the published paper reports **no
branching measurement** — the only occurrence of the word is a citation to
Højfeldt et al. on human myofibre branch fusion. Anything we measure about
branching is therefore new, not a reproduction.

### Correction note — why these were re-read

A first pass took these numbers from a web summary of the journal page. Read
against the PDF, that summary had **misattributed the area result to the head
when it is mid-body** (head and tail were explicitly unaffected), and had
supplied **sample sizes that do not appear anywhere in the paper** — `n=18/20`
for mid (actually 16/20), `n=26/15` for tail (25/15), `n=15/20` for mid
sarcomere number (16/20), `n=13/8` for width (absent entirely).

Recorded because it is the same failure this project keeps meeting from the
other side: **a plausible number with no derivation behind it.** A
reproduction target carrying a fabricated `n` would have made our own result
look like a mismatch, and the search would have started in our pipeline.

**These are targets fixed BEFORE our pipeline measures anything**, which is
what makes them an anchor rather than a comparison chosen afterwards.

### Second deposit — NOT YET READ

The data-availability statement reads: *"All raw measurements and statistical
outputs are provided as a supplement… Representative imaging stacks and
analysis scripts are available at
https://figshare.com/s/8ea23d743d7c3e5740d0."*

**That is a private share link and returns 403** to both the page and the API.
It is Andrés's own deposit, so it needs one logged-in browser visit to
resolve to an article id and license. Until then its contents, license and
whether it duplicates 27341877 are **unknown, not assumed**.

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
