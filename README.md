# WINK: Worm Imaging and Kinematics

**Vidal-Gadea Molecular Neuroscience Lab, Illinois State University**

WINK (Worm Imaging and Kinematics; formerly NIKE) is a free desktop software
suite for *C. elegans* behavior, physiology, and morphology. It is one
application, the Lab Hub, that gathers many analysis tools in a single window.
You pick a tool, point it at a recording, and it guides you through
acquisition aware analysis with a person reviewing the result at every step.

Three principles run through it:

1. **A person stays in the loop.** The software proposes; you review and correct.
   Nothing biological is silently accepted, counted, or classified.
2. **Honest labeling.** Tools marked **Ready** are technically validated. Tools
   marked **Experimental** are shown as such, never hidden or dressed up.
3. **The plate is the unit of replication**, not the individual worm.

## What it does

| Area | Tools |
|------|-------|
| Locomotion and kinematics | single worm tracking (crawl, swim, burrow), body wave and foraging analysis, single worm and population swimming, basal slowing |
| Sensory and mechanosensation | evoked mechanosensation and habituation, population tap response, chemotaxis, thermotaxis, and magnetotaxis orientation |
| Physiology | pharyngeal pumping, defecation (pBoc) cycles, calcium imaging (RGBCaMP, single channel GCaMP) |
| Morphology | muscle (myocyte and nonstriated) morphometry, pharynx morphometry |
| Reproduction | egg counting, egg laying |
| Acquisition and utilities | scale and magnification calculator, sample size planner, acquisition advisor, movie and format conversion |

A few tools run inside Fiji/ImageJ (labeled "(Fiji)"); the hub tells you which
and helps launch them.

## Getting started (from the zip in this folder)

1. **Download** the newest `WINK_Lab_Tools_...` zip.
2. **Extract** it to a folder on your computer (for example, your Desktop). Keep
   the folder structure intact, and do not move individual files out of it.
3. Open the extracted folder and **double click `Launch_Lab_Hub.bat`**. The Lab
   Hub window opens (no console window appears).
4. In the hub, **drag a movie, image stack, or image folder onto the window**
   (or use **Load**), then click a tool. Ready tools launch; greyed out entries
   are tools that are not built yet, so the map of what exists stays honest.

Notes:

* Windows is the supported platform.
* Fiji based tools require Fiji/ImageJ installed; the hub points you to it.
* If a tool asks for scale (micrometres per pixel), use **Acquisition and
  utilities, Scale and magnification calculator** to compute or measure it.
* Your results, CSV files, and review sessions are saved in your own data
  folders, not inside the app, so updating never touches your data.

## Updates

Each new version is posted as a new `WINK_Lab_Tools_..._v<number>` zip, and the
app can also update itself. Version numbers increase over time (for example,
v11.111); higher means newer.

* **On the lab network**, WINK updates automatically from the shared drive.
* **Off the lab network**, WINK checks its GitHub releases
  (github.com/agvg75/WINK) on launch and offers a one click update when a newer
  version is available. You can also just download the newest zip and extract it
  fresh.

## Acknowledgements and references

WINK builds on methods and tools from the wider *C. elegans* and computer vision
communities. The list below names the work each part draws on. Where a citation
is marked TODO, please complete it (authors, year, journal, DOI) before any
formal release.

* **Tierpsy Tracker** informs several behavioral feature definitions and the
  WCON conventions WINK reads and compares against.
  Javer et al., "An open source platform for analyzing and sharing worm
  behaviour data," Nature Methods, 2018.
* **wrMTrck** inspired the fast first pass and the body axis oscillation proxy
  used in population locomotion. wrMTrck ImageJ plugin, Jesper S. Pedersen.
  TODO: confirm the citation you wish to use (for example, Nussbaum-Krammer et
  al., Journal of Visualized Experiments, 2015).
* **PumpKin** inspired the local motion pharyngeal pumping detector.
  TODO: add the PumpKin citation.
* **Eigenworm posture decomposition** underlies part of the kinematics.
  Stephens et al., "Dimensionality and dynamics in the behavior of C. elegans,"
  PLoS Computational Biology, 2008.
* The **myocyte morphometry** measurement set follows the metrics reported in
  Fazyl et al., Biology Open, 2026. TODO: add the full citation.
* Anatomical references follow **WormAtlas** (Altun, Hall, and colleagues,
  www.wormatlas.org).
* Core image and signal processing use standard methods (Shi and Tomasi corner
  detection, Lucas and Kanade optical flow, RANSAC robust estimation, and the
  Hilbert transform for phase) through the open source libraries OpenCV,
  scikit-image, SciPy, NumPy, pandas, Pillow, and Matplotlib.

The reference adult hermaphrodite length used for scale sanity checks is about
1.14 mm.

## About and support

WINK is developed in the Molecular Neuroscience Lab of Prof. Andres Vidal-Gadea
at Illinois State University. Questions, bug reports, and feature requests are
welcome: avidal@ilstu.edu.
