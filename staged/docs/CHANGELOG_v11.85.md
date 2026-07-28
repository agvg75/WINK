# NIKE Lab Tools v11.85

## Population tap response / habituation (new tool)

A population-tracker-based mechanosensation assay: many worms, a plate tap that
moves the whole field of view, and a paired before/after comparison per animal.

Workflow (piggybacks on the population tracker):
1. Run **Population swimming + modality review** to get a tracks CSV
   (`track_id, frame, x, y`).
2. Open **Population tap response / habituation**, choose that CSV and the movie.
3. It:
   - detects the plate **tap(s)** from the **global field motion**, with an
     **intensity** (artifact size), a **duration**, and, across taps, a
     **frequency** (inter-tap interval);
   - splits each worm's centroid track into **before** and **after** windows
     around each tap;
   - classifies, per worm × tap, whether the animal **responded** by changing
     **speed** and/or **direction** (each worm is its own control);
   - rolls up to a **population response fraction per tap** (and the split by
     speed vs direction, and mean response strength).

Outputs: `taps.csv`, `per_worm_tap_response.csv`, `population_tap_summary.json`.

It is **centroid-based**, so it does not need clean spines. The analysis core
(tap detection, paired per-worm classification, population summary) was
unit-tested.

_Only new files were added; existing modules are unchanged._
