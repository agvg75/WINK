from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "movie"))
from image_sequence import discover_images, read_image, sequence_provenance


def test_common_still_formats_and_natural_order(tmp_path):
    image = np.zeros((40, 60), np.uint8)
    cv2.ellipse(image, (30, 20), (15, 5), 20, 0, 360, 180, -1)
    for name in ("frame10.jpg", "frame2.png", "frame1.tif", "frame3.bmp"):
        assert cv2.imwrite(str(tmp_path / name), image)
    files = discover_images(tmp_path)
    assert [p.name for p in files] == [
        "frame1.tif", "frame2.png", "frame3.bmp", "frame10.jpg"]
    assert all(read_image(path, grayscale=True).shape == image.shape
               for path in files)
    provenance = sequence_provenance(files)
    assert provenance["frame_count"] == 4
    assert provenance["lossy_compression_present"] is True
    assert provenance["geometry_use"] == "allowed"
    assert provenance["quantitative_intensity_use"] == "refused"
