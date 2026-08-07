# Motion signature classifier: detecting muscle-group activity from pixel motion

Status: **RECONSTRUCTED** — draft for Codex review, revision 3
Date: 6 August 2026
Companion to: `WINK_grant_plan_SPEC.md` (sections 3.1, 3.3, 5.1)
Supersedes: revisions 1 and 2

---

## 0. Provenance of this file — read before reviewing

**The original revision 3 never reached the working machine.** It was
described as placed in `staged\docs\` and was not present there or anywhere
else on disk. This file was reconstructed on instruction so that work could
continue, and it must be reviewed against the original rather than trusted.

| Section | Source |
|---|---|
| 4 (census), 9.4, 9.5 | **Dictated in conversation, 6 Aug 2026.** Should be faithful. |
| 6.1 pharynx row | **Corrected on instruction** — see the correction notice in 6.1. |
| 1, 2, 3, 5, 7, 8, 10, 11 | Carried forward from revision 2 as circulated, renumbered. |
| 9.1–9.3 | Carried forward from revision 2 section 8. |

**Renumbering.** Revision 2 had no census. Inserting it as section 4 shifts
everything after it by one: rev 2's §4 (stage 1) is now §5, its §5 (feasibility)
is now §6 — which is why the anatomical fractions are at **6.1** — its §6
(discriminators) is now §7, and its §8 (validation) is now §9, which is why the
development set is at **9.4**.

Anything below not covered by the table above is reconstruction and may differ
from the original in wording. The numbered claims, thresholds and
non-negotiables are the parts to check hardest.

**What changed in revision 3.** A frequency census was added ahead of the
detectors, as a QC instrument rather than a gate. The pharynx feasibility
fraction was corrected from an axial-length fraction to a width fraction.

**What changed in revision 2.** Revision 1 treated the three readouts as
co-equal and put a hand-run magnification feasibility test in section 5. That
was wrong. Undulation is detected first, body length is measured from it, and
per-readout feasibility is derived from that measurement per recording.

---

## 1. What this is

A single-pass classifier that reads a recording and reports, per readout, how
much usable material it contains and why the rest is unusable.

It answers the question grant plan section 3.1 asks and has no mechanism for:
not "is this recording eligible" but "how many seconds of pumping, crawling,
and defecation does it actually contain, and where the answer is none, is that
because the animal was not performing or because we could not see it."

It is **triage, not measurement.** Its output routes recordings to the real
analysis tools. Enforce this at the schema level: emit `pumping_present`,
`pumping_usable_seconds`, `pumping_confidence`, never `pump_rate`.

---

## 2. Pipeline order

The order is the design. Each stage supplies the prior the next stage needs.

```
Stage 0   Is anything moving at all?
Census    Frequency catalogue, per recording.  QC ONLY - never branched on.
Stage 1   Find undulation. Measure body length in pixels.
Stage 2   Derive per-readout feasibility from measured body length.
Stage 3   Look only for readouts that stage 2 says are recoverable.
Stage 4   Emit per-readout bout budget with cause-attributed gaps.
```

Nothing downstream runs without the anchor from stage 1. A detector that looks
for a 10-pixel radial convergence without first knowing the animal is 200
pixels long is guessing.

The census sits beside the pipeline rather than inside it. It is retained per
recording and read by people; **no production branch may depend on it.**

---

## 3. Stage 0: is anything moving

Compute a temporal variance map before anything else. Cheap, and it splits the
archive into three cases:

- **Nothing changing anywhere.** Empty field, failed acquisition, or a dead or
  absent animal. Terminate here with `not_visible`. Do not proceed.
- **Motion present.** Proceed.
- **Global motion only** (uniform across the frame): stage drift, illumination
  flicker, or vibration. Flag and attempt correction, since it will otherwise
  contaminate every flow estimate.

This is the earliest not-visible signal and it costs almost nothing.

---

## 4. The frequency census

### 4.1 What it produces

Tile the frame. Compute a spectrum per tile. **Catalogue every peak**, not just
the expected ones:

```
tile_id, tile_bbox, frequency_hz, power, spatial_extent_tiles,
  location_xy, survives_translation_correction, treatment
```

`spatial_extent_tiles` is how many adjacent tiles share the peak — a real
biological rhythm is spatially extended, a compression artifact or a flickering
lamp need not be. `survives_translation_correction` is recorded per peak, not
applied silently, because which peaks die under correction is itself the
finding.

### 4.2 The trap: a spectrum of a moving animal measures passage, not rhythm

**This is the reason the census exists and the reason it must not be branched
on.** A pixel-wise spectrum taken over a moving animal does not measure the
animal's rhythm. A fixed pixel sees the worm **arrive, occupy, and leave**, so
the frequency recovered at that pixel is

```
f ~ 1 / passage_duration        passage_duration ~ body_width / speed
```

which is a function of how fast the animal was going and how wide it is. It has
the units of a rhythm and none of the meaning. It will look like a clean
biological signal, it will shift when the animal speeds up, and it will be
entirely an artifact of translation.

### 4.3 Two required treatments, reported separately

Never merged, never averaged:

1. **Stationary intervals only.** Restrict to intervals where the animal is not
   translating. Passage cannot contaminate what does not move.
2. **Body-centred frame.** Follow the animal and compute the spectrum in its
   own frame, so translation is removed by construction.

**Divergence between the two treatments is diagnostic**, and is the primary
output of the census. A peak present in the fixed frame and absent in the
body-centred frame is passage. A peak present in both is a candidate rhythm. A
peak present only in the body-centred frame is worth looking at, and may be a
tracking artifact rather than biology.

Report both catalogues side by side. Do not emit a merged "best" catalogue;
there is no defensible rule for merging them and the divergence is the
information.

### 4.4 Interpretation: broad peaks are the biological ones

**This inverts the usual instinct and is written down because of that.**

The reflex from instrument spectroscopy is that a sharp narrowband peak is a
real signal and a broad smear is noise. Here it is the other way round:

- **Broad peaks are the biological ones.** Undulation frequency varies with
  speed and with substrate *within a single recording*, so a real body wave
  smears across a band. A worm does not hold a frequency.
- **Sharp narrowband peaks are more likely artifacts.** Mains flicker, camera
  or encoder periodicity, compression group-of-pictures structure, and stage
  vibration are all far more stable than an animal is.

Do not rank peaks by sharpness or by peak power alone. Record bandwidth and let
a person read it.

### 4.5 Defecation will not appear, and its absence means nothing

At roughly 50 s cycles, a five minute recording holds five or six cycles. That
is far too few for a spectral peak to form, so **defecation will be absent from
every census, in every recording, regardless of the animal.**

Its absence is **not evidence about the animal** and must never be reported or
read as such. Defecation is detected by interval statistics on discrete events
(see 7.5), not by spectra. A census row saying nothing near 0.02 Hz is a
statement about the method's resolution and nothing else.

### 4.6 The census samples, it does not traverse

Recordings in the development set run to **108,000 frames**. The census
samples: contiguous windows long enough to resolve the bands of interest,
drawn from several points across the recording, rather than a full traversal.
Record which windows were used and how many frames were actually read, so a
census is reproducible and so its cost is visible.

### 4.7 Status: QC instrument only

The census is **retained per recording and never branched on in production.**
Nothing in stages 1 to 4 may read it. It exists so that a person examining a
surprising result can see what was actually oscillating in the field, and so
that systematic artifacts across the archive become visible. The moment a
production path conditions on a census peak, the passage artifact in 4.2 enters
the measurement.

---

## 5. Stage 1: undulation as the anchor

### 5.1 Why undulation is detected first

It is the largest amplitude, largest spatial extent, and most distinctive of
the three signatures, so it survives poor contrast and low frame rates that
would defeat the others. And it requires no prior: transverse sinusoidal pixel
cycling with a phase gradient travelling along a curve is unlike anything else
in a frame, including debris, drift, and illumination flicker. The travelling
phase is the discriminating feature; a vibrating object oscillates in place
with zero phase gradient.

### 5.2 What stage 1 must produce

```
body_length_px          float, with uncertainty
body_axis               coarse curve or orientation field
anterior_end            candidate, may be null
undulation_present      bool
undulation_frequency    approx., where frame rate supports it
um_per_px               derived, STAGE-DEPENDENT - see 5.5
```

`body_length_px` is the anchor for everything downstream. It carries
uncertainty, and that uncertainty propagates into stage 2.

### 5.3 The stationary animal problem

A stationary animal produces no undulation, and a stationary animal is exactly
when pumping is most visible. **Absence of undulation is not absence of a
worm.**

Fallback when stage 1 finds no undulation but stage 0 found motion: look for
any localised coherent motion, and estimate extent from the moving region
directly. Body length from this route is less reliable and must be marked as
such, which widens the margin in stage 2.

If stage 0 found motion and neither route finds a coherent moving object, that
is a genuinely failed recording. Terminate with `not_visible`.

### 5.4 The foreground rule is not a threshold on intensity

**Established against the development set, 6 August 2026.** These animals are
lit obliquely and cast a **dark shadow alongside the body**. The worm itself is
mid-grey and close to the agar in intensity; the shadow is the darkest thing in
the frame. Every intensity rule tried segmented the shadow and the agar
texture rather than the animal:

| rule | keys on | result on one single-worm frame |
|---|---|---|
| difference from a local illumination median | intensity | **430 components**, largest a tail fragment |
| dark 2nd percentile | intensity | 5 components, largest a 216x137 fragment |
| Otsu on raw | intensity | 26% of the frame; shadow, texture and worm merged |
| relief dipole, `-d/dy` at the body scale | relief amplitude | 7 components, **all agar wrinkles**; the animal is not among them |
| bandpass, sigma 2-14 | spatial scale | 12 components, all 24-73 px fragments |

**None of them found the animal.** The reason is visible in a hand-annotated
frame supplied 6 August 2026 (`5521_cop1524`, midline drawn by eye, head up):

- **The worm is not the darkest thing in the frame, and barely differs from
  the agar in intensity at all.** Every intensity rule is therefore chasing
  either the shadow or unrelated agar.
- **The agar carries broad relief of comparable amplitude to the animal's.** A
  dipole or gradient detector fires on the substrate just as strongly, which is
  why the relief rule returned seven wrinkles and no worm.
- **What the animal does have that the agar does not is fine longitudinal
  texture** - visible cuticle striation along the body - at a scale well below
  the agar's wrinkle scale, together with a body width around 30 px against
  agar features of 100 px and more.

So the discriminating properties are **texture and scale, plus motion** - not
darkness, and not relief amplitude. A rule built on any single frame's
intensity will not work on this set at any threshold.

### 5.4.0 The foreground rule: fine texture, because OP50 is smooth

**The substrate is not agar. It is an OP50 lawn**, which is why there are
tracks at all - worms leave tracks on lawns, not on plain agar - and it is also
where the animals feed, so it is where pumping happens. The lawn has broad
topography but **no fine structure. The animal has cuticle striation.** That
single asymmetry is the whole discriminator:

```
band   = gaussian(f, 1.0) - gaussian(f, 3.0)     # fine structure only
energy = gaussian(|band|, 6.0)                   # local texture energy
mask   = energy >= percentile(energy, 96.5)      # keep the top ~3.5%
mask   = close(mask, ellipse(31))                # link along the body
                                                 # then drop small components
```

Verified against a hand-drawn midline on `5521_cop1524`: this returns **the
whole animal as a single component**, head to tail, following the drawn
midline. The remaining components are small lawn specks and are removed by
area.

**Threshold behaviour**, measured on that frame:

| keep top | close | components | largest | length |
|---|---|---|---|---|
| 1.5% | 21 | 5 | 4,076 px | 143 px — fragments |
| 2.5% | 25 | 2 | 12,938 px | 574 px — most of the body |
| **3.5%** | **31** | **5** | **26,844 px** | **779 px — whole animal** |
| 4.5% | 31 | 8 | 30,579 px | 771 px — whole animal |
| 5.5% | 41 | 12 | 34,224 px | 771 px — whole animal, more specks |

Too tight and the body fragments; too loose and lawn specks multiply while the
animal stays stable. The plateau from 3.5% to 5.5% is the operating range.

**Why the earlier rules failed, in one line each:** intensity rules chase the
shadow, which is darker than the animal; relief rules chase the lawn
topography, which is as strongly relieved as the animal; coarse bandpass
straddles both. Only the fine-texture band contains the animal and not the
lawn.

**Do not port these constants to another set without re-checking.** They
encode the lawn's smoothness and the animal's striation *at this
magnification*. A different magnification moves the striation out of the band.

A length, width or scale derived from any of those is wrong **and looks
entirely reasonable**, which is the failure mode this whole module exists to
prevent. The animal presents as a shadow-and-highlight pair flanking a
mid-grey body, so the body is the region *between* the edges: gradient or
local-contrast based, not threshold based. Where the recording is long and the
animal translates, a temporal median gives clean agar and is available as a
second route — but it recovers body **and shadow together** and does not by
itself solve the problem.

Whatever rule is used, **confirm what was segmented before anything derived
from it is used.** Overlay the mask on raw pixels and look.

### 5.4.1 Illumination geometry of the development set

Established by eye against raw frames from all six recordings, 6 August 2026:

- **A worm is present in every frame.** Absence of a detection on this set is a
  detector failure, not an empty field. Stage 0 should never return `empty`
  here, and if it does that is a bug.
- **The light comes from the top, so the shadow falls BENEATH the worm** — in
  every recording that has one. This is a fixed geometric relationship, not a
  per-frame accident, and it is exploitable: the body is the mid-grey band
  sitting immediately **above** a dark band, and the pair has a known
  orientation. It also explains why an unconstrained intensity rule takes the
  shadow: the shadow is darker than the animal.
- **One recording has no detectable shadow**, because the animal is immersed in
  an OP50 lawn rather than lying on top of it. **The foreground rule must
  therefore not REQUIRE the shadow.** A rule keyed on the body/shadow pair
  will silently fail on that recording while succeeding on the other five,
  which is the worst available failure mode: a per-recording gap that looks
  like biology.

The rule must work in both regimes: use the shadow as corroboration where it
exists, never as a precondition.

### 5.4.2 Bit depth: a 16-bit container holding 8 bits

The TIFFs are `uint16`, which invites the assumption that a conversion to
8 bits discards information. It does not:

| recording | distinct values | effective bits | quantisation step |
|---|---|---|---|
| `41921_cop1367` | 216 | 7.8 | 128 |
| `42821_AG406` | 267 | 8.1 | 128 |
| `52021 food density` | 296 | 8.2 | 4 |

A step of 128 is 8-bit data left-shifted into a 16-bit word. **Converting to
8 bits is lossless on this set**, so the segmentation difficulty in 5.4 is a
choice-of-feature problem and not a quantisation artifact. Do not spend effort
preserving 16-bit precision that was never captured — but do measure the step
before assuming the same of another set.

Measured illumination levels are consistent across the six recordings — median
145 to 155 of 255 — while the dark tail moves considerably, `p1` ranging 66 to
106 and shifting by 20 to 29 counts **within** a single recording. Nothing
clips: maxima sit near 200 of 255. A fixed dark threshold is therefore
unusable across, or even within, a recording.

### 5.5 `um_per_px` from a known adult

Most of the archive carries no calibration metadata. A known animal is the only
ruler in the frame: a day 1 adult is about **1100 um** long, so

```
um_per_px = 1100 / body_length_px
```

> **RETRACTED: 0.45 px/um. Do not resurrect it.** An earlier draft of this
> section gave 0.45 px/um for the development set. That figure was derived
> from a 495 px body length, and the 495 px was the median of a frame census
> **which was withdrawn** — it had measured the shadow, not the animal (5.4).
> A number derived from a withdrawn measurement is withdrawn with it.
>
> This mattered practically: 0.45 was later compared against a live
> measurement and the gap treated as a discrepancy needing explanation. There
> was no discrepancy, because there was only ever one measurement. **A
> withdrawn number propagating forward because something had already been
> built on it** is the same failure as the 14.9:1 aspect ratio, which was also
> a shadow measurement that appeared to confirm an expectation.
>
> When a measurement is withdrawn, walk forward through everything derived
> from it and withdraw that too, in the same edit.

**The current figure is unsettled** — see 9.5.1. Measured scale across the six
frozen recordings spans 1.10 to 1.95 um/px, which is too wide to adopt. Do not
put a number here until that is resolved.

This output is **stage-dependent** and must record which route produced the
length — `undulation`, `coherent_motion`, or `failed` — because the routes are
not equally trustworthy and the scale carries that uncertainty into every
micrometre it converts. It also inherits 5.4 entirely: a scale derived from a
segmented shadow is wrong and plausible.

Implemented as `acquisition_probe.um_per_px_from_adult_length()`.

---

## 6. Stage 2: derived feasibility

### 6.1 The derivation

Anatomical fractions of body length, to be confirmed against curated data
before use:

| structure | fraction | **of what** | notes |
|---|---|---|---|
| pharynx, terminal bulb | **~1/35** | **of body LENGTH, giving a DIAMETER** | see the correction below |
| gut region, pBoc extent | ~1/3 | of body length, axial | |
| whole body | 1 | of body length, axial | |

> **CORRECTION, revision 3.** Revision 2 gave the pharynx as **~1/20 of body
> length** and treated the result as the detectable size. That is an **axial
> length**, and it is the wrong axis. A pump is a contraction **across** the
> bulb, so what has to be resolved is the number of pixels lying **across** the
> structure — its diameter. The axial fraction overestimates detectability by
> roughly twofold.
>
> Worked on the development set: at 0.45 px/um from an 1100 um day 1 adult, the
> terminal bulb is **14 to 16 px across**, not the ~25 px an axial fraction
> implies. That is **marginal, not comfortable**, and the marginal category is
> expected to be populated by this set.
>
> Encoded in `acquisition_check.py` as `GRINDER_MIN_PX = 10` and
> `GRINDER_COMFORTABLE_PX = 25`, with the reasoning beside the numbers so that
> an axial fraction is not reintroduced as a simplification.

**Never express these thresholds in pixels in the code.** They are fractions,
resolved against measured `body_length_px` per recording. This is what makes
the classifier work across an archive with unreliable magnification metadata.

### 6.2 Feasibility is a margin, not a boolean

`body_length_px` has error, so the derived structure size does too. Emit a
margin, not a yes or no:

```
pumping_feasible        recoverable | marginal | not_recoverable
pumping_margin          derived structure px / minimum detectable px
```

`marginal` routes to human review rather than silently into the analysis. This
is a real category and it will be populated; do not collapse it to make the
output tidier.

### 6.3 Two floors, both required

Frame rate and spatial resolution are independent gates. A recording can be
fast enough and too coarse, or coarse enough and too slow.

Frame-rate floors come from `acquisition_check`. Wire the dependency; do not
duplicate the thresholds here. **The pumping frame-rate floor is 30 fps and is
set from pump EVENT DURATION (~150 ms), not from the pump rate via a
samples-per-cycle rule** — pumping is a discrete event, not a waveform. Spatial
floors derive from stage 1 as above.

Grant plan section 5.1's header pass answers the frame-rate half from headers
alone. This module answers the spatial half. Together they give eligibility.

---

## 7. Stage 3: the direction discriminators

Only for readouts stage 2 marked recoverable or marginal.

| readout | motion direction | spatial extent | rate | position |
|---|---|---|---|---|
| pumping | radial, convergent, sums to ~0 | smallest | ~4 to 5 Hz | one end |
| defecation | axial, along body axis | intermediate | ~0.02 Hz | mid-body, sweeping |
| crawling | transverse, travelling phase | whole animal | ~0.5 Hz | whole body |

The primary discriminator is **local flow direction relative to local body
axis**: perpendicular is undulation, parallel is defecation, convergent is
pumping. One computation, three outcomes. Stage 1 supplied the axis.

### 7.1 Direction survives what rate does not

A pump observed at inadequate frame rate is still radial. So the classifier
reports "present, not countable at this frame rate", which is the verdict the
bout budget needs and which a frequency method cannot produce.

### 7.2 Flow quality gate

Optical flow on low-contrast recordings is noise with a direction, which yields
confident nonsense. Compute flow confidence per region and refuse to classify
below threshold.

**Low flow confidence in a region is the not-visible signal** from grant plan
section 3.3. Record it, do not merely act on it.

### 7.3 Translation subtraction

A crawling animal drags every pixel along its path, and the small pharyngeal
signal disappears beneath a large uniform flow. Subtract local mean flow before
classifying.

Expect this to be the fiddliest part of the implementation. Test it explicitly
against a known case rather than assuming it works; a partial subtraction
leaves a directional residue that will look like a real signature. This is the
same artifact the census warns about in 4.2, arriving by a different route.

### 7.4 Orientation tested, not assumed

Pharyngeal motion is small **and** anterior, and that prior removes a class of
false positives. But head versus tail identification is unreliable on messy
data and the pharynx is itself the strongest head cue, so assuming orientation
first is circular.

Test both ends. Report which carried the signal. If neither does, the recording
does not support pumping regardless of orientation.

### 7.5 Defecation uses intervals, not spectra

At ~50 s cycles a five minute recording holds five or six cycles, far too few
for a spectral peak — see 4.5. The pBoc is a discrete visible contraction:
detect events, examine the interval distribution.

### 7.6 Aliasing must be band-gated

Below the pumping frame-rate floor, 4 Hz folds down and can appear inside the
crawling band, producing a confident answer about the wrong readout. Only ask
about bands the frame rate supports.

---

## 8. Output schema

Per recording:

```
recording_id
body_length_px
body_length_uncertainty
body_length_source        undulation | coherent_motion | failed
um_per_px                 derived from a known adult; stage-dependent
stage0_verdict            empty | motion | global_motion_corrected
census_path               pointer to the retained census; NOT read in production
```

Per recording, per readout:

```
readout                    pumping | crawling | defecation
feasible                   recoverable | marginal | not_recoverable
feasibility_margin         float
present                    bool | null      # null where not_recoverable
countable                  bool             # present and both floors cleared
usable_seconds             float
n_bouts                    int
longest_bout_s             float
unusable_not_performing_s  float
unusable_not_visible_s     float
unusable_indeterminate_s   float
confidence                 float
end_carrying_signal        anterior | posterior | null    # pumping only
notes                      free text
```

`unusable_indeterminate_s` is required. Where not-performing cannot be
distinguished from not-visible, abstain. Reuse existing WINK abstain gates.

Note the distinction between `present = false` and `present = null`. False
means looked and found nothing. Null means the recording could not support the
observation. Collapsing these would let coarse recordings masquerade as
non-pumping animals, which is the failure this whole module exists to prevent.

---

## 9. Validation

### 9.1 Do not develop against the legacy human-scored sets

The legacy human-scored datasets (pharyngeal pumping, defecation, swimming
frequency) are held out by default. Developing against them burns them: once
thresholds are tuned until agreement improves, agreement is no longer evidence.
They cannot be regenerated.

### 9.2 Use curated tracking output for development

Recordings where WINK has already produced spine and kinematics with human
correction supply body axis, extent, and timing without touching held-out
scores. They are also the right set for confirming the section 6.1 anatomical
fractions, since spine and outline are already established there.

Split explicitly, in code and not only in this document:

- **Development set**: a named, fixed handful of curated recordings. Not
  expanded when results disappoint.
- **Held-out set**: the legacy human-scored data. Touched once, after
  thresholds are frozen. Report whatever comes out.

### 9.3 What good agreement looks like

The target is not matching a human count; this is triage. The question is
whether it routes correctly: does it flag as containing pumping the recordings
a human scored pumping in, and vice versa.

**False negatives are worse than false positives.** A recording wrongly flagged
as containing pumping costs a human a minute of review. A recording wrongly
flagged as empty is silently dropped and its absence never surfaces.

### 9.4 The development set, frozen

```
L:\05_Proprioception\pezo-1 CRISPR mutants\
```

**Frozen 6 August 2026. Not to be changed when results disappoint.** Day 1
adults, which is what makes 5.5's 1100 um ruler applicable.

Six recordings, all 1024x768 TIFF sequences:

| recording | frames |
|---|---|
| `41921_cop1367` | 107,976 |
| `41921_cop1553` | 10,718 |
| `42821_AG406` | 7,040 |
| `5121_AG405` | 65,793 |
| `pezo CRISPR mutants\5521_cop1524` | 68,406 |
| `CRISPR mutants food density\52021_AG405_a600 0.32` | 7,238 |

**Two properties of this set that must be stated plainly:**

1. **It carries no human pumping scores.** It therefore poses **no held-out
   contamination risk** under 9.1 — developing against it burns nothing. This
   is the reason it is usable as a development set at all.

2. **The "pharynx known resolvable" property does NOT hold for it.** An earlier
   framing held that this set was filmed for pharyngeal pumping and human
   scored, so that the pharynx was known resolvable and any failure would be a
   detector failure rather than a data failure. **That is not true of this
   set.** By 6.1 the terminal bulb here is 14 to 16 px across, which is
   marginal. A pumping failure on this set is therefore **not diagnostic of the
   detector** — it may equally be the data. Do not use it to conclude the
   detector works or does not.

Two further properties recorded from the first inspection: the animals are
**lit obliquely and cast a dark shadow** (see 5.4), and magnification is
moderate rather than high, so a substantial fraction of frames do contain the
whole animal.

### 9.5 First run, before building stage 3

Run the census and stages 0 through 2 alone against the development set. Report,
per recording:

1. **The census peak catalogue, for BOTH treatments** — stationary intervals
   and body-centred — reported side by side, with the divergence between them
   called out. Include bandwidth per peak, and read it per 4.4: broad is
   biological, sharp is suspect. Do not expect defecation to appear (4.5).
2. **The `body_length_px` distribution, with a method breakdown** — how many
   lengths came from `undulation`, how many from `coherent_motion`, how many
   `failed`. A distribution without the breakdown is not interpretable, since
   the two routes have different reliability.
3. **The proportion of frames with the whole animal in view**, per recording.
   Where a recording has none, stage 1 cannot anchor and the calibration has to
   run backwards from bulb size to inferred body length.
4. **The feasibility breakdown** — how many recordings fall in `recoverable`,
   `marginal`, `not_recoverable`, per readout. `marginal` is expected to be
   populated by this set; that is the prediction being tested.

That single output answers the question revision 1 wanted a hand-run test for:
what fraction of the archive can support pumping detection at all. It also
validates the 6.1 anatomical fractions against known spines before anything
depends on them.

**It must not be run until 5.4 is settled.** Every number above derives from a
segmentation, and a segmentation that returns the shadow produces a full set of
plausible wrong answers.

### 9.5.1 First run: what the corrected rule gives, and what it does not

Run 6 August 2026 with the 5.4.0 rule, 30 sampled frames per recording,
lengths conditioned on frames where the animal is fully enclosed.

| recording | n enclosed | length median | length p10-p90 | width | aspect | enclosed |
|---|---|---|---|---|---|---|
| `41921_cop1367` | 24 | 807 | 534-939 | **39.8** | 19.4:1 | 80% |
| `41921_cop1553` | 11 | 702 | 453-1136 | **40.8** | 16.4:1 | 37% |
| `42821_AG406` | 20 | 564 | 392-934 | **38.7** | 13.2:1 | 67% |
| `5121_AG405` | 15 | 997 | 500-1210 | **35.6** | 26.3:1 | 50% |
| `5521_cop1524` | 24 | 739 | 439-936 | **41.2** | 18.4:1 | 80% |
| `52021 food density` | 9 | 587 | 292-1526 | **27.6** | 20.9:1 | 30% |

**WIDTH IS STABLE AND LENGTH IS NOT.** Five of six recordings sit in a 35.6 to
41.2 px band — a 15% spread on a quantity that should be constant for day 1
adults at fixed magnification. That is good evidence that **magnification does
not vary meaningfully across those five**. The food density recording at
27.6 px is the exception and needs its own explanation.

Length, by contrast, spans p10-p90 of roughly 400 to 1200 px **within single
recordings**, a threefold range that cannot be real body-length variation in a
day 1 adult population. So the mask's extent ALONG the body varies frame to
frame while its width does not — texture contrast varies along the animal and
with posture, so the rule sometimes covers the whole body and sometimes part.

**Consequence: length is not yet a usable anchor, and no scale may be set from
it.** Implied scale spans 1.10 to 1.95 um/px across the six, and the spread is
measurement noise rather than magnification. This is why 5.5 carries no number.

**Tested and refuted: short lengths are not partial animals leaving the
frame.** The obvious explanation was that a worm exiting the field measures
short. Measured across 180 frames, the correlation between distance-from-edge
and length is **r = -0.30** — the wrong sign — and objects touching the edge
measure **longer** (844 px) than those clear of it (725 px). Edge contact
inflates length, most likely the 31 px closing bridging the mask into edge
structure. Excluding edge frames is still correct, but for the opposite reason
to the one assumed, and it does not fix the spread: clear of the edge the range
is still 403 to 1119 px.

**What this leaves open**, in priority order:

1. Make length as stable as width — link fragments along the body axis rather
   than relying on a morphological close, or validate the mask's extent against
   a curated spine.
2. Explain the food density recording's narrower width, which may be the OP50
   immersion case from 5.4.1.
3. Only then set the scale, and update what 6.1's fractions resolve to. **The
   fractions themselves do not change** — they are anatomy, not measurement.

---

## 10. Why one module

Three grant-critical outputs from one traversal:

1. **Readout classification** answering grant plan section 5.1.
2. **Bout budget** from section 3.1, the unit the measurement model rests on.
3. **Not-performing versus not-visible split** from section 3.3, which the
   review identified as the most valuable idea in the plan and which has no
   implementation.

Three separate detectors produce the first and neither of the others.

---

## 11. Non-negotiables

- Triage, not measurement. Schema-enforced. No rate leaves this module.
- Spatial thresholds as fractions of measured body length, never pixels — and
  the pharynx fraction resolves to a **diameter**, not an axial length.
- Stage order is not optional. Nothing runs without the stage 1 anchor.
- **Confirm what was segmented before using anything derived from it.**
- The census is QC only. No production path branches on it.
- Census treatments reported separately, never merged. Divergence is the
  finding.
- Broad peaks are biological, sharp peaks are suspect. Do not rank by sharpness.
- Defecation's absence from a census is never evidence about the animal.
- `present = false` and `present = null` never collapse.
- `marginal` is a real feasibility category and routes to human review.
- Flow quality gate before classification, recorded as the not-visible signal.
- Orientation tested both ends, never assumed.
- Frame-rate gating from `acquisition_check`, not duplicated here.
- Development and held-out sets separated in code.
- Abstain where indeterminate. Do not guess to raise coverage.
- Correction logging applies: every overturned verdict captured with the raw
  auto-detected values alongside the human correction.
