# NIKE Lab Tools v11.44

- Population Swimming again defaults to the robust evenly sampled two-pass background.
- The single-pass initial-segment background remains available but is unchecked and labeled experimental.
- Real-file profiling on `vid_0023.mp4` showed that clean two-pass segmentation retained 26 candidate tracks and completed in 116.1 seconds; skeleton graph work consumed only 2.27 seconds.
- This prevents a nominal decoding shortcut from creating hundreds of false track fragments and a much larger downstream workload.
