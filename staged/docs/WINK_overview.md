# WINK — Worm Imaging and Kinematics

**What it is.** WINK is a free, open toolset built in the Vidal-Gadea Lab for measuring *C. elegans* behavior and physiology from video and confocal imaging. It grew out of a single worm tracker and has expanded into a full lab bench: locomotion, sensory behavior, rhythmic programs (pumping, defecation), calcium imaging, and body-wall muscle morphometry, all launched from one hub with a consistent interface, so a student who learns one tool already knows how the rest work.

**Who it's for.** Labs studying *C. elegans* behavior who want tracking and analysis they can actually see inside, rather than a black box. Every WINK tool is built around a simple rule: a human reviews and approves what the software proposes before any number counts as data. Nothing auto-publishes a measurement without a person checking it against the actual recording.

## What it does

WINK's ~40 tools are organized into a few groups:

- **Motor output — locomotion.** Track one worm across crawling, swimming, or burrowing; population-level tracking with automatic bout classification; swimming fatigue/endurance, healthspan decline, and burrowing-against-resistance assays.
- **Motor output — sensory-guided behavior.** Mechanosensation, tap habituation, thermotaxis, chemotaxis/avoidance, magnetotaxis, area-restricted search, roaming vs. dwelling.
- **Motor output — rhythmic programs.** Pharyngeal pumping, defecation motor program, and related periodic behaviors.
- **Physiology — calcium and cellular activity.** Single- and multi-channel GCaMP extraction, AFD neuron tracking, body/cell orientation.
- **Anatomy and morphology.** Body-wall muscle sarcomere morphometry (striated), nonstriated muscle (pharynx, uterine, anal depressor), with more 3D/confocal tools in development.
- **Acquisition and utilities.** Scale and magnification calculators, sample-size planning, plate-orientation combination, a failure-library browser for reviewing what went wrong on a run.

A handful of tools are explicitly labeled **Experimental** — usable, but not yet validated to the same standard as the rest. WINK says so rather than hiding it.

## How it works, in one sentence per idea

- **Review before it counts.** Automatic detection is a first pass a person accepts, edits, or overrides — never a silent final answer.
- **Calibration is a hard requirement, not a guess.** Missing scale or frame-rate information stops a measurement rather than quietly assuming a default.
- **Corrections aren't thrown away.** When a student overrides an automatic call, that correction is logged — building a real record of where the automatic detectors are and aren't reliable, and the raw material for improving them later.
- **One shell, many tools.** Every module shares the same cockpit-style window, so switching tools doesn't mean relearning a new interface.

## Getting started

1. Run `Setup_Lab_Tools.bat` once per lab computer.
2. Launch `Launch_Lab_Hub.bat` — this is the front door to every tool.
3. WINK checks for updates automatically (distributed via GitHub, [agvg75/WINK](https://github.com/agvg75/WINK)), so a lab computer stays current without a manual reinstall.

No programming knowledge is required to use WINK day to day. Reading a tool's own in-hub description before a first run is the fastest way to know whether it fits a given assay.

## Where it's headed

WINK is under active development. Recent and in-progress work includes a full striated-muscle sarcomere morphometry module (ported from an existing Fiji macro, validated against real historical measurements), an in-app documentation assistant, and confocal z-stack support for 3D neurite tracing and muscle volume estimation. The pace of change is real — check the hub's own changelog for what's current.

*Questions, bug reports, or a tool that doesn't fit your assay yet: talk to the Vidal-Gadea lab.*
