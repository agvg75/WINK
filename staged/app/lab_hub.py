"""
lab_hub.py
=========
One window that gathers every lab tool in one place. Ready tools launch; tools
we have not built yet are shown greyed so the map of what exists stays honest.

Drop a movie, stack, or folder onto the window (or use Load), and the movie
tools act on it directly. Everything launches as its own separate process, so
one tool crashing never takes down the hub, and each opens with no console.

Launch by double-clicking Launch_Lab_Hub.bat. Drag-and-drop needs the optional
tkinterdnd2 library; without it the window still works through the Load button
and simply hides the drop hint.

The tool list is data (REGISTRY below): add a tool by adding one entry. Each
entry says where its file lives and how to launch it; the hub resolves the file
on this machine and disables the button if it is not found, rather than failing
at click time.
"""
from __future__ import annotations

import os
import sys
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog, messagebox
from run_feedback import BRIEFINGS, RunFeedbackStore, ToolBriefing, show_first_run_briefing
from updater import ApplicationUpdater, UpdateError
from acquisition_advisor import show_acquisition_advisor
from flow_layout import (FlowFrame, fit_tree_column, keep_panes_usable,
                         set_minimum_size, wrap_to_width)

# Optional: the theme must never be able to stop the Hub from opening.
try:
    import theme_lcars as _theme
except Exception:                                          # pragma: no cover
    _theme = None

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
LOGO_PATH = next(
    (p for p in (ROOT / "resources" / "WINK_logo.png",
                 ROOT / "resources" / "NIKE_logo.png") if p.is_file()),
    ROOT / "resources" / "WINK_logo.png")

# Palette derived from the WINK logo: slate-blue wordmark, sage-green arrows,
# dark-navy worm on an off-white ground.
SLATE = "#3E4F58"        # WINK wordmark - primary
SLATE_DARK = "#2C3B44"   # darker slate - subtitles, lab name
SAGE = "#688877"         # sage-green arrow accent from the logo
SLATE_SOFT = "#E4E9E7"   # soft slate-green tint for accent bars
WARM_WHITE = "#FAFAF7"   # off-white matching the logo ground
PANEL = "#EEF1F0"
TEXT = "#22303A"
MUTED = "#5E6E76"

# Optional drag-and-drop support
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _BASE = TkinterDnD.Tk
    HAS_DND = True
except Exception:
    _BASE = tk.Tk
    HAS_DND = False


# --------------------------------------------------------------------------- #
# Tool registry
# --------------------------------------------------------------------------- #
@dataclass
class Tool:
    name: str
    desc: str
    section: str
    kind: str                 # "python" | "fiji" | "external"
    status: str               # "ready" | "coming"
    filename: str = ""        # script or macro filename to find
    takes_movie: bool = False # movie tools receive the loaded file as an argument
    search: list = field(default_factory=list)  # extra relative dirs to look in
    requires: str = ""          # concise entry bar shown beside the description
    one_line: str = ""
    validation_level: str = ""
    configured_path: str = ""

    def __post_init__(self):
        if not self.one_line:
            self.one_line = self.desc.split(".")[0].strip() + "."
        if not self.validation_level:
            self.validation_level = (
                "computational_regression"
                if "Experimental" in self.name else "technical_validation")


REGISTRY = [
    # --- Motor and behavioral output: locomotion ---
    # Andres: this should live in the Hub - a tab just for him showing the
    # whole lab, and every student seeing their own data arranged their way.
    # Registered as a tool rather than a new pane because the Hub's rail is
    # categories, not tabs, and adding a category is a much smaller change
    # than restructuring the body.
    Tool("My data",
         "Your experiments, arranged the way you arranged them. The lab lead "
         "sees the whole lab. Reads the shared folder catalogue; opens "
         "nothing and moves nothing.",
         "Acquisition and utilities", "python", "ready",
         "app/my_data.py",
         requires="initials set on the Hub; a shared folder catalogue"),
    Tool("Track one worm (crawl, swim, burrow)",
         "Track one visible worm and export signed body kinematics using an assay-specific mode.",
         "Motor output - Locomotion", "python", "ready",
         "tools/worm_kinematics/dic_tracker/run_dic_kinematics.py",
         requires="declared FPS, scale, exposure; resolution depends on selected mode"),
    Tool("Kinematics extractor (Fiji)", "Draw and approve the midline, export the CSV.",
         "Motor output - Locomotion", "fiji", "ready", "tools/worm_kinematics/WormKinematics_patch.java"),
    Tool("Kinematics analysis", "Body wave, locomotion, foraging, dampening from a recording CSV.",
         "Motor output - Locomotion", "python", "ready", "tools/worm_kinematics/run_one_kinematics_launcher.py"),
    Tool("Kinematics browser", "Browse one recording's kinematics results and figures.",
         "Motor output - Locomotion", "python", "ready", "tools/worm_kinematics/kinematics_browser_launcher.py"),
    Tool("Population results movie",
         "Render one population-tracking run as a movie: the plate with every "
         "animal's spine and trail, per-animal speed, proposed modality as a "
         "bout timeline, and how many animals were actually tracked frame by "
         "frame. Surfaces the run's own tracking-quality columns rather than "
         "averaging them away, and measures nothing itself.",
         "Motor output - Locomotion", "python", "ready",
         "tools/population_swimming/population_movie_launcher.py",
         requires="a population-tracking results folder (detections_and_tracks.csv, "
                  "analysis_metadata.json) and, for the plate panel, the recording "
                  "it was tracked on"),
    Tool("Kinematics results movie",
         "Render one tracked recording as a movie: the frame with its midline, "
         "head and tail overlaid, head-bend, centroid speed and a curvature "
         "kymograph on one time cursor. Plays at real time whatever the frame "
         "decimation, and ticks every needs_help frame on each trace. Renders "
         "what the tracker already exported and measures nothing itself.",
         "Motor output - Locomotion", "python", "ready",
         "tools/worm_kinematics/kinematics_movie_launcher.py",
         requires="a kinematics CSV from Track one worm (frame, time_s, segment, "
                  "seg_curv_deg, fps), and the image stack or folder it was "
                  "tracked on for the overlay panel"),
    Tool("Single-worm swimming analysis", "Measure swim frequency, occupancy, amplitude, phase, and usable coverage from a swimming track.",
         "Motor output - Locomotion", "python", "ready", "tools/worm_kinematics/swimming_analysis_launcher.py",
         requires="a Track one worm CSV recorded in swimming mode"),
    Tool("Population tracking", "Track populations, optionally include/exclude drawn ROIs, and visually review proposed swimming, crawling, burrowing, and uncertain bouts.",
         "Motor output - Locomotion", "python", "ready", "tools/population_swimming/population_swimming_tool.py",
         takes_movie=True,
         requires="MP4/movie, TIFF stack, or sequential image folder; declared FPS and scale"),
    Tool("Swimming fatigue and endurance (Experimental)",
         "Review swimming frequency and amplitude across a bout, including valid flat trajectories, collapse, and recovery.",
         "Motor output - Locomotion", "python", "ready",
         "tools/swimming_fatigue_tool.py",
         requires="reviewed per-worm swimming time series with plate identity, frequency, amplitude, and recovery phase"),
    Tool("Longitudinal decline / healthspan (Experimental)",
         "Maintain cohort and plate identity across adult ages and review repeated performance trajectories.",
         "Motor output - Locomotion", "python", "ready",
         "tools/healthspan_tool.py",
         requires="reviewed repeated-session table with cohort, plate, adult age, and one declared measurement"),
    Tool("Burrowing against graded resistance (Experimental)",
         "Review depth trajectories, stalls, resistance, and censored no-penetration outcomes.",
         "Motor output - Locomotion", "python", "ready",
         "tools/burrowing_tool.py",
         requires="reviewed burrowing-mode tracks with depth calibration, resistance, plate, worm, and time"),
    Tool("Population basal slowing",
         "Track many worms and compare paired velocity and body-axis bending before versus after OP50 lawn entry.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/basal_slowing/basal_slowing_tool.py",
         requires="sequential frames; declared FPS and scale; student-drawn starting-drop and OP50 lawn ROIs"),
    Tool("Mechanosensation (Experimental)",
         "Score and review tap, nose-touch, gentle-touch, or harsh-touch trials while preserving trial number, denominator, baseline, and motor kinematics.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/mechanosensation/mechanosensation_tool.py",
         requires="stimulus-aligned track CSV; declared constants; prior locomotor state; matched spontaneous baseline; reviewed events"),
    Tool("Population tap response / habituation (Experimental)",
         "Detect plate taps from the global field motion (intensity, duration, frequency), then split each worm's centroid track before/after each tap to report which animals responded by speed and/or direction, and the population response fraction per tap.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/mechanosensation/population_tap_tool.py",
         requires="a Population swimming tracks CSV (track_id, frame, x, y) and the movie for the tap signal; declared FPS and scale"),
    Tool("Paralysis pharmacology (Experimental)",
         "Review repeated prod observations and export plate-level aldicarb, levamisole, or vehicle fraction-moving and censored time-to-paralysis curves.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/paralysis_pharmacology/paralysis_tool.py",
         requires="plate and worm IDs; repeated times; drug and concentration; reviewed moving/paralyzed/excluded scores"),
    Tool("wrMTrck (Fiji)", "Track many worms in a stack with the wrMTrck plugin (run from Fiji).",
         "Motor output - Locomotion", "fiji", "ready", "",
         validation_level="external"),
    Tool("Tierpsy Tracker (External)",
         "Launch an installed Tierpsy Tracker. Tierpsy-defined WCON and feature outputs do not carry WINK validation stamps, QC, or plate-as-replicate definitions.",
         "Motor output - Locomotion", "external", "ready", "",
         requires="an independently installed Tierpsy; configure TIERPSY_PATH or install in a standard location",
         one_line="Launch an independently installed Tierpsy Tracker.",
         validation_level="external"),
    Tool("Population orientation (Plate state)", "Measure identity-free ROI occupancy, distributions, arrival, and plate-level orientation.",
         "Motor output - Sensory-guided behavior", "python", "ready", "tools/population_orientation/population_orientation_tool.py",
         requires="plate ID, declared FPS, two-point scale calibration, stimulus/control/release positions"),
    Tool("Combine orientation plates", "Run circular statistics across independent plate resultants without pooling worms.",
         "Motor output - Sensory-guided behavior", "python", "ready", "tools/population_orientation/aggregate_plates_tool.py",
         requires="two or more plate_resultant.csv files"),
    Tool("Magnetotaxis workbench (Experimental)",
         "Tier 1 plate-state plus computational-regression Tier 2 dual-clock, state-covariate, censored-departure, and within-plate regime analyses; Config 2 technical validation remains open.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/orientation_assays/magnetotaxis_tool.py",
         requires="Tier 1 plate-state results; SI magnet parameters and uncertainty; humidity, a real time-off-OP50 zero, age, genotype; multiple magnet orientations for causal certification; reviewed spine quality for turn modes"),
    Tool("Sample planner - how many more?",
         "Paste group values or load a module's plate-level CSV, and it checks the data (outliers, normality, equal variance), picks the honest test (Welch t / Mann-Whitney / Welch ANOVA / Kruskal-Wallis), and shows the effect, current power, and how many more replicates you still need - with the plate as the unit. Opens in your browser; runs offline.",
         "Acquisition and utilities", "python", "ready",
         "tools/power_analysis/power_planner.py",
         requires="two or more groups of plate/well-level values, pasted or loaded from a CSV"),
    Tool("Scale & magnification calculator",
         "Work out micrometres-per-pixel from the scope + zoom + camera (presets for the lab's Olympus SZX12 scopes, Zeiss Axioscope, and cameras), or measure it directly by drawing a scale bar on a frame. Includes a 1.14 mm adult-worm sanity check. Copy the value into any module.",
         "Acquisition and utilities", "python", "ready",
         "tools/scale_tools/scale_calculator.py",
         requires="a scope/camera choice, or a frame with a feature of known length"),
    Tool("Failure library browser (Experimental)",
         "Browse before/after image pairs where a module's automatic result was wrong and a person corrected it. Modules capture these as students work, so failure patterns can be spotted and turned into fixes and regression cases.",
         "Acquisition and utilities", "python", "ready",
         "tools/failure_library/failure_gallery.py",
         requires="a folder where a module wrote failure entries (before.png / after.png / meta.json), e.g. the myocyte morphometry output folder"),
    Tool("Thermotaxis workbench (Experimental)",
         "Analyze linear or radial thermotaxis with cultivation, feeding, calibration, migration, and isothermal safeguards.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/orientation_assays/thermotaxis_tool.py",
         requires="reviewed track CSV; cultivation temperature; feeding state; spatial temperature calibration; declared geometry"),
    Tool("Chemotaxis and avoidance workbench (Experimental)",
         "Compute endpoint indices against chance and use tracked gradients as a positive control for the shared orientation analyzer.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/orientation_assays/chemotaxis_tool.py",
         requires="reviewed track CSV or endpoint counts; declared source model and uncertainty; stimulus rotations for certification"),
    Tool("Area-restricted search (Experimental)",
         "Review reversal and omega-event time courses after food removal without forcing a local-search elevation.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/area_restricted_search_tool.py",
         requires="reviewed reversal/omega events, observable duration, plate identity, and food-removal time"),
    Tool("Roaming versus dwelling (Experimental)",
         "Review speed/angular-velocity state assignments, transitions, and valid single-state outcomes.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/roaming_dwelling_tool.py",
         requires="reviewed per-worm tracks with plate identity, speed, angular velocity, and time"),
    Tool("Quiescence and sleep (Experimental)",
         "Review long-recording motion states, quiescent bouts, and valid zero-quiescence outcomes.",
         "Motor output - Sensory-guided behavior", "python", "ready",
         "tools/quiescence_tool.py",
         requires="long reviewed recording with plate/worm identity, calibrated speed, time, and declared bout threshold"),

    # --- Motor and behavioral output: rhythmic programs ---
    Tool("Pharyngeal pumping", "Select a clearly visible interval and quantify reviewed pump events.",
         "Motor output - Rhythmic programs", "python", "ready", "tools/pharyngeal_pumping/pumping_tool.py",
         requires="declared FPS; clearly resolved pharynx"),
    Tool("Defecation cycle analysis",
         "Review candidate pBoc contractions using posterior axial motion, recovery, and editable cycle limits.",
         "Motor output - Rhythmic programs", "python", "ready", "tools/defecation/pboc_tool.py",
         requires="declared FPS, scale, exposure; visible posterior for 1 to 3 s"),
    Tool("Pharynx template placement",
         "Place, review and export the T12 pharynx template on a stack - the "
         "student-facing step that turns an image into a scored pharynx.",
         "Anatomy and morphology", "python", "ready",
         "tools/pharynx_morphometry/pharynx_tool.py",
         requires="a stack with a clearly resolved pharynx and a declared scale"),
    Tool("Endpoint egg counting", "Detect scale-matched eggs and correct the count in a mandatory visual review.",
         "Motor output - Rhythmic programs", "python", "ready", "tools/egg_counting/egg_counting_tool.py",
         requires="two-point scale calibration; image with resolved eggs"),
    Tool("Dynamic egg laying", "Detect persistent newly appearing eggs and review candidate laying times.",
         "Motor output - Rhythmic programs", "python", "ready", "tools/egg_counting/egg_laying_tool.py",
         requires="declared FPS, two-point scale calibration, resolved eggs over time"),

    # --- Physiology and cellular activity ---
    Tool("RGBCaMP extractor (Fiji)", "Track and measure the calcium channels in Fiji.",
         "Physiology - Calcium and cellular activity", "fiji", "ready", "tools/rgbcamp/fiji/WormRGBCaMPMap_v1.java"),
    Tool("RGBCaMP analysis", "Analyse one RGBCaMP recording CSV.",
         "Physiology - Calcium and cellular activity", "python", "ready", "tools/rgbcamp/pipeline/run_one_launcher.py"),
    Tool("RGBCaMP browser", "Browse one RGBCaMP recording's results.",
         "Physiology - Calcium and cellular activity", "python", "ready", "tools/rgbcamp/pipeline/results_browser_launcher.py"),
    Tool("RGBCaMP results movie",
         "Render one recording as a movie: the worm with its measurement bands, a "
         "muscle diagram tinted per myocyte per channel, velocity, and a curvature "
         "kymograph, all on one time cursor. Renders what the CSV and the geometry "
         "sidecar already contain and measures nothing itself.",
         "Physiology - Calcium and cellular activity", "python", "ready",
         "tools/rgbcamp/pipeline/results_movie_launcher.py",
         requires="an exported recording CSV, its _geometry.json sidecar (extractor "
                  "must have 'Export geometry sidecar' ticked), 24 segments per side, "
                  "and the image folder for the worm panel"),
    Tool("Neuron tracker", "Track an anterior sensory neuron after validating scale/exposure; image sequences use bounded parallel loading.",
         "Physiology - Calcium and cellular activity", "python", "ready", "tools/afd_neuron/run_neuron_tracker.py"),
    Tool("Single-channel GCaMP (body / cell / orientation) (Experimental)",
         "Three jobs: assess whether body-wall GCaMP is separable enough to read worm outline/kinematics; track one elongated cell and its soma-to-tip long axis (position, brightness, translational and angular velocity); or both together.",
         "Physiology - Calcium and cellular activity", "python", "ready",
         "tools/single_channel_gcamp/gcamp_tool.py",
         requires="declared FPS, scale, exposure, bit depth, and channel; for cell jobs, a soma and process-tip seed; reviewed low-signal intervals"),
    Tool("GCaMP segmentation calibration",
         "Pick a representative frame and set the background sigma for a "
         "recording by watching the body/signal mask update live. Saves a "
         "calibration record only - it does not track, measure, or classify "
         "anything itself; the sigma chosen here is what the downstream "
         "single-channel tools use.",
         "Physiology - Calcium and cellular activity", "python", "ready",
         "tools/single_channel_gcamp/gcamp_recoverable_tool.py",
         requires="one representative frame from the acquisition being "
                  "calibrated; the dial is a multiplier, not a raw sigma, "
                  "because a raw value does not transfer between a bright and "
                  "a dark acquisition"),
    Tool("Cultured cell calcium (probe-aware) (Experimental)",
         "Calcium, redox and abundance in cultured human muscle cells, from "
         "myoblasts to myofibres and from striated to smooth. Asks which probe "
         "was used and refuses the measurements that probe cannot support - "
         "an irreversible indicator such as MitoSOX gets an accumulation rate "
         "and no decay constant; antibody staining gets abundance and no "
         "kinetics at all. For the shRNA layout it compares transfected "
         "against untransfected cells in the SAME field, normalising each "
         "treated cell to its own field's untransfected median, and reports "
         "the untransfected spread as the null band that a difference has to "
         "clear.",
         "Physiology - Calcium and cellular activity", "python", "ready",
         "tools/cell_calcium/cell_calcium_tool.py",
         requires="one subfolder per condition; declared probe, bit depth and "
                  "channel suffixes; a DIC or nuclear channel to segment on if "
                  "there is one, since segmenting on the calcium channel "
                  "biases the sample towards bright cells"),
    Tool("AFD_MTP (Fiji)", "The Fiji-plugin version of the AFD tracker.",
         "Physiology - Calcium and cellular activity", "fiji", "ready", "tools/afd_neuron/fiji/AFD_MTP_v7_gap_patch.java"),

    # --- Anatomy and morphology ---
    Tool("Myocyte morphometry", "Per-myocyte body-wall muscle morphometry: cell geometry, sarcomere number and spacing across the bands, and actin fibre waviness - with review and hand-correction of ticks and fibres before anything is saved.",
         "Anatomy and morphology", "python", "ready", "tools/morphology/myocyte_morphometry_tool.py",
         requires="a raw fluorescence image, the scale bar's printed length for calibration, and a hand-drawn boundary per myocyte"),
    Tool("Myocyte morphometry (Fiji, legacy)", "The original Fiji-macro version. Superseded by the Python tool above; kept for reproducing older measurements.",
         "Anatomy and morphology", "fiji", "ready", "tools/morphology/Myocyte_Morphometry.ijm"),
    Tool("Myocyte boundary proposer (Experimental)",
         "Propose body-wall myocyte boundaries in a confocal stack so morphometry "
         "becomes correcting rather than drawing. Finds boundaries from traced "
         "individual actin fibres - where fibres terminate, and where many "
         "converge on a cell's end - not from brightness, because both sides of a "
         "myocyte border are bright. Every line is a proposal for a human to "
         "judge; it measures nothing and decides no boundary. Refuses outright on "
         "a stack with no aligned fibrous signal rather than reporting whatever "
         "channel has the most texture.",
         "Anatomy and morphology", "python", "ready",
         "tools/morphology/myocyte_boundary_proposer.py",
         requires="a multi-plane confocal stack with a phalloidin (actin) channel "
                  "and its voxel size; region is read from the file and series names",
         validation_level="computational_regression"),
    Tool("Nonstriated muscle degeneration", "Measure pharyngeal, uterine, somatointestinal, or anal-depressor structure and force-vector geometry.",
         "Anatomy and morphology", "python", "ready", "tools/morphology/nonstriated_morphology_tool.py",
         requires="raw fluorescence image, scale calibration, tissue ROI, and body orientation"),
    Tool("Neurite annotation viewer",
         "Mark where a neurite runs in a confocal stack: orthogonal XY/XZ/YZ slices, start and end points, and correction anchors wherever the automatic path would go wrong. Saves a small sidecar next to the stack - it does no tracing itself.",
         "Anatomy and morphology", "python", "ready", "tools/neurite_viewer.py",
         requires="a confocal stack (LIF/CZI/ND2/OME-TIFF) with its voxel size, if traced lengths are to mean anything"),
    Tool("Trace marked neurites",
         "Trace, measure and export every neurite from an annotation sidecar - length, radius and volume. Headless: needs no viewer, so it runs on any station, including re-tracing old marks with new settings.",
         "Anatomy and morphology", "python", "ready", "tools/neurite_trace_runner.py",
         requires="an annotation sidecar written by the viewer, beside its stack"),

    # --- Acquisition and utilities ---
    Tool("Probe a movie", "Check what a file is and whether it suits calcium or behaviour.",
         "Acquisition and utilities", "python", "ready", "tools/movie/movie_probe_gui.py", takes_movie=True),
    Tool("Convert for Fiji", "Make one clean TIFF stack Fiji opens, from any codec.",
         "Acquisition and utilities", "python", "ready", "tools/movie/convert_gui.py", takes_movie=True),
    Tool("Supervised segmentation review",
         "Preview and lock a spatial or space-time object mask for compatible geometry tools; never changes fluorescence measurements.",
         "Acquisition and utilities", "python", "ready",
         "tools/segmentation_review_tool.py",
         requires="movie, stack, or common image sequence; explicit preview and Accept + Lock"),
    Tool("Install AGVGLab Fiji menu", "Add your Fiji tools to Plugins > AGVGLab so you stop dragging them in.",
         "Acquisition and utilities", "python", "ready", "fiji/install_menu.py"),
]


# Keep the Hub's scientific workflow stable even when tools are added to the
# registry in a different order. Any future, unrecognized categories are
# appended after these established groups rather than being hidden.
CATEGORY_ORDER = [
    "Motor output - Locomotion",
    "Motor output - Rhythmic programs",
    "Motor output - Sensory-guided behavior",
    "Physiology - Calcium and cellular activity",
    "Anatomy and morphology",
    "Acquisition and utilities",
]


def ask_update(parent, title, headline, changelog):
    """Yes/no dialog whose buttons are always reachable, however long the notes.

    This replaces messagebox.askyesno, which interpolated the whole changelog
    into its message. The native Windows message box sizes itself to fit its
    text with no cap and no scrolling, so a long changelog grew the dialog past
    the bottom of the screen and took OK and Cancel with it - leaving a modal
    window that could not be answered or dismissed, on a machine that had just
    opened an old release. Reported from a lab computer, 2026-08-04.

    Two things prevent it recurring:
      * the buttons are packed to the BOTTOM before the notes are added, so
        they claim their space first and the notes take what is left
      * the window is capped to a fraction of the screen and the notes scroll
    Escape and Return also answer it, so a dialog that somehow lands off-screen
    can still be dismissed from the keyboard.
    """
    win = tk.Toplevel(parent)
    win.title(title)
    sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
    w = max(420, min(720, int(sw * 0.55)))
    h = max(260, min(520, int(sh * 0.55)))
    win.geometry(f"{w}x{h}+{max((sw - w) // 2, 0)}+{max((sh - h) // 3, 0)}")
    win.minsize(400, 240)
    result = {"ok": False}

    def answer(ok):
        result["ok"] = ok
        win.destroy()

    # Buttons FIRST and pinned to the bottom: whatever the notes do, these keep
    # their space. This ordering is the fix, not decoration.
    bar = ttk.Frame(win, padding=(12, 10))
    bar.pack(side="bottom", fill="x")
    ttk.Button(bar, text="Not now", command=lambda: answer(False)
               ).pack(side="right")
    ttk.Button(bar, text="Install update", command=lambda: answer(True)
               ).pack(side="right", padx=(0, 8))

    ttk.Label(win, text=headline, wraplength=w - 40, justify="left",
              padding=(14, 12, 14, 6)).pack(side="top", fill="x")

    if changelog:
        body = ttk.Frame(win)
        body.pack(side="top", fill="both", expand=True, padx=14, pady=(0, 6))
        text = tk.Text(body, wrap="word", height=6, relief="flat",
                       borderwidth=1, padx=8, pady=6)
        scroll = ttk.Scrollbar(body, orient="vertical", command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", changelog)
        text.configure(state="disabled")

    win.bind("<Escape>", lambda _e: answer(False))
    win.bind("<Return>", lambda _e: answer(True))
    win.protocol("WM_DELETE_WINDOW", lambda: answer(False))
    try:
        win.transient(parent)
    except Exception:
        pass
    win.grab_set()
    win.focus_force()
    win.wait_window()
    return result["ok"]


def group_tools_by_category(registry=REGISTRY):
    grouped = {}
    for tool in registry:
        grouped.setdefault(tool.section, []).append(tool)

    ordered_sections = [section for section in CATEGORY_ORDER if section in grouped]
    ordered_sections.extend(section for section in grouped if section not in CATEGORY_ORDER)
    return {section: grouped[section] for section in ordered_sections}


# --------------------------------------------------------------------------- #
# Resolution and launching (testable without a GUI)
# --------------------------------------------------------------------------- #
def resolve_tool_path(tool: Tool, base: Path = ROOT) -> Optional[Path]:
    """Find the tool's file on this machine. Look in the hub folder first, then
    any extra search dirs the entry lists. Return None if not found."""
    if not tool.filename:
        return None
    candidates = [base / tool.filename]
    for c in candidates:
        try:
            if c.exists():
                return c.resolve()
        except Exception:
            pass
    return None


FIJI_CANDIDATES = [
    r"C:\Fiji\fiji-windows-x64.exe",
    r"C:\Fiji.app\ImageJ-win64.exe",
    r"C:\Program Files\Fiji.app\ImageJ-win64.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Fiji.app\ImageJ-win64.exe"),
    os.path.expandvars(
        r"%LOCALAPPDATA%\AGVGLab\runtime_layer\Fiji.app\ImageJ-win64.exe"),
    os.path.expandvars(
        r"%LOCALAPPDATA%\AGVGLab\runtime_layer\Fiji.app\fiji-windows-x64.exe"),
    os.path.expandvars(r"%USERPROFILE%\Fiji.app\ImageJ-win64.exe"),
    os.path.expandvars(r"%USERPROFILE%\Desktop\Fiji.app\ImageJ-win64.exe"),
]


def find_fiji(candidates=FIJI_CANDIDATES) -> Optional[str]:
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return None


def _venv_python(base: Path = ROOT) -> str:
    """Find the Lab tools environment's pythonw, so tools run with numpy/scipy/
    scikit-image regardless of how the hub itself was started."""
    cands = [base / ".venv" / "Scripts" / "pythonw.exe",
             Path(os.path.expandvars(
                 r"%LOCALAPPDATA%\AGVGLab\runtime_layer\venv\Scripts\pythonw.exe")),
             Path(os.path.expandvars(r"%LOCALAPPDATA%\AGVGLab\runtime\Scripts\pythonw.exe")),
             Path(os.path.expandvars(r"%ProgramData%\LabTools\.venv\Scripts\pythonw.exe")),
             Path(os.path.expandvars(r"%LOCALAPPDATA%\LabTools\.venv\Scripts\pythonw.exe"))]
    for c in cands:
        try:
            if c.exists():
                return str(c)
        except Exception:
            pass
    return sys.executable


def launch_python(script: Path, movie: Optional[str] = None):
    """Launch a Python tool in the Lab tools environment (not the hub's own
    interpreter, which may lack the scientific libraries)."""
    args = [_venv_python(ROOT), str(script)]
    if movie:
        args.append(movie)
    subprocess.Popen(args, cwd=str(script.parent))


# --------------------------------------------------------------------------- #
# GUI
# --------------------------------------------------------------------------- #
class Hub(_BASE):
    def __init__(self):
        super().__init__()
        self.title("WINK - Worm Imaging and Kinematics")
        self.geometry("1280x760")
        self.minsize(980, 620)
        self.configure(bg=WARM_WHITE)
        self.movie: Optional[str] = None
        self.selected_tool: Optional[Tool] = None
        self.card_widgets = []
        self.feedback_store = RunFeedbackStore()
        self.updater = ApplicationUpdater(ROOT, github_repo="agvg75/WINK")
        self.versions = self.updater.local_versions()
        # FROM THE TREE, NOT FROM A FILE THAT CAN DISAGREE WITH IT. The
        # installed-version JSON is written at install time, so a Hub
        # started from `staged` displayed the last version INSTALLED
        # while running entirely different code. The one indicator
        # anyone would check could not detect the problem.
        import running_version
        self.running = running_version.describe()
        self.app_version = self.running["version"]
        self.runtime_version = self.versions.get("installed_runtime_version",
                                                 "unknown")
        self.title(f"WINK {running_version.title_suffix()}"
                   f" - Worm Imaging and Kinematics")
        self.filter_text = tk.StringVar()
        self.status_filter = tk.StringVar(value="All")
        self.all_tools_value = tk.StringVar(value="All tools")
        self._configure_styles()
        self._build_top_bar()
        self._build_body()
        self.filter_text.trace_add("write", lambda *_: self._filter_changed())
        self.status_filter.trace_add("write", lambda *_: self._rebuild_cards())
        self.after(50, self._select_first_category)
        self.after(1200, self._automatic_update_check)

    @staticmethod
    def _chip(tool):
        if tool.validation_level == "external":
            return "External"
        if tool.validation_level in {
                "technical_validation", "biological_validation",
                "publication_use"}:
            return "Ready"
        return "Experimental"

    def _external_path(self, tool):
        if tool.name.startswith("Tierpsy"):
            candidates = [
                os.environ.get("TIERPSY_PATH", ""),
                os.path.expandvars(
                    r"%LOCALAPPDATA%\Tierpsy\Tierpsy Tracker.exe"),
                r"C:\Tierpsy\Tierpsy Tracker.exe",
            ]
            return next((Path(path) for path in candidates
                         if path and Path(path).exists()), None)
        return None

    def _availability(self, tool):
        if tool.kind == "external":
            return self._external_path(tool) is not None
        if tool.kind == "fiji" and not tool.filename:
            return find_fiji() is not None
        return tool.status == "ready" and (
            not tool.filename or resolve_tool_path(tool) is not None)

    def _build_top_bar(self):
        # A floor on the window size. Wrapping keeps every control reachable;
        # a floor keeps the layout legible - without it a determined drag turns
        # the toolbar into a vertical column of buttons, which is reachable and
        # useless.
        set_minimum_size(self, 860, 560)
        if _theme is not None:
            _theme.apply(self)          # honours the saved preference, off by default
        tk.Frame(self, bg=SAGE, height=7).pack(fill="x")
        header = tk.Frame(self, bg=WARM_WHITE)
        header.pack(fill="x", padx=18, pady=(10, 5))
        brand = tk.Frame(header, bg=WARM_WHITE)
        brand.pack(side="left", fill="y")
        tk.Label(brand, text=f"WINK v{self.app_version}",
                 font=("Segoe UI", 18, "bold"),
                 bg=WARM_WHITE, fg=SLATE).pack(anchor="w")
        tk.Label(brand, text="Worm Imaging and Kinematics",
                 font=("Segoe UI", 10, "bold"), bg=WARM_WHITE,
                 fg=SLATE_DARK).pack(anchor="w")
        tk.Label(brand, text="Molecular Neuroscience Lab",
                 font=("Segoe UI", 9), bg=WARM_WHITE,
                 fg=SLATE_DARK).pack(anchor="w")
        tk.Label(brand, text="Illinois State University",
                 font=("Segoe UI", 9), bg=WARM_WHITE,
                 fg=MUTED).pack(anchor="w")
        self._add_logo(header)

        # A FlowFrame, not a plain Frame packed left/right. Eleven controls in
        # one packed row is exactly the case Tk's pack handles worst: it does
        # not wrap, so narrowing the window makes the widgets that no longer
        # fit SILENTLY VANISH rather than move. The row still looks complete,
        # which is what made it read as the Hub losing features.
        controls = FlowFrame(self)
        controls.pack(fill="x", padx=18, pady=(2, 8))
        controls.add(ttk.Button(controls, text="Load movie / stack / folder",
                                command=self._load))
        controls.add(ttk.Button(controls, text="Plan a recording",
                                command=lambda: show_acquisition_advisor(self)))
        # Who is at this station. Set once here, stamped onto every run, so a
        # result found in 2031 resolves to a person rather than to a machine.
        # Placed on the Hub rather than in each tool because a student should
        # answer it once a session, not once a tool.
        try:
            import operator_identity
            field_widget = operator_identity.add_field(
                controls, on_change=lambda op: self._operator_changed(op))
            if field_widget is not None:
                controls.add(field_widget)
        except Exception as exc:      # never keep the Hub from opening
            print("operator field unavailable:", exc)
        self.movie_lbl = ttk.Label(controls, text="No movie loaded", width=26)
        controls.add(self.movie_lbl)
        controls.add(ttk.Label(controls, text="Filter"))
        self.filter_entry = ttk.Entry(
            controls, textvariable=self.filter_text, width=24)
        controls.add(self.filter_entry)
        values = [f"{tool.section} — {tool.name}" for tool in REGISTRY]
        self.all_tools = ttk.Combobox(
            controls, textvariable=self.all_tools_value, values=values,
            state="readonly", width=31)
        controls.add(self.all_tools)
        self.all_tools.bind("<<ComboboxSelected>>", self._all_tools_selected)
        controls.add(ttk.Label(controls, text="Status"))
        self.status_combo = ttk.Combobox(
            controls, textvariable=self.status_filter,
            values=["All", "Ready", "Experimental"], state="readonly",
            width=13)
        controls.add(self.status_combo)
        controls.add(ttk.Button(controls, text="Check for updates",
                                command=self._manual_update_check))
        controls.add(ttk.Button(controls, text="Revert update",
                                command=self._revert_update))
        controls.add(ttk.Label(
            controls,
            text=(f"App {self.versions['installed_app_version']} · "
                  f"Runtime {self.versions['installed_runtime_version']}")))
        if _theme is not None:
            tog = _theme.add_toggle(controls, self)
            if tog is not None:
                controls.add(tog)

        self.drop = tk.Label(
            self, text=("Drop a movie, stack, or folder here"
                        if HAS_DND else "Load a movie, stack, or folder above"),
            bg=SLATE_SOFT, fg=SLATE_DARK, height=1)
        self.drop.pack(fill="x", padx=18, pady=(0, 6))
        if HAS_DND:
            self.drop.drop_target_register(DND_FILES)
            self.drop.dnd_bind("<<Drop>>", self._on_drop)

    def _build_body(self):
        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18, pady=(0, 14))

        rail = ttk.Frame(body, width=220)
        body.add(rail, weight=0)
        ttk.Label(rail, text="CATEGORIES",
                  style="Section.TLabel").pack(anchor="w", pady=(4, 7))
        self.category_tree = ttk.Treeview(
            rail, show="tree", selectmode="browse", height=22,
            takefocus=True)
        self.category_tree.pack(fill="both", expand=True, padx=(0, 8))
        # The column has its own width, independent of the widget's, and Tk
        # defaults it to about 200px - so "Motor output - Rhythmic programs"
        # was cut with nothing to reveal the rest. Follow the rail.
        fit_tree_column(self.category_tree, rail)
        self.sections = group_tools_by_category()
        for section, tools in self.sections.items():
            self.category_tree.insert(
                "", "end", iid=section,
                text=f"{section}  ({len(tools)})")
        self.category_tree.bind(
            "<<TreeviewSelect>>", lambda _: self._category_selected())

        center = ttk.Frame(body)
        body.add(center, weight=3)
        self.grid_title = ttk.Label(
            center, text="Tools", style="Section.TLabel")
        self.grid_title.pack(anchor="w", pady=(4, 7))
        canvas_frame = ttk.Frame(center)
        canvas_frame.pack(fill="both", expand=True)
        self.card_canvas = tk.Canvas(
            canvas_frame, bg=WARM_WHITE, highlightthickness=0)
        scroll = ttk.Scrollbar(
            canvas_frame, orient="vertical",
            command=self.card_canvas.yview)
        self.card_inner = tk.Frame(self.card_canvas, bg=WARM_WHITE)
        self.card_window = self.card_canvas.create_window(
            (0, 0), window=self.card_inner, anchor="nw")
        self.card_canvas.configure(yscrollcommand=scroll.set)
        self.card_canvas.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.card_inner.bind("<Configure>", self._cards_content_resized)
        self.card_canvas.bind("<Configure>", self._canvas_resized)
        self._card_signature = None

        detail = ttk.Frame(body, width=310)
        body.add(detail, weight=1)
        self.detail_title = ttk.Label(
            detail, text="Choose a tool", style="DetailTitle.TLabel",
            wraplength=285)
        self.detail_title.pack(anchor="w", padx=(14, 4), pady=(6, 6))
        self.detail_chip = tk.Label(
            detail, text="", bg=PANEL, fg=TEXT, font=("Segoe UI", 9, "bold"))
        self.detail_chip.pack(anchor="w", padx=(14, 4))
        ttk.Separator(detail).pack(fill="x", padx=(14, 4), pady=10)
        ttk.Label(detail, text="What it measures",
                  style="Section.TLabel").pack(anchor="w", padx=(14, 4))
        self.detail_desc = ttk.Label(
            detail, text="Select a category and tool card to see details.",
            wraplength=285, justify="left")
        self.detail_desc.pack(anchor="w", padx=(14, 4), pady=(4, 14))
        ttk.Label(detail, text="Needs at load",
                  style="Section.TLabel").pack(anchor="w", padx=(14, 4))
        self.detail_requires = tk.Label(
            detail, text="—", bg=WARM_WHITE, fg=TEXT,
            font=("Consolas", 9), wraplength=285, justify="left")
        self.detail_requires.pack(anchor="w", padx=(14, 4), pady=(4, 14))
        self.launch_button = ttk.Button(
            detail, text="Launch", command=self._launch_selected)
        self.launch_button.pack(anchor="w", padx=(14, 4), pady=4)
        self.launch_button.state(["disabled"])
        # These three carried a FIXED wraplength, which is correct only at the
        # width someone measured once. This pane is user-resizable: narrow it
        # and the text overflows and is clipped; widen it and the space goes
        # unused. Follow the pane instead.
        for _lbl in (self.detail_title, self.detail_desc, self.detail_requires):
            wrap_to_width(_lbl, detail)

        # ttk.Panedwindow has no per-pane minimum, so a narrow window or a
        # dragged sash pushed the detail pane's Launch button past the edge
        # where it could not be clicked at all. Clamp the sashes instead.
        #
        # The rail's minimum is MEASURED from the longest category name rather
        # than guessed. A guess of 190px was tested and still cut "Motor output
        # - Sensory-guided behaviour (13)" in half, which is the same failure in
        # a new place: a number that was right for the text someone had in mind
        # when they wrote it. Categories are added over time; the floor should
        # follow them.
        keep_panes_usable(body, [self._rail_minimum(), 360, 260])

    def _rail_minimum(self, pad=52, floor=190, ceiling=400):
        """Wide enough for the longest category name, within reason."""
        try:
            font = tkfont.nametofont("TkDefaultFont")
            widest = max(font.measure(f"{name}  ({len(tools)})")
                         for name, tools in self.sections.items())
        except Exception:                                  # pragma: no cover
            return floor
        return int(min(max(widest + pad, floor), ceiling))

    def _configure_styles(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 9))
        style.configure("Lab.TFrame", background=WARM_WHITE)
        style.configure("Lab.TLabelframe", background=WARM_WHITE,
                        bordercolor="#BDCAC8", lightcolor="#BDCAC8",
                        darkcolor="#BDCAC8", relief="solid")
        style.configure("Lab.TLabelframe.Label", background=WARM_WHITE,
                        foreground=SLATE, font=("Segoe UI", 9, "bold"))
        style.configure("TFrame", background=WARM_WHITE)
        style.configure("TLabel", background=WARM_WHITE, foreground=TEXT)
        style.configure("TButton", background=SLATE, foreground="white",
                        bordercolor=SLATE_DARK, padding=(8, 5))
        style.map("TButton",
                  background=[("active", SLATE_DARK), ("disabled", "#CBD3D2")],
                  foreground=[("disabled", "#7A8A8E")])
        style.configure("Vertical.TScrollbar", background=SLATE_SOFT,
                        troughcolor=WARM_WHITE, arrowcolor=SLATE)
        style.configure("Section.TLabel", background=WARM_WHITE,
                        foreground=SLATE, font=("Segoe UI", 9, "bold"))
        style.configure("DetailTitle.TLabel", background=WARM_WHITE,
                        foreground=TEXT, font=("Segoe UI", 15, "bold"))
        style.configure("Treeview", rowheight=31, background=PANEL,
                        fieldbackground=PANEL, foreground=TEXT)
        style.map("Treeview", background=[("selected", SLATE)],
                  foreground=[("selected", "white")])

    def _add_logo(self, parent):
        """Place the WINK logo at the upper right without its large white rim."""
        try:
            from PIL import Image, ImageTk
            image = Image.open(LOGO_PATH).convert("RGBA")
            image.thumbnail((360, 120), Image.Resampling.LANCZOS)
            self.logo_image = ImageTk.PhotoImage(image)
            tk.Label(parent, image=self.logo_image, bg=WARM_WHITE,
                     bd=0).pack(side="right", padx=(12, 2), anchor="ne")
        except Exception:
            # The hub remains fully functional if the optional image is absent.
            self.logo_image = None

    def _select_first_category(self):
        first = next(iter(self.sections), None)
        if first:
            self.category_tree.selection_set(first)
            self.category_tree.focus(first)
            self._category_selected()

    def _automatic_update_check(self):
        # Being off-network or lacking L: is normal and intentionally silent.
        manifest = self.updater.check()
        if manifest:
            self._offer_update(manifest)

    def _manual_update_check(self):
        try:
            manifest = self.updater.check()
        except Exception as exc:
            messagebox.showerror("WINK updates", str(exc))
            return
        if not manifest:
            messagebox.showinfo(
                "WINK updates",
                "No newer compatible application update is available.")
            return
        self._offer_update(manifest)

    def _offer_update(self, manifest):
        changelog = manifest.get("changelog", "")
        if not ask_update(
                self, "WINK update available",
                f"Application {manifest['app_version']} is available. "
                f"Install it now? The runtime will not change.",
                changelog):
            return
        try:
            redirect = self.updater.apply(manifest)
        except UpdateError as exc:
            messagebox.showerror("WINK update not applied", str(exc))
            return
        except Exception as exc:
            messagebox.showerror(
                "WINK update not applied",
                f"The existing version was preserved.\n\n{exc}")
            return
        if redirect is not None:
            # NEVER RELAUNCH FROM ANOTHER TREE MID-SESSION. This used to
            # Popen the new folder's lab_hub.py and destroy this one, so a
            # session that began in one tree continued in a different one -
            # and because the version string came from an install-time file
            # rather than the tree, nothing on screen changed to say so.
            # Anyone testing a fix could be moved onto other code after
            # accepting a single dialog, and every observation afterwards was
            # about the wrong build.
            #
            # The update is prepared and the person closes and reopens. One
            # extra click, and the tree they are running is always the tree
            # they started.
            messagebox.showinfo(
                "WINK update ready",
                f"Version {manifest['app_version']} is published and "
                f"ready.\n\n"
                f"CLOSE this Hub and open WINK again to use it.\n\n"
                f"It has been prepared at:\n{redirect}\n\n"
                f"Nothing was changed in the copy you are running now, and "
                f"this window is still the version you started with "
                f"({self.app_version}).")
        else:
            messagebox.showinfo(
                "WINK update installed",
                "The application update is installed. Restart the Hub to use it.")

    def _revert_update(self):
        if not messagebox.askyesno(
                "Revert WINK update",
                "Restore the previous known-good application version? "
                "The runtime will not change."):
            return
        try:
            self.updater.revert()
        except Exception as exc:
            messagebox.showerror("Could not revert", str(exc))
            return
        messagebox.showinfo(
            "Previous version restored", "Restart the Hub to use it.")

    def _category_selected(self):
        if self.filter_text.get().strip():
            return
        selected = self.category_tree.selection()
        self.active_section = selected[0] if selected else None
        self._rebuild_cards()

    def _filter_changed(self):
        if self.filter_text.get().strip():
            self.category_tree.selection_remove(
                self.category_tree.selection())
            self.active_section = None
        self._rebuild_cards()

    def _visible_tools(self):
        query = self.filter_text.get().strip().lower()
        status = self.status_filter.get()
        tools = (REGISTRY if query or not getattr(
            self, "active_section", None)
                 else self.sections.get(self.active_section, []))
        output = []
        for tool in tools:
            haystack = " ".join([
                tool.name, tool.section, tool.one_line,
                tool.desc, tool.requires]).lower()
            if query and query not in haystack:
                continue
            if status != "All" and self._chip(tool) != status:
                continue
            output.append(tool)
        return output

    def _canvas_resized(self, event):
        self.card_canvas.itemconfigure(
            self.card_window, width=event.width)
        self._rebuild_cards()

    def _cards_content_resized(self, _event=None):
        """Grow or shrink the scrollable area, and never leave the view
        stranded past the end of it.

        Rebuilding destroys every card, which momentarily collapses the
        content to nothing while Tk keeps the old pixel offset. Without the
        clamp the hub opens scrolled to the bottom of an empty view and looks
        like it has no tools at all.
        """
        try:
            bbox = self.card_canvas.bbox("all")
            if not bbox:
                return
            self.card_canvas.configure(scrollregion=bbox)
            region = bbox[3] - bbox[1]
            visible = self.card_canvas.winfo_height()
            if region <= 0:
                return
            highest = max(0, region - visible)
            if self.card_canvas.canvasy(0) > highest:
                self.card_canvas.yview_moveto(highest / region)
        except tk.TclError:
            pass

    def _rebuild_cards(self):
        if not hasattr(self, "card_inner"):
            return
        for child in self.card_inner.winfo_children():
            child.destroy()
        self.card_widgets = []
        width = max(320, self.card_canvas.winfo_width())
        columns = max(1, width // 265)
        tools = self._visible_tools()
        self.grid_title.config(text=(
            f"Search results ({len(tools)})"
            if self.filter_text.get().strip()
            else f"{getattr(self, 'active_section', 'All tools')} "
                 f"({len(tools)})"))
        for index, tool in enumerate(tools):
            card = self._make_card(tool)
            card.grid(
                row=index // columns, column=index % columns,
                sticky="nsew", padx=5, pady=5)
            self.card_widgets.append(card)
        for column in range(columns):
            self.card_inner.grid_columnconfigure(column, weight=1)
        if not tools:
            ttk.Label(
                self.card_inner,
                text="No tools match this view. Clear the filter or choose another status.",
                wraplength=420).grid(row=0, column=0, padx=20, pady=30)

        # A different set of tools is a different list, so it starts at the
        # top. A mere window resize is the SAME list and keeps the reader
        # where they were - scrolling them back would be its own small bug.
        signature = tuple(tool.name for tool in tools)
        if signature != getattr(self, "_card_signature", None):
            self._card_signature = signature
            self.card_canvas.yview_moveto(0)

    def _make_card(self, tool):
        active = tool is self.selected_tool
        frame = tk.Frame(
            self.card_inner, bg=("white" if not active else "#E7EDEB"),
            bd=1, relief="solid", highlightthickness=2,
            highlightbackground=(SLATE if active else "#C7D0CE"),
            highlightcolor=SLATE, takefocus=True, cursor="hand2")
        chip = self._chip(tool)
        available = self._availability(tool)
        chip_text = chip if available else f"{chip} · Not configured"
        tk.Label(
            frame, text=tool.name, bg=frame["bg"], fg=TEXT,
            font=("Segoe UI", 10, "bold"), wraplength=220,
            justify="left").pack(anchor="w", padx=10, pady=(9, 4))
        tk.Label(
            frame, text=tool.one_line, bg=frame["bg"], fg=MUTED,
            font=("Segoe UI", 9), wraplength=220,
            justify="left").pack(anchor="w", padx=10, pady=(0, 8))
        tk.Label(
            frame, text=chip_text, bg=(
                "#E1F0E4" if chip == "Ready" else
                "#F7E9C9" if chip == "Experimental" else "#E6E9F0"),
            fg=TEXT, font=("Segoe UI", 8, "bold"),
            padx=6, pady=2).pack(anchor="w", padx=10, pady=(0, 9))
        if self.filter_text.get().strip():
            tk.Label(
                frame, text=tool.section, bg=frame["bg"], fg=MUTED,
                font=("Segoe UI", 8, "italic"), wraplength=220,
                justify="left").pack(anchor="w", padx=10, pady=(0, 7))
        for widget in [frame, *frame.winfo_children()]:
            widget.bind("<Button-1>", lambda _, t=tool: self._select_tool(t))
            widget.bind("<Double-Button-1>",
                        lambda _, t=tool: self._select_and_launch(t))
        frame.bind("<Return>", lambda _, t=tool: self._select_tool(t))
        frame.bind("<space>", lambda _, t=tool: self._select_tool(t))
        frame.bind("<Left>", lambda _: self._focus_card(-1))
        frame.bind("<Right>", lambda _: self._focus_card(1))
        frame.bind("<Up>", lambda _: self._focus_card(-1))
        frame.bind("<Down>", lambda _: self._focus_card(1))
        return frame

    def _focus_card(self, delta):
        if not self.card_widgets:
            return
        current = self.focus_get()
        try:
            index = self.card_widgets.index(current)
        except ValueError:
            index = 0
        self.card_widgets[
            max(0, min(len(self.card_widgets) - 1, index + delta))].focus_set()

    def _select_tool(self, tool):
        self.selected_tool = tool
        chip = self._chip(tool)
        available = self._availability(tool)
        self.detail_title.config(text=tool.name)
        self.detail_chip.config(
            text=(chip if available else f"{chip} · Not configured"),
            bg=("#E1F0E4" if chip == "Ready" else
                "#F7E9C9" if chip == "Experimental" else "#E6E9F0"))
        self.detail_desc.config(text=tool.desc)
        needs = tool.requires or "No additional entry requirement declared."
        if tool.kind == "external" and not available:
            needs += (
                "\n\nNot configured. Set TIERPSY_PATH to the installed "
                "Tierpsy executable.")
        self.detail_requires.config(text=needs)
        self.launch_button.config(text=f"Launch {tool.name}")
        if available:
            self.launch_button.state(["!disabled"])
        else:
            self.launch_button.state(["disabled"])
        self._rebuild_cards()

    def _select_and_launch(self, tool):
        self._select_tool(tool)
        self._launch_selected()

    def _launch_selected(self):
        if not self.selected_tool:
            return
        tool = self.selected_tool
        path = (
            self._external_path(tool) if tool.kind == "external"
            else resolve_tool_path(tool))
        self._launch(tool, path)

    def _operator_changed(self, op):
        """Note the change to the console. The field itself shows the name.

        Deliberately not a dialog: the visible feedback is the full name
        sitting beside the initials, which stays on screen for the whole
        session. The failure to catch is a student working under the last
        person's initials, and only a persistent display catches that.
        """
        print("operator:", op.get("initials") or "unset",
              op.get("full_name") or "")

    def _all_tools_selected(self, _=None):
        value = self.all_tools_value.get()
        tool = next((
            item for item in REGISTRY
            if value == f"{item.section} — {item.name}"), None)
        if tool is None:
            return
        self.filter_text.set("")
        self.category_tree.selection_set(tool.section)
        self.category_tree.see(tool.section)
        self.active_section = tool.section
        self._rebuild_cards()
        self._select_tool(tool)

    # ---- movie loading ----
    def _load(self):
        p = filedialog.askopenfilename(
            title="Choose a movie or stack",
            filetypes=[("Movies and stacks", "*.avi *.mp4 *.mov *.mkv *.webm *.tif *.tiff"),
                       ("All files", "*.*")])
        if not p:
            p = filedialog.askdirectory(title="...or choose a folder of frames")
        if p:
            self._set_movie(p)

    def _on_drop(self, event):
        data = event.data.strip()
        if data.startswith("{") and data.endswith("}"):
            data = data[1:-1]
        data = data.split("} {")[0].strip("{}")
        if data:
            self._set_movie(data)

    def _set_movie(self, path):
        self.movie = path
        self.movie_lbl.config(text=Path(path).name)
        self.drop.config(text=Path(path).name, bg="#E7F0E5", fg="#31562D")

    # ---- launch ----
    def _launch(self, tool: Tool, path: Optional[Path]):
        briefing = BRIEFINGS.get(tool.name)
        if briefing is None:
            watch = tuple(
                item.strip() for item in tool.requires.split(";") if item.strip())
            briefing = ToolBriefing(
                tool.name, "0.1.0", "declared by the assay",
                watch or ("Confirm all acquisition constants before analysis.",),
                "The tool may refuse a measurement when its null or capability "
                "requirements are not met.")
        if not show_first_run_briefing(
                briefing, parent=self, store=self.feedback_store):
            return
        if tool.kind == "external":
            if path is None:
                messagebox.showinfo(
                    tool.name,
                    "Tierpsy is not configured. Install Tierpsy separately "
                    "and set the TIERPSY_PATH environment variable to its "
                    "executable.")
                return
            try:
                subprocess.Popen([str(path)])
            except Exception as exc:
                messagebox.showerror(
                    tool.name, f"Could not launch Tierpsy:\n{exc}")
        elif tool.kind == "python":
            if path is None:
                messagebox.showerror(tool.name, "Could not find this tool's file on this machine.")
                return
            movie = self.movie if tool.takes_movie else None
            try:
                launch_python(path, movie)
            except Exception as e:
                messagebox.showerror(tool.name, f"Could not launch:\n{e}")
        else:  # fiji
            self._launch_fiji(tool, path)

    def _fiji_running(self) -> bool:
        try:
            out = subprocess.run(["tasklist"], capture_output=True, text=True,
                                 timeout=6).stdout.lower()
            return any(k in out for k in ("imagej-win64", "imagej-win32", "fiji.exe"))
        except Exception:
            return False

    def _reveal(self, path: Optional[Path]):
        if path:
            try:
                os.startfile(str(Path(path).parent))
            except Exception:
                pass

    def _launch_fiji(self, tool: Tool, path: Optional[Path]):
        fiji = find_fiji()
        running = self._fiji_running()
        is_macro = bool(path) and str(path).lower().endswith(".ijm")

        # A macro can actually be executed by Fiji; a .java plugin cannot be run
        # from here (it is installed and launched from Fiji's menu).
        if is_macro and fiji:
            if messagebox.askyesno(tool.name, f"Run {tool.name} in Fiji now?"):
                try:
                    subprocess.Popen([fiji, "-macro", str(path)])
                except Exception as e:
                    messagebox.showerror(tool.name, f"Could not run the macro:\n{e}")
            return

        if running:
            # do NOT launch a second Fiji; just point the person to the open one
            messagebox.showinfo(
                tool.name,
                f"{tool.name} runs inside Fiji, and Fiji is already open.\n\n"
                f"Switch to the Fiji window and run it from the menu. "
                f"I'll open the folder holding the tool file.")
            self._reveal(path)
        elif fiji:
            if messagebox.askyesno(
                    tool.name,
                    f"{tool.name} runs inside Fiji, which is not open yet.\n\n"
                    f"Open Fiji now? Then run it from the Fiji menu."):
                try:
                    subprocess.Popen([fiji])
                except Exception as e:
                    messagebox.showerror(tool.name, f"Could not launch Fiji:\n{e}")
            self._reveal(path)
        else:
            messagebox.showinfo(
                tool.name,
                f"{tool.name} runs inside Fiji, but I could not find Fiji "
                f"automatically. Open Fiji yourself and run this tool from it. "
                f"I'll open the folder holding the file.")
            self._reveal(path)


def main():
    Hub().mainloop()


if __name__ == "__main__":
    main()
