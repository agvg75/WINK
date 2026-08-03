"""Myocyte morphometry: per-sarcomere striated body-wall muscle measurement.

Python port of Myocyte_Morphometry.ijm (Fiji macro), following the same
separation of concerns as nonstriated_morphology.py: pure functions here,
no UI code, no file dialogs, images/coordinates in, structured records out.

C. elegans body-wall muscle striation is oblique, not vertebrate-like: the
long bright phalloidin tracks run ALONG the muscle's long axis and are NOT
one sarcomere long. Sarcomere LENGTH is read ACROSS the bands (an intensity
profile roughly normal to the striations); sarcomere NUMBER is the count of
bands crossed ALONG the cell's long axis, at the cell's widest point (so
edge sarcomeres are not undercounted).

WHAT IS VALIDATED, AND HOW. Geometry (area/perimeter/Feret/MinFeret/major/
minor/AR/circularity/solidity/Feret angle) was checked against a REAL
polygon ROI and its REAL ImageJ-measured CSV row from an actual past
session (worm "1", myocyte m1, see tests/test_myocyte_morphometry.py) -
every field matches to within 0.3%. The detrend/autocorrelation/period-
estimate/peak-detection chain was checked bit-for-bit against real
raw_profile arrays the macro itself exported during real measurement
sessions, replaying the EXACT profile and comparing detected peak
positions. `get_profile_band` (the wide-line intensity sampler) is ported
using scipy.ndimage.map_coordinates per the macro's own documented
difficulty reproducing ImageJ's getProfile exactly; it WAS checked against
the real source TIFF for the same real profile (worm "1" myocyte m1,
L:/05_Proprioception/Ella/...). The peak sample INDEX matches exactly
(215 in both), and values match to <2% median relative error once a
single constant scale factor (~3x, consistent across every line width
tried and tightest at the macro's own documented band_width_px=15) is
divided out. That scale factor is real and reproducible, not noise - the
most likely explanation is that the on-disk TIFF is a different
processing version of the frame than whatever the macro's session
actually measured (e.g. one slice vs. a multi-slice projection), a data-
provenance question rather than a sampling-geometry one. This validates
what get_profile_band actually needs for downstream peak detection - WHERE
along the line the signal is, not its absolute brightness, which
detect_band_peaks never uses in absolute terms anyway. Still worth a fresh
check against any NEW dataset before trusting a batch run on it.

WHAT IS NOT YET VALIDATED: the auto-proposed sampling LINE end to end. Real
ROI polygons and real AUTO-mode CSV rows exist for worm "123" (4 myocytes,
L:/10_AGVG LAB/ImageJ_Tools/, source image
Sample_N2_day5A_phalloidin_worm02.tif). Replaying band_normal_angle +
widest_point_line + get_profile_band + detect_band_peaks fresh on those
real polygons reproduces the real geometry exactly (as expected) but
matches sarc_number/sarc_length_um on only 1 of 4 myocytes; the proposed
lines are geometrically sane on all 4 (midpoint inside the polygon,
endpoints within a few px of the boundary), so this is not obviously a
broken line-placement algorithm. The real ambiguity: worm "123"'s CSV rows
don't have a saved profile.txt recording which exact line was actually
used, and the macro lets the operator draw their own line instead of
accepting the proposal - a mismatch here could be a real port bug in the
angle/widest-point logic, OR simply a different (both legitimate) line
choice than whatever a person picked in that historical session. This
can't be resolved without either the original recorded line endpoints or
a live side-by-side comparison - exactly what the port spec's Phase 4
parallel-testing period is for. Treat the auto line proposal as unproven
until that happens; the sarcomere DETECTION math given a fixed line is
proven (see above).

Geometry formulas, and why they are not the "obvious" ones:
  - area/perimeter: computed analytically from the polygon vertices
    (shoelace / edge-length sum), NOT from a rasterized mask. A rasterized
    mask's perimeter estimator (e.g. skimage's) was off from ImageJ's real
    value by >4% on the real test case; the polygon-based formula matches
    to within 0.01%, because ImageJ's own "Perim." for a polygon ROI is
    the polygon's own edge length sum, not a raster boundary estimate.
  - Feret / MinFeret: max / min pairwise distance across the convex hull
    of the polygon. Matches ImageJ to within noise on the real test case.
  - major/minor (ellipse fit): ImageJ's EllipseFitter fits an ellipse with
    the same normalized second central moments as the RASTERIZED region,
    with a +1/12 per-axis bias correction for pixel discretization and a
    final area-matching scale factor. Skipping that correction (a plain
    regionprops ellipse fit) was off by ~3.5% on the real test case;
    including it matches to within 0.3%.
  - solidity: polygon area / convex hull area (both via the shoelace
    formula, not rasterized), matches ImageJ exactly on the real test case.
  - Feret angle: angle of the Feret diameter line, atan2(-dy, dx) mapped
    into [0, 180) degrees - the sign flip on dy accounts for image Y
    increasing downward while ImageJ reports a conventional CCW angle.
    Matches ImageJ exactly on the real test case (1.4603 vs 1.46 deg).
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from matplotlib.path import Path as MplPath
from scipy.ndimage import map_coordinates

# ---------------------------------------------------------------------------
# Tunables. Record any non-default value used for a real batch run, same
# convention as every other exposed threshold in this codebase.
# ---------------------------------------------------------------------------
SARC_LO_UM = 1.2           # sarcomere plausibility window (um) - fallback/
SARC_HI_UM = 2.5           # sanity check only, not a detection filter
CALIB_FLAG_LO_UM = 0.8     # below/above this, flag CHECK_CALIBRATION
CALIB_FLAG_HI_UM = 6.0
BAND_WIDTH_PX = 15         # wide-line averaging width for the across-band profile
MIN_PROFILE_N = 8          # macro requires n>=8 before attempting detection
WAVE_SMOOTH_UM = 0.3
WAVE_WINDOW_UM = 1.0
WAVE_LINK_UM = 1.4
WAVE_THRESH = 1.0
WAVE_AMBIG_THRESH = 0.3


# ---------------------------------------------------------------------------
# 1. Cell boundary geometry - all from the polygon directly, not a raster.
# ---------------------------------------------------------------------------
def _polygon_area_signed(poly):
    x = poly[:, 0]; y = poly[:, 1]
    x2 = np.roll(x, -1); y2 = np.roll(y, -1)
    return float(np.sum(x * y2 - x2 * y)) / 2.0


def _convex_hull(poly):
    hull = cv2.convexHull(np.round(poly).astype(np.int32))
    return hull.reshape(-1, 2).astype(float)


def _feret_and_angle(hull):
    n = len(hull)
    best = (0.0, 0, 1)
    for i in range(n):
        d = np.hypot(hull[i + 1:, 0] - hull[i, 0], hull[i + 1:, 1] - hull[i, 1])
        if d.size and d.max() > best[0]:
            j = i + 1 + int(np.argmax(d))
            best = (float(d.max()), i, j)
    feret, i, j = best
    dx = hull[j, 0] - hull[i, 0]; dy = hull[j, 1] - hull[i, 1]
    angle = np.degrees(np.arctan2(-dy, dx))
    angle = angle % 180.0
    return feret, float(angle)


def _min_feret(hull):
    rect = cv2.minAreaRect(hull.astype(np.float32))
    (_, _), (rw, rh), _ = rect
    return float(min(rw, rh))


def _ellipse_fit_px(mask_shape, poly_local):
    """ImageJ EllipseFitter-equivalent: rasterized second moments with the
    +1/12 per-axis pixel-discretization correction, then a scale factor so
    the fitted ellipse's area matches the true pixel count exactly."""
    h, w = mask_shape
    mask = np.zeros((h, w), np.uint8)
    cv2.fillPoly(mask, [np.round(poly_local).astype(np.int32)], 1)
    ys, xs = np.nonzero(mask)
    if len(xs) < 3:
        return 0.0, 0.0
    xm = xs.mean(); ym = ys.mean()
    x2m = float(((xs - xm) ** 2).mean()) + 1.0 / 12.0
    y2m = float(((ys - ym) ** 2).mean()) + 1.0 / 12.0
    xym = float(((xs - xm) * (ys - ym)).mean())
    common = np.hypot(x2m - y2m, 2 * xym)
    major = np.sqrt(2 * (x2m + y2m + common))
    minor = np.sqrt(2 * (x2m + y2m - common))
    if major <= 0 or minor <= 0:
        return 0.0, 0.0
    n = len(xs)
    scale = np.sqrt(n * 4.0 / (np.pi * major * minor))
    return float(major * scale), float(minor * scale)


def boundary_measurements(polygon_xy):
    """Cell boundary geometry from a hand-drawn polygon, in PIXELS.

    `polygon_xy` is an (N, 2) array of (x, y) vertices, e.g. from ginput
    clicks, matching nonstriated_morphology_tool.py's `draw()` convention.
    Multiply length fields by um_px, area by um_px**2, to get real units.
    """
    poly = np.asarray(polygon_xy, dtype=float)
    if len(poly) < 3:
        raise ValueError("A boundary polygon needs at least 3 vertices")
    area = abs(_polygon_area_signed(poly))
    x = poly[:, 0]; y = poly[:, 1]
    x2 = np.roll(x, -1); y2 = np.roll(y, -1)
    perimeter = float(np.hypot(x2 - x, y2 - y).sum())

    hull = _convex_hull(poly)
    feret, feret_angle = _feret_and_angle(hull)
    minferet = _min_feret(hull)
    hull_area = abs(_polygon_area_signed(hull))
    solidity = area / hull_area if hull_area > 0 else 0.0

    x0, y0 = poly[:, 0].min(), poly[:, 1].min()
    poly_local = poly - [x0, y0] + 5
    h = int(np.ceil(poly_local[:, 1].max())) + 10
    w = int(np.ceil(poly_local[:, 0].max())) + 10
    major, minor = _ellipse_fit_px((h, w), poly_local)
    aspect_ratio = major / minor if minor > 0 else 0.0
    circularity = 4 * np.pi * area / (perimeter ** 2) if perimeter > 0 else 0.0

    return {
        "area_px2": area, "perimeter_px": perimeter,
        "feret_px": feret, "minferet_px": minferet,
        "major_px": major, "minor_px": minor,
        "aspect_ratio": aspect_ratio, "circularity": circularity,
        "solidity": solidity, "feret_angle_deg": feret_angle,
        "anisotropy": feret / minferet if minferet > 0 else 0.0,
    }


# ---------------------------------------------------------------------------
# 2. Band orientation + widest-point sampling line.
# ---------------------------------------------------------------------------
def band_normal_angle(gray, polygon_xy):
    """Structure tensor over the polygon's bounding box, restricted to
    pixels inside the polygon. Direct port of bandNormalAngle(); the
    principal gradient direction is normal to the long bright striations
    = the direction to sample ACROSS bands for sarcomere length.

    Returns the angle in radians.
    """
    poly = np.asarray(polygon_xy, dtype=float)
    path = MplPath(poly)
    x0 = max(1, int(np.floor(poly[:, 0].min())))
    y0 = max(1, int(np.floor(poly[:, 1].min())))
    x1 = min(gray.shape[1] - 2, int(np.ceil(poly[:, 0].max())))
    y1 = min(gray.shape[0] - 2, int(np.ceil(poly[:, 1].max())))
    bw = max(1, x1 - x0); bh = max(1, y1 - y0)
    step = max(1, int(np.floor(min(bw, bh) / 40)))

    xs = np.arange(x0, x1, step)
    ys = np.arange(y0, y1, step)
    if len(xs) == 0 or len(ys) == 0:
        return np.pi / 2
    gx_grid, gy_grid = np.meshgrid(xs, ys)
    pts = np.column_stack([gx_grid.ravel(), gy_grid.ravel()])
    inside = path.contains_points(pts)
    if not inside.any():
        return np.pi / 2
    pts_in = pts[inside].astype(int)
    g = gray.astype(np.float32)
    gx = (g[pts_in[:, 1], np.clip(pts_in[:, 0] + 1, 0, g.shape[1] - 1)]
          - g[pts_in[:, 1], np.clip(pts_in[:, 0] - 1, 0, g.shape[1] - 1)]) / 2
    gy = (g[np.clip(pts_in[:, 1] + 1, 0, g.shape[0] - 1), pts_in[:, 0]]
          - g[np.clip(pts_in[:, 1] - 1, 0, g.shape[0] - 1), pts_in[:, 0]]) / 2
    jxx = float(np.sum(gx * gx)); jyy = float(np.sum(gy * gy)); jxy = float(np.sum(gx * gy))
    return 0.5 * np.arctan2(2 * jxy, jxx - jyy)


def widest_point_line(polygon_xy, normal_angle):
    """Place the across-band sampling line at the polygon's widest point
    along its long axis, so edge sarcomeres are not undercounted. Direct
    port of the marching loop in measureMyocyte().

    Returns (ax1, ay1, ax2, ay2) in pixel coordinates, or None if the
    polygon is too small for the march to find a usable span.
    """
    poly = np.asarray(polygon_xy, dtype=float)
    path = MplPath(poly)
    x0, y0 = poly[:, 0].min(), poly[:, 1].min()
    x1, y1 = poly[:, 0].max(), poly[:, 1].max()
    rbw, rbh = x1 - x0, y1 - y0
    ccx, ccy = x0 + rbw / 2, y0 + rbh / 2

    nux, nuy = np.cos(normal_angle), np.sin(normal_angle)
    mux, muy = -nuy, nux
    long_span = max(rbw, rbh)
    max_reach = 2 * long_span

    def inside(px, py):
        return bool(path.contains_point((round(px), round(py))))

    best_span = -1; best_t = 0; best_px = ccx; best_py = ccy
    best_rp = 0; best_rm = 0
    t = -0.5 * long_span
    while t <= 0.5 * long_span:
        qx, qy = ccx + t * mux, ccy + t * muy
        rp = 0
        while rp < max_reach and inside(qx + rp * nux, qy + rp * nuy):
            rp += 1
        rm = 0
        while rm < max_reach and inside(qx - rm * nux, qy - rm * nuy):
            rm += 1
        span = rp + rm
        if span > best_span:
            best_span, best_t, best_px, best_py = span, t, qx, qy
            best_rp, best_rm = rp, rm
        t += 3

    if best_span < 6:
        samp_len = 0.8 * min(rbw, rbh)
        if samp_len < 20:
            samp_len = min(rbw, rbh)
        if samp_len <= 0:
            return None
        ax1 = ccx - 0.5 * samp_len * nux; ay1 = ccy - 0.5 * samp_len * nuy
        ax2 = ccx + 0.5 * samp_len * nux; ay2 = ccy + 0.5 * samp_len * nuy
        return ax1, ay1, ax2, ay2

    ax1 = best_px - best_rm * nux; ay1 = best_py - best_rm * nuy
    ax2 = best_px + best_rp * nux; ay2 = best_py + best_rp * nuy
    return ax1, ay1, ax2, ay2


# ---------------------------------------------------------------------------
# 3. Profile sampling - the highest-risk port, see module docstring.
# ---------------------------------------------------------------------------
def get_profile_band(gray, x1, y1, x2, y2, line_width=BAND_WIDTH_PX):
    """Intensity profile averaged across a wide line, ported from ImageJ's
    getProfile() on a line with a set width. Samples `n = round(length)+1`
    points along the line (ImageJ's own line-profile length convention),
    averaging across `line_width` parallel offset lines at each point via
    bilinear interpolation.

    NOT validated pixel-for-pixel against real ImageJ output in this port
    (see module docstring) - the macro's own comments note this exact
    behavior was hard to reproduce by approximation. Validate against a
    real profile.txt export before trusting this on new data.
    """
    length = float(np.hypot(x2 - x1, y2 - y1))
    n = int(round(length)) + 1
    if n < 2:
        return np.zeros(0, dtype=np.float64)
    t = np.linspace(0.0, 1.0, n)
    cx = x1 + t * (x2 - x1)
    cy = y1 + t * (y2 - y1)
    ux, uy = (x2 - x1) / max(length, 1e-9), (y2 - y1) / max(length, 1e-9)
    # perpendicular direction to average across
    px, py = -uy, ux
    half = (line_width - 1) / 2.0
    offsets = np.arange(line_width) - half if line_width > 1 else np.array([0.0])
    acc = np.zeros(n, dtype=np.float64)
    for off in offsets:
        sample_x = cx + off * px
        sample_y = cy + off * py
        acc += map_coordinates(gray.astype(np.float64), [sample_y, sample_x],
                                order=1, mode="nearest")
    return acc / len(offsets)


# ---------------------------------------------------------------------------
# 4. Detrend / autocorrelation / period estimate / peak detection.
#    Validated bit-for-bit against real raw_profile arrays - see
#    tests/test_myocyte_morphometry.py.
# ---------------------------------------------------------------------------
def detrend(a, win):
    """Moving-mean detrend: subtract the local windowed mean (window
    `2*win+1`, clipped at the array ends) from each point."""
    a = np.asarray(a, dtype=np.float64)
    n = len(a)
    out = np.empty(n)
    for i in range(n):
        lo = max(0, i - win); hi = min(n - 1, i + win)
        out[i] = a[i] - a[lo:hi + 1].mean()
    return out


def autocorr(a):
    """Normalized autocorrelation: out[lag] = sum(a[i]*a[i+lag]) / sum(a^2)."""
    a = np.asarray(a, dtype=np.float64)
    n = len(a)
    z = float(np.sum(a * a))
    out = np.zeros(n)
    if z <= 0:
        return out
    for lag in range(n):
        out[lag] = float(np.sum(a[:n - lag] * a[lag:])) / z
    return out


def estimate_period_px(prof):
    """Dominant spacing in `prof`, in pixels, from its own autocorrelation,
    with NO dependency on calibration. Only genuine LOCAL MAXIMA beyond a
    small minimum lag are considered (autocorrelation is trivially high
    near lag 0 regardless of real periodicity). Returns -1 if no clear
    local maximum is found."""
    prof = np.asarray(prof, dtype=np.float64)
    n = len(prof)
    min_lag = 5
    max_lag = n // 2
    if max_lag <= min_lag + 1:
        return -1.0
    ac = autocorr(prof)
    best = -1; best_v = -1.0
    for lag in range(min_lag, max_lag + 1):
        if ac[lag] >= ac[lag - 1] and ac[lag] > ac[lag + 1]:
            if ac[lag] > best_v:
                best_v = ac[lag]; best = lag
    if best < 1:
        return -1.0
    yl, y0, yr = ac[best - 1], ac[best], ac[best + 1]
    den = yl - 2 * y0 + yr
    ref = best + (0.5 * (yl - yr) / den if den != 0 else 0.0)
    return float(ref)


def detect_band_peaks(prof, lo_um=SARC_LO_UM, hi_um=SARC_HI_UM, um_px=0.1):
    """Bright band-center peaks along a profile, with minimum spacing and
    spacing-consistency judged RELATIVE to a period estimated from the
    profile's OWN data, not an absolute calibrated target - so a wrong
    um_px cannot silently corrupt which peaks get accepted. `lo_um`/`hi_um`
    are used only as a fallback when the profile has no genuine periodicity
    of its own to measure.

    Returns (peak_indices, est_period_px) - the period is also useful as a
    diagnostic (matches the macro's LASTESTPERIOD debug export).
    """
    prof = np.asarray(prof, dtype=np.float64)
    n = len(prof)
    sm = np.empty(n)
    for i in range(n):
        a = max(0, i - 1); b = min(n - 1, i + 1)
        sm[i] = (prof[a] + prof[i] + prof[b]) / 3

    est_period = estimate_period_px(sm)
    if est_period < 2:
        est_period = ((lo_um + hi_um) / 2) / um_px
    min_spacing_px = max(2, round(0.6 * est_period))

    pos = []
    last = -100000
    for i in range(1, n - 1):
        if sm[i] >= sm[i - 1] and sm[i] > sm[i + 1]:
            if i - last >= min_spacing_px:
                pos.append(i); last = i
            elif pos and sm[i] > sm[pos[-1]]:
                pos[-1] = i; last = i

    if len(pos) < 2:
        return np.array(pos, dtype=int), est_period

    lo_rel, hi_rel = 0.6 * est_period, 1.5 * est_period
    keep = []
    for i in range(len(pos)):
        ok_l = ok_r = False
        if i > 0:
            d = pos[i] - pos[i - 1]
            ok_l = lo_rel <= d <= hi_rel
        if i < len(pos) - 1:
            d = pos[i + 1] - pos[i]
            ok_r = lo_rel <= d <= hi_rel
        if ok_l or ok_r:
            keep.append(pos[i])
    return np.array(keep, dtype=int), est_period


def interval_stats(pos, um_px):
    """(n_intervals, mean_um, sd_um, cv) from refined peak positions (px)."""
    pos = np.asarray(pos, dtype=np.float64)
    if len(pos) < 2:
        return 0, 0.0, 0.0, 0.0
    d = np.diff(pos) * um_px
    n = len(d)
    mean = float(d.mean())
    sd = float(d.std(ddof=1)) if n > 1 else 0.0
    cv = sd / mean if mean > 0 else 0.0
    return n, mean, sd, cv


def calibration_flag(mean_length_um, lo=CALIB_FLAG_LO_UM, hi=CALIB_FLAG_HI_UM):
    """Sanity check on the OUTPUT length, not a filter on detection -
    deliberately loose, exists only to catch a badly wrong um_px."""
    if mean_length_um > 0 and (mean_length_um < lo or mean_length_um > hi):
        return "CHECK_CALIBRATION"
    return "OK"


def sarcomere_quality(n_intervals, cv):
    if n_intervals >= 4 and cv < 0.18:
        return "HIGH"
    if n_intervals >= 3 and cv < 0.30:
        return "MED"
    return "LOW"


# Region boundaries per the lab's body-wall numbering schematic (Myo01-24).
# Matches the macro's regionFromMyoNum() exactly: anterior 1-10, midbody
# 11-18, posterior 19-24.
MYO_NUMBER_REGION_BOUNDS = (("anterior", 1, 10), ("midbody", 11, 18),
                            ("posterior", 19, 24))


def region_from_myo_number(n, default_region):
    """Region implied by a body-wall myocyte number (1-24), falling back to
    `default_region` outside that range - should not normally happen, same
    as the macro's own fallback."""
    for region, lo, hi in MYO_NUMBER_REGION_BOUNDS:
        if lo <= n <= hi:
            return region
    return default_region


# ---------------------------------------------------------------------------
# 5. Fiber tracing and waviness (dystrophic damage proxy).
# ---------------------------------------------------------------------------
def trace_fiber_along(gray, path_contains, x0, y0, mux, muy, nux, nuy,
                       step_px, search_px, max_steps):
    """Ridge-follow along (mux, muy) from (x0, y0), snapping at each step
    to the brightest pixel within `search_px` of the across-band (nux, nuy)
    direction. Also flags each step as ambiguous when a second local
    maximum at least 3px away is at least 80% as bright - a real signature
    of a fiber split or an oblique branch, not ordinary noise.

    `path_contains(x, y)` is a callable, e.g. matplotlib.path.Path's
    contains_point, restricting the trace to the myocyte's own boundary.
    Returns (xs, ys, ambiguous) arrays.
    """
    h, w = gray.shape
    xs = np.empty(max_steps); ys = np.empty(max_steps); amb = np.empty(max_steps, dtype=bool)
    cx, cy = float(x0), float(y0)
    n = 0
    offsets = np.arange(-search_px, search_px + 1)
    for _ in range(max_steps):
        if not path_contains(round(cx), round(cy)):
            break
        px = np.round(cx + offsets * nux).astype(int)
        py = np.round(cy + offsets * nuy).astype(int)
        valid = (px >= 0) & (py >= 0) & (px < w) & (py < h)
        vals = np.full(len(offsets), -1.0)
        vals[valid] = gray[py[valid], px[valid]]
        best_idx = int(np.argmax(vals))
        best_off = offsets[best_idx]; best_v = vals[best_idx]

        second_v = -1.0
        for k in range(1, len(vals) - 1):
            if abs(offsets[k] - best_off) < 3:
                continue
            if vals[k] >= 0 and vals[k] >= vals[k - 1] and vals[k] >= vals[k + 1]:
                if vals[k] > second_v:
                    second_v = vals[k]
        is_ambig = second_v >= 0 and best_v > 0 and (second_v / best_v) >= 0.8

        cx = cx + best_off * nux; cy = cy + best_off * nuy
        xs[n] = cx; ys[n] = cy; amb[n] = is_ambig
        n += 1
        cx = cx + step_px * mux; cy = cy + step_px * muy
    return xs[:n], ys[:n], amb[:n]


def classify_fiber_wavy(fx, fy, mux, muy, nux, nuy, um_px,
                         wave_smooth_um=WAVE_SMOOTH_UM,
                         wave_window_um=WAVE_WINDOW_UM,
                         wave_thresh=WAVE_THRESH):
    """Classify one already-traced fiber as wavy or not, and how much of
    its length is wavy. Projects onto the fiber's own (along, across)
    axes, smooths the perpendicular deviation at a real distance (not a
    fixed pixel count - that mismatch was a confirmed real bug when first
    tried on an image with a different um_px), takes the local slope, then
    slides a window along scoring (direction changes per um) x (mean slope
    magnitude); a window at or above `wave_thresh` marks that stretch wavy.

    Returns (any_wavy: bool, wavy_len_um: float).
    """
    fx = np.asarray(fx, dtype=np.float64); fy = np.asarray(fy, dtype=np.float64)
    n = len(fx)
    if n < 10:
        return False, 0.0
    x0, y0 = fx[0], fy[0]
    rx, ry = fx - x0, fy - y0
    t = rx * mux + ry * muy
    dd = rx * nux + ry * nuy

    spacing_px = (t[-1] - t[0]) / (n - 1) if n > 1 else 1.0
    if spacing_px <= 0:
        spacing_px = 1.0
    smooth_n = max(1, round((wave_smooth_um / um_px) / spacing_px))

    dd_sm = np.empty(n)
    for i in range(n):
        a = max(0, i - smooth_n); b = min(n - 1, i + smooth_n)
        dd_sm[i] = dd[a:b + 1].mean()
    slope = np.zeros(n)
    for i in range(n):
        a = max(0, i - smooth_n); b = min(n - 1, i + smooth_n)
        if t[b] != t[a]:
            slope[i] = (dd_sm[b] - dd_sm[a]) / (t[b] - t[a])

    window_n = max(4, round((wave_window_um / um_px) / spacing_px))
    step_n = max(1, round(window_n / 2))
    deadzone = 0.05

    wavy_mask = np.zeros(n, dtype=bool)
    i = 0
    while i < n:
        j = min(n, i + window_n)
        if j - i < window_n * 0.6:
            i2 = max(0, n - window_n); j = n
        else:
            i2 = i
        turns = 0; state = 0; sum_abs = 0.0; cnt = 0
        for k in range(i2, j):
            s_val = slope[k]
            sum_abs += abs(s_val); cnt += 1
            cur = 1 if s_val > deadzone else (-1 if s_val < -deadzone else 0)
            if cur != 0:
                if state != 0 and cur != state:
                    turns += 1
                state = cur
        length_um_seg = (t[j - 1] - t[i2]) * um_px
        mean_abs = sum_abs / cnt if cnt > 0 else 0.0
        score = (turns / length_um_seg) * mean_abs * 100 if length_um_seg > 0 else 0.0
        if score >= wave_thresh:
            wavy_mask[i2:j] = True
        if j >= n:
            i = n
        else:
            i += step_n

    any_wavy = bool(wavy_mask.any())
    wavy_count = int(wavy_mask.sum())
    wavy_len_um = wavy_count * spacing_px * um_px
    if not np.isfinite(wavy_len_um):
        wavy_len_um = 0.0
    return any_wavy, float(wavy_len_um)


def detect_waves(gray, path_contains, zpos, ax1, ay1, mux, muy, nux, nuy,
                  feret_um, um_px,
                  wave_link_um=WAVE_LINK_UM, wave_ambig_thresh=WAVE_AMBIG_THRESH,
                  **classify_kwargs):
    """Orchestrate wave detection for one myocyte: seed one fiber trace per
    already-detected sarcomere band position (zpos), trace forward and
    backward along the muscle's long axis, classify each fiber, and
    aggregate into two damage-proxy fractions. Reuses the SAME ROI, band
    angle, and sampling line already computed for sarcomere detection - no
    re-detection of any of it. Comparative proxies (same imaging), not
    absolute damage measurements, matching the macro's own framing.

      width fraction  = fraction of fibers (across MinFeret) with any wave
      length fraction = for affected fibers, how much of the myocyte's own
                         Feret their wave covers (mean and max)

    Low-confidence fibers (ambiguous trace fraction >= wave_ambig_thresh,
    e.g. a real split or oblique branch) are excluded from both fractions'
    numerator and denominator reasoning the same way the macro treats them:
    counted separately, not forced into wavy or straight.

    Returns a dict with n_fibers, n_affected, n_lowconf, width_fraction,
    length_frac_mean, length_frac_max, and per-fiber classifications.
    """
    n_fibers = len(zpos)
    result = {"n_fibers": n_fibers, "n_affected": 0, "n_lowconf": 0,
              "width_fraction": 0.0, "length_frac_mean": 0.0,
              "length_frac_max": 0.0, "fibers": []}
    if n_fibers < 2:
        return result

    gaps = np.diff(np.sort(zpos))
    min_gap_px = float(gaps.min()) if len(gaps) else -1.0
    search_px = max(2, round(wave_link_um / um_px))
    if min_gap_px > 0:
        safe_cap_px = max(2, int(np.floor(0.35 * min_gap_px)))
        search_px = min(search_px, safe_cap_px)
    step_px = 2
    max_steps_fiber = max(10, round((3 * feret_um) / um_px))

    fiber_class = []       # 0 straight, 1 wavy, 2 low-confidence
    fiber_len_frac = []
    for zi in zpos:
        seed_x = ax1 + zi * nux; seed_y = ay1 + zi * nuy
        fx_f, fy_f, amb_f = trace_fiber_along(
            gray, path_contains, seed_x, seed_y, mux, muy, nux, nuy,
            step_px, search_px, max_steps_fiber)
        fx_b, fy_b, amb_b = trace_fiber_along(
            gray, path_contains, seed_x, seed_y, -mux, -muy, nux, nuy,
            step_px, search_px, max_steps_fiber)
        fx = np.concatenate([fx_b[::-1], fx_f])
        fy = np.concatenate([fy_b[::-1], fy_f])
        amb = np.concatenate([amb_b[::-1], amb_f])
        n_tot = len(fx)
        if n_tot < 20:
            continue
        ambig_frac = float(amb.sum()) / n_tot

        any_wavy, wavy_len_um = classify_fiber_wavy(
            fx, fy, mux, muy, nux, nuy, um_px, **classify_kwargs)

        cls = 2 if ambig_frac >= wave_ambig_thresh else (1 if any_wavy else 0)
        len_frac = wavy_len_um / feret_um if (cls == 1 and feret_um > 0) else 0.0
        fiber_class.append(cls); fiber_len_frac.append(len_frac)
        result["fibers"].append({
            "x": fx, "y": fy, "class": cls, "length_fraction": len_frac,
            "ambiguous_fraction": ambig_frac,
        })

    n_affected = sum(1 for c in fiber_class if c == 1)
    n_lowconf = sum(1 for c in fiber_class if c == 2)
    len_fracs = [f for c, f in zip(fiber_class, fiber_len_frac) if c == 1]
    result["n_affected"] = n_affected
    result["n_lowconf"] = n_lowconf
    if n_fibers > 0:
        result["width_fraction"] = n_affected / n_fibers
    if len_fracs:
        result["length_frac_mean"] = float(np.mean(len_fracs))
        result["length_frac_max"] = float(np.max(len_fracs))
    return result
