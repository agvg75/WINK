# WINK: Pharynx morphometry — anatomical priors
## Specification amendment — not built yet

Recorded 8 Aug 2026 from Andrés. Applies to `tools/pharynx_morphometry/`.

**Status: recorded, not authorized to build.**

---

## 1. Detection and framing: a parametric bulb–pipe–bulb fit

Detection is **a parametric bulb–pipe–bulb model matched against the z-section
shape SEQUENCE**, not a per-section search for something pharynx-shaped.

What the sequence looks like, and why it is the signal:

- **through the bulbs** — circles waxing then waning across z
- **through the isthmus** — a constant-length, varying-width profile

The organ is identified by how its cross-section *evolves* through the stack.
No single section is diagnostic; the progression is.

**The fit yields two things:** the **organ axis**, and a **per-voxel segment
assignment** (anterior bulb / isthmus / terminal bulb). The segment assignment
is what **feeds wall-thickness-by-segment** — thickness is meaningless without
knowing which part of the organ it was measured in.

---

## 2. Stated requirement: the model must admit deformed organs

**Model tolerance must admit deformed organs, and detection sensitivity is
validated on damaged examples.**

**Why this is a requirement and not a nicety: a detector that finds only
well-formed pharynxes biases against the phenotype.** The deformed pharynx is
the thing being studied. A detector tuned until it cleanly finds healthy
organs will quietly drop exactly the animals the experiment is about, and the
resulting dataset will look clean and be wrong — with the loss invisible,
because the missing animals leave no row behind.

Validation is therefore **on damaged examples**, not on the easy set. A
sensitivity figure measured only on well-formed organs does not describe this
tool's use.

---

## 3. The model finds and frames; geometry measures

**Three roles, kept separate:**

| role | who does it |
|---|---|
| find and frame the organ | the parametric model |
| measure | the geometry metrics |
| **flag** | the model residual |

**The model residual is a FLAG, not a metric.** It says "this organ fits the
model poorly, look at it" — it never becomes a reported measurement of
deformation. Reporting residual as a deformation score would make the number
depend on the model's parameterization rather than on the animal, and would
mean the measurement changes whenever the model is improved.

---

## 4. Related

- **Penetration profile** — the existing per-depth QC record. The bodywall
  flattening module exports its fitted-surface depth map as **the same family
  of record**; see `bodywall_flattening_SPEC.md` §5.
