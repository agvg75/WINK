# NIKE Lab Tools v11.86

## New sample planner replaces the Power analysis workbench

The **Acquisition & utilities** power tool is now the **"Sample planner — how
many more?"** — an interactive page that opens in your browser and runs entirely
offline (no server, no network).

What it does:

- **Paste** two or more groups of plate/well-level values, **or** load a
  **module CSV directly** (new): choose the file, then pick the **group column**
  (genotype/condition) and the **value column** (the metric) and it fills the
  groups for you. This is the "bite" — point it straight at an assay export like
  `plate_trial_series.csv` or `reversal_window_metrics.csv`.
- Runs the data checks: **IQR outliers**, **Shapiro–Wilk** normality, **Levene**
  equal variance — each expandable to show the reasoning.
- Forks to the **honest test**: Welch's t / Mann–Whitney (two groups) or Welch
  ANOVA / Kruskal–Wallis (3+).
- Shows the **standardized effect**, **current power**, the **target n**, and
  **how many more** replicates you still need, on a power-vs-n curve — with the
  **plate (not the worm)** as the replication unit, and a pseudoreplication
  warning if you pick "worm" for a population assay.

The launcher opens the page; the previous tk workbench is retired (its old engine
file is left in place, unused). The CSV parsing and the statistics core were
checked.
