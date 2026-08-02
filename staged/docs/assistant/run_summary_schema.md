# Run summary schema

What a module writes for the assistant to read in **run mode**. One JSON object
per run, alongside the module's normal outputs, as
`assistant_run_summary.json`.

Already-computed values only — never raw logs. The assistant should reason from
numbers the module already validated, not parse verbose text.

**Omit fields that do not apply to a module.** Do not fill them with
placeholders; a missing field is information, a zero is a claim.

## Fields

```jsonc
{
  "module": "population_tracking",
  "module_version": "11.118",
  "run_id": "vid_0012_population_swimming_results",

  // Every parameter used, so the assistant can compare against the
  // typical ranges in the module documentation. Include units in the key
  // where the unit is not obvious - source pixels are a recurring trap.
  "parameters": {
    "declared_fps": 30.0,
    "scale_um_per_px": 2.0,
    "min_object_area_source_px": 885,
    "max_object_area_source_px": 5720,
    "max_link_source_px_per_frame": 60,
    "detection_scale": 0.25,
    "spine_skeleton_method": "morphological",
    "roi_mode": "none"
  },

  // Broken out per filter stage, so the assistant can say WHICH stage is
  // responsible rather than guessing. Counts are of objects, not frames.
  "detection_counts": {
    "candidates_before_filtering": 47893,
    "rejected_below_min_area": 28714,
    "rejected_above_max_area": 61,
    "rejected_outside_roi": 0,
    "retained": 19118
  },

  "frame_diagnostics": {
    "frames_processed": 1662,
    "frames_with_zero_detections": 12,
    "frames_outside_expected_count": 143,
    "expected_detections_per_frame": 10,   // from Mark all animals, if used
    "timestamp_gaps": []
  },

  // Whatever the module already computes. Names differ per module; the
  // module documentation explains each one.
  "signal_quality": {
    "spine_frames_attempted": 7557,
    "spine_frames_valid": 3880,
    "spine_success_fraction": 0.513,
    "spine_sampling_stride_frames": 2,
    "median_track_coverage": 0.588
  },

  "environment": {
    "source_width": 3840,
    "source_height": 2160,
    "declared_fps": 30.0,
    "source_kind": "video",
    "lossy_compressed": true
  },

  // Verbatim, in the module's own words. Often the most direct signal.
  "warnings": [
    "spine_skeleton_method=morphological produced no valid skeleton on 3677 attempted frames"
  ],

  // A path only. The assistant does NOT receive or interpret the image; it
  // may tell the student which frame is worth looking at.
  "preview_frames": [
    { "frame": 840, "path": "preview_0840.png", "why": "median detection count" }
  ],

  // Optional: outcome counts a human review produced, when one has run.
  "review_outcome": {
    "candidate_tracks": 111,
    "accepted_tracks": 19,
    "manual_points_added": 0,
    "bouts_reviewed": 17,
    "final_labels": { "swimming": 15, "burrowing": 1, "unlabelled": 1 }
  }
}
```

## Why per-stage rejection counts matter

The single most useful diagnostic in Population tracking is *which* filter
removed the objects. "Few detections" has at least three unrelated causes —
gates wrong for the magnification, animals absorbed into the background because
they were stationary, or an ROI excluding them — and the stage counts separate
them immediately. Without them the assistant is reduced to guessing, which is
exactly what the system prompt forbids.

## What is already available

For Population tracking, most of this exists and only needs collecting:

- `parameters`, `environment` — `analysis_metadata.json`
- `signal_quality` — `spine_frames_used` / `spine_frames_attempted` /
  `spine_sampling_rate_hz` on the modality windows (v11.117+), plus
  `track_summary.csv`
- `review_outcome` — `reviewed_track_summary.csv`,
  `reviewed_modality_summary.csv`
- `frame_diagnostics` — derivable from `detections_and_tracks.csv`

**`detection_counts` is the real gap.** The per-stage tallies are not currently
recorded anywhere: the detector knows how many components it found and how many
passed the area gates, but writes neither. That is the one piece of new
instrumentation phase 2 needs.

For basal slowing, `analysis_metadata.json` and `decision_transparency.json`
(v11.118+) already cover parameters and definitions; the exclusion-reason
tallies from `paired_entry_events.csv` map naturally onto `detection_counts`.

## Writing it

The summary should be produced by the module at the end of a run, not
reconstructed later by the assistant layer — the module is the only thing that
knows its own stage counts. It is worth having independently of the assistant,
since it is also the cleanest per-run diagnostic for a person to read.
