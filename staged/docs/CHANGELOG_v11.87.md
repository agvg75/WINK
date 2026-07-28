# NIKE Lab Tools v11.87

## Sample planner — correct wiring + hardened CSV loader

v11.86 renamed the Acquisition-and-utilities entry to the browser-based
**"Sample planner: how many more?"** but its launch path still pointed at the
old Power analysis tkinter tool, so clicking it ran the old tool instead of the
planner. This release fixes that:

- A small **launcher** (`power_planner.py`) opens the offline planner page
  (`nike_sample_planner.html`) in your browser, and the hub entry now points to
  it. No server; runs offline.
- The planner's **CSV loader** now uses a **quote-aware parser**, so a module
  export with commas inside quoted fields loads correctly (the previous simple
  split could mis-split those rows).

The planner itself is unchanged in spirit: paste group values **or load a module
plate-level CSV** (choose the group and value columns), and it runs the data
checks (IQR outliers, Shapiro-Wilk normality, Levene variance), forks to the
honest test (Welch t / Mann-Whitney / Welch ANOVA / Kruskal-Wallis), and reports
the standardized effect, current power, and how many more replicate units you
need — with the plate as the unit (it refuses worm-level power for population
assays).

The planner's JavaScript was syntax-checked; the stats core is validated against
SciPy per its own notes.
