# Population Swimming

This tool analyzes low-magnification image sequences containing multiple worms. It uses a sampled median background, detects moving worm-sized objects, links detections, and exports per-frame and per-track tables.

Status: **Ready**. Automated identities, crossings, and modality proposals remain
visually reviewable; Ready status does not remove the QC safeguards.

Identity linking predicts each worm's continuing trajectory through crossings. A close alternative assignment is marked `crossing_ambiguous` rather than silently accepted. The primary swimming-frequency estimate is the lateral oscillation of the centroid around its slowly varying path. Signed midbody-curvature frequency is retained as a secondary diagnostic and fallback. Edge encounters, possible collisions, ambiguous crossings, and short tracks are flagged for human review. FPS and scale must be declared by the user.

The ROI editor includes a full-movie frame navigator. Use its slider, arrow
buttons, or keyboard arrow keys to verify an include/exclude ROI against early,
middle, and late frames before accepting it.

The trajectory reviewer supports conservative manual stitching. Shift-click two
non-overlapping fragments, click **Stitch**, inspect the frame gap and endpoint
distance, and confirm only if they are visibly the same animal. **Undo stitch**
reverts the latest join. Original automatic tracks are preserved;
`reviewed_detections_and_tracks.csv`, `track_summary_after_stitching.csv`, and
`track_stitch_edits.json` record the reviewed result and edit history.

A descriptive banner at the top of the reviewer reports total, accepted and
QC-flagged tracks, median duration, and the median/range/sample size of valid
frequency estimates.

The opening window accepts an inclusive 1-based start frame and an optional end
frame. A blank end frame means the end of the movie. Background construction,
detection, tracking, frequency, and summaries use only that selected interval;
CSV frame numbers still refer to the original recording.

Trajectory review is resumable. **Save progress** writes accept/reject choices,
stitched tracks, summaries, and stitch history immediately. Closing the window
also saves. Use **Resume existing results review** in the opening window to
continue later without rerunning detection.
# Population Swimming and Locomotion-Modality Analysis

The population tracker now proposes reviewable bouts of swimming, crawling,
burrowing, or uncertain locomotion. It does not treat those proposals as
ground truth.

Each detected worm is skeletonized to a consistently oriented 25-point spine.
Four-second overlapping windows combine:

- signed midbody-curvature frequency;
- C-, S-, and W-posture evidence from curvature topology;
- centroid velocity;
- anterior-to-posterior curvature-wave lag;
- spine coverage, collision, edge, and identity QC.

Typical starting criteria are swimming above 0.8 Hz with alternating C
postures, crawling at roughly 0.2--0.6 Hz with S postures, and burrowing below
0.5 Hz with persistent W postures and posterior wave propagation. Frequency
ranges overlap, so frequency alone never determines crawling versus
burrowing. Ambiguous evidence is exported as `uncertain`.

After trajectory review, the bout reviewer lets the user confirm, relabel, or
reject each proposal. Results include window-level evidence,
`reviewed_modality_bouts.csv`, and a per-modality summary of time, bout count,
frequency, and speed.

The reviewer also provides a frame slider and play/pause preview for every
bout, showing the original frames, oriented spine, current centroid, and bout
trajectory before the student assigns the final modality.

Spatial filtering is optional. With no ROIs, the complete frame is analyzed.
Students may draw any number of oval, rectangular, or polygon ROIs and choose:

- `include`: retain detections whose centroids fall inside the union of ROIs;
- `exclude`: suppress detections whose centroids fall inside the union of ROIs.

ROI shapes, original geometry, polygons, mode, and the centroid rule are saved
in `analysis_rois.json` and the analysis metadata.
