# Population tracking

*(Formerly "Population swimming + modality review". Renamed in v11.116 — it was
never only swimming. The folder and results directory are still named
`population_swimming` for compatibility.)*

## What it measures, and why

Many animals in one field of view, tracked simultaneously, to ask how a
population is moving: how fast, at what undulation frequency, and — where the
evidence supports it — whether an animal is swimming, crawling or burrowing.

The design commitment is that **nothing is auto-labelled**. Every track and
every locomotion bout is a proposal a human confirms, relabels or rejects.
Uncertain evidence stays uncertain rather than being forced into a class.

## What it expects

A movie (MP4/AVI/MOV/MKV/WebM), a multipage TIFF stack, or a folder of
sequential images. Declared frame rate and µm/pixel are entered by hand; the
tool does not read them from the file.

A good recording for this module has the whole useful arena visible, enough
contrast between animals and background, and **animals that move**. A
difference-from-background detector cannot see an animal that never moves — it
becomes part of the background by construction.

Worm length in the source image matters more than resolution alone. Around
**100 px of worm length** is the working threshold for posture work (the same
rule of thumb Tierpsy uses). Below that, centroid measurements are still fine
but spine-derived quantities get unreliable.

## Parameters

| Parameter | Units | What it controls |
|---|---|---|
| Declared FPS | frames/s | Sets all time and frequency scales. Wrong here and every Hz is wrong. |
| Scale | µm/pixel | Converts pixels to physical speed. |
| Min / Max object area | **source pixels** | Which blobs count as animals. |
| Max link | **source pixels per frame** | How far one animal may travel between frames. |
| Detection resolution | proportion | 100% / 50% / 25% proxy. Detection runs on the proxy; coordinates are rescaled back to source pixels. |
| Spine skeleton | choice | Standard (historical) or connected thinning. |
| ROI action | none/include/exclude | Optional spatial filter, applied per detection centroid against the exact polygon. |

**The area gates are the most commonly misconfigured setting in WINK.** They are
in source pixels, so their correct value depends entirely on magnification. On a
3840×2160 recording a worm is on the order of **2,000 source pixels**, not tens.
The historical defaults (40 / 2500) suit a low-resolution rig; on a 4K recording
a minimum of 40 keeps roughly **81%** of all detected components, and half of
those are around 10 proxy pixels — sensor noise, not animals.

Two helpers exist so these do not have to be guessed:

- **Measure a worm** — click one animal. The tool reads the area the *detector*
  gives that object (not the click, and not a hand-drawn outline, which is
  systematically more generous than the thresholded mask) and sets the gates
  from it. It also measures how far worm-sized objects actually travel between
  frames and sets Max link from that.
- **Mark all animals** — click every animal. Gates come from the spread of the
  marked population, and the count becomes an expected value the review checks
  against. Duplicate clicks on the same object are detected and ignored. The
  tool asks whether you marked *every* animal: if yes the count is the
  population; if no it is treated as a minimum only.

### Max link

Default 60 source px/frame. Measured on a real 30 fps swimming plate, animals
move **p50 1.8 px, p95 5.8 px** between frames — a gate of 60 is roughly ten
times more permissive than needed. An over-large gate does not merely add noise:
it lets one track jump between different animals, which shows up as long
straight segments crossing the field between tight local squiggles.

### Spine skeleton

Two methods, recorded in `analysis_metadata.json` as `spine_skeleton_method`.
They are **not interchangeable** — spine, curvature and bend frequency all
depend on the choice.

- **Standard** — the historical default, an erosion-residue skeleton. It is not
  guaranteed connected: masks more than about 3 px thick can skeletonise into
  several disconnected pieces, and the extracted spine then describes only part
  of the animal, or fails entirely. Measured on a real recording, it produced a
  usable spine on **51.3%** of the frames where one was attempted.
- **Connected thinning** — scikit-image thinning, which stays a single connected
  curve at any thickness. On the same recording: **99.7%**.

Thinning is not a speed optimisation — on synthetic masks it is slower — but on
real data it was faster because it was not failing repeatedly.

Counter-intuitively, **raising detection resolution makes the standard skeleton
worse**, because it makes masks thicker in pixels, and thickness is what
fragments it. With thinning, higher resolution behaves as you would expect.

## What normal output looks like

From a 3840×2160, 30 fps swimming plate with about ten adults, gates set from a
marked worm (885–5,720 source px), 25% detection proxy:

| | |
|---|---|
| worm length | ~100 source px (median), 18 px wide |
| worm area | ~1,900 source px |
| detections | 11–18 worm-sized objects per frame |
| detection rows | ~19,000 over 1,662 frames |
| candidate tracks | ~110, reduced to ~87 by stitching |
| accepted after review | ~19 |
| median bend frequency | **1.17 Hz** (range 1.02–2.83) |
| median speed | **124 µm/s** |
| median coverage | 0.59 |

Track counts far above the number of animals mean fragmentation; far below means
merging or missed detection. If you used **Mark all animals**, the review states
this comparison for you.

## Outputs

- `detections_and_tracks.csv` — every detection, per frame, with track identity
- `track_summary.csv` — per-track statistics and QC flags
- `modality_window_proposals.csv` — 4 s overlapping windows with their evidence
- `modality_bouts_for_review.csv` — smoothed proposals pending human review
- `reviewed_*` — written by the review; `reviewed_modality_summary.csv` holds
  per-modality time, bout count, speed and frequency
- `analysis_metadata.json` — every threshold and rule used
- `superseded_review_<timestamp>/` — a previous review of the same recording,
  archived when a new analysis runs

### Two columns that are easy to misread

**`spine_bend_frequency_hz` is the centroid oscillation**, not the spine. The
module's primary frequency is the dominant lateral oscillation of the centroid
about its smoothed trajectory; signed midbody spine curvature is retained as a
**fallback and diagnostic** (`curvature_frequency_hz`). When the two disagree
markedly, that disagreement is itself evidence that the spines are unreliable.

**`manual_point` rows carry identity, not measurement.** Positions a reviewer
places by hand — to bridge frames the detector missed — are excluded from speed,
coverage, frequency and curvature. `detected_frames` and `manual_points` are
reported separately per track so a reader can see how much of a track was
asserted rather than observed.

## Troubleshooting

### Far fewer objects detected than animals visible

**What this usually means:** the area gates are in source pixels and are wrong
for the magnification. A maximum carried over from a low-resolution rig rejects
whole animals; a minimum that is too low floods the tracker with noise blobs
that then compete for track assignments.

**Also worth considering:** animals that were not moving during the sampled
frames are absorbed into the median background and become invisible to a
difference-based detector. That is a property of the preparation and the
sampling, not a setting — a plate where several animals were quiescent will
genuinely yield fewer tracks.

**What to check:** run *Measure a worm* and compare the reported area against
your current gates. In the summary, compare detections-per-frame against the
number of animals you can see on the plate.

### Tracks contain long straight jumps between distant animals

**What this usually means:** the link distance is too permissive. The tracker
predicts where an animal should be from its velocity, and across a long gap that
prediction drifts far from where the animal actually was; anything near the
phantom position can capture the identity.

**Also worth considering:** genuinely dense plates where animals cross often
give the tracker more opportunities to swap identity, independent of settings.

**What to check:** the measured per-frame displacement against Max link. In the
review, scrub with a short trail and watch the highlighted marker — the frame
where it jumps to a different animal is where the track should be split.

### Every bout says "uncertain" with confidence 0.00

**What this usually means:** before v11.117, this was a bug — the posture gate
demanded more spine coverage than the sampling rate could ever provide at 30 fps
or above, so no window could be classified regardless of data quality. If the
run predates v11.117, that is the likely explanation and the run should be
repeated.

**On current versions**, check `proposal_reason`, which now distinguishes:
`insufficient_track_coverage` (the animal is not followed through enough of the
window), `insufficient_spine_evidence` (too few usable spines),
`possible_collision_in_window`, `no_usable_frequency`, and
`overlapping_modality_evidence` (the classifier ran and the modalities genuinely
overlap). Only the last is a scientific verdict; the others point at data.

**Also worth considering:** swimming, crawling and burrowing overlap in
frequency, and posture evidence is what separates them. A preparation where the
behaviour is genuinely intermediate will produce overlapping evidence honestly.

### Many frames have no spine

**What this usually means:** if the run used the standard skeleton, masks thicker
than a few pixels fragment and no valid path can be extracted — roughly half of
attempted frames on a real recording. Switching to connected thinning is the
direct comparison to make.

**Also worth considering:** spines are only attempted every *stride* frames,
where stride = fps / 15, so at 30 fps at most half of all frames will ever carry
one. A spine fraction near 0.5 measured against *all* frames may be complete
coverage, not a failure. Also, animals below roughly 100 px of length simply do
not carry enough pixels for a reliable centreline.

**What to check:** `spine_frames_used` against `spine_frames_attempted` rather
than against total frames. Run `compare_spine_methods.py` on the recording to
see both methods side by side.

### Changing the settings appears to change nothing

**What this usually means:** before v11.118 this was a real defect. Results land
in a folder named after the recording, and the review preferred the previous
run's reviewed file over the detections just computed — so every re-analysis
silently displayed the first run's tracks. On a real recording a fresh 5.8 MB
detection set was discarded in favour of a 176 KB leftover holding 432 rows.

**On current versions** a new analysis archives any previous review into
`superseded_review_<timestamp>/` and says so in the process hood.

**What to check:** whether the hood reports archiving a superseded review, and
whether `detections_and_tracks.csv` is large and freshly timestamped.

### The analysis sits on one track for many minutes

**What this usually means:** before v11.116 the skeletoniser could loop forever
on any mask that filled its own bounding box — reachable whenever a low
detection resolution admitted tiny solid blobs. On current versions this cannot
happen.

**Also worth considering:** the detailed spine pass is genuinely the most
expensive step, and its cost scales with worm area × thickness. It is cheap on a
25% proxy and can dominate a run at original resolution. The counter advances
one unit per *track*, so it looks frozen even while working.

### The review window shows a rectangle around the tracks

**What this means:** nothing is wrong. Before the movie frames finish loading in
the background, the plot is scaled to the extent of the tracks. Once the preview
proxy is ready the full frame appears underneath. ROIs filter detections by
centroid against the exact polygon — a drawn polygon is never reduced to its
bounding box.

### Bend frequency looks implausible

**What this usually means:** declared FPS is wrong. Every frequency scales
directly with it, and nothing in the tool can detect a wrong declaration.

**Also worth considering:** the reported frequency is the centroid oscillation.
An animal that is barely translating, or one whose track is short or sparse, can
yield an unstable estimate — the eligibility gate requires at least 3 s of track,
55% coverage and under 5% collision frames before a frequency is reported at all.

**What to check:** whether `centroid_oscillation_frequency_hz` and
`curvature_frequency_hz` agree. Wide disagreement suggests unreliable spines
rather than an unusual animal.
