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

## Installing WINK

The first time on a computer, use the installer. You do not install Python, the
scientific libraries, or Fiji yourself; the installer sets up a private copy of
everything and adds a Desktop shortcut.

1. **Download** a WINK installer. Two options:
   * **WINK_Installer_Online** (about 7 MB): small download, but needs internet
     during setup while it fetches Python, the libraries, and Fiji.
   * **WINK_Installer_Offline** (about 900 MB): needs no internet; everything is
     bundled.
2. **Extract the entire zip** to a folder (for example, your Desktop). Do not run
   the installer from inside the zip.
3. Double click **`Install_Lab_Tools.bat`** and wait while setup completes.
   Administrator rights are normally not needed.
4. Start WINK from the new **AGVG Lab Tools** Desktop shortcut.

Using WINK: drag a movie, image stack, or image folder onto the hub window (or
use **Load**), then click a tool. Ready tools launch; greyed out entries are
tools that are not built yet, so the map of what exists stays honest. If a tool
asks for scale (micrometres per pixel), use **Acquisition and utilities, Scale
and magnification calculator**.

Notes:

* Windows 10 or 11, 64-bit, with about 4 GB free.
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

WINK builds on methods and tools from the wider C. elegans and computer vision communities. Tierpsy Tracker informs several behavioral feature definitions and the WCON conventions WINK reads and compares against (Javer et al., 2018). wrMTrck inspired the fast first pass and the body axis oscillation proxy used in population locomotion (Brooks et al., 2016; wrMTrck by Jesper S. Pedersen). PumpKin inspired the local motion pharyngeal pumping detector (PumpKin, 2026). Eigenworm posture decomposition underlies part of the kinematics (Stephens et al., 2008). Anatomical references follow WormAtlas (Altun et al., WormAtlas).

* **Tierpsy Tracker** Tierpsy Tracker / WCON: Javer, A., Currie, M. A., Lee, C. W., et al. “An open source platform for analyzing and sharing worm behaviour data.” Nature Methods (2018). The Tierpsy materials explicitly describe the platform and cite this paper. This informs several behavioral feature definitions and the WCON conventions WINK reads and compares against.
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
