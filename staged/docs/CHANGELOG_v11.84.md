# NIKE Lab Tools v11.84

## Mechanosensation — interactive stimulus marking

You no longer have to type stimulus times in seconds. A new **"2. Mark stimuli
on movie"** button opens the recording in a frame scrubber:

- Step through frames with the **slider**, **arrow keys**, or **PgUp/PgDn (±10)**.
- Press **m** or **space** to mark the current frame as a stimulus; **u** undoes
  the last mark. The title lists the marked times as you go.
- When you close the viewer, the marked times fill the **Stimulus times** field
  automatically (converted from frame × FPS).

This is especially helpful for a long habituation series with many taps. The
viewer reuses the same movie reader as the tracker, clears the clashing
Matplotlib keyboard shortcuts, and clamps its window to the screen.

### Remaining
- **Population-level assay** (many worms + plate tap → % responding, response
  strength, centroid-based) — next.
- Then: replace the Power analysis utility with the newer planner and wire it to
  the assay outputs.
