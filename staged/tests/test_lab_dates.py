"""The date conventions this lab writes, pinned to real filenames.

Every example below is an actual file from the L drive or the confocal share.
None is invented, because the defect this module fixes was caused precisely by
reasoning about what a date "should" look like instead of looking.

THE DEFECT. Three parsers each grew their own date regex handling 2021-04-19,
20210419 and a bare 2021 - the camera formats. Measured over 1,793 confocal
filenames with mtimes, this lab writes YYMMDD (380 files), MM.DD.YY (55),
MDDYY (50), MMDYY (25) and MMDDYY (21). The regexes were correct in the
abstract and wrong about this lab, and they failed SILENTLY: an unmatched
filename yields no date, indistinguishable from one that carries none. The
confocal census read a year for 91 of 5,206 series before anyone noticed.

THE AMBIGUITY IS REAL AND MUST NOT BE HIDDEN. `10421` is 4 Oct 2021 as MMDYY
and 4 Jan 2021 as MDDYY - same year, so the year is safe. `081021` is Oct 2008
as YYMMDD, Aug 2021 as MMDDYY and Oct 2021 as DDMMYY - two different years, so
the year is NOT safe and must come back as ambiguous rather than as a guess.
That one filename produced all 63 "2008" series in the first census run.

THE MTIME RULE. A filename stamp cannot postdate the file it names, because a
file cannot be written before it exists and copying only moves an mtime later.
So an mtime rules readings OUT. It is never used as the date itself - that is
the whole point of preferring the stamp, since copying an archive rewrites
every mtime while the filenames keep the day the animal was imaged.
"""
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools" / "drive_audit")]

import lab_dates   # noqa: E402

results = []


def check(name, condition, detail=""):
    results.append((name, bool(condition), detail))
    print(f"  {'PASS' if condition else 'FAIL'}  {name}"
          + (f"  [{detail}]" if detail else ""))


print("\n--- the conventions this lab actually writes -------------------")

# YYMMDD, 380 files - the dominant confocal convention, and the one every
# parser missed.
check("YYMMDD: 240126_AVG60_tissue dissociation.lif",
      lab_dates.resolve("240126_AVG60_tissue dissociation",
                        date(2024, 1, 29))["date"] == date(2024, 1, 26))
check("YYMMDD: 241225_AVG63_day1Adult_head+mid.lif",
      lab_dates.year_of("241225_AVG63_day1Adult_head+mid",
                        date(2024, 12, 25)) == 2024)
check("YYMMDD: 230222_AVG60_dys-1_a-g_RNAi.lif",
      lab_dates.resolve("230222_AVG60_dys-1_a-g_RNAi",
                        date(2023, 2, 22))["date"] == date(2023, 2, 22))

# MM.DD.YY, 55 files - the dotted behavioural convention.
check("MM.DD.YY: 09.17.25 AVG77 VID (8).lif",
      lab_dates.resolve("09.17.25 AVG77 VID (8)",
                        date(2025, 9, 22))["date"] == date(2025, 9, 17))
check("MM.DD.YY: 05.26.26 Defecation",
      lab_dates.year_of("05.26.26 Defecation", date(2026, 6, 1)) == 2026)

# MDDYY and MMDYY, 75 files between them - five digits, no separator.
check("MDDYY: 81821_CH1878_BAD.lif is 18 Aug 2021",
      lab_dates.resolve("81821_CH1878_BAD",
                        date(2021, 8, 18))["date"] == date(2021, 8, 18))
check("MDDYY: 41921_cop1367 is 19 Apr 2021",
      lab_dates.resolve("41921_cop1367",
                        date(2021, 4, 20))["date"] == date(2021, 4, 19),
      "the folder audit already documents this one")
check("MMDYY: 10421_larva_CH1878 is 4 Oct 2021",
      lab_dates.resolve("10421_larva_CH1878",
                        date(2021, 10, 4))["date"] == date(2021, 10, 4))

# MMDDYY, 21 files.
check("MMDDYY: 081518_HKK22_anti GFP_worm 1.lsm",
      lab_dates.resolve("081518_HKK22_anti GFP_worm 1",
                        date(2018, 8, 15))["date"] == date(2018, 8, 15))

# The camera formats still work - the behavioural rigs do write them.
check("camera: fc2_save_2021-04-19-143320-8995.tif",
      lab_dates.resolve("fc2_save_2021-04-19-143320-8995")["date"]
      == date(2021, 4, 19))
check("DD.MM.YY: 06-12-2021 DEL.lif",
      lab_dates.year_of("06-12-2021 DEL", date(2021, 12, 6)) == 2021)

# YY.MM.DD - found by the census rather than assumed. This file sits beside
# 02.26.26 CONFOCAL RENE UTERINE.lif in one folder, and its mtime is exactly
# 13 Feb 2026. Read as DD.MM.YY it is Feb 2013, thirteen years out, and it
# was the last spurious year in an 8,446-series census.
check("YY.MM.DD: 26.02.13 CONFOCAL STEIN.lif is Feb 2026",
      lab_dates.resolve("26.02.13 CONFOCAL STEIN",
                        date(2026, 2, 13))["date"] == date(2026, 2, 13))
check("...and its dotted siblings still read MM.DD.YY",
      lab_dates.resolve("02.26.26 CONFOCAL RENE UTERINE",
                        date(2026, 3, 25))["date"] == date(2026, 2, 26))

print("\n--- ambiguity is reported, never resolved by preference --------")

# THE FILE THAT PRODUCED ALL 63 "2008" SERIES.
amb = lab_dates.resolve("081021_Nmgp-1-GFP in OH15500")
check("081021 is ambiguous across YEARS", amb["ambiguous"],
      f"readings: {sorted({d.year for _, d in amb['readings']})}")
check("...so no year is returned rather than a wrong one",
      amb["year"] is None,
      "this is the whole fix - 63 series were dated 2008 from this")
check("...and the readings are still shown for a human to judge",
      len(amb["readings"]) >= 2)

# Same year under both five-digit readings, so the year IS safe.
same = lab_dates.resolve("10421_larva_CH1878")
check("10421 has two readings that agree on the year",
      same["year"] == 2021 and not same["ambiguous"],
      "4 Oct vs 4 Jan 2021 - the day differs, the year does not")

print("\n--- the mtime rules readings out, and is never the date --------")

check("a reading far from the mtime loses to one that sits on it",
      lab_dates.resolve("081021_x", date(2021, 10, 8))["date"]
      != date(2008, 10, 21),
      "the 2008 reading survives only without an mtime")

# THE PRIOR IS NOT A LAW. 241112_AVG59_Head.lif on the scope computer carries
# an mtime of 12 Sep 2024, two months BEFORE the 12 Nov 2024 its own name
# states. Treating "a stamp cannot postdate the file" as absolute dropped the
# 2024 reading and kept the only survivor - 24 Nov 2012 as DDMMYY - dating a
# real file twelve years wrong. Clocks skew and files get renamed.
skewed = lab_dates.resolve("241112_AVG59_Head", date(2024, 9, 12))
check("a filename slightly ahead of its mtime is still read",
      skewed["year"] == 2024,
      f"got {skewed['year']} via {skewed['convention']}")
check("...rather than falling back to an absurd distant reading",
      skewed["date"] != date(2012, 11, 24))
check("but a reading years ahead of the mtime is still refused",
      all(d.year != 2026 for _, d in
          [(n, d) for n, d in lab_dates.readings("260415_x")
           if (d - date(2019, 1, 1)).days <= lab_dates.IMPOSSIBLE_AFTER_DAYS]),
      "2026 cannot be the date of a file last written in 2019")
check("an mtime long after the stamp does not become the date",
      lab_dates.resolve("fc2_save_2021-04-19-143320",
                        date(2026, 8, 7))["date"] == date(2021, 4, 19),
      "a copy moves the mtime later; the filename keeps the imaging day")

# A DISTANT MTIME DOES NOT RESOLVE AMBIGUITY, AND MUST NOT PRETEND TO.
# 240126 is 26 Jan 2024 as YYMMDD and 24 Jan 2026 as DDMMYY. With an mtime of
# Aug 2026 both are possible, so the year stays unknown. Only a NEAR mtime
# eliminates a reading - which is exactly what happened for the same token at
# the top of this file, where an mtime three days later left one candidate.
far = lab_dates.resolve("240126_x", date(2026, 8, 7))
check("a distant mtime leaves a two-year token ambiguous",
      far["ambiguous"] and far["year"] is None,
      f"readings: {sorted({d.year for _, d in far['readings']})}")
check("...while a near mtime resolves the same token",
      lab_dates.resolve("240126_x", date(2024, 1, 29))["year"] == 2024)
check("everything impossible leaves no date rather than a fallback",
      lab_dates.resolve("240126_x", date(2019, 1, 1))["year"] is None)

print("\n--- what is NOT a date ----------------------------------------")

check("a longer digit run is not mined for a date",
      not lab_dates.readings("img_20014567"),
      "no date may be read out of the middle of a sequence number")
check("an impossible month is refused", not any(
    n == "YYMMDD" for n, _ in lab_dates.readings("239922")))
check("an impossible day is refused",
      not any(n == "YYMMDD" for n, _ in lab_dates.readings("230240")))
check("31 February is refused without a lookup table",
      not any(d == date(2023, 2, 31) for _, d in
              lab_dates.readings("230231") if d))
check("a year outside 2000-2030 is not a year",
      not lab_dates.readings("1899"))
check("text with no digits yields nothing",
      lab_dates.resolve("AVG60 dys-1 RNAi")["year"] is None)

print("\n--- three digits is not a date --------------------------------")
check("a three digit run is ignored", not lab_dates.readings("ch3 205 x"[:3]))

print()
failed = [n for n, ok, _ in results if not ok]
print(f"{len(results) - len(failed)} of {len(results)} checks passed")
if failed:
    for name in failed:
        print(f"   FAILED: {name}")
    raise SystemExit(1)
print("LAB_DATES_PASS")
