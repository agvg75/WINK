"""Plate-level circular statistics for population orientation assays.

The plate, never the worm or detected blob, is the inferential replicate.
"""
from __future__ import annotations
import math
import numpy as np
import pandas as pd


def resultant(angles_deg, weights=None):
    a=np.deg2rad(np.asarray(angles_deg,dtype=float)); good=np.isfinite(a)
    a=a[good]
    if weights is None: w=np.ones(len(a))
    else: w=np.asarray(weights,dtype=float)[good]
    if not len(a) or np.sum(w)<=0: return np.nan,np.nan
    z=np.sum(w*np.exp(1j*a))/np.sum(w)
    return float(np.degrees(np.angle(z))%360),float(abs(z))


def reduce_plate(plate_id, angles_deg, weights=None, n_worms=None):
    if not str(plate_id).strip(): raise ValueError("plate_id is required")
    values=np.asarray(angles_deg,dtype=float)
    mean_deg,r=resultant(values,weights)
    axial_doubled,axial_r=resultant((2.0*values)%360.0,weights)
    return {"plate_id":str(plate_id),"plate_mean_angle_deg":mean_deg,
            "plate_resultant_length":r,"plate_axis_orientation_deg":axial_doubled/2.0,
            "plate_axial_resultant_length":axial_r,"n_worms_on_plate":n_worms,
            "inferential_unit":"plate"}


def rayleigh(angles_deg):
    a=np.deg2rad(np.asarray(angles_deg,dtype=float)); a=a[np.isfinite(a)]; n=len(a)
    if n<2:return np.nan,np.nan
    r=abs(np.mean(np.exp(1j*a))); z=n*r*r
    p=math.exp(-z)*(1+(2*z-z*z)/(4*n)-(24*z-132*z*z+76*z**3-9*z**4)/(288*n*n))
    return float(r),float(np.clip(p,0,1))


def axial_rayleigh(angles_deg):
    """Rayleigh on doubled angles: tests clustering on an axis, not a direction."""
    return rayleigh((2.0*np.asarray(angles_deg,dtype=float))%360.0)


def v_test(angles_deg, expected_deg):
    a=np.deg2rad(np.asarray(angles_deg,dtype=float)); a=a[np.isfinite(a)]; n=len(a)
    if n<2:return np.nan,np.nan
    v=float(np.mean(np.cos(a-np.deg2rad(expected_deg))))
    # Large-sample normal approximation, explicitly reported as such.
    z=v*np.sqrt(2*n); p=.5*math.erfc(z/math.sqrt(2))
    return v,float(np.clip(p,0,1))


def analyse_plates(plate_rows, expected_deg=None):
    d=pd.DataFrame(plate_rows)
    if "plate_id" not in d or d.plate_id.astype(str).str.strip().eq("").any():
        raise ValueError("Every record requires plate_id")
    if d.plate_id.duplicated().any(): raise ValueError("Supply one reduced resultant per plate")
    angles=pd.to_numeric(d.plate_mean_angle_deg,errors="coerce").to_numpy()
    r,p=rayleigh(angles); v=vp=np.nan
    axes=pd.to_numeric(d.plate_axis_orientation_deg,errors="coerce").to_numpy()
    axial_r,axial_p=axial_rayleigh(axes)
    axis_doubled,_=resultant((2.0*axes)%360.0)
    if expected_deg is not None:v,vp=v_test(angles,float(expected_deg))
    orientations = (
        pd.to_numeric(
            d.magnet_orientation_relative_to_room_deg, errors="coerce").to_numpy()
        if "magnet_orientation_relative_to_room_deg" in d else
        np.full(len(d), np.nan))
    distinct = np.unique(np.round(orientations[np.isfinite(orientations)], 6))
    rotation_slope = np.nan
    certification = "REFUSED"
    reason = (
        "At least three distinct magnet orientations are required to separate "
        "field-locked response from room-locked or intrinsic bias.")
    valid_rotation = np.isfinite(angles) & np.isfinite(orientations)
    if len(np.unique(orientations[valid_rotation])) >= 3:
        x = np.unwrap(np.deg2rad(orientations[valid_rotation]))
        y = np.unwrap(np.deg2rad(angles[valid_rotation]))
        rotation_slope = float(np.polyfit(x, y, 1)[0])
        certification = "rotation_design_estimable"
        reason = ""
    curvature = (
        d.set_index("plate_id").mean_signed_track_curvature.to_dict()
        if "mean_signed_track_curvature" in d else {})
    pulse_comparison = {
        "status": "not_estimable",
        "reason": "Both pulsed and unpulsed independent plates are required."}
    if "magnetic_pulse_applied" in d:
        pulse = d.magnetic_pulse_applied.astype(bool).to_numpy()
        if pulse.any() and (~pulse).any():
            latency_shift = None
            if "median_departure_latency_s" in d:
                latency = pd.to_numeric(
                    d.median_departure_latency_s, errors="coerce").to_numpy()
                latency_shift = float(
                    np.nanmedian(latency[pulse]) -
                    np.nanmedian(latency[~pulse]))
            zp = np.mean(np.exp(1j * np.deg2rad(angles[pulse])))
            zu = np.mean(np.exp(1j * np.deg2rad(angles[~pulse])))
            pulse_comparison = {
                "status": "computed",
                "pulsed_n_plates": int(pulse.sum()),
                "unpulsed_n_plates": int((~pulse).sum()),
                "departure_latency_shift_s": latency_shift,
                "angle_shift_deg": float(np.rad2deg(np.angle(zp / zu))),
                "validation_level": "computational_regression"}
    return {"n_plates":int(np.isfinite(angles).sum()),
            "n_worms_per_plate":d.set_index("plate_id").n_worms_on_plate.to_dict() if "n_worms_on_plate" in d else {},
            "plate_level_resultant_length":r,"plate_level_rayleigh_p":p,
            "plate_level_axial_resultant_length":axial_r,
            "plate_level_axial_rayleigh_p":axial_p,
            "plate_axis_orientation_deg":axis_doubled/2.0,
            "plate_level_v":v,"plate_level_v_p":vp,
            "expected_direction_deg":expected_deg,"inferential_unit":"plate",
            "lab_frame_plate_angles_deg":
                d.set_index("plate_id").plate_mean_angle_deg.to_dict(),
            "radial_frame_plate_angles_deg": (
                d.set_index("plate_id").radial_frame_mean_angle_deg.to_dict()
                if "radial_frame_mean_angle_deg" in d else {}),
            "field_frame_plate_angles_deg": (
                d.set_index("plate_id").field_frame_mean_angle_deg.to_dict()
                if "field_frame_mean_angle_deg" in d else {}),
            "magnet_rotation_slope":rotation_slope,
            "stimulus_driven_certification":certification,
            "identifiability_reason":reason,
            "magnetic_pulse_comparison":pulse_comparison,
            "mean_signed_track_curvature_by_plate":curvature,
            "validation_level":"computational_regression",
            "pooled_worm_test":"REFUSED",
            "note":"Strong axial with weak directional clustering means the behavior is axial; away-going worms are signal, not noise. Any pooled worm value is descriptive_only_not_a_test."}
