"""Viewer protocol for volume review, and the tier that needs no display.

A viewer shows state and emits intents. It never computes a measured quantity -
that lives in volume_review_state / muscle_boundary, so every tier returns the
same numbers for the same decisions. See the tiered rendering spec §1.

Tiers:
  headless   HeadlessVolumeReviewViewer, replays a scripted intent list. The
             regression path, and the proof the core is separable.
  tier0      Tkinter + matplotlib. Always available, defines behaviour when
             anything is ambiguous.
  tier1      the same viewer with optimisations enabled - not a separate class.
  tier2      accelerated, probe-gated, and deliberately not built yet.

WHY TIER 2 IS NOT HERE. Its headline exclusive was a live rotatable 3D view of
the fitted surfaces. A rendered rotating movie delivers that scientific value -
seeing where the slab model fails - on every machine, with no GPU, no Qt and no
probe (see muscle_volume_runner). What Tier 2 would add beyond that is fluid
full-resolution scrubbing, which is a comfort feature. It stays gated on a fleet
survey showing enough machines would benefit to justify a second maintenance
surface, exactly as the spec asks.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import volume_review_state as vrs


@dataclass
class ReviewOutcome:
    """What a viewer hands back. Status is explicit; there is no 'probably'."""
    status: str                       # "accepted" | "cancelled" | "crashed"
    state: object = None
    error: object = None
    tier: str = "headless"
    recovery_path: object = None

    @property
    def ok(self):
        return self.status == "accepted"


class VolumeReviewViewer(ABC):
    """Show state, emit intents, return an outcome. Compute nothing."""

    tier_name = "abstract"

    @classmethod
    def is_available(cls):
        return False

    @abstractmethod
    def run(self, state):
        """Block until the student accepts, cancels, or this viewer fails."""

    # -- shared crash handling -------------------------------------------
    @staticmethod
    def recover(state, recovery_dir, error, tier):
        """Serialize state so a viewer failure never costs the marking.

        The student's judgement is the expensive part of this workflow; a
        graphics stack falling over must not spend it. The caller reopens the
        same state in the baseline viewer and records tier_fallback.
        """
        recovery_dir = Path(recovery_dir)
        recovery_dir.mkdir(parents=True, exist_ok=True)
        path = recovery_dir / "volume_review_recovery.json"
        state.save_recovery(path)
        return ReviewOutcome(status="crashed", state=state, error=error,
                             tier=tier, recovery_path=path)


class HeadlessVolumeReviewViewer(VolumeReviewViewer):
    """Replays a scripted intent list. No display, no Tk, no graphics stack.

    This is what makes the tier-equivalence test possible and what lets the
    whole review path run in CI with no display available - the practical
    enforcement of "the core is separable".
    """

    tier_name = "headless"

    def __init__(self, intents=None, accept=True):
        self.intents = list(intents or [])
        self.accept = accept

    @classmethod
    def is_available(cls):
        return True

    def run(self, state):
        try:
            state.render_tier = self.tier_name
            state.replay(self.intents)
            if self.accept and not state.accepted:
                state.apply_intent(vrs.AcceptReview())
            return ReviewOutcome(status="accepted" if state.accepted
                                 else "cancelled",
                                 state=state, tier=self.tier_name)
        except Exception as exc:                       # noqa: BLE001
            return ReviewOutcome(status="crashed", state=state, error=exc,
                                 tier=self.tier_name)


def available_viewers():
    """Every viewer class that reports itself usable on this machine."""
    found = [HeadlessVolumeReviewViewer]
    try:
        from volume_review_tk import TkVolumeReviewViewer
        if TkVolumeReviewViewer.is_available():
            found.append(TkVolumeReviewViewer)
    except Exception:
        pass
    return found


def select_viewer(tier=None):
    """Pick a viewer class for a tier name, or the best available.

    Tier 0 is the floor and is always reachable; there is no configuration in
    which a student is left without a working review.
    """
    viewers = {v.tier_name: v for v in available_viewers()}
    if tier and tier in viewers:
        return viewers[tier]
    for name in ("tier0", "headless"):
        if name in viewers:
            return viewers[name]
    return HeadlessVolumeReviewViewer
