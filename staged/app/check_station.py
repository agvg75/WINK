"""What can this station do? Run it on every machine in the fleet.

Confocal work runs across several stations and which one gets used is not
predictable, so "does this machine have what it needs" has to be answerable
without guessing. This reports capability in three tiers:

  BASE      the Tkinter-only install every station gets. Opens confocal
            stacks, traces neurites from an existing annotation sidecar,
            measures, exports. No Qt, no GPU.

  VIEWER    the opt-in 3D annotation viewer (Napari/Qt), installed only on
            appointed stations. Needed ONLY to create annotations, never to
            use them.

  HARDWARE  whether this machine could host the viewer if you wanted it to.

Run it plain for a human summary, or with --json to collect across machines:

    python app/check_station.py
    python app/check_station.py --json > station_report.json
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from pathlib import Path

# Appointed viewer stations. Keep this list here, in the shipped code, so a
# station that lacks the viewer can NAME the machines that have it instead
# of leaving someone to ask around. Hostnames are matched case-insensitively.
VIEWER_STATIONS = {
    # "SLB122E-01": "confocal acquisition PC (Vidal-Gadea_lab share)",
}

BASE_PACKAGES = ("numpy", "scipy", "matplotlib", "tifffile", "skimage",
                 "cv2", "PIL", "nd2", "czifile", "readlif")
VIEWER_PACKAGES = ("napari", "qtpy")

MIN_RAM_GB_VIEWER = 16
MIN_FREE_DISK_GB = 10


def _have(module):
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def _version(module):
    try:
        mod = __import__(module)
        return str(getattr(mod, "__version__", "present"))
    except Exception:
        return None


def _ram_gb():
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:
            return round(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
                         / 1024 ** 3, 1)
    except Exception:
        pass
    try:                                    # Windows
        import ctypes

        class MemStat(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong),
                        ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong),
                        ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong),
                        ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        stat = MemStat()
        stat.dwLength = ctypes.sizeof(MemStat)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
        return round(stat.ullTotalPhys / 1024 ** 3, 1)
    except Exception:
        return None


def _gpu():
    """Best-effort GPU name. Absence is not proof there is no GPU - it means
    this check could not identify one, which is reported as such."""
    try:
        out = subprocess.run(
            ["wmic", "path", "win32_VideoController", "get", "name"],
            capture_output=True, text=True, timeout=20)
        names = [l.strip() for l in out.stdout.splitlines()[1:] if l.strip()]
        if names:
            return names
    except Exception:
        pass
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_VideoController).Name"],
            capture_output=True, text=True, timeout=25)
        names = [l.strip() for l in out.stdout.splitlines() if l.strip()]
        if names:
            return names
    except Exception:
        pass
    return []


def _free_disk_gb(path=None):
    try:
        return round(shutil.disk_usage(str(path or Path.home())).free / 1024 ** 3, 1)
    except Exception:
        return None


def check_station():
    host = socket.gethostname()
    base = {p: _version(p) for p in BASE_PACKAGES if _have(p)}
    base_missing = [p for p in BASE_PACKAGES if not _have(p)]
    viewer = {p: _version(p) for p in VIEWER_PACKAGES if _have(p)}
    viewer_missing = [p for p in VIEWER_PACKAGES if not _have(p)]

    ram = _ram_gb()
    gpus = _gpu()
    free = _free_disk_gb()
    appointed = any(k.lower() == host.lower() for k in VIEWER_STATIONS)

    hardware_ok = True
    hardware_notes = []
    if ram is not None and ram < MIN_RAM_GB_VIEWER:
        hardware_ok = False
        hardware_notes.append(
            f"{ram} GB RAM, below the {MIN_RAM_GB_VIEWER} GB a 3D viewer wants "
            f"for whole-stack rendering.")
    elif ram is None:
        hardware_notes.append("RAM could not be read on this platform.")
    if free is not None and free < MIN_FREE_DISK_GB:
        hardware_notes.append(
            f"Only {free} GB free; installing the viewer needs roughly "
            f"{MIN_FREE_DISK_GB} GB.")
    if not gpus:
        hardware_notes.append(
            "No GPU could be identified. This check cannot prove one is "
            "absent, but 3D rendering will fall back to software if so.")

    report = {
        "station": host,
        "platform": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "base_ok": not base_missing,
        "base_present": base,
        "base_missing": base_missing,
        "viewer_installed": not viewer_missing,
        "viewer_present": viewer,
        "viewer_missing": viewer_missing,
        "appointed_viewer_station": appointed,
        "ram_gb": ram,
        "free_disk_gb": free,
        "gpus": gpus,
        "viewer_hardware_ok": hardware_ok,
        "hardware_notes": hardware_notes,
        "appointed_stations": VIEWER_STATIONS,
    }
    report["capabilities"] = _capabilities(report)
    return report


def _capabilities(r):
    """What this station can actually do today, in plain terms."""
    caps = []
    if r["base_ok"]:
        caps.append("Open confocal stacks (CZI/ND2/LIF/OME-TIFF)")
        caps.append("Trace neurites from an existing annotation sidecar")
        caps.append("Measure length, radius and volume; export CSV")
    else:
        caps.append(f"BASE INSTALL INCOMPLETE - missing {', '.join(r['base_missing'])}. "
                    f"Run Setup_Lab_Tools.bat.")
    if r["viewer_installed"]:
        caps.append("Create neurite annotations in the 3D viewer")
    else:
        caps.append("CANNOT create new annotations here (3D viewer not installed)")
    return caps


def viewer_requirement_message(host=None):
    """What a tool should say when it needs the viewer and cannot find it.

    Names the appointed stations rather than telling someone to install
    something they may not be meant to install.
    """
    host = host or socket.gethostname()
    if VIEWER_STATIONS:
        listing = "\n".join(f"  - {name}  ({why})"
                            for name, why in sorted(VIEWER_STATIONS.items()))
        where = f"Stations set up for annotation:\n{listing}"
    else:
        where = ("No annotation stations have been appointed yet. Ask the lab "
                 "which machine should host the viewer, then add it to "
                 "VIEWER_STATIONS in app/check_station.py.")
    return (
        f"Creating a new neurite annotation needs the 3D viewer, which is not "
        f"installed on this station ({host}).\n\n"
        f"The viewer is an opt-in install kept off the base setup on purpose, "
        f"so ordinary stations stay light.\n\n{where}\n\n"
        f"You do NOT need the viewer to work with annotations that already "
        f"exist: tracing, measuring and exporting run on any station.")


def require_viewer():
    """Raise with a station-naming message unless the viewer is available."""
    missing = [p for p in VIEWER_PACKAGES if not _have(p)]
    if missing:
        raise RuntimeError(viewer_requirement_message())
    return True


def format_report(r):
    lines = [
        f"WINK station check - {r['station']}",
        "=" * 52,
        f"platform      {r['platform']}",
        f"python        {r['python']}",
        f"RAM           {r['ram_gb'] if r['ram_gb'] is not None else 'unknown'} GB",
        f"free disk     {r['free_disk_gb'] if r['free_disk_gb'] is not None else 'unknown'} GB",
        f"GPU           {', '.join(r['gpus']) if r['gpus'] else 'none identified'}",
        "",
        f"BASE install    {'OK' if r['base_ok'] else 'INCOMPLETE'}",
    ]
    if r["base_missing"]:
        lines.append(f"  missing:      {', '.join(r['base_missing'])}")
    lines.append(f"3D VIEWER       {'installed' if r['viewer_installed'] else 'not installed'}")
    lines.append(f"appointed here  {'yes' if r['appointed_viewer_station'] else 'no'}")
    lines.append(f"viewer-capable  {'yes' if r['viewer_hardware_ok'] else 'no'}")
    for note in r["hardware_notes"]:
        lines.append(f"  - {note}")
    lines += ["", "This station can:"]
    lines += [f"  * {c}" for c in r["capabilities"]]
    if not r["viewer_installed"]:
        lines += ["", viewer_requirement_message(r["station"])]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true",
                        help="emit JSON for collecting across the fleet")
    args = parser.parse_args()
    report = check_station()
    print(json.dumps(report, indent=2) if args.json else format_report(report))
    return 0 if report["base_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
