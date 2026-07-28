# NIKE 11.40

## Visible post-frame progress

Population Swimming now reports the stages that occur after the final decoded frame:

- Linking trajectories
- Selecting tracks for detailed spines
- Detailed spines for eligible tracks
- Orienting spines and calculating summaries
- Writing results and timing report

## Tighter selective-spine gate

- Detailed skeletons/spines are calculated only for tracks meeting the same scientific frequency-eligibility prerequisites used in the final report: at least 3 seconds duration, at least 55% temporal coverage, and no more than 5% collision-like frames.
- Short, sparse, or collision-contaminated fragments retain every-frame centroid, area, and ellipse measurements and remain visible for review, but no longer consume detailed-spine time when they cannot produce a reported frequency.
- Source timing, tracking, review flags, and output eligibility rules remain unchanged.
