"""Viewer-independent state for muscle volume review, and the intents that change it.

See docs/specs/muscle_boundary_volume_spec.md and the tiered rendering spec.

THE RULE THIS MODULE EXISTS TO ENFORCE: the render tier changes interaction,
never measurement. If two lab machines can produce different volumes for the
same stack and the same student decisions, the tier has become a hidden analysis
variable and the module is no longer reproducible within the lab.

So every measured quantity is computed here, by muscle_boundary.measure_region,
and no viewer may compute or modify one. Viewers read state and emit intents;
this applies them. apply_intent is the ONLY mutation path, which is also how
correction logging comes for free rather than as something each viewer must
remember to call - the place divergence would otherwise begin.

The whole review runs headless with no viewer instantiated. That is both the
regression-test path and the proof that the core is genuinely separable.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import muscle_boundary as mb

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- #
# Intents: the closed set of things a viewer may ask for
# --------------------------------------------------------------------------- #
@dataclass
class Intent:
    """Base. Anything a viewer can do must be expressible as one of these.

    If a viewer wants something that is not here, the answer is to add the
    intent and expose it in the baseline viewer too - even clumsily - not to
    let one tier accumulate private state.
    """
    kind: str = "intent"

    def describe(self):
        return self.kind


@dataclass
class AddBoundaryPoint(Intent):
    region: str = ""
    surface: str = "upper"
    z: int = 0
    x: float = 0.0
    y: float = 0.0
    kind: str = "add_boundary_point"

    def describe(self):
        return (f"add {self.surface} point to '{self.region}' "
                f"at z={self.z} ({self.x:.1f}, {self.y:.1f})")


@dataclass
class RemoveBoundaryPoint(Intent):
    region: str = ""
    surface: str = "upper"
    z: int = 0
    index: int = -1
    kind: str = "remove_boundary_point"

    def describe(self):
        return (f"remove {self.surface} point {self.index} from "
                f"'{self.region}' at z={self.z}")


@dataclass
class MoveBoundaryPoint(Intent):
    region: str = ""
    surface: str = "upper"
    z: int = 0
    index: int = -1
    x: float = 0.0
    y: float = 0.0
    kind: str = "move_boundary_point"

    def describe(self):
        return (f"move {self.surface} point {self.index} in '{self.region}' "
                f"at z={self.z} to ({self.x:.1f}, {self.y:.1f})")


@dataclass
class SetExclusion(Intent):
    region: str = ""
    z: int = 0
    polygon: list = field(default_factory=list)
    reason: str = "unclear"
    note: str = ""
    kind: str = "set_exclusion"

    def describe(self):
        return (f"exclude region on '{self.region}' z={self.z} "
                f"as {self.reason}")


@dataclass
class RemoveExclusion(Intent):
    region: str = ""
    index: int = -1
    kind: str = "remove_exclusion"

    def describe(self):
        return f"remove exclusion {self.index} from '{self.region}'"


@dataclass
class AddRegion(Intent):
    region: str = ""
    channel: int = 0
    kind: str = "add_region"

    def describe(self):
        return f"add region '{self.region}' on channel {self.channel}"


@dataclass
class AcceptReview(Intent):
    note: str = ""
    kind: str = "accept_review"

    def describe(self):
        return "accept review" + (f": {self.note}" if self.note else "")


INTENT_TYPES = {
    "add_boundary_point": AddBoundaryPoint,
    "remove_boundary_point": RemoveBoundaryPoint,
    "move_boundary_point": MoveBoundaryPoint,
    "set_exclusion": SetExclusion,
    "remove_exclusion": RemoveExclusion,
    "add_region": AddRegion,
    "accept_review": AcceptReview,
}


def intent_from_dict(d):
    kind = d.get("kind")
    cls = INTENT_TYPES.get(kind)
    if cls is None:
        raise mb.BoundaryError(
            f"Unknown intent '{kind}'. A viewer has emitted something the core "
            f"does not implement, which means a measurement could differ "
            f"between tiers - the one failure this design exists to prevent.")
    return cls(**{k: v for k, v in d.items() if k != "kind"})


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
class VolumeReviewState:
    """Everything a review is, independent of how it is displayed."""

    def __init__(self, volume=None, voxel_size_um=(1.0, 1.0, 1.0),
                 shape_zcyx=None, source_path=None, identity=None,
                 render_tier="headless"):
        self.volume = volume                    # referenced, never copied
        self.voxel_size_um = tuple(float(v) for v in voxel_size_um)
        if shape_zcyx is None:
            if volume is None:
                raise mb.BoundaryError(
                    "A review needs either a volume or an explicit shape; "
                    "without one, marks cannot be bounded to the stack.")
            arr = np.asarray(volume)
            shape_zcyx = (arr.shape[0], 1, arr.shape[-2], arr.shape[-1])
        self.shape_zcyx = tuple(int(v) for v in shape_zcyx)
        self.source_path = str(source_path) if source_path else None
        self.identity = identity
        self.render_tier = render_tier
        self.regions = []
        self.correction_log = []
        self.accepted = False

    # -- the only mutation path -------------------------------------------
    def apply_intent(self, intent, station=None):
        """Apply one intent and log it. Every change goes through here."""
        handler = getattr(self, "_do_" + intent.kind, None)
        if handler is None:
            raise mb.BoundaryError(
                f"Intent '{intent.kind}' has no handler in the core.")
        handler(intent)
        self.correction_log.append({
            "utc": datetime.now(timezone.utc).isoformat(),
            "intent": asdict(intent),
            "description": intent.describe(),
            "render_tier": self.render_tier,
        })
        return self

    def _region(self, name, create=False):
        for r in self.regions:
            if r.name == name:
                return r
        if create:
            r = mb.Region(name=name)
            self.regions.append(r)
            return r
        raise mb.BoundaryError(
            f"No region named '{name}'. Add it before marking into it, so a "
            f"stray click cannot silently create a region nobody named.")

    def _do_add_region(self, i):
        if any(r.name == i.region for r in self.regions):
            raise mb.BoundaryError(f"Region '{i.region}' already exists.")
        self.regions.append(mb.Region(name=i.region, channel=int(i.channel)))

    def _surface(self, region, surface, z, create=True):
        for s in region.surfaces:
            if s.surface == surface and int(s.z) == int(z):
                return s
        if not create:
            return None
        s = mb.Surface(surface=surface, z=int(z), points=[])
        region.surfaces.append(s)
        return s

    def _do_add_boundary_point(self, i):
        s = self._surface(self._region(i.region), i.surface, i.z)
        s.points.append([float(i.x), float(i.y)])

    def _do_remove_boundary_point(self, i):
        s = self._surface(self._region(i.region), i.surface, i.z, create=False)
        if s is None or not (0 <= i.index < len(s.points)):
            raise mb.BoundaryError(
                f"No point {i.index} on the {i.surface} boundary of "
                f"'{i.region}' at z={i.z}.")
        s.points.pop(i.index)

    def _do_move_boundary_point(self, i):
        s = self._surface(self._region(i.region), i.surface, i.z, create=False)
        if s is None or not (0 <= i.index < len(s.points)):
            raise mb.BoundaryError(
                f"No point {i.index} on the {i.surface} boundary of "
                f"'{i.region}' at z={i.z}.")
        s.points[i.index] = [float(i.x), float(i.y)]

    def _do_set_exclusion(self, i):
        if i.reason not in mb.EXCLUSION_REASONS:
            raise mb.BoundaryError(
                f"'{i.reason}' is not an exclusion reason. Use one of "
                f"{', '.join(mb.EXCLUSION_REASONS)} - a free-text reason cannot "
                f"be counted across students, and 'unclear' exists so nobody "
                f"has to invent one.")
        self._region(i.region).exclusions.append(
            mb.Exclusion(z=int(i.z), polygon=[list(map(float, p))
                                              for p in i.polygon],
                         reason=i.reason, note=i.note))

    def _do_remove_exclusion(self, i):
        r = self._region(i.region)
        if not (0 <= i.index < len(r.exclusions)):
            raise mb.BoundaryError(
                f"No exclusion {i.index} on region '{i.region}'.")
        r.exclusions.pop(i.index)

    def _do_accept_review(self, i):
        self.measure()                      # refuse to accept an unmeasurable state
        self.accepted = True

    # -- measurement: the one path, viewer or no viewer --------------------
    def measure(self):
        """Volume per region. Raises if any region cannot be measured."""
        return [mb.measure_region(r, self.shape_zcyx, self.voxel_size_um)
                for r in self.regions]

    def masks(self):
        return {r.name: mb.region_mask(r, self.shape_zcyx) for r in self.regions}

    # -- serialization, so a crash never costs the student the session -----
    def to_dict(self):
        return {
            "schema_version": SCHEMA_VERSION,
            "voxel_size_um": list(self.voxel_size_um),
            "shape_zcyx": list(self.shape_zcyx),
            "source_path": self.source_path,
            "identity": self.identity,
            "render_tier": self.render_tier,
            "accepted": self.accepted,
            "regions": [asdict(r) for r in self.regions],
            "correction_log": self.correction_log,
        }

    @classmethod
    def from_dict(cls, d, volume=None):
        state = cls(volume=volume,
                    voxel_size_um=d.get("voxel_size_um", (1.0, 1.0, 1.0)),
                    shape_zcyx=d.get("shape_zcyx"),
                    source_path=d.get("source_path"),
                    identity=d.get("identity"),
                    render_tier=d.get("render_tier", "headless"))
        for r in d.get("regions", []):
            state.regions.append(mb.Region(
                name=r["name"], channel=int(r.get("channel", 0)),
                surfaces=[mb.Surface(**s) for s in r.get("surfaces", [])],
                exclusions=[mb.Exclusion(**e) for e in r.get("exclusions", [])]))
        state.correction_log = list(d.get("correction_log", []))
        state.accepted = bool(d.get("accepted", False))
        return state

    def save_recovery(self, path):
        """Serialize mid-session. A viewer crash must not cost the marking."""
        path = Path(path)
        path.write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")
        return path

    def to_provenance(self):
        """How the review was conducted - NOT what was measured.

        The manual should say so explicitly, so a reviewer meeting render_tier
        in a methods report knows it describes interaction, not analysis.
        """
        return {
            "render_tier": self.render_tier,
            "n_regions": len(self.regions),
            "n_intents": len(self.correction_log),
            "accepted": self.accepted,
            "voxel_size_um_z": self.voxel_size_um[0],
            "voxel_size_um_y": self.voxel_size_um[1],
            "voxel_size_um_x": self.voxel_size_um[2],
            "interpolation": mb.INTERPOLATION,
            "exclusion_vocabulary": list(mb.EXCLUSION_REASONS),
        }

    def replay(self, intents, station=None):
        """Apply a scripted list of intents. The tier-equivalence test path."""
        for it in intents:
            self.apply_intent(it if isinstance(it, Intent)
                              else intent_from_dict(it), station=station)
        return self
