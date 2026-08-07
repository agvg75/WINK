# WINK: Muscle Boundary and Volume
## Build specification

Phase 2 of `confocal_stack_and_neurite_tracer_spec.md`. That document assumed
this module would be Napari-based and framed the work as rewiring an existing
module onto the shared loader. Neither holds: **Napari was rejected** on
2026-08-03, and no muscle boundary/volume module exists in the tree under any
name. This is therefore a build spec, not a plumbing change, and it is written
against the Tkinter viewer that shipped instead.

---

## 0. Purpose

Measure the physical volume of body-wall muscle regions from a confocal stack,
and produce the mask that marking them implies.

**Several regions per stack**, not one: a stack yields multiple named regions,
each with its own volume row. The student names them.

The layer is a gently concave sheet, not a solid block, so volume is taken
between two surfaces: an upper and a lower boundary marked through the stack.
A student marks boundary points; the volume is arithmetic over those points and
the stack's own voxel size.

**What this module must not become:** a second confocal reader, a second
calibration source, or a second place where micrometres are derived. It
consumes `tools/confocal_loader.py`'s `(Z, C, Y, X)` array and metadata dict,
and `voxel_size_um` from that dict is the ONLY source of physical scale.

---

## 1. Why Napari is not used, since the earlier spec says it is

The confocal spec (§2.3, and nine other mentions) specified Napari for the
viewer. It was evaluated and rejected: it would have put Qt on every machine
that ever opens a stack, `Setup_Lab_Tools.bat` stays Tkinter-only, and the
judgement being made here is slice-by-slice rather than volumetric. The
"hardware compatibility check before committing to Napari" that spec requires
is moot — `check_station.py`'s viewer tier was removed on 2026-08-04 precisely
because it described a capability nothing implemented.

Everything Napari would have provided is already built and in use in
`tools/neurite_viewer.py`:

- orthogonal XY / XZ / YZ panels over one stack
- blitted redraw from a laterally decimated texture, with clicks mapped back to
  full-resolution coordinates
- explicit z-stretch, because at true physical aspect a z plane is a fraction of
  a screen pixel and unclickable; every stretched panel carries a caption and
  both depth panels share one stretch factor
- contrast handling that does not bury sparse signal

**Reuse it. Do not fork it.** If a boundary-marking need cannot be met by the
existing viewer, extend `neurite_viewer.py` behind a mode flag rather than
copying 600 lines that will then diverge.

---

## 2. Annotation and computation are separate

Follow the split that `neurite_annotation.py` / `neurite_trace_runner.py`
established, for the same reasons:

- **Marking** is slow human judgement and needs a screen.
- **Volume** is cheap arithmetic and must run anywhere, unattended, and be
  re-runnable months later without anyone re-marking.

So marking writes a **sidecar** beside the stack, and a headless runner computes
volume from it. A parameter change then costs a re-run, not a re-marking. This
is also what keeps the module usable on stations that never got a viewer.

### 2.1 Sidecar

Mirror `neurite_annotation.py`: same identity check, same refusal style.

```
{
  "stack_identity": {...},          # as stack_identity(): path, series, shape,
                                    # voxel_size_um - so a sidecar cannot be
                                    # silently applied to a different stack
  "channel": int,
  "boundaries": [
    {"surface": "upper"|"lower",
     "z": int,
     "points": [[x, y], ...]}       # full-resolution stack coordinates
  ],
  "exclusions": [
    {"z": int, "polygon": [[x, y], ...], "reason": str}
  ],
  "station": str, "saved_at": str
}
```

Reuse `stack_identity()` and the strict-load behaviour verbatim. A sidecar
paired with the wrong stack must be refused naming the consequence — wrong
lengths, wrong volume — not "file not found".

---

## 3. The slab model

### 3.1 What is computed

For each marked z plane, the two boundary point sets define an upper and lower
surface. Volume is the integral between them over the marked extent:

- interpolate each surface between marked planes and across the lateral extent
  it was marked over. Interpolation is core, not a fallback: marking is sparse
  by design (§3.2), so interpolation quality determines the result and the
  method used must be named on the output rather than left implicit
- volume element = (upper − lower) thickness × voxel area, summed
- convert with `voxel_size_um` from the loader's metadata, never from a value
  entered here

### 3.2 What it must refuse rather than approximate

- **Extrapolation beyond the marked extent.** Volume is reported for the region
  actually bounded, never beyond the outermost marked plane.

  Note this is the NORMAL case, not a warning. Marking is deliberately sparse:
  the student marks the inflection points of the structure and the module
  interpolates between them, which is what keeps the work proportionate to the
  shape rather than to the number of planes. So "measured over the marked
  extent" is a routine statement on every result, not an exception report.
  What must still be refused is integrating OUTSIDE that extent because the
  shape looked simple.
- **Surfaces that cross.** If the lower boundary rises above the upper at any
  sampled point, that is a marking error or a fold, not a negative volume.
  Refuse and name where.
- **A single surface.** Both are required; one surface is not a slab.

### 3.3 Exclusions

Exclusions here are **anatomical, not defect-driven**. A worm is a cylinder and
the muscle occupies one layer of it, but a stack images the whole cylinder — so
structures above and below the muscle layer are imported into the field and
contaminate it. Excluding them is normal practice, not an admission that
something went wrong.

Fixed vocabulary, from how the marking is actually used:

| reason | what it excludes |
|---|---|
| `out_of_layer_above` | structure above the muscle layer |
| `out_of_layer_below` | structure below it |
| `pharynx` | the pharynx and the structures around it, at the centre of the worm |
| `neuron` | neurons, which sit between muscle and pharynx |
| `other_structure` | anything else identifiable, with free text |
| `unclear` | the student cannot tell — always available |

`unclear` is not optional. A person required to choose a reason will supply one,
and invented reasons are worse than none because they look like data.

Exclusions are recorded as structured data — polygon, z, reason, optional note —
never as a free-text remark. Excluded volume is reported separately from
included volume so the fraction excluded is visible: a result that quietly
integrated over 40% of the field is not comparable with one that did not.

### 3.4 The mask is a first-class output, not a by-product

Marking the muscle layer is also how the neurons underneath become resolvable —
removing the muscle is what reveals what is sandwiched between it and the
pharynx. So the boundaries define a **mask**, and that mask is useful to tools
that have nothing to do with volume.

Export it (§4). Specifically, it is the natural input to
`tools/neurite_viewer.py` / `neurite_trace_runner.py`: a stack with muscle
excluded is the stack in which a neurite can actually be followed. Do not bury
this inside the volume computation.

---

## 4. Outputs

Beside the stack, sharing its stem:

- `<stack>_muscle_volume.csv` — one row per measured region: included volume
  (µm³), excluded volume, fraction excluded, z range, number of marked planes,
  channel, `voxel_size_um`, and the identity fields.
- `<stack>_muscle_mask.tif` — the mask implied by the boundaries, per region,
  with exclusions applied. A first-class output (§3.4): a stack with muscle
  removed is the stack in which the neurons beneath can be resolved, so this
  feeds `neurite_viewer.py` / `neurite_trace_runner.py` directly.
- `<stack>_muscle_volume_provenance.json` — sidecar path and hash, loader
  version, `voxel_size_um` and where it came from (file metadata vs declared),
  interpolation method, station, timestamp, and the exclusion vocabulary used.

**`voxel_size_um` provenance is not optional.** Volume scales as the cube of
lateral scale and linearly in z; a wrong or defaulted voxel size is wrong by a
large factor and looks entirely plausible. If the loader marked it as assumed
rather than read from the file, that must appear in the CSV, not only the JSON.

---

## 5. Hub integration

Two entries, matching the neurite pattern:

- **Mark muscle boundaries** — the viewer. `requires` a confocal stack.
- **Measure marked muscle volume** — headless. `requires` a stack and its
  sidecar; runs on any station.

`validation_level`: **`computational_regression`, and it stays there for now.**

No hand-measured muscle volumes exist to compare against, because no tool has
been able to produce them - this is the first. So the tests can show the
arithmetic is correct on shapes of known volume, which is worth having, but
nothing yet shows the METHOD returns true volumes for real muscle. Those are
different claims and only the first is currently supported.

**How the ceiling actually lifts, which is not by waiting.** A 3D muscle volume
cannot realistically be measured by hand, so there is no prior ground truth and
there never could have been: the tool has to exist before anything can be
curated. Human stays in the loop, and validation is built from use rather than
found beforehand.

That gives this module a window it can lose silently. **Every mark made today is
uncontaminated**, because the student marks from scratch with nothing proposed.
The moment auto-detection arrives - and the pharynx is exactly the stereotyped
structure to start with - marking becomes *correcting a proposal*, which
`calibration_ground_truth_pipeline_spec.md` §1 classifies as anchored: tuning
data, not ground truth. The clean set has to be gathered BEFORE the helpful
suggestion is added, not after.

Two things follow, both available now:

- **Record whether anything was proposed.** The intent log captures every action
  already; it needs one field per region distinguishing marked-from-scratch from
  adjusted-from-proposal, so the two can never be pooled by accident later.
- **Independent double marking.** Two students mark the same stack with no
  proposal shown to either. Their agreement is the ceiling on how well ANY
  method can be scored here, it is uncontaminated by construction, and it needs
  no new capability - only the discipline of doing it while marking is still
  unassisted.

The ceiling therefore lifts
when measurements accumulate and can be compared against something independent -
a second method, a second scorer, or a phantom of known size. Until then the
label should not be argued upward.

---

## 6. Tests

Synthetic stacks with a **known** volume — a slab of known thickness over a
known area — so the arithmetic is checked against a number rather than itself.
Then, in the spirit of everything else this month:

- a sidecar from a different stack is refused, naming the consequence
- crossing surfaces are refused, naming where
- marking three planes of forty reports a bounded sub-volume and says so
- exclusions change the reported fraction, and excluded volume is reported
  separately rather than folded into the total
- a stack whose `voxel_size_um` was assumed rather than read carries that
  through to the CSV

---

## 7. Non-goals

- no segmentation: boundaries are marked, not detected. Automatic detection is a
  later question and would need its own validation against marked ground truth
- no Napari, and no new dependency of any kind
- no second confocal reader and no second calibration path
- not a general 3D volume tool — the slab assumption is specific to a gently
  concave muscle layer and is stated on every output

---

## 8. Answered before the build (2026-08-04)

1. ~~One region or several~~ — **several per stack**, each named by the student,
   one CSV row each (§0).
2. ~~Exclusion vocabulary~~ — **answered, and it reframed the section**.
   Exclusions are anatomical rather than defect-driven: a worm is a cylinder,
   the muscle occupies one layer, and a stack images the whole cylinder, so
   structure above and below is imported and contaminates the field. Vocabulary
   in §3.3, plus `unclear`.
3. ~~Marking density~~ — **sparse and plastic**: the student marks inflection
   points of the structure and the module interpolates between them, keeping
   the work proportionate to the shape rather than to the plane count. This
   makes bounded-extent the normal case (§3.2) and interpolation a core
   component rather than a fallback (§3.1).
4. ~~Hand-measured volumes to validate against~~ — **none exist**, because no
   tool has been able to produce them; this is the first. Validation ceiling is
   stated in §5 rather than left implied.
5. ~~Earlier separately-speced version~~ — **none exists.** The confocal spec's
   reference to one "already speced separately" is stale. Nothing to reconcile.

## 9. Still open

- **Region naming.** Free text, or a fixed list like the myocyte Myo01-24
  scheme? Free text is flexible and unaggregatable; a fixed list is the reverse.
  Not blocking - it can start free-text and tighten once the real names are
  known from use.
- **Interpolation between marked planes.** Linear is the obvious default and the
  honest one. Anything smoother invents curvature between the points a student
  actually judged, which for a structure marked AT its inflection points is
  exactly the information they were being careful about. Recommend linear, name
  it on the output, and revisit only if real stacks show it failing.
