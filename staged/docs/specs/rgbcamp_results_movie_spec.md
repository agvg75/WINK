# WINK: Synchronized Results Movie (RGBCaMP)
## Build specification

Status: draft for review. Not yet placed in `docs/specs/`.

Depends on one change to `tools/rgbcamp/fiji/WormRGBCaMPMap_v1.java` (§2). Every
other input already exists in the exported recording CSV.

---

## 0. Purpose and scope

One recording, rendered as a single movie with four vertically stacked panels
sharing one time cursor:

1. the worm movie, with midline and measurement ROIs overlaid
2. a muscle diagram, each muscle split into three channel sections, tinted by
   that channel's brightness in the current frame, with the segment bend
   printed alongside
3. linear velocity over time
4. a body-curvature kymograph

The point is that a reader sees the calcium, the posture, the locomotion and
the raw pixels *at the same instant*, so the relationship between them is
observed rather than asserted.

**This module measures nothing.** It renders what `run_one.analyse_one()` and
the extractor already produced. If a number appears on screen it came from the
CSV; if it is not in the CSV it does not appear. There is one analysis path in
this toolset and this is not it — the same rule `results_browser.py` follows.

That constraint has a payoff: because nothing is measured, every display choice
is a *render-time* parameter and re-rendering is cheap and safe. See §9.

Uses: lab meeting and conference talks, figure supplements, teaching what a
good versus bad recording looks like, and reviewing a student's completed work
without re-running extraction.

---

## 1. Inputs

### 1.1 Required

| Input | Source |
|---|---|
| recording CSV | the extractor's `SaveDialog` export — one row per (frame, segment, side) |
| image sequence | the tracked stack the student ran on (TIFF sequence or movie) |
| geometry sidecar | **new**, see §2 |

### 1.2 Columns consumed

Nothing here is new. All of it is in the header at `WormRGBCaMPMap_v1.java:3861`.

- time base — `frame`, `time_s`, `fps`, `um_per_px`
- identity — `segment`, `hemisegment`
- calcium — `blue_mean`, `green_mean`, `red_mean`, and `bg_blue`, `bg_green`,
  `bg_red` for background subtraction
- posture — `seg_curv_deg`, `side_curv_label`
- locomotion — `axial_vel_px_s`
- honesty — `body_provenance`, `edge_source`, `coil_flag`, `skip`, `found`,
  `low_evidence`, `len_short_flag`, `len_long_flag`, `self_approach_flag`,
  `src8bit`, `correction_note`

Deliberately **not** consumed: `dorsal_label`, `dorsal_known`, `seg_angle_deg`.
See §4.1 and §4.2 for why.

### 1.3 Refusals

Follow `neurite_trace_runner.py`: name the consequence, not the errno.

- geometry sidecar absent → render panels 2–4 and state on panel 1 that
  overlay geometry was not exported by this run, naming the extractor version
  that would produce it. Do not silently drop the panel.
- sidecar frame count ≠ CSV frame count ≠ image count → refuse, reporting all
  three counts. A sidecar paired with the wrong recording produces a movie that
  looks right and is wrong, which is worse than no movie.
- `src8bit=1` → render, with a permanent caption that absolute intensities are
  8-bit and ratios are the trustworthy quantity.
- `n_seg ≠ 24` → **refuse**, and say why in anatomical terms rather than as an
  unsupported-value error: at 24 each cell is one projected myocyte, which is
  what makes this a muscle diagram; at 12 each segment lumps several
  neighbouring myocytes, so a diagram drawn from it would show cells that do
  not exist and attribute one calcium value to several muscles at once. Name
  the recording's actual `n_seg` and state that re-extracting at 24 is what
  makes it renderable. See §4.1.

---

## 2. Geometry sidecar (extractor change)

`exportReviewRois` currently writes two ROIs per frame — `frame_NNNNN_body` and
`frame_NNNNN_midline_head_to_tail`. The measurement bands from `segPolygon()`
are built for display only (`WormRGBCaMPMap_v1.java:3196`) and lost when the
window closes. Panel 1 needs them.

Add a plain sidecar written in the same export pass, `<base>_geometry.json`:

```
{
  "n_frames": …, "n_seg": …, "n_mid": …,
  "width_scale": …, "muscle_boundary_frac": [ … full array, not sampled … ],
  "frames": [
    {"frame": 1, "found": true, "skip": false,
     "midline": [[x,y], …],
     "outline": [[x,y], …],
     "bands": {"0": {"L": [[x,y]×4], "R": [[x,y]×4]}, … }},
    …
  ]
}
```

Rationale for JSON rather than reading the ROI ZIP from Python: parsing ImageJ
ROI files needs `roifile`, a new dependency on every lab machine for a format
that is already being written from the side that knows the geometry natively.
The ZIP stays as the Fiji-facing artifact; the JSON is the machine-readable one.

`width_scale`, `n_seg` and the **full** `muscle_boundary_frac` array must be
recorded. `boundaryFracString()` currently emits only every `n_seg/8`th
boundary, which is a summary, not a reconstruction.

Size: at ~2×n_seg quads plus midline and outline per frame this is larger than
the ROI ZIP.

**Its own checkbox, checked by default.** Not tied to the ROI export checkbox —
they answer different questions, and someone turning one off should not
silently lose the other. Defaulting on means the common case produces a
complete record without anyone having to know to ask for it; the checkbox
exists for the operator who knows they are short on disk and is choosing
deliberately.

Label it by what is lost, not by what it is: unchecking should read as "no
results movie and no post-hoc ROI review for this recording," because that is
the actual consequence and it is not recoverable without re-running extraction.

---

## 3. Panel 1 — worm and overlay

- the original frame, display-ranged; never the background-subtracted working copy
- midline, head green and tail red, matching the extractor's own colour language
- band ROIs per (segment, side), coloured convex/concave as `segPolygon` does,
  so a reviewer sees the same picture the student saw
- frames where `found=false` or `skip=true` show the frame with an explicit
  "no geometry this frame" mark, never a silently bare image

---

## 4. Panel 2 — muscle diagram

### 4.1 Construction and layout

Drawn procedurally in matplotlib. Do not source an anatomical image: the
diagram must be tinted per-frame per-channel, which a raster asset cannot do,
and a schematic generated from `n_seg` stays correct if `n_seg` changes.

**Reference figure:** the lab's existing muscle schematic (`Short paper
Figure 1A`) — a lateral worm outline with 24 numbered spindle-shaped myocytes
in a staggered, interdigitated double band, landmarks for head, pharynx, vulva
and tail, and anterior / midbody / posterior brackets beneath.

That figure shows **one quadrant**. The panel here draws **two opposite
quadrants**, so 48 cells total, since `nSeg = 24` per side
(`WormRGBCaMPMap_v1.java:106`, dialog default line 1342).

Match the reference figure's visual language rather than inventing one:

- worm outline in lateral view, head left, tail right
- cells as staggered interdigitated spindles, not rectangles in a grid — the
  overlap is anatomically real and a student reading the diagram should see the
  same shape they see in the published figure
- landmarks drawn: pharynx, vulva, anus/tail (see §4.1.1 on the vulva)
- anterior / midbody / posterior brackets carried over, so a viewer can say
  where along the animal a wave is without counting cells
- cell numbering visible, matching the reference figure's scheme

Cell fill is the calcium tint (§4.1 below); the outline and landmarks are
static and belong in the blitting background (§8).

### 4.1.1 The vulva landmark

Reproduce the reference figure's treatment exactly: the vulva is drawn as an
**X spanning the full width of the worm**, crossing both bands.

This is deliberate and already correct in the source figure. The vulva is a
ventral structure, so drawing it against one band would implicitly label that
band ventral — an anatomical claim this module refuses to make (§4.1). Spanning
the full width marks its position along the length while associating it with
neither half. Do not "improve" this into a ventral-side marker.

Same rule for pharynx and anus: position along the length, no band attachment.

### 4.1.2 Why one cell is one myocyte

These recordings are Leica **confocal optical sections** — a single plane
through the animal, showing one myocyte layer. That is what makes the
one-cell-one-myocyte mapping true: there is no superimposition of opposing
quadrants, as there would be in a widefield or maximum-intensity projection,
where each visible band would collapse two quadrants into one apparent cell.

This is a constraint on acquisition, not something the CSV records. If this
module is ever pointed at projected or widefield data, every cell in the
diagram silently becomes two myocytes averaged together and the panel's central
claim fails without any error appearing. State the assumption in the panel
caption, and if an acquisition field is ever added upstream, refuse on it.

**24 is not a resolution setting; it is the anatomy.** At 24 per side each cell
corresponds to one projected individual myocyte, which is the whole reason this
panel is a muscle diagram rather than a heatmap of arbitrary bins. The
extractor already builds toward this: `buildMuscleBoundaries()` makes segment
boundaries proportional to the muscle-size profile rather than uniform — body
wall muscles are shorter at the ends and larger in the midbody (PNAS Fig 7;
Palyanov et al. 2018) — *"so each reported segment corresponds to a true
anatomical muscle share of body length."*

The earlier 12-per-side setting was a simplification in which each segment spans
several neighbouring myocytes. A diagram drawn from it would render cells that
do not correspond to real muscles and would attribute a single calcium value to
several of them at once. `n_seg` is still read from the sidecar rather than
assumed — but any value other than 24 is refused (§1.3), not rescaled.

**No anatomical identity is claimed.** The two rows are the two sides as the
tracker labels them, `hemisegment` L and R. They are not asserted to be dorsal
and ventral, and `dorsal_label` / `dorsal_known` are not consumed. Row labels
say "side A / side B" or equivalent — never D/V. Assigning anatomy needs a
vulva seed that is often absent, and a diagram that says "dorsal" when the seed
was missing is a fabrication of exactly the kind §7 exists to prevent.

Each cell is divided into three stacked sections — red, green, blue. Section
fill intensity is that channel's brightness for that (segment, side) in the
current frame, background-subtracted using `bg_*`.

### 4.2 The bend readout — one measurement, two cells

The quantity printed is `seg_curv_deg`, local bend, not `seg_angle_deg`.
`seg_angle_deg` is absolute body angle in the image frame, so it changes for
every cell when the animal merely reorients — unreadable in a diagram.

**`seg_curv_deg` is a per-segment value, not per-side.** `segCurv(f,k)` averages
midline curvature over the segment and takes no side argument
(`WormRGBCaMPMap_v1.java:3819`); it is computed outside the side loop and the
same value is written into both rows of that segment.

It is anatomically true that a bending segment shortens on one side and
lengthens on the other. It is *not* true that this tracker measured both. It
measured midline bend once and labelled the sides by its sign. So the diagram
must not print `+12°` in one cell and `−12°` in its partner: that renders one
number as two independent measurements.

Render it instead as:

- the bend value **once per segment**, centred across the two cells so it
  visibly belongs to the pair rather than to either cell
- the per-side distinction carried by `side_curv_label`
  (`concave`/`convex`/`flat`), which *is* genuine per-side information, drawn
  in the extractor's existing colour language — cyan concave, orange convex, so
  a reviewer reads the diagram the same way they read the overlay
- `flat` (|bend| < 1e-6) styled distinctly from a missing value; a straight worm
  and an untracked frame must not look alike

If per-side asymmetry is later wanted as a measured rather than inferred
quantity, that is a change to the extractor — per-side arc length along each
edge polyline — not something this module can derive.

### 4.3 Normalisation

**Default: per-recording percentile**, per channel, with the mode and its
numeric range printed permanently on the panel.

The alternatives, and what each costs:

- per-recording — best contrast; two movies are not comparable
- fixed absolute — comparable across recordings, often flat-looking
- shared across a named set of recordings — comparable within that set only

Selectable at render time (§9), and recorded in the provenance JSON. The
governing rule is that the scale is never implicit: a viewer must never have to
guess whether a brighter cell means more calcium or a different normalisation.

---

## 5. Panel 3 — velocity

`axial_vel_px_s × um_per_px` → µm/s, with the axis labelled in physical units
and `um_per_px` shown as declared, not verified — `worm_reference.py` exists
because that number is routinely wrong.

Full trace drawn once as static background; a moving cursor is the only thing
redrawn. Sign convention stated on the axis (anterior→posterior = forward),
since `results_browser` derives direction from body-wave sign and not from the
raw sign of `axial_vel_px_s`.

Plausibility band from `worm_reference.py` shaded behind the trace, so a
recording with a wrong declared fps or scale looks wrong here.

---

## 6. Panel 4 — curvature kymograph

`seg_curv_deg` as segment × time, diverging colormap centred at zero, segment
on y (head at top), time on x, with the same cursor as panel 3.

`results_browser.build_kinematics_views()` already builds a full-body curvature
kymograph. Reuse it rather than reimplementing — one analysis path.

---

## 7. Honest rendering

The reason this section exists: a polished movie is the most persuasive artifact
this toolset will produce, and persuasion is exactly what makes hidden
uncertainty dangerous. Everything else in WINK works to surface doubt. This
module must not be where that stops.

- **provenance by opacity** — `body_provenance` of `inferred` renders faint or
  greyed against `measured`; `manual` gets its own distinct treatment. This
  applies to both the panel 1 overlay and the panel 2 cells, so a reviewer
  scanning either sees immediately how much of the frame was actually observed.
- **gaps stay gaps** — `skip`, `found=false`, and NaN are drawn as absence,
  never interpolated across, in every panel including the kymograph
- `coil_flag`, `low_evidence`, `self_approach_flag`, `len_short_flag`,
  `len_long_flag` — a visible per-frame flag strip along the time axis
- `correction_note` — surfaced when present on the current frame
- a legend explaining every one of these appears in the movie itself, not only
  in documentation, because the movie will be watched detached from its folder

If a viewer cannot tell measured from inferred at a glance, the module has
failed regardless of how good it looks.

---

## 8. Performance

Per-frame full redraw of four matplotlib panels will not hold up at a few
thousand frames — the ortho viewer hit exactly this.

- static layer drawn once: axes, diagram outlines, full velocity trace,
  kymograph image, legends
- per-frame redraw limited to: worm frame, overlay geometry, cell fills, bend
  text, two cursors, flag strip
- blit; write frames to `imageio-ffmpeg` as they are produced rather than
  accumulating in memory
- report progress and estimated remaining time; a long render with no feedback
  reads as a hang
- decimation option (every Nth frame) with the factor printed on the movie

---

## 9. Re-rendering and preview

Because the module measures nothing, a second render with different choices is
not a re-analysis — it cannot change any reported quantity, only how it is
drawn. Design for that from the start rather than treating a render as final.

- **All display choices are render-time parameters**: normalisation mode and
  range, decimation, panel 1 image source, which flags are shown, colour
  choices, output size and fonts. None are baked into the export.
- **Parse once, render many.** Reading the CSV, the geometry sidecar and the
  image sequence dominates startup. Cache the parsed result for the session so
  a second render with a different normalisation does not repeat it.
- **Preview mode is required, not optional.** Given §8's render cost, offer a
  preview that renders a handful of representative frames — brightest, dimmest,
  median, one flagged frame — as a still contact sheet. Choosing normalisation
  by looking at four stills beats rendering a full movie twice.
- **Re-render from provenance.** Given a previous movie's provenance JSON, the
  tool reloads those exact settings as the starting point, so "the same but
  absolute scaling" is one change rather than a reconstruction from memory.
- Output filenames must not silently overwrite a previous render with different
  settings. Include a short settings tag, or refuse and say what differs.

---

## 10. Outputs

Beside the CSV, sharing its base name:

- `<base>_results_movie.mp4`
- `<base>_results_movie_provenance.json` — source CSV path and hash, geometry
  sidecar path and hash, image source, normalisation mode and range,
  decimation, `n_seg`, tool version, render timestamp
- optional PNG frame stack for figure use

---

## 11. Hub integration

- name: `RGBCaMP results movie`
- section: `Physiology - Calcium and cellular activity`
- kind: `python`, launcher pattern matching `results_browser_launcher.py`
  (file picker, no typed paths, silent-failure guard writing a log beside the
  script and a message box)
- `validation_level`: `technical_validation` — it renders validated numbers and
  introduces no new computation
- `requires`: declared fps and scale; geometry sidecar from extractor ≥ the
  version that adds §2

---

## 12. Non-goals

- no between-animal, genotype or isoform comparison — same deferral as
  `results_browser`, and for the same reason
- no anatomical dorsal/ventral assignment (§4.1)
- no re-analysis, no re-tracking, no parameter fitting
- not a replacement for the browser: that is for reading numbers, this is for
  seeing them in time
- no editing of geometry; corrections happen in the extractor

---

## 13. Open questions for Andres before the build starts

1. ~~Normalisation default~~ — resolved: per-recording, selectable at render
   time (§4.3, §9).
2. ~~Dorsal/ventral~~ — resolved: no anatomical identity, alternating sides
   only (§4.1).
3. ~~Angle inside the cell~~ — resolved: local bend `seg_curv_deg`, printed
   once per segment (§4.2).
4. ~~Sidecar default~~ — resolved: its own checkbox, checked by default,
   labelled by what unchecking costs (§2).
5. **Panel 1 source** — the DIC stack, the fluorescence channels, or a toggle?
8. ~~What one drawn cell represents~~ — resolved: one cell is one myocyte.
   These are Leica confocal optical sections, a single plane through one
   myocyte layer, so opposing quadrants are not superimposed as they would be
   in a projection (§4.1.2).
9. ~~Landmark geometry~~ — resolved: procedural. A working generator exists
   (`draw_schematic.py`), building cell boundaries from
   `buildMuscleBoundaries()` so drawn sizes are the measured segment sizes and
   the diagram follows any change to `n_seg` or the profile. Pharynx ends with
   myocyte 7 and lands at 24.5% of body length; vulva drawn at 50%, which the
   profile puts exactly on the cell 12/13 boundary.

   **Second use:** this replaces `tools/morphology/myocyte schematic.jpg`, the
   static image behind "Show myocyte numbering schematic" in the myocyte
   morphometry tool. One generator, two consumers, and the numbering can no
   longer drift out of step with the segmentation the tools actually use.
6. **Audience** — if this is primarily for talks, aspect ratio and font sizes
   should be fixed for projection rather than inherited from figure defaults.
7. ~~Older recordings~~ — resolved: refuse anything other than 24 per side. 24
   maps to projected individual myocytes; 12 lumps neighbours (§1.3, §4.1).
