# WINK: Muscle Boundary and Volume
## Build specification for Codex

Phase 2 of `confocal_stack_and_neurite_tracer_spec.md`. That document assumed
this module would be Napari-based and framed the work as rewiring an existing
module onto the shared loader. Neither holds: **Napari was rejected** on
2026-08-03, and no muscle boundary/volume module exists in the tree under any
name. This is therefore a build spec, not a plumbing change, and it is written
against the Tkinter viewer that shipped instead.

---

## 0. Purpose

Measure the physical volume of a body-wall muscle layer from a confocal stack.

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

- interpolate each surface across the lateral extent it was marked over
- volume element = (upper − lower) thickness × voxel area, summed
- convert with `voxel_size_um` from the loader's metadata, never from a value
  entered here

### 3.2 What it must refuse rather than approximate

- **Extrapolation beyond the marked extent.** Volume is reported for the region
  actually bounded. If a surface was marked on three planes of a forty-plane
  stack, say so and report the bounded sub-volume; do not integrate over the
  whole stack because the shape looked simple.
- **Surfaces that cross.** If the lower boundary rises above the upper at any
  sampled point, that is a marking error or a fold, not a negative volume.
  Refuse and name where.
- **A single surface.** Both are required; one surface is not a slab.

### 3.3 Concavity exclusions

The layer is gently concave, and the slab assumption fails where it is not.
Excluded regions are recorded as **structured data, not a note**: polygon, z,
and a reason from a fixed vocabulary plus free text. Excluded volume is reported
separately from included volume so the fraction excluded is visible — a result
that quietly integrated over 40% of the field is not comparable with one that
did not.

---

## 4. Outputs

Beside the stack, sharing its stem:

- `<stack>_muscle_volume.csv` — one row per measured region: included volume
  (µm³), excluded volume, fraction excluded, z range, number of marked planes,
  channel, `voxel_size_um`, and the identity fields.
- `<stack>_muscle_volume_provenance.json` — sidecar path and hash, loader
  version, `voxel_size_um` and where it came from (file metadata vs declared),
  station, timestamp, and the exclusion vocabulary used.

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

`validation_level`: `computational_regression` until measured against something
independent. It should not claim `technical_validation` on synthetic slabs
alone.

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

## 8. Open questions for Andres before Codex starts

1. **Which muscle, and one region or several per stack?** The CSV shape depends
   on whether a stack yields one volume or several named regions.
2. **Exclusion vocabulary** — what are the real reasons a region gets excluded?
   Fixed list plus "unclear", following the pBoc spec's reasoning that a forced
   choice produces invented causes.
3. **Marking density** — is marking every Nth plane acceptable, or must a
   surface be marked on every plane it spans? This decides whether §3.2's
   "bounded extent" rule is the normal case or the exception.
4. **Is there existing hand-measured volume data** to validate against? Without
   it this stays `computational_regression` indefinitely.
5. **Does the earlier separately-speced version exist in your files?** If so its
   decisions should be reconciled with this rather than silently replaced.
