# NIKE 11.35

## Population Swimming candidate-local processing

- Fixes a major textured-scene bottleneck: component coordinates and spines are now extracted from each candidate's small bounding box.
- The prior implementation rescanned the complete original/proxy frame once per accepted candidate, multiplying work on frames containing many bacterial or illumination objects.
- Detection logic, thresholds, source-scale coordinates, areas, and spine metrics are unchanged.
- Progress now refreshes every five frames rather than every twenty, so active processing is visible sooner.
- Includes NIKE 11.34 automatic safe-resolution advice, proxy controls, adaptive backgrounds, and phase timing.
