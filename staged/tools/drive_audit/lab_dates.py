"""The date conventions THIS LAB writes, measured rather than assumed.

WHY THIS MODULE EXISTS. Three parsers in this repo each grew their own date
regex from general expectations - ISO dates, camera stamps, four-digit years -
and each was correct in the abstract and wrong about this lab. The confocal
census read a year for 91 of 5,206 series before this was noticed. The failure
is quiet by construction: a filename that does not match simply yields no
date, which is indistinguishable from a filename that carries none.

MEASURED, 7 August 2026, over 1,793 confocal filenames carrying an mtime.
Every candidate reading was scored against the file's own mtime, on the rule
that a filename stamp CANNOT POSTDATE THE FILE - a file cannot be written
before it exists, and copying only ever moves an mtime later. So a reading
landing after the mtime is impossible, and among the possible ones the closest
is the best explanation.

    convention  files  example                          reads as
    YYMMDD        380  240126_AVG60_tissue dissoc.lif   26 Jan 2024
    MM.DD.YY       55  09.17.25 AVG77 VID (8).lif       17 Sep 2025
    MDDYY          50  81821_CH1878_BAD.lif             18 Aug 2021
    MMDYY          25  10421_larva_CH1878.lif            4 Oct 2021
    MMDDYY         21  081518_HKK22_anti GFP.lsm        15 Aug 2018
    DD.MM.YY        6  06-12-2021 DEL.lif                6 Dec 2021

Against which the parsers previously handled `2021-04-19`, `20210419` and a
bare `2021` - the camera formats, which are the ones the CONFOCAL data hardly
uses. They are kept because the behavioural cameras do write them.

Bare `DDMMYY` was NEVER the best explanation in those 1,793 files, and was
ruled impossible by the mtime 74 times. It is kept anyway, ranked last: one
corpus of confocal filenames is not proof that no one on this drive has ever
written it, and the cost of keeping it is an honest ambiguity flag rather
than a wrong date.

THE FIVE-DIGIT FORMS ARE MUTUALLY AMBIGUOUS. `10421` is 4 Oct 2021 as MMDYY
and 4 Jan 2021 as MDDYY. So is the six-digit family: `081021` is Oct 2008 as
YYMMDD, Aug 2021 as MMDDYY and Oct 2021 as DDMMYY - three readings, two
years. 49 of 1,793 filenames had more than one live reading.

SO THIS MODULE NEVER SILENTLY PICKS. `resolve()` returns the readings it
found and says whether they agree on a YEAR, which is the field the audit
actually stores. Callers that have an mtime should pass it as `not_after`;
callers that do not must handle `ambiguous`.

A BARE FOUR OR FIVE DIGIT NUMBER IS A DATE, NEVER AN ALLELE. That rule lives
in propose_labels and is the reason this module is separate from it: the same
digits mean different things in different columns, and one of the two must
not quietly win.
"""
from __future__ import annotations

import datetime as dt
import re

# A run of digits that could be a date, ANCHORED TO THE START of the text.
#
# THIS ANCHOR IS LOAD-BEARING. Every one of the 531 filenames whose convention
# was identified against its mtime puts the date FIRST: 240126_AVG60...,
# 81821_CH1878..., 081518_HKK22.... An unanchored version reads a date out of
# any five- or six-digit run anywhere in a name, and the archive is full of
# them - strain numbers, worm numbers, sample IDs, magnifications. Measured
# unanchored on the real census: 119 series dated 2002, 84 dated 2015, from
# filenames whose actual dates are 2025.
#
# A trailing separator or end-of-string is required so a longer number cannot
# have a date read out of its front.
TOKEN_RE = re.compile(r"^(\d{4,8})(?!\d)")

# Separated forms: 09.17.25, 02.14.25, 06-12-2021.
#
# ZERO PADDING IS REQUIRED on the first two fields, and that is also
# load-bearing. `AVG60.3.1.02.14.25.lif` contains `3.1.02`, which reads as
# 1 March 2002 if single digits are allowed - and the file's real date,
# 02.14.25, sits further along the same name. This lab pads: 02.14.25,
# 09.17.25, 05.26.26, 06-12-2021.
SEPARATED_RE = re.compile(
    r"(?<!\d)(\d{2})[.\-_/](\d{2})[.\-_/](\d{2}|\d{4})(?!\d)")

# Cameras write this into the filename: fc2_save_2021-04-19-143320-8995.tif.
# Unambiguous, so it is tried first and wins outright.
CAMERA_RE = re.compile(r"(?<!\d)(20\d\d)[-_](\d{2})[-_](\d{2})(?!\d)")

EARLIEST = 2000
LATEST = 2030

# How close an mtime must sit to a reading to count as confirming it. Set
# from the measured corpus, where an uncopied file's mtime lands on the
# filename's own date: gaps of 0 to 3 days dominate, and the next reading of
# the same token is at least a month away by construction, since the rival
# conventions permute month against day or year.
COINCIDENT_DAYS = 3

# A reading further than this beyond the file's own mtime is absurd rather
# than merely surprising. Generous on purpose: a filename dated slightly
# after its mtime is ordinary - clock skew, a rename, an archive touched out
# of order - and treating that as impossible cost a real file twelve years.
IMPOSSIBLE_AFTER_DAYS = 365


def _date(year, month, day):
    """A real calendar date, or None. Rejects 31 February without a table."""
    try:
        value = dt.date(year, month, day)
    except ValueError:
        return None
    return value if EARLIEST <= value.year <= LATEST else None


def _yy(two):
    return 2000 + two


def readings(text):
    """Every date this text could carry, as (convention, date) pairs.

    Order is not significance. Nothing here decides; `resolve` does.
    """
    out = []

    match = CAMERA_RE.search(text)
    if match:
        y, m, d = (int(g) for g in match.groups())
        found = _date(y, m, d)
        if found:
            return [("YYYY-MM-DD", found)]

    for match in SEPARATED_RE.finditer(text):
        a, b, c = (int(g) for g in match.groups())
        year = c if c > 99 else _yy(c)
        for name, value in (("MM.DD.YY", _date(year, a, b)),
                            ("DD.MM.YY", _date(year, b, a)),
                            # YY.MM.DD, found by this tool rather than
                            # assumed: 26.02.13 CONFOCAL STEIN.lif sits in a
                            # folder beside 02.26.26 CONFOCAL RENE UTERINE.lif
                            # and its mtime is exactly 13 Feb 2026. Read as
                            # DD.MM.YY it would be Feb 2013, thirteen years
                            # out. It rarely competes, because it only yields
                            # a valid date when the middle field is a month
                            # and the last a day.
                            ("YY.MM.DD", _date(_yy(a), b,
                                               c if c <= 31 else 1)
                             if a <= 99 and c <= 99 else None)):
            if value:
                out.append((name, value))

    for token in TOKEN_RE.findall(text.lstrip()):
        n = len(token)
        if n == 8:
            value = _date(int(token[:4]), int(token[4:6]), int(token[6:8]))
            if value:
                out.append(("YYYYMMDD", value))
        elif n == 6:
            for name, value in (
                    ("YYMMDD", _date(_yy(int(token[:2])), int(token[2:4]),
                                     int(token[4:6]))),
                    ("MMDDYY", _date(_yy(int(token[4:6])), int(token[:2]),
                                     int(token[2:4]))),
                    ("DDMMYY", _date(_yy(int(token[4:6])), int(token[2:4]),
                                     int(token[:2])))):
                if value:
                    out.append((name, value))
        elif n == 5:
            for name, value in (
                    ("MDDYY", _date(_yy(int(token[3:])), int(token[:1]),
                                    int(token[1:3]))),
                    ("MMDYY", _date(_yy(int(token[3:])), int(token[:2]),
                                    int(token[2:3])))):
                if value:
                    out.append((name, value))
        elif n == 4:
            year = int(token)
            if EARLIEST <= year <= LATEST:
                # A bare year names no day. Mid-year so that a comparison
                # against an mtime cannot be wrong by more than six months
                # in either direction.
                out.append(("YYYY", dt.date(year, 7, 1)))

    return out


def resolve(text, not_after=None):
    """The date this text carries, and how sure that is.

    Returns a dict with:
        year        the year, or None if nothing was found or the readings
                    disagree about it
        date        the best single date, or None
        convention  which convention produced it
        ambiguous   True when live readings disagree on the YEAR
        readings    everything found, so a caller can show its working

    `not_after` is the file's own mtime where the caller has one. It is used
    as EVIDENCE, by nearness, not as a hard cutoff - see below.
    """
    found = readings(text)
    if not found:
        return {"year": None, "date": None, "convention": "",
                "ambiguous": False, "readings": []}

    live = found
    if not_after is not None:
        # AN EARLIER VERSION APPLIED THIS AS A LAW - "a stamp cannot postdate
        # the file it names" - and dropped every reading after the mtime.
        # That is a strong prior, not a law, and it fails: on the real drive
        # 241112_AVG59_Head.lif carries an mtime of 12 Sep 2024, two months
        # BEFORE the 12 Nov 2024 its name states. Clocks skew, archives are
        # touched, files are renamed after the fact. The law threw away the
        # reading matching this lab's dominant convention and kept the only
        # survivor, 24 Nov 2012, dating the file twelve years wrong.
        #
        # So the mtime now only excludes the absurd - more than a year in the
        # future of the file - and otherwise ranks by NEARNESS in either
        # direction.
        live = [(n, d) for n, d in found
                if (d - not_after).days <= IMPOSSIBLE_AFTER_DAYS]
        if not live:
            return {"year": None, "date": None, "convention": "",
                    "ambiguous": False, "readings": found}

    years = {d.year for _, d in live}
    if not_after is not None:
        def distance(pair):
            return abs((not_after - pair[1]).days)

        best = min(live, key=distance)
        # NEARNESS IS EVIDENCE, not just a tie-break. For a file that was
        # never copied the mtime is about the day it was acquired, and across
        # the measured corpus the winning reading sat 0 days from it again
        # and again. When one reading is an order of magnitude closer to the
        # file's own timestamp than every alternative, that is the
        # explanation rather than a coin flip.
        #
        # 230222 is 22 Feb 2023 as YYMMDD and 23 Feb 2022 as DDMMYY, a year
        # apart; an mtime of 22 Feb 2023 settles it. 240126 against an mtime
        # of Aug 2026 does NOT settle - its two readings are 924 and 195 days
        # away, under 10x apart - and stays ambiguous, correctly.
        gap = distance(best)
        rivals = [distance(p) for p in live if p[1] != best[1]]
        decisive = max(COINCIDENT_DAYS, gap * 10)
        if rivals and all(r >= decisive for r in rivals):
            return {"year": best[1].year, "date": best[1],
                    "convention": best[0], "ambiguous": False,
                    "readings": found}
    else:
        # No mtime to lean on. Prefer the convention this lab writes most,
        # but only to CHOOSE A DATE - the ambiguity flag below still reports
        # that the year was not certain.
        order = {"YYYY-MM-DD": 0, "YYYYMMDD": 1, "YYMMDD": 2, "MM.DD.YY": 3,
                 "MDDYY": 4, "MMDYY": 5, "MMDDYY": 6, "DD.MM.YY": 7,
                 "DDMMYY": 8, "YYYY": 9}
        best = min(live, key=lambda nd: order.get(nd[0], 99))

    ambiguous = len(years) > 1
    return {
        "year": None if ambiguous else best[1].year,
        "date": best[1],
        "convention": best[0],
        "ambiguous": ambiguous,
        "readings": found,
    }


def year_of(text, not_after=None):
    """Just the year, or None when absent or ambiguous. The common case."""
    return resolve(text, not_after)["year"]
