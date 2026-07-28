# WINK — Worm Imaging and Kinematics

**Vidal‑Gadea Molecular Neuroscience Lab · Illinois State University**

WINK (Worm Imaging and Kinematics; formerly *NIKE*) is a desktop analysis suite
for *C. elegans* behavior, physiology, and morphology. One window — the **Lab
Hub** — gathers every tool in one place: pick a tool, point it at a recording,
and it walks you through acquisition‑aware analysis with human review at each
step.

Three principles run through it:

- **Human‑in‑the‑loop.** The software *proposes*; you *review and correct*.
  Nothing biological is silently accepted, counted, or classified.
- **Honest labeling.** Tools marked **Ready** are technically validated. Tools
  marked **Experimental** are shown as such, never hidden or dressed up.
- **The plate is the unit of replication** — not the individual worm.

---

## What it does

| Area | Tools |
|------|-------|
| **Locomotion & kinematics** | single‑worm tracking (crawl / swim / burrow), body‑wave & foraging analysis, single‑worm and population swimming, basal slowing |
| **Sensory & mechanosensation** | evoked mechanosensation + habituation, population tap response, chemotaxis / thermotaxis / magnetotaxis orientation |
| **Physiology** | pharyngeal pumping, defecation (pBoc) cycles, calcium imaging (RGBCaMP, single‑channel GCaMP) |
| **Morphology** | muscle (myocyte / nonstriated) morphometry, pharynx morphometry |
| **Reproduction** | egg counting, egg laying |
| **Acquisition & utilities** | scale & magnification calculator, sample‑size planner, acquisition advisor, movie/format conversion |

A few tools run inside **Fiji/ImageJ** (labeled “(Fiji)”); the hub tells you
which and helps launch them.

---

## Getting started (from the zip in this folder)

1. **Download** the newest `WINK_Lab_Tools_…` zip from this folder.
2. **Extract** it to a folder on your computer (e.g., your Desktop). Keep the
   folder structure intact — don’t move individual files out of it.
3. Open the extracted folder and **double‑click `Launch_Lab_Hub.bat`**. The Lab
   Hub window opens (no console window appears).
4. In the hub, **drag a movie, image stack, or image folder onto the window**
   (or use **Load**), then click a tool. Ready tools launch; greyed‑out entries
   are tools that aren’t built yet — the map of what exists stays honest.

**Notes**

- Windows is the supported platform.
- Fiji‑based tools require **Fiji/ImageJ** installed; the hub points you to it.
- If a tool asks for scale (µm/pixel), use **Acquisition and utilities → Scale &
  magnification calculator** to compute or measure it.
- Your results, CSVs, and review sessions are saved in **your own data folders**,
  not inside the app — so updating the app never touches your data.

---

## Updates

**Today:** each new version is posted here as a new `WINK_Lab_Tools_…_v<number>`
zip. To update, download the newest zip and extract it fresh. Version numbers
increase over time (for example, v11.108); **higher means newer**. You can delete
old extracted copies once you’ve confirmed the new one runs — nothing important
lives inside the app folder.

**Coming soon — automated updates via GitHub.** WINK will check a GitHub release
channel on launch and offer a **one‑click update** when a new version is
available, so you won’t need to download and extract zips by hand. When that goes
live, this README will be updated with the details. (Lab machines on the shared
drive already update automatically; this brings the same convenience to everyone
sharing through this folder.)

---

## About & support

WINK is developed in the **Molecular Neuroscience Lab** of **Prof. Andrés
Vidal‑Gadea** at **Illinois State University**. Questions, bug reports, and
feature requests are welcome: **avidal@ilstu.edu**.
