"""Review state for proposed myocyte boundaries: accept, edit, reject, log.

WHY THIS EXISTS. The boundary proposer writes proposals and nothing accepts
them. Measurements taken straight off proposals inherit their errors silently -
a 17% miss rate at midbody would become 17% error in the morphometry with
nothing saying so. Until a human has judged each boundary, nothing downstream
is defensible.

THE ONE RULE, borrowed from volume_review_state because two review systems that
behaved differently would be worse than either: `apply_intent` is the ONLY way
state changes, the set of intents is CLOSED, and every intent appends to the
correction log. A viewer that wants something not expressible as an intent must
get the intent added rather than mutate state privately - otherwise two review
sessions on the same data could diverge with no record of how.

WHAT THE LOG IS FOR. It is not an audit trail for its own sake. Corrections
anchored on an algorithm's proposal are TUNING data, not ground truth, and the
log is what lets that distinction survive: it records what was proposed, what
the human changed it to, and therefore how far the detector was off. Marks made
without seeing a proposal are the only clean validation data, and they must be
collected separately (see docs and the fixtures under tests/).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict

import numpy as np


class ReviewError(Exception):
    """Refusals that name the consequence, not the errno."""


STATUSES = ("proposed", "accepted", "rejected", "edited")

# Why a proposal was rejected. A closed vocabulary because these are counted
# across students and across sessions; free text cannot be tallied, and
# "looked wrong" tells a later reader nothing about the detector.
REJECT_REASONS = (
    "no_boundary_here",        # detector invented it
    "wrong_position",          # a boundary exists but not there
    "duplicate",               # same boundary already proposed
    "follows_tissue_edge",     # tracked the silhouette, not a cell border
    "follows_damage",          # tracked a lesion
    "outside_region_of_interest",
    "unclear",
)


# --------------------------------------------------------------------------- #
# Intents
# --------------------------------------------------------------------------- #
@dataclass
class Intent:
    kind: str = "intent"

    def describe(self):
        return self.kind


@dataclass
class AcceptBoundary(Intent):
    boundary_id: str = ""
    kind: str = "accept_boundary"

    def describe(self):
        return f"accept boundary '{self.boundary_id}' as proposed"


@dataclass
class RejectBoundary(Intent):
    boundary_id: str = ""
    reason: str = "unclear"
    kind: str = "reject_boundary"

    def describe(self):
        return f"reject boundary '{self.boundary_id}' ({self.reason})"


@dataclass
class MovePoint(Intent):
    boundary_id: str = ""
    index: int = -1
    x: float = 0.0
    y: float = 0.0
    kind: str = "move_point"

    def describe(self):
        return (f"move point {self.index} of '{self.boundary_id}' to "
                f"({self.x:.1f}, {self.y:.1f})")


@dataclass
class InsertPoint(Intent):
    boundary_id: str = ""
    index: int = -1
    x: float = 0.0
    y: float = 0.0
    kind: str = "insert_point"

    def describe(self):
        return (f"insert point at {self.index} of '{self.boundary_id}' "
                f"at ({self.x:.1f}, {self.y:.1f})")


@dataclass
class RemovePoint(Intent):
    boundary_id: str = ""
    index: int = -1
    kind: str = "remove_point"

    def describe(self):
        return f"remove point {self.index} of '{self.boundary_id}'"


@dataclass
class AddBoundary(Intent):
    boundary_id: str = ""
    points: list = field(default_factory=list)
    kind: str = "add_boundary"

    def describe(self):
        return (f"add new boundary '{self.boundary_id}' drawn by hand "
                f"({len(self.points)} points)")


@dataclass
class AcceptReview(Intent):
    note: str = ""
    kind: str = "accept_review"

    def describe(self):
        return "accept the review as complete" + (f": {self.note}" if self.note else "")


_INTENTS = {c.kind: c for c in (
    AcceptBoundary(), RejectBoundary(), MovePoint(), InsertPoint(),
    RemovePoint(), AddBoundary(), AcceptReview())}


def intent_from_dict(d):
    kind = d.get("kind")
    cls = _INTENTS.get(kind)
    if cls is None:
        raise ReviewError(
            f"Unknown review action '{kind}'. The intent set is closed on "
            f"purpose: an action that only one viewer understands would let "
            f"two reviews of the same stack differ with nothing recording how.")
    out = type(cls)()
    for k, v in d.items():
        if hasattr(out, k):
            setattr(out, k, v)
    return out


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #
@dataclass
class Boundary:
    boundary_id: str
    points: list                     # [(x_px, y_px), ...] ordered along x
    source: str = "proposed"         # "proposed" | "hand_drawn"
    status: str = "proposed"
    reason: str = ""
    proposed_points: list = field(default_factory=list)

    def as_array(self):
        return np.asarray(self.points, dtype=float)


class MyocyteReviewState:
    """All review state for one field. No viewer, no display, no I/O."""

    def __init__(self, shape_yx, um_per_px, source_path="", series_name="",
                 region=None, detector_version=""):
        self.shape_yx = tuple(int(v) for v in shape_yx)
        self.um_per_px = float(um_per_px)
        self.source_path = str(source_path)
        self.series_name = str(series_name)
        self.region = region
        self.detector_version = detector_version
        self.boundaries = {}
        self.correction_log = []
        self.accepted = False

    # -- population -------------------------------------------------------
    def add_proposals(self, proposals):
        """Seed with detector output. NOT logged: proposing is not a decision.

        The original is kept as `proposed_points` so the log can later say how
        far a human moved it, which is the whole value of the record.
        """
        for bid, pts in proposals:
            pts = [(float(x), float(y)) for x, y in pts]
            self.boundaries[bid] = Boundary(boundary_id=bid, points=list(pts),
                                            source="proposed",
                                            proposed_points=list(pts))
        return self

    # -- the only mutation path ------------------------------------------
    def apply_intent(self, intent):
        if isinstance(intent, dict):
            intent = intent_from_dict(intent)
        handler = getattr(self, "_do_" + intent.kind, None)
        if handler is None:
            raise ReviewError(
                f"No handler for intent '{intent.kind}'. Adding an intent "
                f"means adding it here too, so every viewer gets it.")
        handler(intent)
        self.correction_log.append({
            "intent": intent.kind,
            "description": intent.describe(),
            "timestamp": time.time(),
            **{k: v for k, v in asdict(intent).items() if k != "kind"},
        })
        return self

    def replay(self, intents):
        for i in intents:
            self.apply_intent(i)
        return self

    def _get(self, bid):
        b = self.boundaries.get(bid)
        if b is None:
            raise ReviewError(
                f"There is no boundary '{bid}' to act on. Editing something "
                f"that does not exist would silently create it, and a "
                f"hand-drawn boundary must be distinguishable from a "
                f"corrected proposal.")
        return b

    def _do_accept_boundary(self, i):
        self._get(i.boundary_id).status = "accepted"

    def _do_reject_boundary(self, i):
        if i.reason not in REJECT_REASONS:
            raise ReviewError(
                f"'{i.reason}' is not a recognised rejection reason. These are "
                f"counted across students and sessions to show HOW the "
                f"detector fails; free text cannot be tallied. Use one of: "
                f"{', '.join(REJECT_REASONS)}.")
        b = self._get(i.boundary_id)
        b.status = "rejected"
        b.reason = i.reason

    def _do_move_point(self, i):
        b = self._get(i.boundary_id)
        if not (0 <= i.index < len(b.points)):
            raise ReviewError(
                f"Point {i.index} does not exist on '{i.boundary_id}' "
                f"({len(b.points)} points).")
        b.points[i.index] = (float(i.x), float(i.y))
        if b.status == "proposed":
            b.status = "edited"

    def _do_insert_point(self, i):
        b = self._get(i.boundary_id)
        idx = max(0, min(int(i.index), len(b.points)))
        b.points.insert(idx, (float(i.x), float(i.y)))
        if b.status == "proposed":
            b.status = "edited"

    def _do_remove_point(self, i):
        b = self._get(i.boundary_id)
        if not (0 <= i.index < len(b.points)):
            raise ReviewError(
                f"Point {i.index} does not exist on '{i.boundary_id}'.")
        if len(b.points) <= 2:
            raise ReviewError(
                f"'{i.boundary_id}' would be left with fewer than two points, "
                f"which is not a boundary. Reject it instead - that records "
                f"WHY it was wrong, which deleting its points does not.")
        b.points.pop(i.index)
        if b.status == "proposed":
            b.status = "edited"

    def _do_add_boundary(self, i):
        if i.boundary_id in self.boundaries:
            raise ReviewError(
                f"'{i.boundary_id}' already exists. Reusing an id would make a "
                f"hand-drawn boundary indistinguishable from a proposed one in "
                f"the log.")
        if len(i.points) < 2:
            raise ReviewError("A boundary needs at least two points.")
        self.boundaries[i.boundary_id] = Boundary(
            boundary_id=i.boundary_id,
            points=[(float(x), float(y)) for x, y in i.points],
            source="hand_drawn", status="accepted")

    def _do_accept_review(self, i):
        pending = [b.boundary_id for b in self.boundaries.values()
                   if b.status == "proposed"]
        if pending:
            raise ReviewError(
                f"{len(pending)} boundaries have not been judged yet: "
                f"{', '.join(pending[:6])}{'...' if len(pending) > 6 else ''}. "
                f"Accepting a review with unjudged proposals would let them "
                f"reach the measurements as though a human had approved them.")
        self.accepted = True

    # -- measurement ------------------------------------------------------
    def measure(self):
        """Per-boundary geometry, in micrometres. Rejected ones are excluded.

        Displacement is how far the human moved the proposal - the detector's
        error on that boundary as judged by a person, and the number that makes
        the correction log worth keeping.

        BOTH median and max are reported, because either alone misleads. A
        single badly placed point on an otherwise correct boundary vanishes
        into the median (move one point of three and the median is 0), while
        the max alone would make a whole-boundary shift look like a local
        glitch. The two together say what kind of error it was.
        """
        rows = []
        for b in sorted(self.boundaries.values(), key=lambda x: x.boundary_id):
            if b.status == "rejected":
                continue
            pts = b.as_array()
            seg = np.diff(pts, axis=0)
            length_um = float(np.hypot(seg[:, 0], seg[:, 1]).sum()) * self.um_per_px
            disp = disp_max = None
            if b.proposed_points and len(b.proposed_points) == len(b.points):
                orig = np.asarray(b.proposed_points, dtype=float)
                d = np.hypot(*(pts - orig).T) * self.um_per_px
                disp = float(np.median(d))
                disp_max = float(d.max())
            rows.append({
                "boundary_id": b.boundary_id,
                "source": b.source,
                "status": b.status,
                "n_points": len(b.points),
                "length_um": round(length_um, 4),
                "x_start_um": round(float(pts[:, 0].min()) * self.um_per_px, 4),
                "x_end_um": round(float(pts[:, 0].max()) * self.um_per_px, 4),
                "displacement_from_proposal_um":
                    None if disp is None else round(disp, 4),
                "displacement_max_um":
                    None if disp_max is None else round(disp_max, 4),
                "human_judged": True,
            })
        return rows

    def summary(self):
        counts = {s: 0 for s in STATUSES}
        for b in self.boundaries.values():
            counts[b.status] = counts.get(b.status, 0) + 1
        reasons = {}
        for b in self.boundaries.values():
            if b.status == "rejected":
                reasons[b.reason] = reasons.get(b.reason, 0) + 1
        return {"n_boundaries": len(self.boundaries), "by_status": counts,
                "reject_reasons": reasons, "n_intents": len(self.correction_log),
                "review_accepted": self.accepted}

    # -- serialisation ----------------------------------------------------
    def to_dict(self):
        return {
            "shape_yx": list(self.shape_yx), "um_per_px": self.um_per_px,
            "source_path": self.source_path, "series_name": self.series_name,
            "region": self.region, "detector_version": self.detector_version,
            "accepted": self.accepted,
            "boundaries": [asdict(b) for b in self.boundaries.values()],
            "correction_log": self.correction_log,
        }

    @classmethod
    def from_dict(cls, d):
        st = cls(d["shape_yx"], d["um_per_px"], d.get("source_path", ""),
                 d.get("series_name", ""), d.get("region"),
                 d.get("detector_version", ""))
        for bd in d.get("boundaries", []):
            st.boundaries[bd["boundary_id"]] = Boundary(**bd)
        st.correction_log = list(d.get("correction_log", []))
        st.accepted = bool(d.get("accepted", False))
        return st

    def to_provenance(self):
        """Describes the REVIEW. Says nothing about what was measured."""
        return {
            "source_path": self.source_path, "series_name": self.series_name,
            "region": self.region, "detector_version": self.detector_version,
            "n_intents": len(self.correction_log),
            "review_accepted": self.accepted,
            **self.summary(),
            "corrections_are_tuning_data_not_ground_truth": True,
            "note": ("Every boundary here was anchored by a detector proposal, "
                     "so agreement with it is not independent validation. "
                     "Clean ground truth must be marked without seeing "
                     "proposals."),
        }
