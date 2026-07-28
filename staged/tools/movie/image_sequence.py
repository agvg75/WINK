"""Shared discovery/decoding for numbered microscopy image sequences."""
from __future__ import annotations

from pathlib import Path
import re
import cv2
import numpy as np

IMAGE_EXTENSIONS = {
    ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".bmp",
    ".pgm", ".ppm", ".pnm", ".webp",
}
LOSSY_EXTENSIONS = {".jpg", ".jpeg", ".webp"}


def natural_key(path):
    return [int(part) if part.isdigit() else part.lower()
            for part in re.split(r"(\d+)", Path(path).name)]


def discover_images(folder):
    folder = Path(folder)
    files = sorted(
        (path for path in folder.iterdir()
         if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS),
        key=natural_key)
    if not files:
        formats = ", ".join(sorted(IMAGE_EXTENSIONS))
        raise FileNotFoundError(
            f"No supported images found in {folder}. Supported: {formats}")
    return files


def read_image(path, grayscale=False):
    path = Path(path)
    image = cv2.imread(
        str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise OSError(f"Could not decode image: {path}")
    if grayscale and image.ndim == 3:
        if image.shape[2] == 4:
            image = cv2.cvtColor(image, cv2.COLOR_BGRA2GRAY)
        else:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def sequence_provenance(files):
    files = [Path(path) for path in files]
    extensions = sorted({path.suffix.lower() for path in files})
    lossy = any(ext in LOSSY_EXTENSIONS for ext in extensions)
    first = read_image(files[0])
    return {
        "frame_count": len(files),
        "extensions": extensions,
        "mixed_formats": len(extensions) > 1,
        "lossy_compression_present": lossy,
        "geometry_use": "allowed",
        "quantitative_intensity_use": (
            "refused" if lossy else "depends_on_bit_depth_and_acquisition"),
        "dtype": str(first.dtype),
        "bit_depth": int(np.dtype(first.dtype).itemsize * 8),
    }
