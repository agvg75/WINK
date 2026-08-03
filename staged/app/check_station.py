"""What can this station do? Run it on every machine in the fleet.

Confocal work runs across several stations and which one gets used is not
predictable, so "does this machine have what it needs" has to be answerable
without guessing.

There used to be a second, opt-in VIEWER tier here, for a Napari/Qt
annotation viewer on a few appointed machines. That viewer was never built:
the annotation viewer ships as `tools/neurite_viewer.py`, which is Tkinter
and matplotlib and is part of the base install like every other WINK tool.
The tier has been removed rather than left to rot, because a stale
capability check is worse than none - it told every station it could not
create annotations and sent students to appointed machines that do not
exist. Annotation is BASE. If a genuinely optional heavyweight dependency
ever arrives, add the tier back then, for that thing.

What remains is two questions:

  BASE      are the packages every WINK tool needs actually installed?
  HARDWARE  can this machine comfortably hold a large confocal stack in
            memory? Nothing here is optional software - it is about whether
            a big acquisition will fit.

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

BASE_PACKAGES = ("numpy", "scipy", "matplotlib", "tifffile", "skimage",
                 "cv2", "PIL", "nd2", "czifile", "readlif")

# A single Leica plane in this lab is ~8.2 megapixels; a 24-plane 3-channel
# acquisition is well over a gigabyte once it is float. Below this there is
# nothing to install - the stack simply will not be comfortable.
MIN_RAM_GB_LARGE_STACKS = 16
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

    ram = _ram_gb()
    gpus = _gpu()
    free = _free_disk_gb()

    hardware_ok = True
    hardware_notes = []
    if ram is not None and ram < MIN_RAM_GB_LARGE_STACKS:
        hardware_ok = False
        hardware_notes.append(
            f"{ram} GB RAM, below the {MIN_RAM_GB_LARGE_STACKS} GB a large "
            f"confocal acquisition wants. Small stacks are unaffected; a big "
            f"multi-channel one may swap.")
    elif ram is None:
        hardware_notes.append("RAM could not be read on this platform.")
    if free is not None and free < MIN_FREE_DISK_GB:
        hardware_notes.append(
            f"Only {free} GB free, which is tight for exporting converted "
            f"stacks.")

    report = {
        "station": host,
        "platform": f"{platform.system()} {platform.release()}",
        "python": sys.version.split()[0],
        "python_executable": sys.executable,
        "base_ok": not base_missing,
        "base_present": base,
        "base_missing": base_missing,
        "ram_gb": ram,
        "free_disk_gb": free,
        "gpus": gpus,
        "large_stack_hardware_ok": hardware_ok,
        "hardware_notes": hardware_notes,
    }
    report["capabilities"] = _capabilities(report)
    return report


def _capabilities(r):
    """What this station can actually do today, in plain terms."""
    if not r["base_ok"]:
        return [f"BASE INSTALL INCOMPLETE - missing "
                f"{', '.join(r['base_missing'])}. Run Setup_Lab_Tools.bat."]
    return [
        "Open confocal stacks (CZI/ND2/LIF/OME-TIFF)",
        "Mark neurites in the annotation viewer (Tkinter, no 3D hardware)",
        "Trace neurites from an existing annotation sidecar",
        "Measure length, radius and volume; export CSV",
    ]


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
    lines.append(f"large stacks    {'comfortable' if r['large_stack_hardware_ok'] else 'tight'}")
    for note in r["hardware_notes"]:
        lines.append(f"  - {note}")
    lines += ["", "This station can:"]
    lines += [f"  * {c}" for c in r["capabilities"]]
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
