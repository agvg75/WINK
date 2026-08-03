"""3D neurite tracing through a confocal stack: tubeness + shortest path.

Traces ONE neurite the user identifies, through the real volume, without
collapsing to a maximum intensity projection first - a projection stacks
noise from every plane onto the same pixel and throws away the depth that
distinguishes two neurites crossing in xy but separated in z.

This is semi-automated, not an auto-tracer. A person clicks a start and an
end, the algorithm proposes the path between them, and the person accepts
or corrects it. Full arbor reconstruction is deliberately out of scope.

HOW THE PATH IS FOUND, AND WHY IT CAN STILL BE WRONG
-----------------------------------------------------
A Hessian tubeness filter (Frangi or Sato) scores how tube-like each voxel
is, giving the search a landscape shaped like neurites rather than raw
noisy intensity. The cost of stepping into a voxel is the reciprocal of
that score, so a minimum-cost path prefers to run along tubes.

That is a preference, not a guarantee. The path follows the cheapest route,
which is not always the true neurite:

* Where the target dims and a brighter structure (another neurite, a gut
  granule, cuticle) lies near the straight line between the endpoints, the
  cheapest route crosses onto it. This is the single most common failure
  and the reason anchors exist - it is a property of the cost landscape,
  not a tuning bug to be eliminated by adjusting sigma.
* Photobleaching across a long acquisition lowers tubeness over the later
  part of a trace, so a path can degrade along its length.
* Crowded expression raises the odds of the first failure. Sparse or
  single-cell labelling, or a second disambiguating channel, is what
  actually fixes it; no path-search parameter can.

ANISOTROPY IS HANDLED IN PHYSICAL UNITS
----------------------------------------
Confocal z spacing is routinely several times the lateral spacing (3.1x on
this lab's own Leica stacks). Both the tubeness scales and the step costs
are therefore expressed in micrometres, not voxels: a sigma given in
micrometres becomes a different number of voxels along z than along x, and
a diagonal step costs its true physical length. Treating voxels as cubes
would make z-running neurites systematically cheaper to traverse than
lateral ones.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import numpy as np


DEFAULT_SIGMA_SCALES = (0.5, 1.0, 2.0)   # multipliers on the expected radius
EPSILON = 1e-6


class NeuriteTraceError(RuntimeError):
    """A trace cannot be produced as asked."""


@dataclass
class TracedPath:
    """One traced neurite, raw and corrected kept separately."""
    nodes_zyx: np.ndarray                 # (N, 3) voxel coordinates
    voxel_size_um: tuple
    anchors_zyx: list = field(default_factory=list)
    raw_nodes_zyx: np.ndarray | None = None   # the automatic proposal, never overwritten
    sigma_um: tuple = ()
    notes: list = field(default_factory=list)

    def physical_nodes_um(self):
        return np.asarray(self.nodes_zyx, float) * np.asarray(self.voxel_size_um, float)

    def length_um(self):
        pts = self.physical_nodes_um()
        if len(pts) < 2:
            return 0.0
        return float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())

    def was_corrected(self):
        if self.raw_nodes_zyx is None:
            return False
        raw = np.asarray(self.raw_nodes_zyx)
        cur = np.asarray(self.nodes_zyx)
        return raw.shape != cur.shape or not np.array_equal(raw, cur)


# ---------------------------------------------------------------------------
# tubeness
# ---------------------------------------------------------------------------
def tubeness(volume, voxel_size_um, radius_um, sigma_scales=DEFAULT_SIGMA_SCALES,
             method="sato"):
    """Tube-likeness of every voxel, 0..1.

    `radius_um` is the expected neurite radius in MICROMETRES and
    `sigma_scales` are multipliers around it, per the lab's rule that a
    parameter should mean the same thing at any magnification. A raw
    pixel sigma would silently mean a different physical size on every
    objective.
    """
    from skimage.filters import frangi, sato

    volume = np.asarray(volume, dtype=np.float32)
    if volume.ndim != 3:
        raise NeuriteTraceError(
            f"Tubeness needs a single (Z, Y, X) volume, got shape {volume.shape}. "
            "Pick one channel from the stack first.")
    dz, dy, dx = (float(v) for v in voxel_size_um)
    if min(dz, dy, dx) <= 0:
        raise NeuriteTraceError("Voxel size must be positive in all three axes.")

    # A sigma in micrometres is a different number of voxels per axis. Feed
    # skimage sigmas in voxels for the LATERAL axes and pre-scale the volume
    # anisotropy by passing per-axis spacing through the sigma list, using
    # the smallest voxel dimension as the reference so no scale is lost.
    finest = min(dz, dy, dx)
    sigmas_um = [radius_um * s for s in sigma_scales]
    sigmas_vox = [max(s / finest, 0.5) for s in sigmas_um]

    fn = sato if method == "sato" else frangi
    kwargs = dict(sigmas=sigmas_vox, black_ridges=False)
    response = fn(volume, **kwargs)

    response = np.nan_to_num(response, nan=0.0, posinf=0.0, neginf=0.0)
    peak = float(response.max())
    if peak > 0:
        response = response / peak
    return response.astype(np.float32), tuple(sigmas_um)


# ---------------------------------------------------------------------------
# path search
# ---------------------------------------------------------------------------
def _cost_volume(tube_response):
    """Reciprocal cost: tube-like voxels are cheap, background expensive."""
    return (1.0 / (np.asarray(tube_response, dtype=np.float64) + EPSILON))


def trace_between(tube_response, start_zyx, end_zyx, voxel_size_um):
    """Minimum-cost path between two voxels through the tubeness volume.

    Uses `skimage.graph.route_through_array`, which is Dijkstra over the
    voxel lattice - the same outcome as SNT's bidirectional A* for stacks
    this size, and already available through scikit-image.
    """
    from skimage.graph import route_through_array

    tube_response = np.asarray(tube_response)
    start = tuple(int(v) for v in start_zyx)
    end = tuple(int(v) for v in end_zyx)
    for name, point in (("start", start), ("end", end)):
        if not all(0 <= p < s for p, s in zip(point, tube_response.shape)):
            raise NeuriteTraceError(
                f"The {name} point {point} lies outside the volume "
                f"{tube_response.shape}.")
    if start == end:
        raise NeuriteTraceError("Start and end are the same voxel.")

    # geometric=True makes a diagonal step cost its true length rather than
    # one unit, so a path is not biased toward diagonals.
    indices, _cost = route_through_array(
        _cost_volume(tube_response), start, end,
        fully_connected=True, geometric=True)
    return np.asarray(indices, dtype=int)


def snap_to_ridge(tube_response, point_zyx, radius_vox=2):
    """Move a click to the most tube-like voxel nearby.

    Mirrors SNT's cursor snapping: a person cannot click the exact centre
    of a neurite in three dimensions, and a start point sitting one voxel
    off the ridge makes the first segment of every trace wrong.
    """
    tube_response = np.asarray(tube_response)
    z, y, x = (int(v) for v in point_zyx)
    zs = slice(max(z - radius_vox, 0), min(z + radius_vox + 1, tube_response.shape[0]))
    ys = slice(max(y - radius_vox, 0), min(y + radius_vox + 1, tube_response.shape[1]))
    xs = slice(max(x - radius_vox, 0), min(x + radius_vox + 1, tube_response.shape[2]))
    window = tube_response[zs, ys, xs]
    if window.size == 0:
        return (z, y, x)
    local = np.unravel_index(int(np.argmax(window)), window.shape)
    return (zs.start + local[0], ys.start + local[1], xs.start + local[2])


def trace_with_anchors(tube_response, points_zyx, voxel_size_um):
    """Trace through an ordered list of points, resolving each leg apart.

    Anchors exist because the cheapest path is not always the true neurite.
    Each consecutive pair is solved independently, so placing an anchor
    fixes the leg it belongs to WITHOUT re-running - and therefore without
    disturbing - any leg the person already accepted. This is the same
    all-anchor rule the spine tracker uses, where a later correction must
    never be silently overwritten by an earlier interpolation.
    """
    points = [tuple(int(v) for v in p) for p in points_zyx]
    if len(points) < 2:
        raise NeuriteTraceError("At least a start and an end point are needed.")
    legs = []
    for a, b in zip(points[:-1], points[1:]):
        leg = trace_between(tube_response, a, b, voxel_size_um)
        # Drop the duplicated joint so the concatenated path has no repeats.
        legs.append(leg if not legs else leg[1:])
    return np.concatenate(legs, axis=0)


# ---------------------------------------------------------------------------
# measurement along the path
# ---------------------------------------------------------------------------
def radius_profile_um(volume, path_zyx, voxel_size_um, threshold=None,
                      max_radius_um=5.0):
    """Local radius at each node, from a thresholded cross-section.

    Deliberately the simple version: at each node, step outward along the
    two directions perpendicular to the local path tangent until intensity
    drops below the threshold, and average. A full circular cross-section
    fit (SNT's approach) is a later refinement - this is honest about being
    a coarse estimate rather than pretending to sub-voxel accuracy.
    """
    volume = np.asarray(volume, dtype=np.float32)
    path = np.asarray(path_zyx, dtype=float)
    spacing = np.asarray(voxel_size_um, dtype=float)
    if threshold is None:
        vals = volume[tuple(np.asarray(path, dtype=int).T)]
        threshold = float(np.median(vals) * 0.5)

    radii = []
    for i in range(len(path)):
        lo = max(i - 1, 0)
        hi = min(i + 1, len(path) - 1)
        tangent = path[hi] - path[lo]
        norm = np.linalg.norm(tangent)
        tangent = tangent / norm if norm > 0 else np.array([1.0, 0.0, 0.0])
        perp = _perpendicular_pair(tangent)
        widths = []
        for direction in perp:
            widths.append(_half_width_um(volume, path[i], direction, spacing,
                                         threshold, max_radius_um))
        radii.append(float(np.mean(widths)) if widths else 0.0)
    return np.asarray(radii, dtype=float)


def _perpendicular_pair(tangent):
    helper = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(helper, tangent))) > 0.9:
        helper = np.array([0.0, 1.0, 0.0])
    u = np.cross(tangent, helper)
    u = u / (np.linalg.norm(u) or 1.0)
    v = np.cross(tangent, u)
    v = v / (np.linalg.norm(v) or 1.0)
    return (u, -u, v, -v)


def _half_width_um(volume, origin, direction, spacing, threshold, max_radius_um):
    step_um = float(min(spacing)) / 2.0
    travelled = 0.0
    while travelled < max_radius_um:
        travelled += step_um
        offset_vox = (direction * travelled) / spacing
        point = np.round(origin + offset_vox).astype(int)
        if not all(0 <= p < s for p, s in zip(point, volume.shape)):
            break
        if volume[tuple(point)] < threshold:
            break
    return travelled


def volume_from_radii_um3(radii_um, path_zyx, voxel_size_um):
    """Frustum volume along the path: each segment is a truncated cone
    between consecutive radii. Reported as an estimate derived from the
    coarse radius profile above, not a segmentation-based measurement."""
    pts = np.asarray(path_zyx, float) * np.asarray(voxel_size_um, float)
    radii = np.asarray(radii_um, float)
    if len(pts) < 2:
        return 0.0
    lengths = np.linalg.norm(np.diff(pts, axis=0), axis=1)
    r1, r2 = radii[:-1], radii[1:]
    return float((np.pi / 3.0 * lengths * (r1 ** 2 + r1 * r2 + r2 ** 2)).sum())


def preflight_notes(stack_metadata, tube_response=None):
    """What a person should know before trusting a trace from this stack."""
    notes = []
    vox = stack_metadata.get("voxel_size_um")
    if vox:
        dz, dy, dx = vox
        ratio = dz / ((dy + dx) / 2.0)
        if ratio >= 2.0:
            notes.append(
                f"z spacing is {ratio:.1f}x the lateral pixel size. A neurite "
                f"running diagonally will look segmented between z planes, and "
                f"its traced length is less certain along z than across it.")
    if tube_response is not None:
        response = np.asarray(tube_response)
        strong = float((response > 0.5).mean())
        if strong < 1e-4:
            notes.append(
                "Almost no voxels score as tube-like. The expected radius may "
                "not match this structure, or the neurite may be too dim to "
                "trace in this stack.")
    return notes
