# Population Basal Slowing (Experimental)

This tool tracks multiple moving worms and creates paired measurements before
and after each worm enters a student-drawn OP50 lawn.

## Recording requirements

- A folder of sequential TIFF, PNG, or JPEG frames.
- Declared frame rate and spatial calibration.
- Worms visible at sufficient contrast for centroid tracking.
- At least 3 seconds of usable recording on each side of an entry. Ten seconds
  is the default.

## Student workflow

1. Choose the recording folder.
2. Enter the declared FPS and micrometers per pixel.
3. Draw the central starting-drop ROI as an oval, rectangle, or polygon.
4. Draw and label all OP50 lawns in one persistent ROI window. Oval is the
   default. Add ROI commits each lawn; Undo removes the current or most recent
   lawn; Finish returns all lawns to the assay.
5. Adjust the before/after windows and outside buffer if needed.
6. Analyze.
7. Review every entry marker. Green events will be retained; orange or red
   events will be rejected unless the student deliberately accepts them.

The ROI editor provides Undo, Clear, Accept, and Cancel. The main window also
provides Undo last ROI and Clear ROIs. The same shared editor supports line
geometry for other assays that define an entry or crossing by a line.

ROIs are automatically saved as `basal_slowing_rois.json` beside the recording.
Load saved ROIs, or accept the prompt when reopening that folder, to change
analysis parameters without drawing them again. The analysis output also keeps
the exact ROI vertices and original oval/rectangle/polygon geometry.

The default entry definition is at least 50% of the segmented worm area inside
the lawn. This fraction is editable. The before window includes only positions
at least the specified buffer outside that lawn.

Tracking continues through lawn exit and later encounters. Each event reports
the encounter number, time since the first and previous encounters, cumulative
prior lawn exposure, lawn residence time, and post-exit velocity and frequency.
These columns support tests of habituation, cumulative exposure, recovery, and
mutant-specific encounter histories.

## Outputs

- `detections_and_tracks.csv`: frame-level positions, speed, ROI state, and QC.
- `detections_and_tracks_reviewed.csv`: the same records with manual track
  status added.
- `manual_track_review.csv`: accepted, rejected, needs-correction, or
  unreviewed status for each trajectory.
- `inferred_tracklet_stitches.csv`: auditable gaps joined using predicted
  position and aligned travel direction.
- `paired_entry_events.csv`: all candidate before/after comparisons.
- `reviewed_paired_entry_events.csv`: the student's final accepted events.
- `reviewed_summary.json`: descriptive means after review.
- `rois.json`: reusable ROI vertices.
- `analysis_metadata.json`: acquisition provenance and measurement definitions.
- `background_reference.png`: the detector's static reference.

Speed is reported in micrometers per second. Each cleaned worm mask is
skeletonized, reduced to its longest path, and resampled to 25 ordered spine
points. Frame-level outputs include spine length, signed midbody curvature, and
the full segment-curvature vector. Bend frequency is derived from midbody
curvature. Missing frequency is reported separately and does not reject an
otherwise usable speed comparison.

The starting ROI is a release gate. Unresolved animals in the initial droplet
are not measured. A trajectory becomes active at an observed exit, or at its
first individual detection outside when the animal could not be resolved
inside the droplet. Once active, it remains active even if it later re-enters
the starting ROI.

## QC and inference

Possible collisions, ambiguous crossings, frame-edge contact, short windows,
and unavailable frequency estimates are flagged. They are not silently
interpolated.

The track-review browser overlays centroids, yellow spines, track IDs, recent trails, ROI
boundaries, entries, and exits on the original stack. Scroll with the slider or
arrow keys. Outside tracks are lime, starting-drop tracks cyan, inside-lawn
tracks maroon, accepted tracks green, rejected tracks red, and tracks marked
for correction orange. Select a centroid to set the trajectory's manual status.

When tracking briefly loses a worm, a conservative second pass may join the
tracklets if the later track begins nearby, follows the predicted trajectory,
and has an aligned direction. A competing plausible continuation prevents the
merge. The original tracklet IDs and every inferred stitch remain in the
outputs.

The design is paired within worm. Retain `track_id` during statistical
analysis. Several entries from one worm are repeated observations and must not
be treated as independent animals. A mixed-effects or repeated-measures model
can test encounter number or elapsed time while accounting for worm identity.

The tool is incapable of returning a trustworthy paired measurement when
identity is ambiguous or either window has insufficient unambiguous frames.
