"""C1: reversal and escape scoring shared by evoked and spontaneous assays."""
from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


VALID_STATES = {"forward", "paused", "reversing", "turning"}


@dataclass(frozen=True)
class ReversalEvent:
    worm_id: str
    plate_id: str
    stimulus_id: str
    response: str
    exclusion_reason: str | None
    prior_state: str
    event_type: str | None
    latency_s: float | None
    reversal_length_body_lengths: float | None
    peak_reversal_velocity_body_lengths_s: float | None
    duration_s: float | None

    def as_dict(self) -> dict:
        return asdict(self)


def score_stimulus(
    *, worm_id: str, plate_id: str, stimulus_id: str, times_s,
    signed_velocity_body_lengths_s, stimulus_time_s: float,
    prior_state: str, artifact_frame_indices=(), response_window_s: float = 5,
    reversal_threshold_bl_s: float = 0.05,
    acceleration_threshold_bl_s: float = 0.1,
) -> ReversalEvent:
    if prior_state not in VALID_STATES:
        raise ValueError(f"prior_state must be one of {sorted(VALID_STATES)}")
    if prior_state == "reversing":
        return ReversalEvent(
            worm_id, plate_id, stimulus_id, "excluded",
            "already reversing at stimulus onset", prior_state,
            None, None, None, None, None)
    times = np.asarray(times_s, dtype=float)
    velocity = np.asarray(signed_velocity_body_lengths_s, dtype=float)
    if len(times) != len(velocity) or len(times) < 2:
        raise ValueError("times and velocity must have equal length >=2.")
    valid = (
        (times >= stimulus_time_s) &
        (times <= stimulus_time_s + response_window_s))
    artifact = np.zeros(len(times), dtype=bool)
    artifact[list(artifact_frame_indices)] = True
    indices = np.flatnonzero(valid & ~artifact & np.isfinite(velocity))
    reverse = indices[velocity[indices] <= -abs(reversal_threshold_bl_s)]
    if reverse.size:
        start = int(reverse[0])
        contiguous = [start]
        for index in range(start + 1, len(times)):
            if artifact[index]:
                continue
            if velocity[index] >= 0 or times[index] > stimulus_time_s + response_window_s:
                break
            contiguous.append(index)
        chosen = np.asarray(contiguous)
        dt = np.diff(times[chosen], append=times[chosen[-1]])
        length = float(np.sum(np.maximum(0, -velocity[chosen]) * dt))
        return ReversalEvent(
            worm_id, plate_id, stimulus_id, "yes", None, prior_state,
            "reversal", float(times[start] - stimulus_time_s), length,
            float(np.max(-velocity[chosen])),
            float(times[chosen[-1]] - times[start]))
    forward = indices[velocity[indices] >= abs(acceleration_threshold_bl_s)]
    if forward.size:
        start = int(forward[0])
        return ReversalEvent(
            worm_id, plate_id, stimulus_id, "yes", None, prior_state,
            "forward_acceleration", float(times[start] - stimulus_time_s),
            None, float(velocity[start]), None)
    return ReversalEvent(
        worm_id, plate_id, stimulus_id, "no", None, prior_state,
        None, None, 0.0, 0.0, 0.0)


def response_summary(
    events: list[ReversalEvent], spontaneous_events: list[ReversalEvent],
    *, mode: str,
) -> dict:
    if mode not in {"population", "single_worm"}:
        raise ValueError("mode must be population or single_worm.")
    eligible = [event for event in events if event.response != "excluded"]
    baseline = [
        event for event in spontaneous_events if event.response != "excluded"]
    probability = (
        None if not eligible else
        sum(event.response == "yes" for event in eligible) / len(eligible))
    spontaneous_probability = (
        None if not baseline else
        sum(event.response == "yes" for event in baseline) / len(baseline))
    plate_ids = sorted({event.plate_id for event in eligible})
    result = {
        "response_probability": probability,
        "spontaneous_reversal_probability": spontaneous_probability,
        "evoked_minus_baseline": (
            None if probability is None or spontaneous_probability is None
            else probability - spontaneous_probability),
        "eligible_denominator": len(eligible),
        "prior_state_counts": {
            state: sum(event.prior_state == state for event in events)
            for state in sorted(VALID_STATES)},
        "inferential_unit": "plate" if mode == "population" else "worm",
        "plate_count": len(plate_ids),
    }
    if mode == "single_worm":
        result["worm_count"] = len({event.worm_id for event in eligible})
    return result


def detect_population_tap(frame_difference_signal, times_s) -> dict:
    signal = np.asarray(frame_difference_signal, dtype=float)
    times = np.asarray(times_s, dtype=float)
    if len(signal) != len(times) or len(signal) < 3:
        raise ValueError("Tap signal and time must have equal length >=3.")
    baseline = float(np.median(signal))
    mad = float(np.median(np.abs(signal - baseline)))
    threshold = baseline + max(8 * mad, np.std(signal) * 3)
    candidates = np.flatnonzero(signal > threshold)
    if not candidates.size:
        return {"detected": False, "stimulus_time_s": None,
                "artifact_amplitude": None, "artifact_frame_indices": []}
    index = int(candidates[np.argmax(signal[candidates])])
    return {
        "detected": True, "stimulus_time_s": float(times[index]),
        "artifact_amplitude": float(signal[index] - baseline),
        "artifact_frame_indices": [index, min(index + 1, len(signal) - 1)]}
