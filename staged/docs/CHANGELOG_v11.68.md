# NIKE Lab Tools v11.68

## Track one worm — one setup form instead of a pop-up chain (W2)

- Assay mode is now a **drop-down** (crawling / swimming / burrowing) — no more
  typing the word.
- FPS, micrometres-per-pixel, worm ID, exposure, and the two acceleration
  options are all on **one setup window** with a single Start button.

## Focus / exclude ROIs: scroll the movie, and never get trapped (W3)

- The focus and exclude ROI editors now let you **scroll the whole recording**
  (Frame slider and `<` `>`), so you can see everywhere the worm travels before
  committing a region.
- The exclude step can be **finished with no regions** — the button reads
  "Finish / none", so an optional ROI step never blocks you from proceeding.
- All of this stays opt-in: choosing No at the guidance prompt tracks the full
  working region exactly as before.

## Workbench windows fit the screen (window controls)

- Cockpit / review windows now **clamp to the screen size and centre**
  themselves. Previously a large window (e.g. the guided pharyngeal review)
  could push its minimize/maximize/close buttons off the edge of a small laptop
  screen, leaving no way to resize or close it.

## Carried forward

- v11.67 pharyngeal guided review with corrective anchors.
- v11.66 worm search focus/exclude ROIs; v11.65 defecation cockpit landmarks.

## Known / still planned

- Time-dependent ROIs (a focus/exclude region active only over a frame range)
  and partial-interval analysis start/end are the next step for the worm tracker.
- A persistent, resize-in-place ROI you can adjust across frames is planned with
  the time-dependent ROI work.
