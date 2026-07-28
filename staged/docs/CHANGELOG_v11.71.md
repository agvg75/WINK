# NIKE Lab Tools v11.71

## Fix: pressing "f" in Track one worm blew the review window up

- The review window uses single letters as shortcuts (`f` = fix, `s` = finalize,
  `g` = segmentation workbench, `c` = close interval) and the arrow keys.
  Matplotlib **also** binds those by default (`f` = toggle fullscreen, `s` =
  save, `g` = grid, `left`/`c` = back, `right` = forward).
- So pressing **`f`** ran the fix *and* toggled fullscreen, expanding the window
  with no easy way to get back — you had to quit.
- Those clashing Matplotlib default key bindings are now cleared for this tool,
  so `f` only fixes the frame. The review window is also re-clamped to the
  screen shortly after it opens, in case a HiDPI display sized it too large.

Builds on v11.70 (faster `set_data` scrubbing; PgUp/PgDn ±10; Home/End). No
tracking or measurement logic changed.
