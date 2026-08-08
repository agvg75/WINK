"""Does Zarr change what drive we need to buy? Measure, do not assume.

    py tools\\storage\\zarr_prototype.py --source "L:\\...\\some.lif"
    py tools\\storage\\zarr_prototype.py --source "C:\\scratch\\frames" --local-copy

SEPT1 Tier 1 item 6, and its ONLY job is to inform item 2's purchase. So it
measures the two things a purchase turns on and ignores everything else:

    HOW MUCH SPACE      the compression ratio decides how many TB to buy
    HOW FAST TO READ    if reads stay fast enough, a cheaper drive will do

WHAT THIS DELIBERATELY SEPARATES. Format and transport are different
variables, and confusing them is how a network problem gets solved by buying
a disk. Every measurement is reported per storage location, so "TIFF on a
share" is never compared against "Zarr on a local disk".

READ PATTERNS ARE NOT INTERCHANGEABLE. A whole-stack read and a single-plane
read stress opposite things: sequential throughput versus per-chunk overhead.
Zarr usually wins the second by a lot and the first by little, so a prototype
that measured only one would recommend the wrong drive.

CONTENTION IS RECORDED, NOT IGNORED. A benchmark run while 1.5 TB is copying
across the same bus is measuring the copy. The run refuses to report a
headline number without saying what else was running.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))
sys.path.insert(0, str(ROOT / "tools"))


def _timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


def folder_bytes(path):
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total


def load_stack(source):
    """(array, how) for a .lif series or a folder of TIFFs."""
    import numpy as np
    source = Path(source)
    if source.is_dir():
        import tifffile
        files = sorted(p for p in source.iterdir()
                       if p.suffix.lower() in (".tif", ".tiff"))
        if not files:
            raise SystemExit(f"no TIFFs in {source}")
        planes = [tifffile.imread(str(p)) for p in files]
        # REAL FOLDERS ARE NOT UNIFORM. A recording can hold planes of more
        # than one shape - a cropped re-acquisition, a stray calibration
        # frame - and np.stack simply raises "all input arrays must have the
        # same shape", which says nothing about which planes differ or how
        # many. Group, report, and use the dominant shape.
        from collections import Counter
        shapes = Counter(p.shape for p in planes)
        if len(shapes) > 1:
            print(f"  MIXED SHAPES in {source.name}: "
                  + ", ".join(f"{shape} x{count}"
                              for shape, count in shapes.most_common()))
            keep = shapes.most_common(1)[0][0]
            planes = [p for p in planes if p.shape == keep]
            print(f"  using the dominant shape {keep} "
                  f"({len(planes)} of {len(files)} planes)")
        return np.stack(planes), f"{len(planes)} TIFF planes"
    import confocal_loader
    stack = confocal_loader.load_stack(source, require_calibration=False)
    array = stack["array"] if isinstance(stack, dict) else stack
    return np.asarray(array), "one .lif series"


def running_load():
    """What else is using the disks. A benchmark alone on a busy box is a lie."""
    busy = []
    try:
        import subprocess
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name like '%python%'\" | "
             "Where-Object { $_.CommandLine -match 'consolidate|copy' } | "
             "Measure-Object | Select-Object -ExpandProperty Count"],
            capture_output=True, text=True, timeout=60)
        n = int((out.stdout or "0").strip() or 0)
        if n:
            busy.append(f"{n} consolidation/copy process(es) running")
    except Exception:                                        # noqa: BLE001
        busy.append("could not determine")
    return busy


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", required=True)
    ap.add_argument("--targets", nargs="+",
                    default=[os.environ.get("TEMP", ".")],
                    help="storage locations to write the Zarr copies into")
    ap.add_argument("--chunk-z", type=int, default=1,
                    help="planes per chunk; 1 favours single-plane reads")
    args = ap.parse_args()

    import numpy as np
    import zarr
    # zarr 3 wants its own codec objects; numcodecs.Blosc is rejected with
    # "Expected a BytesBytesCodec".
    from zarr.codecs import BloscCodec, BloscShuffle

    busy = running_load()
    print("ZARR READ-SPEED PROTOTYPE")
    print(f"  source        {args.source}")
    if busy:
        print(f"  CONTENTION    {'; '.join(busy)}")
        print("                numbers below are lower bounds, not clean "
              "measurements")
    print()

    (array, how), load_seconds = _timed(lambda: load_stack(args.source))
    raw_bytes = int(array.nbytes)
    print(f"  loaded        {how}: shape {array.shape}, {array.dtype}, "
          f"{raw_bytes / 1e6:.0f} MB in memory ({load_seconds:.1f}s)")

    chunks = (args.chunk_z,) + tuple(array.shape[1:])
    codecs = {
        "blosc-zstd-3": BloscCodec(cname="zstd", clevel=3,
                                   shuffle="bitshuffle"),
        "blosc-lz4-5": BloscCodec(cname="lz4", clevel=5,
                                  shuffle="bitshuffle"),
        "none": None,
    }

    results = []
    for target in args.targets:
        target = Path(target)
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            print(f"  SKIP {target}: {exc}")
            continue
        for label, codec in codecs.items():
            store = target / f"zarr_probe_{label}.zarr"
            if store.exists():
                shutil.rmtree(store, ignore_errors=True)
            try:
                def write():
                    z = zarr.create_array(
                        store=str(store), shape=array.shape, chunks=chunks,
                        dtype=array.dtype,
                        compressors=[codec] if codec is not None else [])
                    z[:] = array
                    return z
                _z, write_s = _timed(write)
                on_disk = folder_bytes(store)

                opened = zarr.open_array(str(store), mode="r")
                _all, read_all_s = _timed(lambda: np.asarray(opened[:]))
                middle = array.shape[0] // 2
                _one, read_one_s = _timed(
                    lambda: np.asarray(opened[middle]))
                results.append({
                    "location": str(target), "codec": label,
                    "raw_MB": raw_bytes / 1e6,
                    "stored_MB": on_disk / 1e6,
                    "ratio": raw_bytes / on_disk if on_disk else 0,
                    "write_s": write_s, "read_all_s": read_all_s,
                    "read_one_plane_ms": read_one_s * 1000,
                    "read_all_MBs": (raw_bytes / 1e6) / read_all_s
                    if read_all_s else 0,
                })
            except Exception as exc:                         # noqa: BLE001
                print(f"  FAILED {label} at {target}: {exc}")
            finally:
                shutil.rmtree(store, ignore_errors=True)

    if not results:
        print("no measurements taken")
        return 1

    print(f"  {'location':<28} {'codec':<14} {'stored MB':>9} {'ratio':>6} "
          f"{'read MB/s':>9} {'1 plane ms':>10}")
    for r in results:
        print(f"  {r['location'][:28]:<28} {r['codec']:<14} "
              f"{r['stored_MB']:>9.0f} {r['ratio']:>6.2f} "
              f"{r['read_all_MBs']:>9.0f} {r['read_one_plane_ms']:>10.1f}")

    best = max(results, key=lambda r: r["ratio"])
    print()
    print(f"  BEST COMPRESSION {best['ratio']:.2f}x ({best['codec']})")
    print(f"  WHAT THAT MEANS FOR SIZING: 1 TB of this material would occupy "
          f"about {1 / best['ratio']:.2f} TB stored as Zarr.")
    print()
    print("  This is ONE stack. Compression is content-dependent - confocal "
          "background compresses far better than dense signal - so a purchase "
          "decision needs several stacks spanning the range, not this number.")
    if busy:
        print("  AND THE BOX WAS BUSY. Re-run when the consolidation is done "
              "before any purchase relies on the read rates.")

    out = Path(os.environ.get("TEMP", ".")) / "zarr_prototype_results.json"
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n  results -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
