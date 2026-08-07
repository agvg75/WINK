# WINK handoff — the reasoning behind 6 August 2026

Third and final handoff of the day. The other two record **what** was done:

- `HANDOFF_2026-08-06_evening.md` — gates, acquisition standard, GCaMP marks,
  drive audit parser.
- `HANDOFF_2026-08-06_late.md` — foreground rule, oblique illumination,
  substrate gate, tip extension.

**This one records WHY**, because today's chain of corrections was long and
most of the reasoning lived in conversation rather than in the specs. Each
section below is a conclusion that is cheap to overturn by accident and
expensive to rediscover.

---

## 1. Why `0.45 px/um` was withdrawn, and why that matters beyond the number

**The number.** `0.45 px/um` came from dividing 1100 um by a 495 px body
length. That 495 px was the median of a frame census. **The census had already
been withdrawn** — it had measured the animal's *shadow* rather than the animal
(section 2). A figure derived from a withdrawn measurement is withdrawn with
it, and this one was not.

**What it then did.** It survived long enough to be compared against a live
measurement of 771 px, and the 1.56x gap was treated as a real discrepancy
needing an explanation. Three candidate explanations were weighed. **There was
no discrepancy.** There was one measurement and one ghost.

**Why it survived.** A derived number keeps its apparent independence after its
parent dies. Nothing about "0.45 px/um" says "this came from a shadow". And it
is most dangerous when it *agrees* with an expectation — the same day, a body
width measured on a shadow gave 14.9:1 against an expected 15:1, and the
agreement read as confirmation.

**The rule, now in spec 5.5:** when a measurement is withdrawn, walk forward
through everything derived from it and withdraw that too, **in the same edit**.
Not as a follow-up task.

**Current state:** `um_per_px` is unset. Spec 6.1's fractions are unchanged,
because they are anatomy — only what they resolve to depends on the scale.

---

## 2. Why intensity thresholding segments the shadow on this set

**The animals are lit obliquely, deliberately** — it is assay technique for
pumping and defecation, chosen for contrast (spec 5.4.1). The light comes from
the top, so **the shadow falls beneath the animal.**

**The consequence is not obvious and cost five attempts.** The worm body is
mid-grey and close to the lawn in intensity. **The shadow is the darkest thing
in the frame.** So any rule that looks for "the dark object" finds the shadow,
not the animal — and the shadow is a different shape, in a different place,
with a different length.

Every intensity rule failed this way:

| rule | keyed on | result |
|---|---|---|
| difference from local illumination median | intensity | 430 components, largest a tail fragment |
| dark 2nd percentile | intensity | 5 components, all fragments |
| Otsu on raw | intensity | 26% of the frame |
| relief dipole `-d/dy` | relief amplitude | 7 components, **all lawn wrinkles** |
| coarse bandpass sigma 2-14 | spatial scale | 12 fragments |

The relief rule deserves its own note, because it looks like the right idea:
the animal *does* show a bright edge and a dark edge, exactly as expected from
oblique light. But **the lawn has relief of comparable amplitude**, so a
dipole detector fires on the substrate just as hard.

**Every one of these produced lengths, widths and aspect ratios that looked
entirely reasonable.** The failure is invisible in the numbers. It is obvious
the moment the mask is drawn on the raw pixels — which is why "confirm what was
segmented before using anything derived from it" is a non-negotiable in the
spec, and why the shadow-derived 14.9:1 in section 1 was believed for a while.

**What actually works** is fine texture: the lawn is smooth at fine scale and
the animal has cuticle striation. That came from domain knowledge, not from
tuning.

---

## 3. Why the substrate gate uses sigma 6-24 while tip extension uses sigma 1-3

**These two look like they should share a scale. They must not.** They are
asking opposite questions about the same substrate.

| | question | band | why |
|---|---|---|---|
| **substrate gate** | is there a lawn here? | **sigma 6-24** | the lawn's own structure is its wrinkles, which live at this scale. Lawns score 18.3-31.8, a worm off food scores 5.09 |
| **tip extension** | is there still animal here? | **sigma 1-3** | the lawn is *quiet* at this scale and the cuticle is not, so the lawn cannot be mistaken for more animal |

**The failure mode if they were swapped or unified.** Extending on sigma 6-24
would walk the mask straight off the animal and into the lawn — and it would do
so **at the tail, which is exactly where the animal's own texture is weakest
and where the evidence is thinnest.** The extension would look successful and
would be measuring substrate.

Conversely, scoring substrate at sigma 1-3 measures **sensor noise**, which
both substrates have in equal measure. Tried: lawns scored 1.44-1.64 against
1.24 off food, a 25% separation that cannot gate anything. At sigma 6-24 the
same recordings separate four to sixfold.

**So the bands are not tuning parameters. They encode which of the two signals
- lawn wrinkles or cuticle striation - the question is about.** Anyone
"simplifying" these to a shared constant will break both.

A third band exists for completeness: the **foreground rule** also uses
sigma 1-3, for the same reason as tip extension — it is separating animal from
lawn, not lawn from bare agar.

---

## 4. Why two single-frame lengths agreeing within 2.6% is not a validated scale

**The observation.** After tip extension, the two recordings that passed
exclusion gave 787 px and 767 px. Agreement within 2.6% across two independent
recordings looks like convergence on a real quantity.

**Why it is not.** Both were **single frames**. Length carries the same posture
exposure that a directional estimate does (spec 5.4.3): **a coiled animal
traces short, a stretched one long.** One frame samples a posture, not an
animal.

**What the distribution showed.** Sampling 60 frames per recording across the
whole recording, with exclusions applied:

- **Within-recording spread is 21% to 46% of the median.** The 2.6% agreement
  sat well inside the noise of either recording alone. It was luck.
- **No consistent shoulder.** By the falsifiable criterion in spec 5.2.1, three
  of five recordings climb steadily to the maximum with no shoulder — slopes of
  0.63, 1.59 and 4.51 percent per percentile point against 0.26 and 0.35 for
  the two that flattened.
- **Extension correlates with posture.** `r ~ -0.2` between extension fraction
  and straightness in three of five recordings. Weak, but consistent in sign:
  tip extension does more work on coiled animals, which is precisely the
  dependence that would ride into the length.

**Conclusion: 6.1 stays held.** Setting um/px from this would have been the
third coincidence-driven number of the day, after 14.9:1 and 0.45 px/um.

**The general form**, which is the part worth keeping: **two numbers agreeing
is evidence only if the spread of each is smaller than the gap between them.**
Neither agreement here was measured against its own spread until the
distribution was computed, and by then the agreement had already been used to
raise a question about magnification that did not exist.

---

## 5. What would change these conclusions

Stated so they are falsifiable rather than settled:

- **Section 1** would change if a calibration target were measured on this rig.
  Nothing about the shadow argument affects a real calibration.
- **Section 2** would change on a preparation that is not a bacterial lawn.
  The texture rule needs a lawn; it is available exactly where pumping and
  defecation are possible, so there is no coverage gap (spec 5.4.0), but a
  different substrate needs the whole argument re-run.
- **Section 3** would change at a different magnification. The bands encode the
  lawn's wrinkle scale and the cuticle's striation scale **in pixels**, so a
  change of magnification moves both.
- **Section 4** would change if the length distributions developed a shoulder —
  most plausibly after fragment linking improves, since the current spread is
  partly the mask covering variable fractions of the body.

---

## 6. Immediate next step

**Re-run the per-frame dump** (needs L drive access) and compute the full
percentile curve p50-p100. The shoulder table in `HANDOFF_2026-08-06_late.md`
rests on p50/p75/p90/p95 only, because a patch to the analysis script silently
failed to write its per-frame output.

The conclusion is not expected to move — the shoulder evidence and the
posture correlation both already point the same way — but it should be
confirmed rather than assumed, given that assuming is what section 1 is about.

`persistent_length()` is implemented and tested and will consume that dump
directly.
