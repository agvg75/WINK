# NIKE Lab Tools v11.73

## Track one worm — time-dependent exclude regions (W4)

Exclude regions no longer have to apply to the whole movie.

- After you draw your exclude regions (scrolling the movie as before), you're
  asked for the **frames each region is active** — e.g. `1-100`, `250-500`, or
  blank for the whole movie.
- A region can therefore be present for part of the recording and gone for the
  rest, and different regions can cover different spans (a bubble that drifts in
  and out, another animal that only appears later, and so on).
- The tracker assembles the **per-frame** exclusion mask on demand: for each
  frame it excludes the regions active then, plus everything outside the focus
  region. This applies to the initial track and to any re-tracking.

The focus region still spans the whole movie. All of this stays opt-in (choose
No at the guidance prompt to track the full working region).

### Still planned
- A persistent, resize-in-place ROI you can adjust frame-by-frame with
  interpolation between keyframes (the drawing step already lets you drag/resize
  a region and scroll frames; per-frame keyframing is the next step).
- W5: partial-interval analysis (choose analysis start/end to skip a noisy
  section).
