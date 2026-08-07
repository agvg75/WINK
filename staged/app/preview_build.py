"""Preview build identity and crash reporting. Crash-tolerant by design.

A preview goes to students knowing it will break. What matters is that a
break is REPORTABLE: the student sees a dialog rather than a vanished window,
and a full traceback lands somewhere Andres can read without asking them to
reproduce anything.

EVERY EXPORT CARRIES THE PREVIEW FLAG. A CSV that outlives the build it came
from must say what produced it, or preview numbers get quoted next to
released ones a year later with nothing to tell them apart.
"""
from __future__ import annotations

import datetime as _dt
import os
import platform
import sys
import traceback
from pathlib import Path

PREVIEW = True
BUILD_NAME = "WINK_CellViewer_PREVIEW_2026-08-07"

CRASH_LOG = Path(r"L:\10_AGVG LAB\Lab Tools\preview_crash_log")


def _read(path, default=""):
    try:
        return Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return default


def commit_hash():
    """The commit this build was cut from, recorded at build time.

    Read from a file rather than by running git, because the students'
    machines have no git and the snapshot is not a repository.
    """
    return _read(Path(__file__).with_name("BUILD_COMMIT.txt"), "unknown")


def version_string():
    return f"PREVIEW {commit_hash()} ({BUILD_NAME})"


def stamp():
    """The version fields every export and sidecar must carry."""
    return {
        "version": version_string(),
        "preview": True,
        "commit": commit_hash(),
        "build": BUILD_NAME,
        "not_for_publication": (
            "Preview build. Numbers may change without notice and this file "
            "must not be quoted beside released results without checking the "
            "commit."),
    }


def probe_dependencies():
    """Probe BY USE, not by import, and name the interpreter on failure.

    An import can succeed against a broken binary wheel; a call cannot. And
    the first question after a failure is always which Python is running, so
    it is in the message rather than in a follow-up email.
    """
    problems = []
    try:
        import numpy as np
        np.zeros((4, 4), dtype=np.float32).mean()
    except Exception as exc:                                 # noqa: BLE001
        problems.append(f"numpy: {type(exc).__name__}: {exc}")
    try:
        import cv2
        import numpy as np
        cv2.GaussianBlur(np.zeros((8, 8), np.uint8), (0, 0), 1.0)
        cv2.connectedComponentsWithStats(np.zeros((8, 8), np.uint8))
    except Exception as exc:                                 # noqa: BLE001
        problems.append(f"cv2: {type(exc).__name__}: {exc}")
    try:
        import tifffile                                      # noqa: F401
    except Exception as exc:                                 # noqa: BLE001
        problems.append(f"tifffile: {type(exc).__name__}: {exc}")
    try:
        from scipy import ndimage
        ndimage.label(__import__("numpy").zeros((4, 4), bool))
    except Exception as exc:                                 # noqa: BLE001
        problems.append(f"scipy: {type(exc).__name__}: {exc}")
    if problems:
        return False, (
            "This preview cannot run in the Python it was started with.\n\n"
            f"  interpreter: {sys.executable}\n\n"
            + "\n".join(f"  - {p}" for p in problems)
            + "\n\nStart it with the .bat in this folder, which finds the lab "
              "environment. Do not double-click the .py file.")
    return True, f"dependencies OK in {sys.executable}"


def write_crash(exc_type, value, tb, context=""):
    """Append a full traceback somewhere Andres can read it.

    Appends rather than overwrites: the second crash matters as much as the
    first, and a student who hits one will often hit three. Falls back to the
    build folder if L: is unreachable, and never raises - a crash reporter
    that crashes tells nobody anything.
    """
    body = [
        "=" * 70,
        f"when      {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"build     {version_string()}",
        f"machine   {platform.node()}  ({platform.platform()})",
        f"user      {os.environ.get('USERNAME', '?')}",
        f"python    {sys.executable}",
        f"context   {context or '-'}",
        "",
        "".join(traceback.format_exception(exc_type, value, tb)).rstrip(),
        "",
    ]
    text = "\n".join(body) + "\n"
    for target in (CRASH_LOG / f"crashes_{_dt.date.today():%Y%m}.log",
                   Path(__file__).resolve().parents[1] / "crashes.log"):
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "a", encoding="utf-8") as handle:
                handle.write(text)
            return target
        except Exception:                                    # noqa: BLE001
            continue
    return None


def install(root=None, context=""):
    """Top-level handler: dialog for the student, traceback for the log.

    Covers uncaught exceptions on the main thread AND in Tk callbacks, which
    are separate paths - pythonw discards stderr, so a Tk callback that
    raises otherwise makes a button simply appear to do nothing.
    """
    def report(exc_type, value, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, value, tb)
            return
        where = write_crash(exc_type, value, tb, context=context)
        summary = f"{exc_type.__name__}: {value}"
        try:
            import tkinter as tk
            from tkinter import messagebox
            owner = root
            if owner is None:
                owner = tk.Tk()
                owner.withdraw()
            messagebox.showerror(
                "WINK preview - something went wrong",
                f"{summary}\n\n"
                f"This is a PREVIEW build, so breakage is expected and worth "
                f"reporting.\n\n"
                f"The full details were written to:\n{where}\n\n"
                f"Nothing you have already saved is affected. Tell Andres "
                f"what you were doing when it happened.",
                parent=owner if owner is not root else root)
        except Exception:                                    # noqa: BLE001
            print(f"CRASH: {summary}\nlogged to {where}", file=sys.stderr)

    sys.excepthook = report
    if root is not None:
        try:
            root.report_callback_exception = (
                lambda exc_type, value, tb: report(exc_type, value, tb))
        except Exception:                                    # noqa: BLE001
            pass
    return report
