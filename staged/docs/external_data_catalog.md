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

**`n` counts MYOCYTES, not animals** — the study analysed **97 animals (52
crawl, 45 swim) yielding 215 myocytes before outlier removal** (112 crawl, 103
swim), and reports **N = 96–103 animals**.

**EVERY PANEL HAS ITS OWN n.** There is no single per-region sample size, and
taking one legend's numbers for another measure is the error that produced the
correction note below.

| panel | head C/S | mid C/S | tail C/S |
|---|---|---|---|
| **2B area** | 13 / 9 | **18 / 20** | 26 / 15 |
| 2C Feret | 13 / 10 | 18 / 18 | 25 / 15 |
| 2D MinFeret | 13 / 8 | 18 / 20 | 26 / 16 |
| 2E anisotropy | 13 / 9 | 18 / 20 | 22 / 14 |
| 2F circularity | 12 / 10 | 16 / 20 | 25 / 15 |
| 3B sarcomere length | 13 / 10 | 18 / 20 | 26 / 16 |
| 3C sarcomere number | 12 / 10 | **15 / 20** | 25 / 14 |
| 3D sarcomere density | 13 / 10 | 18 / 20 | 22 / 16 |

**SPREAD TYPE IS UNRESOLVED, and this matters more than it looks.** The figure
legends state *"Data are shown as mean±s.e.m."* But recomputing from the
anchor's own source worksheet gives, for mid-body area:

| | crawl | swim |
|---|---|---|
| mean | 1217.2 | 1063.0 |
| **s.d.** | **243.0** | **206.6** |
| s.e.m. | 57.3 | 46.2 |

**The published ±243 and ±207 are the STANDARD DEVIATIONS**, not the s.e.m. the
legend claims. Since s.e.m. = s.d./√n, a comparison made under the wrong
assumption is wrong by ~4.3× here. **Recorded as `spread_type: s.d. (legend
says s.e.m.; recomputation says s.d.)`** — the registry's `spread_type` field
exists for exactly this, and the honest entry names the disagreement rather
than choosing a side.

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

### Correction note — two errors, and the second was mine

**First:** a web summary of the journal page **misattributed the area result
to the head when it is mid-body**. Head and tail were explicitly unaffected. A
region error in an anchor is silent and total.

**Second:** I then declared four of that summary's sample sizes fabricated,
because they were absent from the one figure legend my text search happened to
surface. **They were not fabricated** — they came from the correct per-panel
legends, and what I "corrected" them to (16/20) belongs to *circularity*,
a different panel. My correction was the less accurate of the two.

**Settled by recomputation, not by argument.** With the anchor's own source
worksheet in hand, mid-body area recomputes to crawl n=18 mean 1217.2 and swim
n=20 mean 1063.0 — matching the paper to 0.1 µm² and confirming 18/20.

**What this actually teaches**, and it is not what I first wrote down: **a
published value is identified by its PANEL, not by its measure name.** An `n`
copied from the nearest legend is as wrong as an invented one and looks better
sourced. Recorded in `REFERENCE_REGISTRY_SPEC.md` §7.2, where the incident
originally went in overconfidently and has been rewritten.

**These are targets fixed BEFORE our pipeline measures anything**, which is
what makes them an anchor rather than a comparison chosen afterwards.

### FINALIZED ANCHOR ENTRY (8 Aug 2026)

| field | value |
|---|---|
| `source_document` | **Biology Open PDF**, 10.1242/bio.062371 — sole document of record |
| `location` | per-panel figure legends; see the panel table above |
| `spread_type` | **s.d., per recomputation.** The legends state s.e.m.; the source data say s.d. **Both are recorded; neither is silently chosen.** |
| `unit_of_n` | **myocytes** |
| `lineage` | preprint values **superseded** by the remeasurement; preprint-era files preserved, marked superseded |
| **regenerating source** | the worksheet below, joined to the FILE MASTER LIST |

**TOLERANCES COME FROM THE PER-MYOCYTE DISTRIBUTION, NOT FROM EITHER PRINTED
SPREAD.** The data supersede both. A printed ± is one summary choice made
once; the distribution is the thing that choice was made *from*, and it
answers the question a tolerance actually asks — *how much does a correct
measurement of this quantity vary here?*

Per-myocyte myocyte area (µm²), recomputed from the source worksheet:

| region | condition | n | mean | s.d. | p05 | p25 | p75 | p95 |
|---|---|---|---|---|---|---|---|---|
| head | crawl | 13 | 748.8 | 148.1 | 570.9 | 606.2 | 884.5 | 932.2 |
| head | swim | 10 | 862.0 | 87.2 | 739.2 | 820.6 | 887.7 | 994.0 |
| **mid** | **crawl** | **18** | **1217.2** | **243.0** | 801.6 | 1055.2 | 1350.8 | 1535.7 |
| **mid** | **swim** | **20** | **1063.0** | **206.6** | 775.0 | 887.1 | 1239.2 | 1338.5 |
| tail | crawl | 26 | 741.2 | 88.5 | 605.0 | 679.2 | 792.4 | 886.9 |
| tail | swim | 16 | 739.0 | 238.2 | 453.4 | 557.1 | 876.5 | 1084.4 |

Note what the distribution shows that no ± could: **tail swim is as variable
as mid-body (s.d. 238 on a mean of 739) while tail crawl is the tightest group
in the table (88.5).** A tolerance set from the pooled spread would be far too
loose for one and too tight for the other.

**The regenerating source.** `Muscle_Area_with_averages_2.xlsx` — per-myocyte
rows carrying region, worm ID, regimen and 16 shape measures, each keyed by
its `.lif` filename, which is what joins it to the FILE MASTER LIST and hence
to the 38 acquisitions. It reproduces the published mid-body means to 0.1 µm².

Archived, because it arrived as an upload and uploads do not persist:

```
L:\10_AGVG LAB\Lab Tools\anchors\fazyl_bio062371_Muscle_Area_with_averages_2.xlsx
sha256 9200c072e0607a6348768f0408328c72d8c9d999b81a82b29ebec3f85d07462b
390,955 bytes
```

**Still missing: tracings / ROIs (tier b).** Adina's `Adina_branching paper`
and `Muscle sizes` folders hold TIFF exports and Leica metadata only — no
`.roi`, no `RoiSet.zip`. The outlines behind these numbers have not been
located.

### The anchor's working folder, and the search for the first rater

**`L:\05_Proprioception\Muscle growth paper`** is the paper's working folder,
found while sweeping for Akash Anbu. It holds the **`FILE MASTER LIST.xlsx`**
itself, plus `Sarcomere Number.xlsx`, `I-Band Measurement.xlsx`,
`Branching Number.xlsx`, `Outlier calculation.xlsx`,
`Raw Data and Supporting Information.xlsx`, and
`ANDRES USE THIS\Muscle Area.xlsx`.

**Branching WAS measured**, even though the published paper reports no
branching result — `Branching Number.xlsx` and `Sorted Branching Number.xlsx`
exist. That is prior art for the branching new-measurement candidate, not a
reproduction target.

**Authorship, read from each workbook's own metadata rather than inferred:**

| author | files |
|---|---|
| Fazyl, Adina | Muscle Area, Sarcomere Number, New Sarcomere Width, Raw Data, Sorted Branching, Full Comparison |
| Marchiafava, Danny | **FILE MASTER LIST**, Branching Number, I-Band Measurement, Sorted Sarcomere Number |
| Vidal-Gadea, Andrés | Outlier calculation, multiple regression, working spreadsheet |
| **Akash Anbu** | **none** |

**AKASH'S WORKSHEETS ARE NOT IN THIS FOLDER AS SPREADSHEETS.** The only
artifact bearing his name is **`ANDRES USE THIS\Akash Graphs.JNB`** — a
SigmaPlot notebook (OLE2, 330 KB) whose embedded text names its own data
sources (*"Data source: Sarcomere Number in Akash Graphs"*). **His per-myocyte
numbers are inside that notebook**, in SigmaPlot worksheets that need SigmaPlot
to export. The lab appears to have it — sibling files are `SP 11.0.JNB`.

**Two caveats on the negative result, because absence of evidence is doing
work here:**

- **Office metadata records the account that SAVED a file**, not who measured.
  If Akash worked on a shared login, or his numbers were transcribed into
  Adina's or Danny's sheets, his name would not appear.
- **Two Adina generations exist** — `Muscle Area.xlsx` (23 Jul 2024) and
  `Muscle_Area_with_averages_2.xlsx` (25 Aug 2025), both authored by her. That
  is an **intra-rater** pair, not the human-vs-human comparison, and the two
  differ in structure: the earlier carries `Muscle Number` and a `Special`
  column (*Wavy*, *Slightly Wavy*), the later carries the full 16-measure
  shape descriptor set.

**To unblock the inter-rater deliverable: export the worksheets from
`Akash Graphs.JNB` in SigmaPlot.** That is the whole blocker. Once exported,
the join is per-myocyte on `.lif` + series, both raters against the same
acquisitions, with the drift direction recorded — and it yields the lab's
first measured human-vs-human error distribution, which becomes the reference
floor for automation tolerances.

**When found, Akash's material seals with the anchor**, under the same
circularity logic as Adina's (§7.4 of the registry spec).

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
