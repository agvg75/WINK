# WINK handoff — 6 August 2026, late session

Continues `HANDOFF_2026-08-06_evening.md`, which continues
`L:\10_AGVG LAB\Lab Tools\_session_archive\SESSION_2026-08-06_INDEX.md`.
Written mid-session against the risk of losing it, so the last section is
work in flight rather than finished.

Repo `staged/`, branch `main`, pushed to `https://github.com/agvg75/WINK.git`.

---

## 1. The headline: a foreground rule that works, and why the previous five did not

**Domain knowledge solved it, not tuning.** Andres: *"OP50 is smooth. Worms are
textured."* The substrate is a bacterial lawn — which is also why tracks exist,
since worms leave tracks on lawns and not on plain agar, and why the animals
feed there at all. The lawn has broad topography and no fine structure; the
animal has cuticle striation.

```
band   = gaussian(f, 1.0) - gaussian(f, 3.0)     # fine structure only
energy = gaussian(|band|, 6.0)
mask   = energy >= percentile(energy, 95.5)
mask   = close(mask, ellipse(31)); drop small components
```

Verified against a hand-drawn midline, then against midlines on all six frozen
recordings. **Red traced the animal in every one**, including the five it was
not tuned on.

Five earlier rules failed, all recorded in spec 5.4 with what each keyed on:

| rule | keyed on | result |
|---|---|---|
| difference from local illumination median | intensity | 430 components |
| dark 2nd percentile | intensity | 5 components, fragments |
| Otsu on raw | intensity | 26% of frame, merged |
| relief dipole `-d/dy` | relief amplitude | 7 components, **all agar wrinkles** |
| bandpass sigma 2-14 | spatial scale | 12 fragments |

Intensity rules chase the shadow, which is darker than the animal. Relief rules
chase the lawn, which is as strongly relieved as the animal. Only the fine
band contains the animal and not the lawn.

---

## 2. Lessons that generalise, added to the evening handoff's list

### 2.1 Retract forward — this bit twice more

`0.45 px/um` was derived from a 495 px body length whose census had already
been withdrawn as a shadow measurement. It survived, and was then compared
against a live measurement with the gap treated as a real discrepancy. There
was no discrepancy. Same shape as the earlier 14.9:1.

**Rule, now in spec 5.5: when a measurement is withdrawn, walk forward through
everything derived from it and withdraw that too, in the same edit.**

### 2.2 An absolute constant where a relative one belongs

Three instances in one day:

- `min_area=40, max_area=2500` px in the basal slowing gates.
- A fixed **400 px** floor in `continues_beyond`, which let a lawn speck
  exclude the one animal known to be traced correctly. Now relative to the
  animal already found.
- Grey levels compared against the **16-bit container** rather than the
  measured quantisation step.

Andres's note: worth grepping for other absolute pixel constants in the same
modules. **Not yet done — see section 6.**

### 2.3 A single-frame estimate of a directional property inherits posture

One frame of `41921_cop1367` gave a shadow azimuth of 146 deg at concentration
0.56; twenty-five frames gave **94 deg at 0.86**. A 52 degree error carrying a
consistency figure high enough to look trustworthy.

Generalised in spec 5.4.3 to every directional quantity: sample across
postures, report concentration alongside angle, **never emit a bare bearing**.

**Length has the same exposure by a different route** — a coiled animal
measures short, a stretched one long — which is what section 5 below is about.

### 2.4 Measure the thing, not the container

The "16-bit" TIFFs carry 7.8-10.6 effective bits, with a quantisation step of
128 on some recordings: 8-bit data left-shifted into a 16-bit word. It reaches
the top of the range, so **a maximum-based check sees nothing wrong.**

Audit findings (section 4) and a caution: the step must be measured **per
frame** and pooled by median. Across pooled frames it reads 2 instead of 128,
because separate frames sit at different offsets and their union fills in codes
no single frame contains.

---

## 3. What was committed since the evening handoff

| commit | what |
|---|---|
| `b13eea4` | oblique illumination as a checked requirement; azimuth measured across the six |
| `c19101c` | substrate gate, bit depth audit, single-frame direction rule |
| `05e502b` | substrate gate: fix the measure and the scale |
| `0b5322f` | tip extension, exclusion rather than repair, per-animal substrate note |
| *(pending)* | terminology fix, Codex -> tool-neutral, 8 spec files |

---

## 4. Findings that change how things are measured

### 4.1 Oblique illumination is assay technique, and now a checked requirement

It is chosen for contrast on pumping and defecation, so it is a property of the
**assay**, not the rig on a given day. Azimuth verified across the six:

| recording | date | azimuth | R | contrast |
|---|---|---|---|---|
| 41921_cop1367 | 19 Apr | 94 deg below | 0.86 | 66 |
| 41921_cop1553 | 19 Apr | 92 deg below | 0.89 | 79 |
| **42821_AG406** | 28 Apr | **53 deg below-right** | **0.96** | 34 |
| 5121_AG405 | 1 May | 91 deg below | 0.74 | 57 |
| 5521_cop1524 | 5 May | 75 deg below | 0.90 | 52 |
| 52021_AG405 | 20 May | 99 deg below | 0.83 | 65 |

Ends of the date range agree to **5 degrees across a month**. `42821_AG406` is
genuinely rotated with the *highest* internal consistency of the six, so the
check tests for **a consistent direction, not a particular bearing**.

Documented in `ACQUISITION_STANDARD.md` with the OP50-immersion exception: an
immersed animal casts little shadow under correct lighting, which is to be
recorded rather than relit. The analysis does not depend on the shadow.

### 4.2 Substrate is an eligibility gate, and it was wrong twice

Worms do not pump or defecate without food, so neither readout occurs on plain
agar or in liquid, and neither provides background texture. **The texture rule
needs a lawn and those readouts only happen on a lawn**, so there is no
coverage gap and no preparation-aware selector is needed.

Two wrong versions, both recorded in the code:

- **Wrong measure**: fine divided by coarse energy *inverts* on a textureless
  background, because it has almost no coarse energy either. A worm off food
  scored **148** where lawns scored 17 — the highest of the six went to the one
  recording with no lawn.
- **Wrong scale**: absolute energy at sigma 1-3 is sensor noise, which both
  substrates have. Lawns 1.44-1.64 against 1.24 off food.

Correct: **sigma 6-24**, the lawn's own wrinkle scale, animal masked out.
Lawns 18.3-31.8, off food **5.09**.

Consequence for the schema: a textureless background gives pumping and
defecation `present = null`, not `present = false`.

### 4.3 Declared bit depth audit

Two real cases; most of the codebase normalises by percentiles first and is
safe.

- `cell_calcium.check_recording` derived `levels = 2**bit_depth` from the
  **declared** depth, including the ratiometric-depth warning. Now accepts
  `measured_bits` and tests the floor against the effective depth.
- `confocal_loader` guarded the low-range case (12-bit topping out at 4095) but
  **structurally cannot see the left-shift case**. Now detects it from the code
  step.

`measured_bit_depth()` is the single implementation; `measure_intensity`
delegates to it. The two had already drifted — 1560 usable levels against 512
on the same recording — which is the same defect the audit was looking for.

### 4.4 Tip extension and exclusion

**Tip extension** grows the mask along the body axis while the animal's texture
persists. The stopping band is the **fine** band, sigma 1-3, deliberately not
the sigma 6-24 band the substrate gate uses: the lawn's wrinkles live there, so
extending on that band would walk into the substrate at exactly the tail where
the animal's signal is weakest. Threshold is the background's own fine energy
times 1.6. Extension is recorded per end and **never enters `body_length_px`
silently**.

**Exclusion, not repair.** Verdicts now match annotated ground truth on all six:

| recording | verdict | reason |
|---|---|---|
| 41921_cop1367 | MEASURABLE | — |
| 41921_cop1553 | EXCLUDED | edge |
| **42821_AG406** | **EXCLUDED** | **continues into another component** |
| 5121_AG405 | EXCLUDED | edge |
| 5521_cop1524 | MEASURABLE | — |
| 52021 | EXCLUDED | edge + merged limbs |

`continues_beyond()` was needed because `42821_AG406`'s mask **stops short of
the frame edge**, so the edge rule never fires, and it reported a completely
believable 478 px for a fragment of a mostly out-of-view animal. **It asks
whether there is more animal; the edge rule asks whether the mask reached the
wall. Those come apart exactly when a mask stops short for its own reasons.**

Two self-corrections, both retained rather than deleted:

- An **end-count exclusion nobody asked for**. Swept against known cases, no
  spur-prune length separates them: at prune 45 a clean animal and a known
  fragment both report <=2 ends while an off-frame animal reports 4. **Demoted
  to a diagnostic** rather than removed, so the negative result stays available
  when someone proposes it again.
- The fixed 400 px continuation floor, see 2.2.

---

## 5. WORK IN FLIGHT — the length distribution, and why 6.1 is still held

**Do not set `um_per_px` from what is below.** This is the state at the point
this handoff was written.

Two recordings gave 787 px and 767 px from **single frames**, agreeing within
2.6%. Andres correctly refused that as a basis: both are one posture each, and
length has the same posture exposure as a directional estimate.

So tip extension was applied across 60 frames per recording, sampled across the
whole recording so postures vary, with exclusions applied:

| recording | used | excluded | p50 | p75 | p90 | p95 | IQR as % of median | median ext % | r(ext, straightness) |
|---|---|---|---|---|---|---|---|---|---|
| 41921_cop1367 | 30 | 30 | 906 | 971 | 1016 | 1097 | **44%** | 8.2% | -0.23 |
| 41921_cop1553 | 12 | 48 | 921 | 1056 | 1077 | 1111 | 26% | 6.2% | -0.22 |
| 42821_AG406 | 19 | 41 | 600 | 786 | 917 | 1124 | **46%** | 6.1% | +0.09 |
| 5121_AG405 | 11 | 49 | 843 | 999 | 1087 | 1101 | 21% | 6.1% | -0.02 |
| 5521_cop1524 | 29 | 31 | 728 | 815 | 1015 | 1033 | 23% | 7.7% | -0.19 |
| 52021 food density | 2 | 56 | — | — | — | — | — | — | — |

**Read against Andres's own shoulder criterion**, using p90 to p95 slope as
percent per percentile point:

| recording | p90-p95 slope | shape |
|---|---|---|
| 5121_AG405 | 0.26 %/pt | shoulder |
| 5521_cop1524 | 0.35 %/pt | shoulder |
| 41921_cop1553 | 0.63 %/pt | climbing |
| 41921_cop1367 | 1.59 %/pt | climbing |
| 42821_AG406 | 4.51 %/pt | climbing steeply |

**There is no consistent shoulder.** Two recordings flatten, three keep
climbing. By the criterion as stated, that is evidence the percentile choice
would paper over residual posture dependence rather than sit on a stable value.

Supporting that: **extension correlates negatively with straightness** in three
of five recordings, r about -0.2. Weak, but consistent in sign — extension does
slightly more work on coiled animals, which is the dependence that would ride
into the length.

Within-recording spread is 21% to 46% of the median. The 2.6% agreement between
two single frames sat well inside that, so it was luck.

**Conclusion: 6.1 stays held.** Setting um/px here would be the third
coincidence-driven number of the day.

### 5.1 What is NOT yet done on this

- The **fine percentile curve** (p50 through p100 in steps) was to be computed
  from a per-frame dump. The dump did not write — a patch to the analysis
  script silently failed on its last replacement — so the shoulder table above
  is derived from p50/p75/p90/p95 only. **Re-run and confirm before acting.**
- `body_length_method` should record `percentile_persistent`,
  `coherent_motion`, or `failed`. **Not yet implemented.**
- Spec note that 5.2.1's percentile-and-persistence logic is being applied to
  **traced length after tip extension**, not to the **extent trace** it was
  written for. That is a change from what the section describes and must be
  stated. **Not yet written.**
- **Section 5.2.1 is absent from the reconstructed spec.** The original v3
  never reached this machine and the reconstruction has no 5.2.1; "persistent
  high percentile" appears nowhere. The method is known only from Andres's
  description in conversation.

---

## 6. Open items

**Blocking the scale, in order:**

1. Re-run the per-frame dump and compute the full percentile curve. Decide on
   shoulder evidence, not on a chosen percentile.
2. Implement `body_length_method`.
3. Write the 5.2.1 traced-length-vs-extent note into the spec.
4. Only then revisit 6.1. **The fractions do not change either way** — they are
   anatomy; only what they resolve to depends on the scale.

**Also open:**

- Grep for other absolute pixel constants in the same modules (2.2).
- `52021 food density` yields only 2 measurable frames of 60. It is off food,
  hairpin-postured and frequently edge-touching. It may be unusable for length
  and that should be stated rather than worked around.
- Which recording is the OP50-immersed shadowless one is **still
  unidentified**. `52021` was ruled out — it has a strong shadow, R 0.83.
- Per-animal substrate scoring (spec 5.4.4). The reason is specific: pumping
  stops off food, so an animal leaving the lawn mid-recording produces a
  genuine not-performing stretch that per-frame scoring would read as an
  unexplained gap.
- Section 4 of the motion signature spec — the frequency census — specified,
  not built.
- `L_drive_inventory.csv` counts immediate files only and will undercount n for
  grant plan items 0.1 and 0.2.
- ReagentHub scheduled task (grant plan 0.7).
- `CHANGELOG_v11.56.md:63` still says "the bundled Codex runtime". Left as a
  historical record rather than rewritten; confirm whether to change it.

**Owned by Andres:** SMB mount test (grant plan 0.0); review of the
reconstructed v3 spec against the original, which section 0 is laid out to
support.
