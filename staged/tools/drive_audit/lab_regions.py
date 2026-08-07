"""Body regions and individual animals, as this lab names them in a .lif.

Built on the pattern lab_dates.py established: survey what is actually
written before writing a parser, and keep one shared table so three tools
cannot drift into three private vocabularies.

WHERE THE LABEL LIVES, and this was got wrong first. One Leica file holds
many stacks, and the student names the REGION ON THE STACK, not on the file.
A survey of filenames found `head` 17 times across 1,793 names and concluded
region labels were rare. Surveyed against the 8,446 SERIES names inside those
files instead: head 235, tail 259, mid 177, midbody 89, full 169, ventral 229.
The information was there; the survey was looking at the wrong level.

THE ACQUISITION PATTERN THIS EXPOSED. Series named `full worm 3_head`,
`full worm 3_mid`, `full worm 3_tail` are three stacks of ONE animal, tiled
along its length. That is neither a head crop nor a single-field whole-animal
stack - it is whole-animal coverage at crop-like resolution WITH THE
INDIVIDUAL IDENTIFIED, which is exactly the two-tissue within-individual
pairing the grant needs. 31 distinct animals have all three regions.

MEASURED over 5,190 acquisition z-stacks, 7 August 2026:

    term        series   what it is
    ventral        229   ORIENTATION, not a region - see below
    tail           259
    head           235
    mid            177
    full           169
    bottom         125   stack side
    top            108   stack side
    midbody         89
    anterior        52

WORDS THAT LOOK ANATOMICAL AND ARE NOT. `back` (72) sits alongside `ventral`
(229), `top` (108) and `bottom` (125): these name which SIDE of the animal or
which end of the stack, not which part of the body. Mapping `back` to tail
would have mislabelled 72 stacks. Orientation terms are recognised here
precisely so they can be excluded from region matching.

UNDERSCORE IS A SEPARATOR AND THE REGEX ENGINE DISAGREES. `_` is a word
character, so `\\bmid\\b` never fires inside `full worm 1_mid`. That one
detail reported 0 complete animals when the examples were plainly on screen.
Everything here separates before matching.
"""
from __future__ import annotations

import re

# Underscores, hyphens and dots join tokens in these names. Split before any
# word-boundary match, or \b silently fails against `1_mid`.
SEPARATORS_RE = re.compile(r"[_\-.]+")

REGIONS = (
    ("head", r"\bhead\b|\banterior\b|\bnose\b|\bpharyn\w*\b"),
    ("midbody", r"\bmid\b|\bmidbody\b|\bmiddle\b|\bmidsection\b|\bvulva\w*\b"),
    ("tail", r"\btail\b|\bposterior\b"),
)

# Named so they can be EXCLUDED. See the docstring: these are sides and stack
# ends, and one of them - `back` - reads as a region if you are careless.
ORIENTATION = (
    ("ventral", r"\bventral\b|\bvent\b"),
    ("dorsal", r"\bdorsal\b|\bback\b"),
    ("stack top", r"\btop\b"),
    ("stack bottom", r"\bbottom\b"),
    ("lateral", r"\blateral\b|\bside\b"),
)

# `full worm 3`, `worm 12`, `w7`. The number is what ties three tiles to one
# animal, so it is the identity, not decoration.
ANIMAL_RE = re.compile(
    r"(?:(?:full\s*)?worms?\s*|(?<![a-z])w)(\d{1,3})(?!\d)", re.I)

# `full worm`, `whole worm`, `entire` - a claim that the SET covers the
# animal, which is different from any single stack doing so.
WHOLE_SET_RE = re.compile(r"\b(full|whole|entire)\s*(worm|animal)?\b", re.I)


def separate(name):
    """Underscores and dots become spaces so word boundaries work."""
    return SEPARATORS_RE.sub(" ", name or "")


def region_of(name):
    """The body region a series name states, or "" if none or more than one.

    Two regions in one name is not a region: `head+mid` says the stack spans
    both, and calling it either would be a guess. It comes back empty and the
    caller can look at the field of view, which is a measurement.
    """
    text = separate(name).lower()
    found = [region for region, pattern in REGIONS
             if re.search(pattern, text)]
    return found[0] if len(found) == 1 else ""


def orientation_of(name):
    """Which side or stack end a name states. Never a region."""
    text = separate(name).lower()
    for label, pattern in ORIENTATION:
        if re.search(pattern, text):
            return label
    return ""


def animal_of(name):
    """The individual this series belongs to, as written, or "".

    Only meaningful WITHIN one file: `worm 3` in two different .lif files is
    two different animals, so callers must key on (file, animal).
    """
    match = ANIMAL_RE.search(separate(name))
    return match.group(1) if match else ""


def group_by_animal(series, file_key):
    """Collect series into individuals: {(file, animal): {region: series}}.

    `file_key` extracts the file identity from a series record. Pass the
    BASENAME rather than the full path where the same file is held on more
    than one share, or one animal is counted once per copy - that inflated a
    first count of complete animals from 31 to 54.
    """
    animals = {}
    for item in series:
        name = item.get("series_name", "")
        region = region_of(name)
        animal = animal_of(name)
        if not region or not animal:
            continue
        animals.setdefault((file_key(item), animal), {})[region] = item
    return animals


def completeness(animals):
    """How many individuals carry all three regions, two, or one."""
    counts = {3: 0, 2: 0, 1: 0}
    for regions in animals.values():
        counts[min(len(regions), 3)] = counts.get(min(len(regions), 3), 0) + 1
    return counts
