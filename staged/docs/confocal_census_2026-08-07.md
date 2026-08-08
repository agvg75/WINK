# Confocal census — what exists, what shape it is, where it lives

Grant plan item 0.2. Run 7 August 2026.
Tools: `tools/confocal_census/find_confocal.py`, `confocal_census.py`
Data: `tools/confocal_census/confocal_census_2026-08-07.csv` (9,872 rows)

---

## 1. Where the data is, and what that does and does not tell us

| storage | confocal files | size | not present on the other share |
|---|---|---|---|
| `L:\` (lab drive) | 1,404 | 942.2 GB | 1,312 files — 558.9 GB |
| `\\SLB122E-01\Vidal-Gadea_lab` (scope PC) | 389 | 1,711.6 GB | 312 files — 1,359.4 GB |

**The scope computer holds nearly twice as much confocal data as the lab
drive**, and only 77 of its 389 files have a counterpart on L. That is worth
knowing for migration planning: the scope share is not a subset of the lab
drive, so a census or a migration that reads only `L:` sees well under half
the Leica data.

> **CORRECTED 7 Aug 2026, and the correction matters more than the finding.**
> An earlier version of this section reported the 1,359.4 GB as data that
> "exists nowhere else" and called it a live risk of loss. **That was wrong.**
> The confocal share is backed up to the same place the L drive is. Andrés is
> taking an independent external copy as well, but not because of this.
>
> **What the census actually compared was two live shares against each other.**
> It had no visibility into any backup system, and none of its inputs could
> have shown one. Redundancy *between two shares* is not the same claim as
> *absence of backup*, and the first does not license the second. The column
> above is now named for what it measures.
>
> The failure was one of scope, not arithmetic: every number was right, and
> the sentence built on them was about a system the tool never looked at.
> A comparison can only ever report on the things compared, and a report
> should name them.

Matching is by filename **and** exact byte count, so cross-share overlap is
under-reported rather than over-reported: a file copied and renamed reads as
two distinct files.

---

## 2. What was acquired

648 `.lif` files opened, **8,446 acquisition series**, in 57 seconds.

| shape | series | z planes |
|---|---|---|
| z-stack | **5,190** | 277,356 |
| single plane | 2,965 | 2,965 |
| timelapse | 291 | 291 |

Stacks run 2 to 1,240 planes, **median 37**. Median z step **0.355 µm** over a
median depth of 18.5 µm, with z:xy anisotropy of 3.3× (p90 4.9×) — ordinary,
well-sampled confocal geometry.

**1,426 series were excluded as derived**, and this matters for any count
quoted from here:

- **767 LIGHTNING deconvolutions** (`Series001_Lng`) — Leica stores the
  deconvolved result as a sibling series in the same file. It is the *same
  recording* as its parent.
- **659 FLIM analysis products** — `Fast Flim`, `Standard Deviation`,
  `FlimDecayTime`, `Pattern Matching Scatter Plot`. Not recordings at all.

One series in six is one of these. The first run of this census reported 3,564
z-stacks on the scope computer; the true figure is 3,077.

---

## 3. Can anything be measured from them

**91.8% carry spatial calibration** (7,754 of 8,446). µm/px runs 0.0078 to
25.83, median 0.180.

The 8.2% without it are mostly the uncalibrated derived planes and a tail of
older acquisitions. A stack without µm/px can still be counted and looked at;
it cannot contribute a distance, a volume, or a neurite length.

---

## 4. What region each stack covers, and what it can resolve

> **REFRAMED 7 Aug 2026.** An earlier version of this section asked "which of
> these are heads" and filtered to stacks under 250 µm. That was the wrong
> question and the filter did real damage: **most stacks contain the whole
> animal**, so head, midbody and tail are all present, and a sub-250 µm filter
> was selecting head-scale *crops* while discarding the whole-animal pool —
> which is the more valuable one, because one stack gives body wall and
> pharyngeal muscle in the same animal in the same acquisition. That is the
> two-tissue within-individual pairing the grant rests on.

### 4.1 The full distribution, all 5,190 acquisition z-stacks

All 5,190 carry a calibrated field of view.

| percentile | field of view |
|---|---|
| p1 | 46 µm |
| p10 | 123 µm |
| p25 | 185 µm |
| **p50** | **217 µm** |
| p75 | 291 µm |
| **p90** | **1,050 µm** |
| p99 | 1,167 µm |
| max | 1,552 µm |

**The distribution is sharply bimodal.** Half the stacks sit near 217 µm and
there is almost nothing between 300 µm and 1,000 µm — then a second cluster at
1,050–1,167 µm, which is one adult animal in one field.

| band | stacks | µm/px | grinder | bulb | pharynx | sarcomere |
|---|---|---|---|---|---|---|
| < 100 µm, sub-head crop | 449 | 0.008–0.605 | 258 px | 1031 px | — | 25.8 px |
| 100–250 µm, region crop | 3,149 | 0.032–0.484 | 111 px | 443 px | — | 11.1 px |
| 250–500 µm, several regions | 590 | 0.071–1.147 | 19.7 px | 79 px | 296 px | 1.97 px |
| 500–900 µm, most of an animal | 439 | 0.071–1.679 | 17.6 px | 70 px | 264 px | 1.76 px |
| **900–1,400 µm, whole adult** | **546** | 0.282–2.279 | **5.2 px** | 21 px | 77 px | **0.52 px** |
| > 1,400 µm, whole with margin | 17 | 0.691–1.515 | 13.2 px | 53 px | 198 px | 1.32 px |

Resolutions are computed at each band's median µm/px against a 10 µm grinder,
40 µm terminal bulb, 150 µm pharynx and 1 µm sarcomere spacing.

### 4.2 The resolution cost is real, and it decides what each pool is for

**Whole-animal pool (≥900 µm): 563 stacks in 90 files**, median **1.94 µm/px**.
- grinder spans **5.2 px — below the 10 px floor** in `acquisition_check`
- terminal bulb 21 px, whole pharynx 77 px
- body wall sarcomere 0.52 px — **not resolved**

**Crop pool (<250 µm): 3,598 stacks in 433 files**, median **0.090 µm/px**.
- grinder 111 px, bulb 444 px, sarcomere 11.1 px — everything resolved

So the two pools serve genuinely different measurements. **Pharyngeal
*geometry* is recoverable from whole-animal stacks — 77 px along the pharynx,
21 px across the terminal bulb is enough for outline, position and gross
shape — but grinder-scale detail and sarcomere striation are not.** Anything
needing the grinder or the striation pattern needs a crop.

The 250–900 µm middle band deserves attention: **1,029 stacks** covering
several regions at ~0.5 µm/px, where the grinder still spans ~18–20 px, above
the floor. That band buys multi-region coverage without losing the grinder.

### 4.3 Z depth: a whole-animal stack does not go all the way through

| pool | median z span | of a 65 µm body diameter |
|---|---|---|
| whole-animal | 43.0 µm | 66% |
| crop | 13.9 µm | 21% |

Neither pool reliably spans the full thickness. For volumetric or
quadrant-complete work this needs checking per file, not assuming.

### 4.4 The pool that actually matters: tiled whole animals

Reading the **series names inside** the files rather than the filenames turned
up a third acquisition mode that neither band above describes:

```
full worm 3_head    518 µm   0.863 µm/px
full worm 3_mid     518 µm   0.863 µm/px
full worm 3_tail    518 µm   0.863 µm/px
```

Three stacks tiled along **one identified animal**. Not a crop, not a
single-field whole-animal stack — whole-animal coverage at crop-like
resolution, with the individual named.

**31 distinct animals have all three regions. 44 more have two.** But the two
sets are not equivalent, and **plane count separates them cleanly**:

Across all 551 region-named stacks, depth is bimodal with an almost empty
middle — **58 stacks at 2–6 planes, 7 at 7–15, 486 at 16 or more**. That gap
is in the data; it is not a threshold anyone chose.

| set | animals | year | person | strain | µm/px | planes | channels |
|---|---|---|---|---|---|---|---|
| **Adina, 217 µm tiles** | **17** | 2024 | Fazyl A | AVG60 | **0.106** | **24–49** | 3 |
| Kiley, 518 µm tiles | 14 | 2020 | Hughes K | N2 | 0.863 | **5** | — |

**The 2024 set is the pairing pool.** `W1_Series001_head_bottom_ventral`,
`W1_Series002_mid`, `W1_Series003_tail` — deep three-channel stacks, one
animal, three regions, 0.106 µm/px (sarcomere at 9.4 px), and the orientation
recorded in the name as well. **That is the two-tissue within-individual
pairing, already acquired, in the dystrophic reporter strain.** 17 animals is
a pilot, not a powered n — but it exists.

The 2020 set is 5 planes per tile at 0.86 µm/px. The same files also hold
`WORM 1` … `WORM 12` at 21–101 planes and 0.569 µm/px, which are **not**
region-labelled. The plain reading — a low-magnification survey of the whole
animal, then deeper stacks of chosen regions — fits, but **it is an inference
about workflow, not a lab guideline.** Nobody was writing these names expecting
a parser to read them, so the census records plane count, field and
magnification, which are measured, and leaves the workflow reading to a person.

**The thin stacks are not written off.** A 5-plane, 0.86 µm/px survey of a
whole animal can still show a missing or disorganised fibre even where it
cannot resolve a sarcomere. Whether it does is an inspection question, and
they stay in the census as their own pool rather than being filtered out.

Counts are deduplicated by filename: `10720_N2_IBD5.lif` is held twice on L
and once on the scope, and keying on the full path counted its 9 animals three
times, inflating 31 complete animals to 54.

### 4.5 Region terms, surveyed before parsing

Same discipline as the dates: measure what is written, then parse.

| term | series | | term | series |
|---|---|---|---|---|
| tail | 259 | | midbody | 89 |
| head | 235 | | anterior | 52 |
| ventral | 229 | | full | 169 |
| mid | 177 | | top / bottom | 108 / 125 |

**Only ~7% of z-stacks name a region at all**, which is consistent with most
stacks being whole-animal: you do not label a region when the frame holds the
whole animal.

Two traps, both encoded in `tools/drive_audit/lab_regions.py`:

- **`back` is not a tail.** It appears 72 times beside `ventral`, `top` and
  `bottom` — these name which *side* of the animal or which end of the stack.
  Mapping it to posterior would have mislabelled 72 stacks.
- **`_` is a word character**, so `\bmid\b` cannot match inside
  `full worm 1_mid`. That detail alone reported *zero* complete animals while
  the examples sat on screen. Everything separates before matching.

Where a region *is* named, the field of view agrees with it: head, midbody and
tail crops all sit at a median 185 µm, and `full`/`whole` sits at 518 µm.

**Orientation is recorded more often than expected**, and usefully:
`W1_Series001_head_bottom_ventral` states region, which side of the coverslip
the animal lay on, and that the ventral surface faces the objective. `ventral`
appears 229 times. For a tissue whose four muscle quadrants are only
interpretable once you know which way up the animal is, that is not incidental
metadata.

### 4.5.1 Note for the motion spec: the pharynx as orientation anchor

The pharynx has stereotyped geometry and is already the registration anchor in
the phalloidin design. It can serve as the **orientation** anchor here too,
which removes the head-versus-tail ambiguity the motion signature spec
currently has to resolve by testing both ends. Worth carrying into that spec
rather than re-deriving it there — the same structure settles both questions,
and it is present in every whole-animal and every head stack by definition.

### 4.6 What is labelled is mostly not knowable from metadata

Not all of these are phalloidin — some are transcriptional reporters marking
other structures. **A `.lif` header records channel count and display colour;
it does not record what was in the sample.** Phalloidin and a GFP reporter
both come back as "one channel, green".

Filenames and series names name a marker only sometimes — `phalloidin` 64,
`GFP` 49, `WGA` 28, `AlexaFluor` 35 across 1,793 filenames. **The two-tissue
pairing claim only holds for stacks that actually label muscle**, so the
marker has to be established per file before the 31 complete animals can be
counted on. That is a bench record question, not a metadata one.

---

## 5. Caveats, so nothing here is read as firmer than it is

- **This census compared two live shares, `L:` and `\\SLB122E-01`.** It read no
  backup catalogue, no snapshot history and no tape index, because it had none
  to read. Nothing here supports any statement about whether a file is backed
  up. See the correction in §1 for what happens when that boundary is crossed.
- **`.lsm`, `.czi` and `.nd2` were counted but not opened** — 1,143 files,
  41 GB, most of it 1,078 Zeiss `.lsm`. No reader for these exists in this
  codebase and guessing at their headers would be worse than reporting them
  unread. The 8,446 series figure therefore covers Leica only.
- **Confocal data exported as TIFF is invisible to this census.** At least one
  such export exists on L (`06.11.25 CONFOCAL_AVG77 ... _t001_ch03_SV.tif`),
  so the true confocal footprint is larger than 942 GB on the L drive.
- **The 2008 row is one ambiguous filename**, not a year. All 63 series come
  from `081021_Nmgp-1-GFP in OH15500.lif` (held in three places). Under the
  lab's YYMMDD convention that reads 21 Oct 2008 — before this lab existed —
  so it is far more likely October 2021 written another way. Do not treat any
  pre-2019 year from this census as real without opening the file.
- **Two files could not be read**, both under `\Aalimah\`:
  `Aalmah  Earth gen 2.lif` and `Project.lif` — a `.lif` marker but no image
  series. Possibly truncated, possibly project-container files.
- **3,935 series have no year in their path** and 4,472 no strain. The
  filename-stamp pass (`parse_filenames.py`) would recover much of the year;
  it has not been pointed at these paths yet.

---

## 6. What this changes

1. **Any tool that reads only `L:` sees under half the Leica data.** The scope
   share is not a subset of the lab drive — 312 of its 389 files are not on L.
   Sweep both, keep `source` as a column. (This replaces an earlier item here
   calling for the scope PC to be backed up; see the correction in §1. It is
   backed up, and the census could not have known either way.)
2. **§5.3 branches on ~3,600 candidate stacks**, with calibration on 92% of
   them, spanning 2019–2025 and concentrated in AVG60, AVG57, N2 and VG03.
   The September decision has data under it.
3. **The scope share is organised by person**, and those folder names resolve
   against the same authority the drive audit uses — 5,112 of 5,206 series got
   a person. It should be swept into `experiment_folders` alongside L, with
   `source` kept as a column, not merged.
4. **The geometry supports volumetric work.** 0.355 µm z steps at 3.3×
   anisotropy is not a limitation to design around.

---

## 7. Queued query (recorded 8 Aug 2026): nuclear channel in Anjelica's stacks

**Question.** Which of Anjelica's confocal stacks carry a **nuclear channel**?
She resolves as a person in `tools/drive_audit/filename_labels_2026-08-07.csv`,
so the subset is addressable.

**Method, and the constraint is the point: check channel count and metadata,
then VERIFY BY LOOKING — not by header alone.** Channel count in a Leica
header records what the acquisition was configured to collect, which is not
the same as what a channel contains. A configured-but-dark channel and a real
DAPI channel are indistinguishable in the header and obvious on screen.

**Why it is worth finding.** Any DAPI subset is **reserved as the
seeded-watershed validation bridge**: nuclei-seeded segmentation on those
stacks is an **independent, near-ground-truth answer** for validating the
**stain-free composite** proposer. Independent, because the seed comes from a
channel the stain-free method never sees.

**Disposition: TAG IN THE CATALOG, DO NOT SPEND ON DEVELOPMENT.** The value
here is as a held-back validation set. A subset that gets used to build the
method cannot afterwards be used to check it.
