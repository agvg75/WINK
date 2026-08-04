"""Work in the animal's own frame: find its axis, rotate, and map back.

WHY. Everything in the myocyte pipeline is stated "along the body axis" -
boundaries run longitudinally, the seam tracer walks left to right one image
column at a time, region names assume anterior is left. All of that silently
assumes the animal LIES HORIZONTAL in the frame. It usually does not. A worm
mounted diagonally makes the tracer walk across background instead of along
muscle, and it produces confident nonsense rather than an error, because
nothing in the code ever states the assumption it is breaking.

So rather than ask people to crop and rotate by hand, the analysis is done in
the animal's frame and the results are mapped back to the original image. The
transform is explicit and invertible, so a boundary drawn here can always be
reported in the coordinates of the file it came from.

The rotation is written with an explicit affine rather than ndimage.rotate,
because the inverse must be exactly known to map results back - a sign or
convention error there would misplace every boundary by a consistent amount,
which looks like a systematic biological finding rather than a bug.
"""
from __future__ import annotations

import numpy as np


class FrameError(Exception):
    """Refusals that name the consequence."""


def tissue_mask(image, percentile=70, min_fraction=0.01):
    """The animal, as the largest bright connected region."""
    from scipy import ndimage as ndi

    img = np.asarray(image, dtype=float)
    sm = ndi.gaussian_filter(img, 3.0)
    m = sm > np.percentile(sm, percentile)
    m = ndi.binary_closing(m, np.ones((9, 9)))
    lab, n = ndi.label(m)
    if n == 0:
        raise FrameError(
            "No tissue was found in this image, so there is no body axis to "
            "work along. Every measurement downstream is stated relative to "
            "that axis.")
    sizes = ndi.sum(m, lab, range(1, n + 1))
    biggest = int(np.argmax(sizes)) + 1
    keep = lab == biggest
    if keep.mean() < min_fraction:
        raise FrameError(
            f"The largest bright region covers only {100 * keep.mean():.1f}% of "
            f"the frame, which is too little to be an animal. Rotating to the "
            f"axis of a speck would orient everything downstream to noise.")
    return ndi.binary_fill_holes(keep)


def axis_angle_deg(mask):
    """Angle of the tissue's long axis, in degrees, measured from horizontal.

    Positive is clockwise in image coordinates (y down), which is the same
    convention the rotation below uses. Also returns elongation - a nearly
    round region has no meaningful axis, and rotating to it would be arbitrary.
    """
    m = np.asarray(mask, dtype=bool)
    ys, xs = np.nonzero(m)
    if ys.size < 10:
        raise FrameError("Too few tissue pixels to estimate a body axis.")
    cy, cx = ys.mean(), xs.mean()
    yy, xx = ys - cy, xs - cx
    cov = np.array([[(xx * xx).mean(), (xx * yy).mean()],
                    [(xx * yy).mean(), (yy * yy).mean()]])
    evals, evecs = np.linalg.eigh(cov)
    order = np.argsort(evals)[::-1]
    evals, evecs = evals[order], evecs[:, order]
    vx, vy = evecs[0, 0], evecs[1, 0]
    angle = float(np.degrees(np.arctan2(vy, vx)))
    # fold to (-90, 90]: the axis is undirected, and anterior-left is decided
    # elsewhere from landmarks, not from which way the eigenvector happened to
    # point.
    if angle > 90:
        angle -= 180
    elif angle <= -90:
        angle += 180
    elongation = float(np.sqrt(evals[0] / max(evals[1], 1e-9)))
    return angle, elongation, (float(cy), float(cx))


def _rot(theta):
    """Matrix acting on (y, x) column vectors.

    CONVENTION TRAP, and the source of a real bug here: because the vector is
    ordered (y, x) rather than (x, y), this matrix performs a rotation by MINUS
    theta in the usual (x, y) sense. So straightening an animal whose axis sits
    at +theta needs `_rot(+theta)`, not `_rot(-theta)`. The first version used
    the latter and rotated a +30 degree bar to +60 - away from horizontal - and
    the round trip still verified exactly, because both directions shared the
    same wrong sign. Self-consistent and wrong.
    """
    c, s = np.cos(theta), np.sin(theta)
    return np.array([[c, -s], [s, c]])


def build_transform(shape, angle_deg, centre=None):
    """Everything needed to rotate by -angle and to map points back.

    Returns a dict with the inverse matrix and offset that
    `scipy.ndimage.affine_transform` wants (it maps OUTPUT coordinates to
    INPUT ones), the output shape, and the centres.
    """
    H, W = int(shape[0]), int(shape[1])
    theta = np.deg2rad(angle_deg)
    c_in = np.array(centre if centre is not None else (H / 2.0, W / 2.0))

    # forward: p_out = R(theta) (p_in - c_in) + c_out, which straightens an
    # axis sitting at +theta - see the convention note on _rot.
    fwd = _rot(theta)
    corners = np.array([[0, 0], [0, W - 1], [H - 1, 0], [H - 1, W - 1]],
                       dtype=float)
    proj = (fwd @ (corners - c_in).T).T
    lo, hi = proj.min(axis=0), proj.max(axis=0)
    out_shape = (int(np.ceil(hi[0] - lo[0])) + 1, int(np.ceil(hi[1] - lo[1])) + 1)
    c_out = -lo                                  # so the content starts at 0

    inv = _rot(-theta)                           # output -> input
    offset = c_in - inv @ c_out
    return {"angle_deg": float(angle_deg), "inv_matrix": inv, "offset": offset,
            "out_shape": out_shape, "c_in": c_in, "c_out": c_out,
            "in_shape": (H, W)}


def rotate_image(image, tf, order=1):
    from scipy import ndimage as ndi

    return ndi.affine_transform(np.asarray(image, dtype=float), tf["inv_matrix"],
                                offset=tf["offset"], output_shape=tf["out_shape"],
                                order=order, mode="constant", cval=0.0)


def rotate_volume(volume, tf, order=1):
    """Rotate each z plane. Depth is untouched - the animal is not tilted in z
    here, and resampling depth would blur planes that are physically apart."""
    vol = np.asarray(volume, dtype=float)
    if vol.ndim != 3:
        raise FrameError(f"Expected a (Z, Y, X) volume, got {vol.shape}.")
    return np.stack([rotate_image(p, tf, order=order) for p in vol])


def points_to_original(points_yx, tf):
    """Map (y, x) points from the working frame back to the original image.

    `crop_offset` is added back first: rotation pads the canvas, the padding is
    then trimmed away, and a point measured in the trimmed image is offset from
    the rotated one by exactly that amount.
    """
    p = np.atleast_2d(np.asarray(points_yx, dtype=float))
    # Undo detection downsampling FIRST: a point measured at 0.5 scale is half
    # the coordinate it would have at full resolution, and mapping it without
    # this would misplace every boundary by exactly the scale factor - a
    # consistent offset, which looks like a systematic finding rather than a
    # bug.
    s = float(tf.get("detect_scale", 1.0) or 1.0)
    if abs(s - 1.0) > 1e-9:
        p = p / s
    p = p + np.asarray(tf.get("crop_offset", (0.0, 0.0)), dtype=float)
    return (tf["inv_matrix"] @ (p - tf["c_out"]).T).T + tf["c_in"]


def points_to_rotated(points_yx, tf):
    """Inverse of points_to_original, for putting hand marks into the frame."""
    p = np.atleast_2d(np.asarray(points_yx, dtype=float))
    fwd = _rot(np.deg2rad(tf["angle_deg"]))
    out = (fwd @ (p - tf["c_in"]).T).T + tf["c_out"]
    out = out - np.asarray(tf.get("crop_offset", (0.0, 0.0)), dtype=float)
    s = float(tf.get("detect_scale", 1.0) or 1.0)
    return out * s if abs(s - 1.0) > 1e-9 else out


def trim_to_tissue(volume, tf, margin_um=4.0, um_per_px=1.0, percentile=70):
    """Trim the padding rotation added, back to the animal's bounding box.

    Two reasons, and the second is the important one:
      * rotation pads the canvas with zeros, and a seam forced to span the full
        width must cross that padding - where it means nothing, and from where
        it maps to coordinates OUTSIDE the source image
      * it is also the crop the tool otherwise lacks, so the analysis runs on
        the animal rather than on the whole field
    The offset is recorded in the transform, so mapping back still lands in the
    original image.
    """
    from scipy import ndimage as ndi

    vol = np.asarray(volume, dtype=float)
    proj = vol.max(axis=0)
    sm = ndi.gaussian_filter(proj, 3.0)
    m = sm > np.percentile(sm[sm > 0], percentile) if (sm > 0).any() else sm > 0
    if not m.any():
        return vol, tf
    ys, xs = np.nonzero(m)
    pad = int(max(margin_um / max(um_per_px, 1e-9), 2))
    y0 = max(int(ys.min()) - pad, 0)
    y1 = min(int(ys.max()) + pad + 1, vol.shape[1])
    x0 = max(int(xs.min()) - pad, 0)
    x1 = min(int(xs.max()) + pad + 1, vol.shape[2])
    out = dict(tf)
    prev = np.asarray(tf.get("crop_offset", (0.0, 0.0)), dtype=float)
    out["crop_offset"] = (float(prev[0] + y0), float(prev[1] + x0))
    out["cropped_shape"] = (int(y1 - y0), int(x1 - x0))
    return vol[:, y0:y1, x0:x1], out


def align(volume, projection=None, min_elongation=2.0, max_correction_deg=60.0):
    """Find the animal's axis and rotate the volume so it lies horizontal.

    Returns (rotated_volume, transform, report). The report carries the angle
    and elongation so a human can see how much was done and why, rather than
    the image quietly changing under them.

    REFUSES on a nearly round region: with no clear long axis, rotating picks a
    direction from noise and every 'longitudinal' result afterwards would be
    measured along an arbitrary line.
    """
    vol = np.asarray(volume, dtype=float)
    proj = np.asarray(projection) if projection is not None else vol.max(axis=0)
    mask = tissue_mask(proj)
    angle, elong, centre = axis_angle_deg(mask)
    report = {"axis_angle_deg": round(angle, 3),
              "elongation": round(elong, 3),
              "tissue_fraction": round(float(mask.mean()), 4),
              "rotated": False, "reason": ""}

    if elong < min_elongation:
        raise FrameError(
            f"The tissue is nearly round (elongation {elong:.2f}), so it has no "
            f"clear body axis. Rotating to it would pick a direction from noise, "
            f"and every longitudinal measurement afterwards would be taken along "
            f"an arbitrary line. Crop to a length of animal first.")

    if abs(angle) > max_correction_deg:
        report["reason"] = (
            f"axis at {angle:.1f} deg exceeds the {max_correction_deg:.0f} deg "
            f"correction limit; left unrotated")
        return vol, build_transform(proj.shape, 0.0, centre), report

    tf = build_transform(proj.shape, angle, centre)
    report["rotated"] = abs(angle) > 0.5
    report["reason"] = (f"rotated by {-angle:.1f} deg to bring the body axis "
                        f"horizontal" if report["rotated"] else
                        "already within half a degree of horizontal")
    if not report["rotated"]:
        return vol, build_transform(proj.shape, 0.0, centre), report
    return rotate_volume(vol, tf), tf, report
