"""S2: transparent per-metric capability gating."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import ceil


PASS = "pass"
AMBER = "amber"
RED = "red"


@dataclass(frozen=True)
class RecordingProxies:
    worm_length_px: float | None
    worm_width_px: float | None
    fps: float | None
    contrast_ratio: float | None
    saturation_fraction: float | None
    bit_depth: int | None
    focus_score: float | None
    occluded_fraction: float | None
    compression_artifact_score: float | None


@dataclass(frozen=True)
class MetricRequirement:
    metric_id: str
    min_length_px: float | None = None
    min_width_px: float | None = None
    min_fps: float | None = None
    min_contrast_ratio: float | None = None
    max_saturation_fraction: float | None = None
    min_bit_depth: int | None = None
    min_focus_score: float | None = None
    max_occluded_fraction: float | None = None
    max_compression_artifact_score: float | None = None
    identity_dependent: bool = False
    provisional: bool = True


@dataclass(frozen=True)
class GateDecision:
    metric_id: str
    status: str
    measured: dict
    unmet: tuple[str, ...]
    acquisition_actions: tuple[str, ...]
    expected_manual_fraction: float | None
    provisional_thresholds: bool
    forced: bool = False
    acknowledgment: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _ratio_action(label: str, measured: float | None, required: float) -> str:
    if measured is None or measured <= 0:
        return f"measure {label}; the required floor is {required:g}"
    factor = required / measured
    return (
        f"{label} is {measured:g}; needs about {required:g}; increase the "
        f"relevant acquisition setting roughly {factor:.1f}x")


def evaluate_metric(
    proxies: RecordingProxies,
    requirement: MetricRequirement,
) -> GateDecision:
    measured = asdict(proxies)
    hard: list[str] = []
    actions: list[str] = []
    amber_load = 0.0

    minimums = (
        ("worm_length_px", requirement.min_length_px, "worm length in pixels"),
        ("worm_width_px", requirement.min_width_px, "worm width in pixels"),
        ("fps", requirement.min_fps, "frame rate"),
        ("contrast_ratio", requirement.min_contrast_ratio, "contrast ratio"),
        ("bit_depth", requirement.min_bit_depth, "bit depth"),
        ("focus_score", requirement.min_focus_score, "focus score"),
    )
    for field_name, required, label in minimums:
        if required is None:
            continue
        value = getattr(proxies, field_name)
        if value is None or value < required:
            deficit = 1.0 if value is None else max(0.0, 1.0 - value / required)
            message = f"{field_name}: measured {value}, requires >= {required}"
            actions.append(_ratio_action(label, value, required))
            if value is None or deficit > 0.35:
                hard.append(message)
            else:
                amber_load = max(amber_load, deficit / 0.35)

    maximums = (
        ("saturation_fraction", requirement.max_saturation_fraction,
         "reduce exposure or illumination"),
        ("occluded_fraction", requirement.max_occluded_fraction,
         "reduce density or improve identity review"),
        ("compression_artifact_score",
         requirement.max_compression_artifact_score,
         "use lossless or lower-compression recording"),
    )
    for field_name, required, action in maximums:
        if required is None:
            continue
        value = getattr(proxies, field_name)
        if value is None or value > required:
            excess = 1.0 if value is None else (value - required) / max(
                required, 1e-9)
            message = f"{field_name}: measured {value}, requires <= {required}"
            actions.append(action)
            if value is None or excess > 0.5:
                hard.append(message)
            else:
                amber_load = max(amber_load, min(1.0, excess / 0.5))

    if hard:
        status = RED
        unmet = tuple(hard)
        manual = None
    elif actions:
        status = AMBER
        unmet = tuple(actions)
        manual = min(0.95, max(0.05, amber_load))
    else:
        status = PASS
        unmet = ()
        manual = 0.0
    return GateDecision(
        requirement.metric_id, status, measured, unmet, tuple(actions),
        manual, requirement.provisional)


def gate_recording(
    proxies: RecordingProxies,
    requirements: list[MetricRequirement],
) -> list[GateDecision]:
    return [evaluate_metric(proxies, requirement)
            for requirement in requirements]


def force_gated_metric(
    decision: GateDecision,
    acknowledgment: str,
) -> GateDecision:
    if decision.status == PASS:
        return decision
    if not acknowledgment.strip():
        raise ValueError("A logged expert acknowledgment is required.")
    data = asdict(decision)
    data["forced"] = True
    data["acknowledgment"] = acknowledgment.strip()
    data["unmet"] = tuple(data["unmet"])
    data["acquisition_actions"] = tuple(data["acquisition_actions"])
    return GateDecision(**data)


def do_not_attempt(decisions: list[GateDecision]) -> bool:
    return bool(decisions) and all(item.status == RED for item in decisions)


DEFAULT_REQUIREMENTS = [
    MetricRequirement("population_centroid_speed", min_length_px=25, min_fps=3,
                      min_contrast_ratio=1.15,
                      max_occluded_fraction=0.50),
    MetricRequirement("single_worm_spline", min_length_px=150, min_width_px=8,
                      min_fps=10, min_contrast_ratio=1.25,
                      max_compression_artifact_score=0.20),
    MetricRequirement("pharyngeal_pumping", min_length_px=250, min_width_px=12,
                      min_fps=30, min_contrast_ratio=1.30,
                      max_compression_artifact_score=0.10),
]


def proxies_from_probe_report(
    report: dict, *, worm_length_px=None, worm_width_px=None,
    contrast_ratio=None, saturation_fraction=None, focus_score=None,
    occluded_fraction=None, compression_artifact_score=None,
) -> RecordingProxies:
    """Create biological proxies on top of Probe a movie's technical report."""
    return RecordingProxies(
        worm_length_px=worm_length_px, worm_width_px=worm_width_px,
        fps=report.get("fps"), contrast_ratio=contrast_ratio,
        saturation_fraction=saturation_fraction,
        bit_depth=report.get("bit_depth"), focus_score=focus_score,
        occluded_fraction=occluded_fraction,
        compression_artifact_score=(
            compression_artifact_score if compression_artifact_score is not None
            else (1.0 if report.get("lossy") else 0.0)))


def capability_menu(decisions: list[GateDecision]) -> dict:
    passing = [item.metric_id for item in decisions if item.status == PASS]
    gated = [{
        "metric_id": item.metric_id, "status": item.status,
        "label": (
            item.metric_id + " — " +
            (item.acquisition_actions[0] if item.acquisition_actions
             else "capability floor unmet")),
        "force_acknowledgment_required": item.status == RED,
    } for item in decisions if item.status != PASS]
    alternative = None
    if ("population_centroid_speed" in passing and
            any(item["metric_id"] == "single_worm_spline" for item in gated)):
        alternative = (
            "Single-worm posture is gated; use population centroid analysis.")
    return {
        "passing_metrics": passing, "gated_metrics": gated,
        "do_not_attempt": do_not_attempt(decisions),
        "alternative_route": alternative,
        "threshold_status": "provisional_pending_technical_validation"}
