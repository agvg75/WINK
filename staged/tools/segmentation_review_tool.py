"""Launch the supervised WINK segmentation review without changing an assay."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools" / "movie"))

from movie_reader import open_movie  # noqa: E402
from segmentation_review import (  # noqa: E402
    GEOMETRY_TOOLS, SegmentationReviewWindow)
# Imported at module level, not inside the handler that uses it: an `except
# ContextError` clause whose name is only bound on the success path raises
# NameError while handling the very error it was written to report.
from analysis_context import (  # noqa: E402
    ContextError, add_argument, from_arguments, sample_indices)


LABELS = {
    "track_one_worm": "Track one worm",
    "neuron_tracker_geometry": "Neuronal tracker worm geometry",
    "population_swimming": "Population swimming",
    "population_basal_slowing": "Population basal slowing",
    "population_orientation": "Population orientation",
    "defecation_cycle": "pBoc / defecation cycle",
    "endpoint_egg_counting": "Endpoint egg counting",
    "dynamic_egg_laying": "Dynamic egg laying",
}


def _arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", nargs="?",
        help="Movie, image stack, numbered image, or sequence folder.")
    parser.add_argument(
        "--tool", choices=tuple(LABELS),
        help="Target geometry tool (otherwise chosen interactively).")
    add_argument(parser)
    return parser.parse_args(argv)


def main(argv=None):
    args = _arguments(argv)
    root = tk.Tk()
    try:                      # error reporting
        from process_ui import install_error_reporting
        install_error_reporting(root)
    except Exception as _e:   # never break the tool for this
        print('error reporting unavailable:', _e)
    root.withdraw()
    # A CONTEXT, IF THE CALLER SENT ONE. It carries the recording as the
    # calling tool loaded it and the frame range it is working on, so this
    # window judges the same span rather than sampling the whole recording.
    # A malformed one is reported, not ignored: silently falling back to
    # "ask the user" would hide exactly the handoff failure this fixes.
    context = None
    try:
        context = from_arguments(args)
    except ContextError as exc:
        messagebox.showerror("Segmentation workbench", str(exc))
        return 2

    source = args.source
    if source is None and context is not None:
        source = context.source
    if source is None:
        source = filedialog.askopenfilename(
            title="Choose a movie, stack, or one image from a numbered sequence",
            filetypes=[(
                "Movies and images",
                "*.avi *.mp4 *.mov *.mkv *.tif *.tiff *.png *.jpg *.jpeg "
                "*.bmp *.pgm *.ppm *.pnm *.webp"), ("All files", "*.*")])
        if not source:
            folder = filedialog.askdirectory(
                title="Or choose a folder of sequential images")
            if not folder:
                return
            source = folder
    tool_name = args.tool
    if tool_name is None:
        prompt = "\n".join(
            f"{i + 1}. {LABELS[key]}" for i, key in enumerate(LABELS))
        choice = simpledialog.askinteger(
            "Target tool",
            "Choose the Python tool whose object extent this map will define:\n\n" + prompt,
            minvalue=1, maxvalue=len(LABELS), parent=root)
        if choice is None:
            return
        tool_name = list(LABELS)[choice - 1]
    try:
        movie = open_movie(source)
        # movie_reader exposes the canonical uniform API as n_frames/get_frame.
        # Keep fallbacks for older packaged video readers during migration.
        count = int(getattr(movie, "n_frames", getattr(movie, "frame_count", 0)))
        if count < 1:
            raise ValueError("No readable frames were found.")
        read_frame = getattr(movie, "get_frame", None)
        if read_frame is None:
            read_frame = movie.read_frame
        import numpy as np
        first=read_frame(0);bytes_per_frame=max(int(np.asarray(first).nbytes),1)
        # Keep the sampled preview/reference below 512 MiB even for 4K color.
        sample_limit=max(3,min(81,(512*1024**2)//bytes_per_frame))
        # Sample the span the CALLER is working on, not the whole recording,
        # and refuse a range that does not fit rather than trimming it. The
        # rule lives in analysis_context because every receiver needs it.
        indices = sample_indices(count, sample_limit, context)
        frames = [read_frame(i) for i in indices]
    except ContextError as exc:
        # A frame range that does not fit is not a broken source, and calling
        # it one would send the reader to check the wrong thing.
        messagebox.showerror("Frame range does not fit", str(exc), parent=root)
        return 2
    except Exception as exc:
        messagebox.showerror("Cannot open source", str(exc), parent=root)
        return
    save_dir = Path(source) if Path(source).is_dir() else Path(source).parent
    window = SegmentationReviewWindow(
        root, frames, source=source, save_dir=save_dir, tool_name=tool_name,
        frame_numbers=indices, frame_loader=read_frame,
        source_frame_count=count)
    window.protocol("WM_DELETE_WINDOW", window.destroy)
    root.deiconify()
    root.withdraw()
    root.wait_window(window)
    movie.close()
    root.destroy()


if __name__ == "__main__":
    main()
