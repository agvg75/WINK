"""Render queued myocyte-morphometry failure breadcrumbs into the library.

Myocyte_Morphometry.ijm writes a small JSON "breadcrumb" (no image) to
<output>\\failure_queue\\<id>.json whenever a correction happens, using only
plain-data ImageJ calls (roiManager Select / getSelectionBounds / Select None /
File.saveString) - deliberately nothing that opens, flattens, or closes an image
window, because earlier versions that did stalled the tool during live use.

This script does the image work instead, entirely outside Fiji: it finds each
breadcrumb, opens the source image with PIL, crops it to the recorded myocyte
ROI (with a margin), and writes it into the shared failure library alongside a
meta.json - the same schema failure_gallery.py already reads. Run this any time
after a Fiji session ends; never while one is in progress.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
from PIL import Image

MARGIN_FRACTION = 0.15  # extra context around the myocyte ROI, as a fraction of its size


def sanitize(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(s))


def to_uint8(arr: np.ndarray) -> np.ndarray:
    if arr.dtype == np.uint8:
        return arr
    lo, hi = np.percentile(arr, [0.5, 99.5])
    return np.clip((arr.astype(float) - lo) * 255 / max(hi - lo, 1), 0, 255).astype(np.uint8)


def crop_with_margin(arr: np.ndarray, bbox_xywh, margin_fraction=MARGIN_FRACTION):
    x, y, w, h = bbox_xywh
    H, W = arr.shape[:2]
    mx = int(round(w * margin_fraction))
    my = int(round(h * margin_fraction))
    x0 = max(0, int(x) - mx)
    y0 = max(0, int(y) - my)
    x1 = min(W, int(x + w) + mx)
    y1 = min(H, int(y + h) + my)
    if x1 <= x0 or y1 <= y0:
        return arr
    return arr[y0:y1, x0:x1]


def find_breadcrumbs(scan_root: Path):
    return sorted(Path(scan_root).rglob("failure_queue/*.json"))


def find_source_image(image_title: str, search_roots) -> Path | None:
    """Locate the source image by filename under each root, in order.

    The breadcrumb intentionally does not record the image's folder (the Fiji
    call needed for that broke the tool twice - see Myocyte_Morphometry.ijm);
    it only has the filename. This searches likely locations instead, the same
    way the one-off bootstrap script located Ella's images by filename.
    """
    if not image_title:
        return None
    for root in search_roots:
        if root is None:
            continue
        root = Path(root)
        if not root.exists():
            continue
        hits = list(root.rglob(image_title))
        if hits:
            return hits[0]
    return None


def render_one(breadcrumb_path: Path, library_root: Path, extra_image_root=None) -> tuple[bool, str]:
    try:
        rec = json.loads(breadcrumb_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return False, f"could not read breadcrumb: {exc}"

    image_title = rec.get("image_title", "")
    # The breadcrumb's own output folder (two levels up from the .json, since
    # it lives at <output>\failure_queue\<id>.json) is tried first - a common
    # case is the images sitting right there - then the explicit search root.
    breadcrumb_output_dir = breadcrumb_path.parent.parent
    src = find_source_image(image_title, [breadcrumb_output_dir, extra_image_root])
    if src is None:
        return False, f"source image '{image_title}' not found under {breadcrumb_output_dir} or {extra_image_root}"

    try:
        im = Image.open(src)
        arr = np.asarray(im)
    except Exception as exc:
        return False, f"could not open source image: {exc}"

    bbox = rec.get("roi_bbox_px")
    crop = to_uint8(crop_with_margin(arr, bbox)) if bbox else to_uint8(arr)

    worm_id = rec.get("worm_id", "unknown")
    myo_id = rec.get("myocyte_id", "0")
    entry_id = f"{sanitize(worm_id)}_myo{myo_id}_{sanitize(breadcrumb_path.stem)}"
    entry_dir = library_root / "myocyte" / entry_id
    entry_dir.mkdir(parents=True, exist_ok=True)

    try:
        Image.fromarray(crop).save(entry_dir / "source.png")
    except Exception as exc:
        return False, f"could not save cropped PNG: {exc}"

    meta = dict(rec)
    meta["tool"] = "myocyte_morphometry"
    meta["source"] = "queued_breadcrumb_render"
    meta["source_image_path"] = str(src)
    meta["image"] = "source.png"
    (entry_dir / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return True, str(entry_dir)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scan_root", help="Folder to search recursively for failure_queue/*.json")
    parser.add_argument("library_root", help="Failure library root to write into (…/failure_library)")
    parser.add_argument("--image-root", default=None,
                        help="Extra folder to search (recursively, by filename) if a source image "
                             "isn't found next to its breadcrumb's output folder")
    parser.add_argument("--keep-queue", action="store_true",
                        help="Do not delete breadcrumbs after a successful render (default: delete)")
    args = parser.parse_args(argv)

    scan_root = Path(args.scan_root)
    library_root = Path(args.library_root)
    library_root.mkdir(parents=True, exist_ok=True)

    breadcrumbs = find_breadcrumbs(scan_root)
    print(f"Found {len(breadcrumbs)} breadcrumb(s) under {scan_root}")
    ok_count = 0
    for path in breadcrumbs:
        ok, detail = render_one(path, library_root, extra_image_root=args.image_root)
        status = "OK" if ok else "SKIP"
        print(f"  [{status}] {path.name}: {detail}")
        if ok:
            ok_count += 1
            if not args.keep_queue:
                try:
                    path.unlink()
                except Exception:
                    pass
    print(f"Rendered {ok_count}/{len(breadcrumbs)} into {library_root}")


if __name__ == "__main__":
    main()
