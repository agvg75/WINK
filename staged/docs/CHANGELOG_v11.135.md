# WINK Lab Tools v11.135 — calcium in cultured human muscle cells

## A new tool: Cultured cell calcium (probe-aware)

Under **Physiology → Calcium and cellular activity**. Built for the lab's
cultured human muscle work, from myoblasts to myofibres and from striated to
smooth.

### It asks which probe you used, and refuses what that probe cannot support

A single "is it ratiometric?" flag cannot describe what the lab actually images.
Probes are registered on three axes that fail independently:

| Axis | Question | Why it matters |
|---|---|---|
| **Loading-independent** | can two cells be compared on raw signal? | Fura-2 cancels dye loading; Fluo-4 does not, so dF/F0 is comparable and raw F is not |
| **Reversible** | does the signal come back down? | MitoSOX's oxidised product intercalates DNA and stays |
| **Live** | is there any time in the sample? | antibody staining is fixed |

The reversibility axis is the one a boolean could not see. A decay constant
fitted to MitoSOX fits *perfectly* and means nothing, because the curve is an
accumulation, not a response. That is now refused and an **accumulation rate**
offered instead. Antibody staining is refused every kinetic measure however many
frames are supplied — frames of a fixed slide are not time.

Registered: Fura-2, Indo-1, Fluo-3, Fluo-4, Cal-520, GCaMP, Rhod-2,
Grx1-roGFP2, roGFP2, HyPer7, JC-1, TMRM, MitoSOX, CM-H2DCFDA, antibody. Each
carries the caveat that decides how its numbers read — TMRM's sign flips between
quench and non-quench mode, the roGFP/HyPer sensors are pH-sensitive, a Fura-2
ratio is not a concentration until it is calibrated on that rig.

### Transfected against untransfected, in the same field

For the shRNA layout — one calcium channel, one mCherry channel marking
transfected cells — the untransfected cells in the *same field* are the control.
They share the coverslip, the dye loading, the illumination and the focus, and
all of those cancel. That is what makes a single-wavelength dye usable for a
resting comparison at all.

Each transfected cell is normalised to the median of the untransfected cells in
its own field. A per-field median was tried first and was wrong for real data:
at 3% transfection efficiency it required three transfected cells in one field,
discarded 23 of 24 fields, and left a single field whose answer moved from 0.50
to 1.27 depending on where the segmentation threshold was set.

**The untransfected cells are also reported as a null band.** Normalised the
same way they spread 0.65–1.85 on the pilot data — that is how much one cell
differs from another with no treatment at all. Each condition reports how many
of its cells fall inside it. Without that band a 1.3-fold difference looks like
a result.

### Three guards, for artefacts that point the same way as the hypothesis

- **Segmentation channel.** Finding cells by thresholding the calcium channel
  finds the bright ones. The tool's own test shows this: on a synthetic field it
  recovers 12 of 16 cells, and the 4 it misses are the dim treated ones — the
  bias removes exactly the cells carrying the effect. Segment on DIC or a
  nuclear stain. DIC needs gradient-based or learned segmentation, not a
  grey-level threshold, since shear shading puts a cell's interior near
  background.
- **Marker bleed-through.** mCherry reaching the green detector raises
  transfected cells optically, in precisely the direction a knockdown that
  raises calcium would predict. Tested by whether signal scales with marker
  brightness among positives, since knockdown is closer to all-or-none.
- **A scramble control that is not at unity.** Then transfection itself moved
  the signal, and every other condition inherits it.

### What it says before it measures anything

Step 1 reports what the recording can support *before* any number is computed.
On the lab's pilot images the answer was that eight of nine calcium measurements
were impossible — single 8-bit frames using 47 of 256 grey levels, with no time
dimension. That is the answer worth having before a morning is spent on the
ninth.

## Also

Marker classification holds out cells near the threshold as **ambiguous** rather
than forcing them into a class — a graded marker means a graded knockdown, so
those are the least certain cells. Bimodality is measured as Otsu separability,
which has a known reference value: a single normal distribution cut in half
scores 0.64, so anything near that is not two populations.
