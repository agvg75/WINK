# WINK Lab Tools v11.116 — Population tracking: one window, and eight real defects fixed

Population swimming is renamed **Population tracking** (it was never only
swimming), its review now happens inside the cockpit window over the movie, and
eight genuine defects were found and fixed — including one that silently
discarded every re-analysis of a recording, and one that could hang the tool
forever.

**Read this if you have used Population swimming before: your re-runs were
probably not what you were looking at.** See "The stale review" below.

---

## The stale review — the one that mattered

Results land in a folder derived from the recording, so re-analysing the same
movie writes into the same folder. The review then did this:

```python
track_path = out/"reviewed_detections_and_tracks.csv"
tracks = pd.read_csv(track_path if track_path.exists() else out/"detections_and_tracks.csv")
```

Correct when resuming a review. **Wrong after a new analysis**: the freshly
computed detections were ignored and the previous session's reviewed tracks
were loaded instead — then saved back over the reviewed file. Change your area
gates, your resolution, your ROI: the review showed the first run's tracks every
time.

Observed on a real recording: a fresh run wrote a 5.8 MB
`detections_and_tracks.csv` (~20,000 rows) and the review loaded a 176 KB
leftover containing **432 rows across 8 tracks**.

A new analysis now moves any previous review into
`superseded_review_<timestamp>/` with a README explaining why. Nothing is
deleted. `Resume existing results review` still restores prior work — that is
its job.

After the fix, the same recording: **18,891 detection rows, 111 candidate
tracks, 19 accepted, median bend frequency 1.17 Hz, median speed 124 µm/s.**

## The hang

`_ordered_spine` skeletonises with `while cv2.countNonZero(image):`, eroding
until the mask empties. `cv2.erode` treats the image border as *maximal*, so it
never erodes inward from the crop edge — a component that fills its own bounding
box erodes to itself, `countNonZero` never reaches zero, and the loop spins at
100% CPU forever.

Reachable in ordinary use: `min_area` is scaled by `detection_scale²`, so a 25%
proxy admits ~2 px components, and any tiny solid blob fills its bounding box.
Runs sat on one track for 20+ minutes.

Fixed by breaking at the erosion fixed point. Output-preserving: masks that
already terminated produce **byte-identical** skeletons (verified on worm, disc,
box-with-hole, band, ellipse); masks that hung produced no result at all.

## Everything else that was broken

| defect | effect |
|---|---|
| Bout review buttons dead | `reviewed_modality` reads as float64 when empty; writing `"swimming"` raises `TypeError` on pandas ≥3.0. Confirm, Relabel and Reject all silently did nothing. |
| Tk exceptions invisible | Callback errors went to stderr, which `pythonw` discards — a failing button looked like a button that did nothing. Now reported in the hood and status line with file and line. |
| Linking welded separate animals | Position was extrapolated by `velocity × gap` and gated at `max_link_px × √gap`; across a 45-frame crossing hold the projection drifts most of a frame away and drags identity onto a different animal. |
| `max_link_px` hard-coded | Fixed at 60 source px with no UI control. Measured displacement on a real recording: p50 **1.8 px**, p95 **5.8 px** — the gate was ~10× too permissive. |
| Skeleton fragments on thick masks | The erosion-residue skeleton is not guaranteed connected. At 9 px thickness it yields **no spine at all**; at 5 px a spine covering **16%** of the animal. |
| Review framed the tracks, not the frame | Matplotlib autoscaled to track extents before the movie loaded, which read as though the analysis had cropped the frame. It had not — ROIs filter by centroid against the exact polygon. |

## Population tracking now reviews in one window

Four windows became one. Review happens in the centre pane, which previously
held four lines of text.

- **Tracks over the movie**, synced, with a frame slider and Play. A marker
  follows every track at the current frame.
- **Each accepted animal gets its own colour**; rejected tracks fade to grey.
- **The selected track carries a large magenta dot**, and every animal is
  labelled with its track id — so the frame where a track jumps to the wrong
  animal is findable, and splittable.
- **Trail length** selectable (full / 10 / 20 / 50 / 100 / 250 frames).
- **Bout list** is a table under the canvas; selecting a bout previews it on the
  same canvas.
- Frames come from a low-resolution proxy built in one background pass.

## Editing tracks

Because fighting the settings is not always the fastest route to a correct
answer:

- **Shift-click any number of tracks** (the two-track cap is gone), or **lasso**
  a region to select every track inside it.
- **Stitch N fragments** into one animal in time order, with each gap and
  endpoint distance shown before committing.
- **Split at the current frame**, **delete selected tracks**, **undo**.
- **Add missing points** by scrubbing and clicking where the animal is, and
  **fill gaps** with straight-line interpolation.

### Manual points never become measurements

Points you place carry **identity only**. They are flagged `manual_point` and
excluded from speed, coverage, frequency and curvature; `summarize_tracks`
computes every statistic from detected rows alone.

Verified: ten manual points at absurd coordinates injected into a track changed
**no** reported value — duration, coverage, activity, speed and all three
frequencies identical — while identity extended from 120 to 130 frames with
`manual_points = 10` and `speed_um_s` blank on those rows. A 30-frame gap fill
gave the same result.

New per-track columns: `detected_frames`, `manual_points`.

## Setting the parameters from the recording

Areas are in **source pixels**, so the right value depends on magnification — on
a 4K recording a worm is thousands of pixels, not tens. The defaults (40 / 2500)
are tuned for a low-resolution rig and flood a 4K recording with noise: measured
on a real file, min area 40 kept **81%** of all components, and half of those
were ≤10 proxy px.

- **Measure a worm** — click one animal; WINK reads the area the *detector*
  gives it (not your click, and not a traced outline, which is systematically
  more generous than the thresholded mask). Sets both gates, and sets
  `max_link_px` from how far worm-sized objects actually travel between frames.
- **Mark all animals** — click each animal; every click leaves a numbered marker
  so you can see what you have done. Duplicate clicks on the same object are
  detected and ignored; clicks that miss are reported. It then asks whether you
  marked *every* animal: if yes the count is the population and the review flags
  when tracking finds a different number; if no it is treated as a minimum.

## Faster

Opening a compressed video used to decode the whole file to count frames —
**123 s** on a 126 MB 4K clip, on *every* open, including opens that wanted one
preview frame. Interactive paths now use a cheap container estimate.

| | before | after |
|---|---|---|
| Open a movie (UI paths) | 122.8 s | **4.3 s** |
| Scrub one frame | 4.17 s | **0.002 ms** |
| Playback | 0.24 fps | GUI-limited |

`exact_count` still defaults to `True`, so no existing caller changed: an audit
found ~10 sites in other modules that iterate `range(n_frames)` or write a frame
count into results. Only Population tracking's four interactive call sites opt
in. `analyze()` forces an exact count before touching `len(files)`, because a
blank end frame sets `coverage_fraction`.

## Choices that change measurements — deliberate, and yours

**Spine skeleton** is now selectable and recorded in `analysis_metadata.json` as
`spine_skeleton_method`. The default is **unchanged** (`morphological`). The
alternative (`thinning`, scikit-image) does not fragment: on the project's own
fixture it yields a usable spine on **100%** of detection rows against **17.5%**
for the default. It is *not* faster — measured 0.4–0.9× at realistic crop sizes.

The default was not flipped because switching changes modality classification
(bend frequency was unchanged on that fixture, but the classifier reads
curvature topology). Compare on your own recording first:

```
python tools/population_swimming/compare_spine_methods.py <movie> --fps 20 --scale 2.0
```

**Linking speed limit** (`enforce_speed_limit`, on by default at your request):
a link must now also satisfy *distance from the last observed position ≤
max_link_px × gap*. Momentum still carries identity through a crossing, but an
animal cannot exceed its own travel limit however long it went unseen. On the
synthetic fixture every measured value is identical (its worms never trigger
it); on recordings with long crossing holds it will change track identity, which
is the point.

## Verification

Automated, all passing: population-swimming and movie-input regression tests;
byte-comparison of every scientific CSV against a pre-change baseline for the
non-measurement changes; manual-point firewall; gap-fill firewall; stale-review
archiving; in-window structure; and a new undefined-name check that catches an
import removed while still in use — the class of bug that shipped a `NameError`
into the resolution dialog mid-session.

That name check also flags two **pre-existing** issues elsewhere, untouched:
`tools/basal_slowing/basal_slowing.py:681` (`minimum_window_s`) and
`tools/worm_kinematics/worm_kinetics_foraging_dampening.py:167`
(`wave_propagation`).

**Not automated:** the GUI. Everything here was exercised by hand during
development, and the end-to-end result above is from a real recording, but there
is no automated UI test. Per-track colours, lasso selection, trail length and
gap filling landed after the last hands-on pass.

## Renamed

"Population swimming + modality review" is now **Population tracking**, in the
hub and in the module. The folder `tools/population_swimming/`, the module
filenames and the results folder name are **unchanged** — renaming those would
break imports and orphan every existing results folder.
