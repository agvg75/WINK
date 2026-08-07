"""A derived image is not an acquisition, and 1 metre per pixel is not a scale.

Three defects found against the 387 .lif files on the scope computer are
pinned here. All three made the census report a confident wrong number rather
than fail, which is the failure mode that matters for a document that feeds a
grant.

FIRST, DERIVED SERIES. Leica stores processed copies and analysis outputs as
ordinary sibling series inside the same file. A LIGHTNING-deconvolved stack
(`Series001_Lng`) is the SAME recording as its parent, and a FLIM decay map is
not a recording at all. Measured: 5,206 series in the files, of which 848 -
one in six - were one of these. The first run reported 3,564 z-stacks; the
true acquisition count is 3,077.

SECOND, THE METRE PIXEL. Those same FLIM products carry the ELEMENT INDEX in
the Length field with the unit still reading metres, so Length comes back as
n - 1 and the calibration works out to exactly 1 m per pixel. The first run
reported a maximum of 1,000,620 um/px next to a median of 0.106. Anything
built on that would carry a millionfold error.

THIRD, THE YEAR. This lab writes YYMMDD on the front of a confocal filename -
`230222_AVG60_dys-1_a-g_RNAi.lif`. A four-digit year regex reads none of it:
the first run found a year for 91 of 5,206 series, the fix finds one for
4,291.

The span convention is pinned too. Length is the extent from the FIRST
element to the LAST, so it covers n - 1 steps. Over a 5-plane stack, reading
it as n instead biases the z spacing by 25%.
"""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app"), str(ROOT / "tools" / "confocal_census"),
                str(ROOT / "tools" / "drive_audit")]

import cell_calcium_lif as lif      # noqa: E402
import confocal_census as census    # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


def dim(length, n, unit="m"):
    return ET.fromstring(
        f'<DimensionDescription NumberOfElements="{n}" '
        f'Length="{length}" Unit="{unit}"/>')


print("\n--- calibration is read, or honestly absent --------------------")

# A real series from the scope: 512 px across a 54.6 um field.
check("metres convert to micrometres",
      abs(lif._extent_um(dim(54.6e-6, 512)) - 0.1068) < 1e-3,
      f"{lif._extent_um(dim(54.6e-6, 512)):.4f} um/px")

check("the span covers n-1 steps, not n",
      abs(lif._extent_um(dim(4e-6, 5)) - 1.0) < 1e-9,
      "4 um over 5 planes is 1.0 um spacing, not 0.8")

# THE FLIM SIGNATURE. Length carries the element index, unit still says m.
check("a metre per pixel is refused, not reported",
      lif._extent_um(dim(511, 512)) is None,
      "Length=511 'm' over 512 elements is an index, not an extent")

check("...and so is any millimetre-scale pixel",
      lif._extent_um(dim(1.0, 512)) is None,
      "no light microscope has a 2 mm pixel")

check("a zero length is absent, never zero",
      lif._extent_um(dim(0, 512)) is None)
check("a single element has no spacing",
      lif._extent_um(dim(1e-5, 1)) is None)
check("a missing dimension is absent",
      lif._extent_um(None) is None)
check("an unknown unit is refused rather than assumed",
      lif._extent_um(dim(1e-5, 512, unit="furlong")) is None)
check("micrometre units pass through unscaled",
      abs(lif._extent_um(dim(511, 512, unit="um")) - 1.0) < 1e-9)

print("\n--- a processed copy is not a second recording -----------------")

check("LIGHTNING output is marked derived",
      "LIGHTNING" in census.derivation_of("Series001_Lng"))
check("...case-insensitively",
      "LIGHTNING" in census.derivation_of("W1_Series002_LNG"))
check("FLIM products are marked derived",
      all(census.derivation_of(n) for n in
          ("Fast Flim", "Intensity", "Standard Deviation",
           "FlimDecayTime 1 ch1", "Pattern Matching Scatter Plot Channel 1")))
check("a plain acquisition is NOT marked derived",
      not any(census.derivation_of(n) for n in
              ("Series001", "Image004", "W1_Series001", "Series012")),
      "the common case must survive the filter")
check("a series merely containing 'lng' is not derived",
      not census.derivation_of("Lung_series001"),
      "the suffix is anchored, so it cannot match mid-name")

print("\n--- the year this lab actually writes -------------------------")

check("YYMMDD is read", census.year_of("230222_AVG60_dys-1_a-g_RNAi") == 2023)
check("...and so is a four-digit year",
      census.year_of("2021 pezo experiments") == 2021)
check("a four-digit year wins over a stray six-digit run",
      census.year_of("2019_240517") == 2019)
check("an impossible month is not a date",
      census.year_of("239922") is None, "month 99")
check("an impossible day is not a date",
      census.year_of("230240") is None, "day 40")
check("a bare five-digit number is not a date",
      census.year_of("41921") is None,
      "same rule the folder audit holds: 41921 is a sequence, not a stamp")

print("\n--- shape comes from dimensions, never from a name -------------")

check("z>1 t=1 is a stack",
      census.shape_of({"n_z": 40, "n_t": 1}) == "z-stack")
check("z=1 t>1 is a timelapse",
      census.shape_of({"n_z": 1, "n_t": 224}) == "timelapse")
check("both is a stack timelapse",
      census.shape_of({"n_z": 12, "n_t": 30}) == "z-stack timelapse")
check("neither is a single plane",
      census.shape_of({"n_z": 1, "n_t": 1}) == "single plane")

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("CONFOCAL_CENSUS_PASS")
