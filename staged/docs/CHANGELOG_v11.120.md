# WINK Lab Tools v11.120 — basal slowing: "needs correction" can now correct something

Basal slowing's review offered three actions: accept a track, reject it, or flag
it as needing correction. Nothing in the module could act on that flag, and
nothing else did either — so a track that jumped between animals could be
labelled, and then stayed exactly as it was.

## Tracks can be edited, and the events follow

**Join** two fragments (shift-click a pair), **Split at frame**, **Trim before**
or **Trim after** the current frame, **Delete track**, and **Undo**.

The guard that matters: two tracks that overlap in time **cannot be joined** —
things visible simultaneously are not one animal — and a refused join records
nothing.

Entry events are *derived from* trajectories: when an animal crosses into a
lawn, and what falls inside the before/after windows either side. An edited
track whose events were not rebuilt would describe a trajectory that no longer
exists. So editing now triggers a re-derivation, verified: splitting one track
turns one entry event into two across two tracks. If the rebuild fails you are
told plainly that the events still describe the **original** tracks, rather than
being left with stale ones and no warning.

Every edit is written to `manual_track_edits.json`, so a recomputed event can be
traced back to a decision.

### Two new engine entry points

`derive_entry_events(tracks, ...)` was extracted out of `analyze()` — 145 lines
lifted verbatim and proven output-preserving: every CSV and JSON from a full run
is byte-identical before and after the extraction.

`recompute_events_from_tracks(...)` rebuilds events from saved or edited tracks
without decoding a frame. Detection, linking and spines are reused unchanged.
Verified to match a direct run with corrected parameters exactly, while leaving
the original results byte-for-byte untouched.

This also means a finished basal slowing run can be corrected for a wrong
declared frame rate or scale, the same way Population tracking can.

## Tracks you can actually see

The event map drew every trajectory in `#777777` at 0.7 width and 60% opacity,
on blank white with no image underneath. It now draws the recording underneath —
`background_reference.png` was already being saved and simply was not used —
gives **each animal its own colour**, and runs at 1.6 width and 90% opacity.
Entry markers went from 8 to 13 px with a white outline so they read against the
image. The whole thing moved into a `ReviewWorkbench`, so it is themed, clamped
to the screen and cannot hide behind the main window.

In the track reviewer, one colour scheme had been doing two jobs. Trails now
carry **identity** — one colour per animal, at 2.2 width instead of 1.2 —
because previously every undecided track in the open field was the same green
and several animals were impossible to tell apart. Position markers keep their
**region** meaning: cyan in the start ROI, red on a lawn, with decision colours
overriding once a call has been made. Colouring the markers per animal too would
have destroyed the information the review depends on.

## The link distance is adjustable, and measurable

`max_link_px` — how far one animal may travel between frames — was fixed at the
`analyze()` default of 60 source pixels with no way to change it. An over-large
gate is what lets a track jump across the plate to a different animal.

Measured on a real 7.5 fps basal slowing recording (1024×768, 15 µm/px), animals
move **0.42 px per frame at the median and 3.15 px at the 95th percentile** —
against a gate of 60, roughly nineteen times larger than needed.

The field is now exposed, with **Measure motion to set this…**, which samples
the recording, reports median/p95/p99 displacement and suggests a value with
headroom. On that recording it suggests about 9.

Worth knowing: the physical speed limit added in v11.116 **already applied
here**. `basal_slowing` imports `link_detections` from `population_swimming` and
does not override `enforce_speed_limit`, so results produced before v11.116 will
already improve on a re-run.

## Compatibility

`review_tracks(..., return_edits=False)` defaults to the previous contract — a
plain decisions mapping — so `app/diagnostics.py` and any other caller is
unaffected.

## Verification

Seven structural suites and four regression tests pass: extraction
output-preserving, recompute equivalence, editing operations and their guards,
review visibility, in-window structure, calibration wiring, undefined names,
plus the basal slowing, population swimming, movie-input and shared-cores
regressions.

A missing `cv2` import in the new motion-measurement code was caught by the
undefined-name check before it could reach anyone — the same class of bug that
shipped a `NameError` into a dialog in v11.116.

**Not GUI-tested.** The basal slowing reviewer is a matplotlib button panel that
now carries eleven controls, and layout problems do not show up in structural
checks. Worth a hands-on pass before relying on it.
