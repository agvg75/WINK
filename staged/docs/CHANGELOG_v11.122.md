# WINK Lab Tools v11.122 — Myocyte morphometry ported to Python, with reviewable fibres

Ports `Myocyte_Morphometry.ijm` to a native Python tool and adds the review
step the macro never had: sarcomere ticks **and** actin fibres can now be seen
and corrected before anything is written.

The Fiji macro remains available as **Myocyte morphometry (Fiji, legacy)** for
reproducing older measurements.

## Validated against the macro's own historical output

Not against synthetic fixtures — against real ROIs, real debug exports, and
real CSV rows from past measurement sessions on disk.

**Cell geometry**, replayed on a real 35-vertex boundary polygon against the
ImageJ row it produced:

| field | this port | real ImageJ row | error |
|---|---|---|---|
| area | 1128.8823 µm² | 1128.9498 | 0.006% |
| perimeter | 244.7216 µm | 244.7285 | 0.003% |
| Feret | 118.9715 µm | 118.9748 | 0.003% |
| MinFeret | 16.8687 µm | 16.8692 | 0.003% |
| major / minor | 100.388 / 14.399 | 100.1602 / 14.3512 | 0.23% / 0.33% |
| circularity | 0.2369 | 0.2369 | 0.01% |
| solidity | 0.9059 | 0.9059 | 0.004% |
| Feret angle | 1.4603° | 1.46 | — |

Three formulas had to be derived rather than taken from the obvious library
call: ImageJ's `Perim.` for a polygon ROI is the polygon's own edge-length sum
(a rasterised estimator was off by >4%), its ellipse fit applies a +1/12
per-axis pixel-discretisation correction (omitting it was off by ~3.5%), and
its Feret angle negates dy because image Y runs downward.

**Sarcomere detection** was checked bit-for-bit against `*_profile.txt` debug
exports the macro itself wrote: same raw profile in, identical peak indices and
data-driven period out — including a 319-sample profile with two real
saturation spikes that the smoothing must suppress rather than count.

`get_profile_band` was checked against the source TIFF: peak sample index
matches exactly, values to <2% after one constant scale factor.

## Fibre review, before saving

Wave detection previously ran at save time, so fibre traces only appeared
**after** a myocyte was already committed — no preview, no correction. It now
runs at review time, with:

- **Relabel** — click a fibre to cycle straight → wavy → low-confidence
- **Delete** — right-click a fibre; for a trace that jumped between two real fibres
- **Draw a missed fibre by hand** — the tracer only ever seeds from detected
  bands, so a fibre it missed could not previously be added at all. Hand-drawn
  fibres are resampled to traced spacing, drawn dashed, and tagged `manual`.
- **Retry tracing** with an adjustable link distance — the knob that decides
  whether the tracer follows one fibre or hops onto its neighbour

New provenance columns: `wave_n_seeded`, `wave_n_manual`, `wave_n_relabelled`,
`wave_link_um`.

**Divergence from the macro, deliberate:** `wave_n_fibers` — and the
`wave_width_fraction` denominator — is now the number of fibres actually
**traced and shown**, not the number of bands seeded. The macro counted seeds
whose trace was too short to use in that denominator; those fibres are invisible
and uncorrectable, which is indefensible once a person reviews the visible set.
The seeded count is retained as `wave_n_seeded`. Wave fractions will therefore
not match legacy macro rows exactly.

## A detection failure is no longer recorded as a measurement of zero

A sampling line that crosses no resolvable banding used to pass silently into a
`sarc_mode=AUTO` row with `sarc_number=0` — indistinguishable in the CSV from a
real measurement of zero sarcomeres. It now says so plainly and asks for
confirmation before saving, pointing at **Skip sarcomeres** as the honest way to
record a cell whose banding could not be read.

## Scale-bar calibration is now two explicit steps

Auto-detect measures a burned-in bar's pixel length, but no longer applies a
scale using whatever sits in the Known-length box. That box defaults to 1.0 mm —
correct for plate-scale behavioural rigs, wrong for a confocal bar printed in
µm. In real use this produced a **~20× calibration error twice in one session**:
a 904 px bar labelled "49.2 µm" read as 1.0 mm gives 1.10619 µm/px instead of
0.05442, and every downstream length, area and wave measure inherits it.
`CHECK_CALIBRATION` caught it, but only after the rows were written.

Measuring the bar now sets nothing. The printed value must be entered, then
applied with a second, explicit click.

## Also in this release

- Myocyte body-wall identity (Myo01–24) with next-number suggestion, the
  anterior/midbody/posterior mapping, and the bundled numbering schematic
- Saved myocytes stay outlined and labelled on the image for the whole session
- Session save/resume — closing the tool never loses more than the cell in progress
- Mouse-wheel zoom on the cursor, display brightness/contrast (view-only, never
  touches measured pixels)
- Correction logging for every EDITED / MANUAL / MANUAL_RECOUNT sarcomere count,
  joinable to its CSV row, with matched/missed/spurious agreement counts

## Still not built

Branch-point marking within a fibre, and per-segment (rather than per-fibre)
identity assignment.
