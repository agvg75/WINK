"""Read-only diagnostics for a staged or installed Lab Tools tree."""
from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"


def load_hub():
    spec = importlib.util.spec_from_file_location("lab_hub_diagnostic", APP / "lab_hub.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load app/lab_hub.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def check_registry() -> list[str]:
    hub = load_hub()
    failures = []
    for tool in hub.REGISTRY:
        if tool.status != "ready" or not tool.filename:
            continue
        path = hub.resolve_tool_path(tool)
        if path is None:
            failures.append(f"MISSING registry entry: {tool.name} -> {tool.filename}")
        else:
            print(f"OK registry: {tool.name} -> {path.relative_to(ROOT)}")
    return failures


def check_python_syntax() -> list[str]:
    failures = []
    excluded = {".venv", "__pycache__", "archive", "distribution"}
    for path in ROOT.rglob("*.py"):
        if any(part in excluded for part in path.parts):
            continue
        try:
            ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            print(f"OK syntax: {path.relative_to(ROOT)}")
        except Exception as exc:
            failures.append(f"SYNTAX {path.relative_to(ROOT)}: {exc}")
    return failures


def check_required_pairs() -> list[str]:
    pairs = {
        "tools/movie/convert_gui.py": ["tools/movie/convert_for_fiji.py", "tools/movie/movie_reader.py"],
        "tools/movie/movie_probe_gui.py": ["tools/movie/movie_reader.py"],
        "tools/worm_kinematics/run_one_kinematics.py": [
            "tools/rgbcamp/pipeline/run_one.py",
            "tools/rgbcamp/pipeline/worm_kinetics.py",
            "tools/rgbcamp/pipeline/worm_rgbcamp_analysis.py",
        ],
        "tools/worm_kinematics/kinematics_browser.py": [
            "tools/rgbcamp/pipeline/results_browser.py",
            "tools/worm_kinematics/run_one_kinematics.py",
        ],
        "tools/worm_kinematics/dic_tracker/run_dic_kinematics.py": [
            "tools/worm_kinematics/dic_tracker/worm_dic_tracker.py",
            "tools/afd_neuron/neuron_tracker.py",
            "tools/movie/movie_reader.py",
        ],
        "tools/afd_neuron/run_neuron_tracker.py": ["tools/movie/movie_reader.py"],
        "tools/pharyngeal_pumping/pumping_tool.py": [],
        "tools/defecation/pboc_tool.py": [
            "tools/defecation/pboc_engine.py",
            "tools/defecation/defecation_feasibility.py",
            "tools/worm_kinematics/dic_tracker/worm_dic_tracker.py",
        ],
        "tools/basal_slowing/basal_slowing_tool.py": [
            "tools/basal_slowing/basal_slowing.py",
            "tools/basal_slowing/track_review.py",
            "tools/population_swimming/population_swimming.py",
            "app/roi_editor.py",
            "app/roi_geometry.py",
        ],
        "app/intake.py": ["app/acquisition.py"],
        "app/capability_gate.py": ["app/acquisition.py"],
        "app/failure_library.py": ["app/acquisition.py"],
        "app/run_feedback.py": [
            "app/acquisition.py", "app/failure_library.py"],
        "app/stimulus_fields.py": [],
        "app/departure_roi.py": [],
        "app/reversal_core.py": [],
        "app/orientation_core.py": ["app/stimulus_fields.py"],
        "tools/mechanosensation/mechanosensation.py": [
            "app/reversal_core.py", "app/capability_gate.py",
            "app/failure_library.py"],
        "tools/mechanosensation/mechanosensation_tool.py": [
            "tools/mechanosensation/mechanosensation.py",
            "app/reversal_core.py", "app/run_feedback.py"],
        "tools/paralysis_pharmacology/paralysis.py": [
            "app/capability_gate.py", "app/failure_library.py"],
        "tools/paralysis_pharmacology/paralysis_tool.py": [
            "tools/paralysis_pharmacology/paralysis.py",
            "app/run_feedback.py"],
        "tools/orientation_assays/thermotaxis.py": [
            "tools/orientation_assays/common.py", "app/orientation_core.py"],
        "tools/orientation_assays/magnetotaxis.py": [
            "tools/orientation_assays/common.py", "app/departure_roi.py"],
        "tools/orientation_assays/chemotaxis.py": [
            "tools/orientation_assays/common.py", "app/orientation_core.py"],
        "tools/orientation_assays/orientation_workbench.py": [
            "tools/orientation_assays/magnetotaxis.py",
            "tools/orientation_assays/thermotaxis.py",
            "tools/orientation_assays/chemotaxis.py",
            "app/stimulus_fields.py", "app/departure_roi.py",
            "app/run_feedback.py"],
        "tools/orientation_assays/magnetotaxis_tool.py": [
            "tools/orientation_assays/orientation_workbench.py"],
        "tools/orientation_assays/thermotaxis_tool.py": [
            "tools/orientation_assays/orientation_workbench.py"],
        "tools/orientation_assays/chemotaxis_tool.py": [
            "tools/orientation_assays/orientation_workbench.py"],
        "tools/longitudinal_performance/performance.py": [
            "app/capability_gate.py", "app/failure_library.py"],
        "tools/track_derived_workbench.py": [
            "tools/longitudinal_performance/performance.py",
            "tools/behavioral_states/states.py",
            "tools/burrowing/burrowing.py", "app/run_feedback.py"],
        "tools/swimming_fatigue_tool.py": [
            "tools/track_derived_workbench.py"],
        "tools/healthspan_tool.py": ["tools/track_derived_workbench.py"],
        "tools/area_restricted_search_tool.py": [
            "tools/track_derived_workbench.py"],
        "tools/roaming_dwelling_tool.py": [
            "tools/track_derived_workbench.py"],
        "tools/quiescence_tool.py": ["tools/track_derived_workbench.py"],
        "tools/burrowing_tool.py": ["tools/track_derived_workbench.py"],
        "tools/behavioral_states/states.py": [
            "app/reversal_core.py"],
        "tools/burrowing/burrowing.py": [
            "app/capability_gate.py"],
        "tools/pharynx_morphometry/pharynx.py": [
            "app/acquisition.py"],
        "tools/pharynx_morphometry/pharynx_tool.py": [
            "tools/pharynx_morphometry/pharynx.py",
            "app/capability_gate.py", "app/run_feedback.py"],
        "tools/single_channel_gcamp/gcamp.py": [
            "app/capability_gate.py"],
        "tools/single_channel_gcamp/gcamp_tool.py": [
            "tools/single_channel_gcamp/gcamp.py",
            "app/acquisition.py", "app/run_feedback.py"],
    }
    failures = []
    for owner, dependencies in pairs.items():
        if not (ROOT / owner).exists():
            failures.append(f"MISSING owner: {owner}")
        for dependency in dependencies:
            if not (ROOT / dependency).exists():
                failures.append(f"MISSING dependency for {owner}: {dependency}")
    return failures


def check_acquisition_contract() -> list[str]:
    failures = []
    try:
        from acquisition import AcquisitionMetadata
        AcquisitionMetadata(
            fps=30, fps_source="declared",
            um_per_px=1.0, um_per_px_source="declared",
            exposure_ms=2.0, exposure_source="declared",
        ).validate()
        AcquisitionMetadata(
            fps=None, fps_source="not_applicable",
            um_per_px=2.35, um_per_px_source="two_point_calibration",
            exposure_ms=None, exposure_source="not_applicable",
        ).validate()
        for kwargs in (
            dict(fps=30, fps_source="user_declared", um_per_px=1.0,
                 um_per_px_source="declared", exposure_ms=None,
                 exposure_source="not_applicable"),
            dict(fps=30, fps_source="declared", um_per_px=0,
                 um_per_px_source="declared", exposure_ms=None,
                 exposure_source="not_applicable"),
        ):
            try:
                AcquisitionMetadata(**kwargs).validate()
            except ValueError:
                pass
            else:
                failures.append("ACQUISITION contract accepted invalid metadata")
    except Exception as exc:
        failures.append(f"ACQUISITION contract: {exc}")
    return failures


def main() -> int:
    failures = (check_registry() + check_python_syntax() +
                check_required_pairs() + check_acquisition_contract())
    if failures:
        print("\nDIAGNOSTIC FAILURES")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("\nALL STATIC DIAGNOSTICS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
