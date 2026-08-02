# Basal slowing

## What it measures, and why

The basal slowing response: a well-fed animal slows when it encounters a
bacterial lawn. The module measures each animal's locomotion **before and after
it enters a lawn**, so the comparison is within the same animal rather than
between groups.

The paired unit is therefore **an unambiguous worm trajectory**, not an isolated
detection. An event only counts when a linked track leaves the start region,
enters a student-drawn lawn ROI, and has enough usable frames on both sides of
the entry to compare. Ambiguous identity, collisions, missing windows and weak
frequency estimates are exported as QC rather than hidden.

## What it expects

A folder of sequential images or a movie, plus two hand-drawn regions: a **start
ROI** where animals begin, and one or more **lawn ROIs** marking the bacterial
food. Declared FPS and µm/pixel are entered by hand.

A good recording shows the lawn boundary clearly, includes animals both before
and after entry, and starts before the transition of interest. A recording that
begins after animals have already reached the lawn has no "before" window and
yields nothing.

## Parameters

| Parameter | Units | What it controls |
|---|---|---|
| Declared FPS | frames/s | Time and frequency scales |
| Scale | µm/pixel | Physical speed |
| Min / Max worm area | **source pixels** | Which blobs count as animals |
| Max link | source pixels/frame | Track linking distance |
| Before / After window | seconds | Length of the paired comparison, minimum 3 s each |
| Pre-entry gap | seconds | Dead time excluded immediately before entry |
| Outside buffer | source pixels | How far outside the lawn counts as genuinely outside |
| Minimum window fraction | proportion (0–1] | How complete each window must be, default 0.70 |
| Minimum worm fraction inside | proportion | How much of the body must be inside the lawn to count as entry, default 0.50 |
| Tracklet stitch gap / distance / heading | s, px, degrees | When two fragments may be joined into one trajectory |

**The area gates carry the same caveat as every other WINK module: they are in
source pixels.** The defaults (40 / 2500) suit a low-resolution rig. On a high
resolution recording a worm is thousands of pixels, and a maximum of 2500 will
reject whole animals while a minimum of 40 admits noise. Unlike Population
tracking, this module does not yet have a *Measure a worm* helper, so the values
have to be reasoned about directly.

Note that this module uses a connected thinning skeleton throughout, so it does
not suffer the fragmentation failure that affects Population tracking's
historical skeleton option.

## What normal output looks like

- `paired_entry_events.csv` — one row per qualifying entry, with before/after
  mean speed and a body-axis frequency proxy on each side
- `detections_and_tracks.csv` — every detection with track identity
- `inferred_tracklet_stitches.csv` — every fragment join the tool inferred
- `departure_clocks.csv` — timing of departures from the lawn
- `analysis_metadata.json` — all thresholds and definitions
- `decision_transparency.json` — plain-language provenance manifest
- `background_reference.png`, `rois.json`

A useful sanity check is that events with `automatic_eligible = true` outnumber
those rejected for QC. Every event is exported either way; eligibility says
whether it passed the automatic gates, not whether it is real.

### The frequency is a proxy

The before/after frequency columns are named
`before_body_axis_frequency_proxy_hz` and `after_body_axis_frequency_proxy_hz`
for a reason: they are a body-axis oscillation proxy, not a direct measurement of
undulation. Missing frequency is reported separately from usable speed
(`before_frequency_unavailable`, `after_frequency_unavailable`), so an event can
contribute a speed comparison while contributing no frequency comparison.

## Troubleshooting

### No paired events, or far fewer than animals that entered the lawn

**What this usually means:** the windows could not be filled. Each event needs
`before_s` and `after_s` of usable track on either side, at
`minimum_window_fraction` completeness. An animal that enters near the start or
end of the recording, or whose track breaks around the entry, produces no event.
The exclusion reasons name which side failed:
`insufficient_buffered_before_frames`, `insufficient_inside_after_frames`,
`insufficient_post_exit_frames`.

**Also worth considering:** entry is defined by the fraction of the animal's area
inside the lawn ROI reaching `minimum_worm_fraction_inside`. If the lawn ROI was
drawn tightly inside the visible lawn edge, animals feeding at the rim may never
formally "enter". This is a drawing decision, not a detection failure.

**What to check:** the exclusion reasons on the rejected events, and whether the
lawn ROI matches where animals actually behave as though they are on food.

### Events flagged `ambiguous_identity`

**What this usually means:** the tracker could not hold identity through the
window with confidence — usually crossings or collisions near the lawn boundary,
which is exactly where animals congregate.

**Also worth considering:** this is a real property of a crowded plate rather
than a fixable setting. Reducing the number of animals per plate, or drawing the
lawn ROI so the boundary region is less crowded, addresses the cause; loosening
the tracker only hides it.

### Speed differs but frequency is missing on one side

**What this usually means:** the frequency proxy needs enough clean oscillation
to estimate. A short window, sparse detection, or an animal that pauses will
yield speed but no frequency. The `*_frequency_unavailable` columns say which
side, deliberately kept separate from the speed comparison so a partial event is
still usable.

**Also worth considering:** an animal that genuinely stops moving on encountering
food has no oscillation to measure. Missing frequency after entry can be the
biological result rather than a measurement failure — which is precisely why the
column is reported rather than imputed.

### `decision_transparency_error.txt` appears instead of the manifest

**What this means:** on versions before v11.118, the manifest write referenced an
undefined variable and failed on every run, leaving only this stub. The analysis
itself was unaffected — no measurement depended on it — but the provenance record
was never written. On current versions `decision_transparency.json` is produced
normally. If you see the stub, the run predates the fix.

### Tracks are stitched that should not be, or vice versa

**What this usually means:** the stitching thresholds
(`max_stitch_gap_s`, `max_stitch_distance_px`, `max_heading_change_deg`) decide
when two fragments are treated as one animal. Every join is exported to
`inferred_tracklet_stitches.csv` precisely so it can be audited rather than
trusted.

**Also worth considering:** a plate where animals frequently touch will generate
genuinely ambiguous fragments, and no threshold setting resolves that cleanly.
The exported stitch list is the place to check what the tool assumed.
