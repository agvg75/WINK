# WINK: Confocal Stack Support and 3D Neurite Tracing
## Build specification for Codex

Status: draft, ready for Codex review pass
Author: Andres (Vidal Gadea Lab), drafted with Claude
Depends on: existing WINK Python stack (numpy, scipy, scikit image, opencv, tifffile, matplotlib, tkinter), planned Napari dependency for the volume module

---

## 0. Scope and phasing

This spec covers three deliverables that share one piece of infrastructure.

Phase 0, shared infrastructure: a confocal stack loader. WINK currently has no way to open confocal output directly (CZI, ND2, LIF, or generic multi page OME TIFF with real z and channel axes). This is new.

Phase 1: a 3D neurite tracer built on the loader, modeled on Simple Neurite Tracer's approach (Hessian based tubeness filtering plus shortest path search on the filtered volume), reimplemented natively in Python rather than depending on Fiji.

Phase 2: rewire the existing muscle boundary and volume module (already speced separately, Napari based two surface slab model) to consume Phase 0's loader instead of whatever ad hoc stack reading it currently assumes.

No Java, no Fiji, no Bio Formats bridge is required for any of this. All three confocal formats below have mature pure Python readers already on PyPI.

---

## 1. Confocal stack loader (shared infrastructure)

### 1.1 Supported formats and libraries

| Format | Source systems | Library | Notes |
|---|---|---|---|
| OME TIFF / generic multipage TIFF | Most systems can export this | tifffile (already in stack) | Preferred target format, richest metadata support, no new dependency |
| CZI | Zeiss confocal/LSM | czifile or pylibCZIrw | Pure Python, no JVM |
| ND2 | Nikon | nd2 (Talley Lambert's package) | Pure Python, actively maintained, reads z/c/t axes and calibration directly |
| LIF | Leica | readlif | Pure Python |
| Folder of sequential TIFFs | Any system exporting per slice images | Existing WINK sequential image folder reader, extended to treat the sequence as a z axis rather than a time axis when the user declares it a stack |

Add nd2, czifile, and readlif to the environment installers (Setup_Lab_Tools.bat) alongside the existing pip install list.

### 1.2 Internal data model

Every loader path should normalize to one shape regardless of source format:

```
array: (Z, C, Y, X) numpy array, dtype preserved from source (do not silently downcast bit depth)
metadata: {
    voxel_size_um: (dz, dy, dx) or None if unavailable,
    channel_names: [str, ...] or None,
    channel_wavelengths_nm: [(ex, em), ...] or None,
    objective: str or None,
    bit_depth: int,
    source_format: str,
    source_path: str,
    acquisition_datetime: str or None,
    raw_metadata_blob: dict  # everything the reader could extract, unfiltered, kept for provenance even if WINK doesn't use all of it
}
```

This is the same contract the tracker and morphometry modules already expect from single plane images, just with a Z axis and explicit voxel_size_um instead of a 2D micrometers per pixel scalar.

### 1.3 Metadata and calibration handling

Follow the existing calibration rule from Track one worm: a missing or zero physical calibration is not a silent unknown scale mode, it is an invalid state that stops the load.

Specifically:

Attempt to read dz, dy, dx from format native metadata first (all three target formats expose this).

If any axis is missing, prompt the user for manual entry before the stack can be handed to a downstream module. Do not guess isotropic voxels from dy, dx alone, z spacing on confocal systems is frequently different from lateral pixel size and getting this wrong silently corrupts every downstream length and volume measurement.

Log which values were read from metadata versus manually entered, per stack, as provenance.

### 1.4 Failure modes to handle explicitly

Multi position files (some ND2/CZI exports bundle multiple XY positions or multiple series in one file). Require the user to pick a position/series before proceeding rather than silently loading the first one.

Truncated or corrupted stacks (acquisition interrupted mid capture). Report the expected versus actual frame count from the header and let the user decide whether to proceed with a partial stack.

Bit depth surprises (12 bit data stored in a 16 bit container, which is common on Zeiss and Nikon systems). Report the observed intensity range versus the theoretical range for the declared bit depth so students can catch this during the probe step rather than after analysis.

Very large stacks that do not fit comfortably in memory. Support lazy/memory mapped reading where the underlying library allows it (tifffile and nd2 both support this) so a full whole stack load is not mandatory just to preview or crop.

---

## 2. Neurite 3D tracer module

### 2.1 Biological aim and use when

Trace one neurite's path through a 3D confocal stack without collapsing to a maximum intensity projection first, avoiding the accumulated noise and depth ambiguity that MIP based tracing introduces. Use when a z stack resolves the neurite of interest well enough for a trained observer to follow it plane by plane, and a point to point traced path (not full automated arbor reconstruction) answers the biological question.

This is a manual/semi automated tool, not an auto tracer. Scope is deliberately narrower than SNT's full feature set for a first version: one user identified neurite per trace, human clicks start and end, algorithm proposes the path between them, human accepts or corrects it.

### 2.2 Preprocessing: tubeness filter

Before path search, compute a tube enhancement filter over the 3D volume so the path search has a meaningful cost landscape rather than raw noisy intensity.

Use skimage.filters.frangi or skimage.filters.sato, both support 3D input directly.

Expose sigma range as a user adjustable parameter (a multiplier/range around the expected physical neurite radius, per the lab's existing adaptive parameter design principle, not a raw absolute pixel value) so it stays meaningful across different magnifications.

Cache the filtered volume per stack since it is the expensive step and multiple traces will reuse it.

### 2.3 Interactive tracing UI

**Superseded by what was built (2026-08-03).** This section originally
specified Napari's orthogonal slice viewer. The requirement it was serving -
seeing XY, XZ and YZ at once to place a start or end point - was met with
Tkinter and matplotlib instead (`tools/neurite_viewer.py`), because the
judgement being made is slice by slice and a volume renderer added little
against putting Qt on every station that ever opens a stack.

Two things Napari would have given for free had to be built explicitly, and
both turned out to matter more than any feature in the comparison:
blitting from a decimated display texture (an XY plane is 8.15M pixels), and
an explicit z stretch for the depth panels (at true physical aspect a plane
is 0.35 screen pixels tall - unclickable). See `tools/neurite_viewer_core.py`.

Annotation and tracing were also split: the viewer only writes a sidecar of
marked points, and all measurement is headless, so re-tracing with different
parameters costs no re-marking.

Point placement snaps to the local maximum of the tubeness filtered volume within a small 3D neighborhood of the click, mirroring SNT's cursor snapping behavior, so students do not need pixel perfect clicking.

### 2.4 Path search algorithm

Cost image: reciprocal of the tubeness filtered volume (with a small epsilon added to avoid division by zero in background).

Path search: skimage.graph.route_through_array (Dijkstra based minimum cost path) between the two user selected voxels. This is algorithmically equivalent in outcome to SNT's bidirectional A* for this use case at WINK's typical stack sizes, and it is already reachable through the existing scikit image dependency, no new path search library needed.

Store the path as an ordered list of voxel coordinates plus the corresponding physical coordinates (using voxel_size_um from the loader).

### 2.5 Correction and bounded retrace pattern

Reuse the bounded correction pattern already established in Track one worm's b/e anchor system rather than inventing a new interaction model:

Student can place intermediate anchor points along a proposed path if the automatic path jumps to the wrong branch or a neighboring structure.

Each new anchor splits the trace into independently resolved subpaths between anchors, same all anchor rule as the spine tracker, so a later anchor never gets silently overwritten by an earlier interpolation.

Raw (uncorrected) path and corrected path are both retained, never overwrite the raw automatic proposal in place.

### 2.6 Outputs

Ordered path nodes, voxel and physical coordinates.

Path length in physical units (sum of physical distances between consecutive nodes).

Estimated radius per node (start with a simple approach: local thresholded cross section perpendicular to the path direction at each node; a full circular cross section fit like SNT's can be a later refinement, do not block the first version on this).

Volume estimate from the radius profile.

Overlay image/figure showing the traced path against the original (unfiltered) stack for review, consistent with WINK's overlay QC convention elsewhere.

Full provenance: sigma parameters used, anchor points placed, raw versus corrected path, source stack identity.

### 2.7 Correction logging schema

Extend the same append only JSONL correction log schema already used for sarcomere peak corrections and planned for the flattening/boundary modules. One record per trace, containing at minimum: stack identity, raw auto path nodes, final corrected path nodes, anchor points placed, sigma parameters, timestamp, student identifier if collected. This is the same "enabling future recalibration or a learned tracer later" investment already made elsewhere, no separate design needed.

### 2.8 Known failure modes to document

Path jumps to a brighter neighboring structure (another neurite, autofluorescent gut granule, cuticle) when the true neurite dims or the wrong one is closer to the straight line cost path. This is the primary reason anchors exist, document it plainly rather than tuning sigma to try to make it disappear entirely.

Photobleaching across a long acquisition can make the tubeness filter's response drop over the later portion of a trace, worth flagging as a QC note rather than a bug.

Crowded expression (multiple neurons labeled) increases the odds of the above jump failure. This is the same problem flagged earlier about needing sparse or single cell expression, or a second disambiguating channel, to get clean results, that limitation carries over from the literature review and is not something the path search algorithm can solve on its own.

Anisotropic voxel spacing (z spacing much coarser than xy) can make a true diagonal neurite look artificially segmented between z planes. Report the z to xy spacing ratio as a preflight warning when it is large.

---

## 3. Muscle boundary and volume module: wiring to the shared loader

### 3.1 What changes

Replace whatever stack input path the boundary and volume module currently assumes with Phase 0's loader. The module's own logic (two surface slab model, physical volume from calibration, Napari draggable boundary points, concavity exclusion flags) does not change, this is purely a plumbing change so both modules read confocal data the same way instead of maintaining two separate readers.

### 3.2 What stays the same

Everything already speced for that module: the slab assumption for a gently concave muscle layer, the concavity exclusion flags as structured data, the hardware compatibility check before committing to Napari. None of that is affected by where the stack came from.

The only new requirement is that the module now receives the full metadata dict from Phase 0 (voxel_size_um in particular) rather than whatever ad hoc calibration entry it had before, and should use that as the source of truth for physical volume calculations.

---

## 4. New dependencies to add to Setup_Lab_Tools.bat

```
pip install nd2 czifile readlif
```

No napari. The annotation viewer was built on Tkinter and matplotlib
instead (see section 3), so nothing in Phase 0 or Phase 1 needs Qt, and the
base install stays as light as it was. The volume module spec still assumes
Napari for its own reasons; if that module is built, its dependency is its
own decision to justify, not one inherited from here.

---

## 5. Suggested file layout

Follow existing WINK conventions:

**As planned:**

`tools/confocal_loader.py` (new, shared by both consumers)
`tools/neurite_tracer.py` and `tools/neurite_tracer_tool.py` (new, template on `nonstriated_morphology.py` / `nonstriated_morphology_tool.py` split between logic and Hub facing tool wrapper)
`tools/muscle_boundary_volume.py` (existing spec, modify import to use `confocal_loader`)

**As actually built (2026-08-03).** The plan above is left as written because it
records the intended shape, but two of these names never existed and looking for
them wastes time:

- `tools/confocal_loader.py` — built as planned.
- `tools/neurite_tracer_tool.py` — **never existed.** Rejecting Napari (§2.3)
  split the work three ways instead of two: `tools/neurite_tracer.py` is the
  algorithm core, `tools/neurite_viewer.py` is the Tkinter orthogonal-slice
  annotator that writes a sidecar, and `tools/neurite_trace_runner.py` traces
  headlessly from that sidecar. The two-file logic/wrapper template did not
  survive separating annotation from tracing, because the halves run on
  different machines at different times.
- `tools/muscle_boundary_volume.py` — **still unbuilt**, and its own spec is not
  in `docs/specs/`. This is the remaining Phase 2 work; the loader it is meant
  to import already exists and is in use.

---

## 6. Open questions for Andres before Codex starts

Should the confocal loader also become the standard entry point for the RGBCaMP pipeline's multichannel input, or does that stay on its current Fiji extractor path for now? Not required for this phase, worth deciding before Codex builds something that only half generalizes.

Radius estimation for the neurite tracer: is a simple thresholded cross section acceptable for version one, or is physical radius accuracy important enough from the start to warrant the fuller circular cross section fit up front?

Should multi position CZI/ND2 files auto detect a single position when only one exists, or always prompt, for consistency even when the prompt is trivial?
