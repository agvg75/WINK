# WINK: Bodywall flattening (phalloidin)
## Build specification — not built yet

Recorded 8 Aug 2026 from Andrés. Several specs already reference "the planned
flattening module" (batch audit §, calibration ground-truth §, confocal
stack/neurite §); this is that module's spec.

**Status: recorded, not authorized to build.** The domain constraints below
are the reason the obvious implementation is wrong, and they were supplied
before any code exists — which is the point of writing them down now.

---

## 0. The problem

Bodywall muscle stained with phalloidin sits in a **shell** just under the
cuticle of a curved, bent animal. To measure it, the shell must be found and
unrolled. Every naive approach fails for a reason that is anatomical rather
than computational, so each rule below names the anatomy it answers to.

---

## 1. Depth selection is ORIENTED, not generic

**The per-(x,y) depth is the argmax of ORIENTED FIBROUS ENERGY** — structure
tensor coherence, or tubeness — **not a generic focus or intensity metric.**

**Why.** Autofluorescence and debris are often brighter and sharper than the
muscle, and a generic focus metric will select them without hesitation. What
they lack is the **oriented signature**: bodywall fibres are locally parallel
and elongated, gut autofluorescence and dust are not. Selecting on
orientedness discriminates on the property that actually distinguishes signal
from the brightest competing artefact.

**Share the tubeness implementation with the planned neurite tracer**
(`confocal_stack_and_neurite_tracer_spec.md` §2.2). One filter, two callers.
Two independent tubeness implementations would drift, and the second one
written would be the one nobody validated.

---

## 2. The surface is FIT from the animal's geometry, not picked per pixel

> **SUPERSEDED CLAUSE, kept because the reasoning matters.** An earlier
> amendment specified a smooth regularized surface fitted over per-pixel depth
> observations with outlier rejection and a gentle cylindrical curvature
> prior. That is replaced by the rod fit below. The cylindrical prior was
> reaching for the animal's shape indirectly; fitting the rod reaches for it
> directly, **and handles bends natively** instead of treating a bend as
> curvature to be penalized.

**Fit the worm rod first: a bent axis plus a radius profile along it.**
**Shells are concentric inward offsets from that rod.**

Consequences that follow from doing it this way and not the other way:

- **Bends are native, not error.** A bent animal is a bent axis, not a
  surface fit fighting its own smoothness prior.
- **Shell half-thickness is measured per animal**, never assumed from a
  previous one. The band projected is *surface ± thickness*, and **the
  thickness used is recorded** with the result.

---

## 3. Shell selection uses TWO independent criteria

A candidate shell qualifies only on **both**:

1. **oriented fibrous energy** (§1), and
2. **in-layer area dominance of fibrous signal** — the fibrous signal must
   dominate the *area* of that layer, not merely peak somewhere in it.

These fail differently, which is the whole reason for requiring both: a small
intensely oriented artefact passes (1) and fails (2); a diffusely bright layer
passes (2) and fails (1).

**Among qualifying shells, take the SHALLOWEST strong shell, and record the
presence of a second one.** A deep stack legitimately contains both the near
and the far bodywall — two real shells, not one shell and one error. The
second is recorded rather than discarded because its presence is a fact about
the stack that the reader needs.

**A bimodal fibrous-depth profile that does not resolve into shallowest-strong
plus recorded-second takes the abstain path.**

---

## 4. Self-check per stack, threshold pre-stated

For each stack, compute the **distribution of |fibre orientation · surface
normal|**. Fibres lying in the shell are perpendicular to its normal, so this
quantity is near zero when the fit is right and drifts up when the surface has
been fitted to the wrong thing.

**The threshold is stated before the run, not chosen after seeing the
distribution.** **Failing stacks ABSTAIN, and the number is shown** — an
abstention that hides its own statistic teaches the reader nothing and cannot
be argued with.

---

## 5. Exports

| export | why it exists |
|---|---|
| **per-(x,y) depth of the fitted surface** | a QC record, **same family as the pharynx penetration profile** — see `pharynx_morphometry_SPEC.md` |
| **animal orientation on slide** (from shell position relative to the axis) | **joins the bias note.** Quadrants are **reported separately or depth-annotated, NEVER blindly pooled** — pooling dorsal with ventral, or coverslip-side with far-side, averages away the very asymmetry someone will later ask about |
| **the bent axis as a 3D midline / posture record** | the fit already computes it; a posture record is worth more than the intermediate it was derived from |

---

## 6. The establishment UI — myocyte 3D scanner (working name)

**The auto-fit PROPOSES; the person ESTABLISHES.** Both selection criteria of
§3 (oriented energy and area dominance) run first and produce proposed rod and
shell parameters. A live adjustment view is where those become established
values. This is the propose/establish split WINK already uses elsewhere, and
it is what makes the automatic fit safe to have: a proposal that is wrong
costs a dial movement, not a silently wrong dataset.

### 6.1 Layout

| pane | content |
|---|---|
| XZ and YZ projections | the band drawn as curves over each |
| XY top view | |
| in-band projection preview | what the band actually yields |

Dials: **top, bottom, band thickness, curvature extent, axis.**

### 6.2 Requirements

1. **Render the excluded content above and below the band as SEPARATE
   PANES.** The task is boundary-drawing, and **the eye needs both sides** —
   a boundary can only be judged against what it is excluding. Showing the
   band alone shows only the answer, never the evidence for it.
2. **QC numbers update live with the dials** — the fibre ⊥ surface score (§4)
   and the area-dominance fraction (§3). Moving a dial and watching the
   statistic move is what makes the setting an act of measurement rather than
   of taste.
3. **Tier 0 is three orthogonal projections plus sliders, re-rendering on
   release.** Higher tiers **may smooth the interaction and must never change
   the values.** Interaction quality is an affordance; a value that depends on
   which tier the student was running is a defect.
4. **The correction log records (auto-proposed params, established params) per
   stack.** Two uses, both of which need the pair rather than the final value:
   **the deltas feed fitter recalibration**, and **the established surfaces
   become golden ground truth.**
5. **Established params and the module version go in the sidecar**, and
   **downstream projections consume ONLY established surfaces** — never a
   proposal that nobody looked at.

---

## 7. Open

- Threshold value for §4, to be stated before first run.
- Whether the second shell, when present, is measured or only recorded.
