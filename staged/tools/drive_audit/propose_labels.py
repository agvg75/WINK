"""Propose values for the blank columns in LABEL_ME_L_drive.csv.

    python propose_labels.py --labels LABEL_ME_L_drive.csv \
                             --authority lab_name_authority.xlsx \
                             --out label_proposals.csv

Reads folder path text, matches it against the authority tables, and writes a
SEPARATE proposals file. The label CSV is opened read-only and is never
written to: a proposal is a suggestion to be accepted or rejected by a person,
and a file that silently acquires 551 guesses is worse than a blank one.

EVERY PROPOSAL CARRIES ITS EVIDENCE - the literal token matched, the path
segment it was found in, the table it came from, and a confidence tier - so a
reviewer can judge each one without re-deriving it.

CONFIDENCE ORDER IS THE AUTHORITY FILE'S, not this parser's. Its Read me
sheet says: "A person match narrows but does not identify, since students work
across lines. A project token match is stronger. A strain match is
strongest." Exact normalised matches outrank fuzzy ones within each kind.

    1  strain_exact           a strain named in ReagentHub or the Projects sheet
    2  lab_strain_prefix      AVG/AG/COP/VG naming, but NOT in ReagentHub
    2  project_token_exact    a token from the Projects sheet, whole-word
    3  person_surname_exact   a surname from the People sheet, whole-token
    4  project_token_fuzzy    near-miss on a project token
    5  person_surname_fuzzy   near-miss on a surname
    6  path_text              read from the path itself, backed by no table

A BARE FOUR OR FIVE DIGIT NUMBER IS NEVER AN ALLELE. On this drive the dates
are written 41921 and 5121 and 3_22_21, which is exactly the shape of an
allele number. Any strain proposal therefore requires a letter prefix -
cop1367, ok1234, AG405 - and bare digits are read as dates only. Getting this
wrong turns 19 April 2021 into allele 41921 and files it under a strain that
does not exist.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "app"))

import xlsx_lite   # noqa: E402

TIERS = {
    "strain_exact": 1,
    # A control is unambiguous - L4440 for RNAi, N2 for mutants and edited
    # strains. A gene name needs the vector nearby before it means knockdown.
    "control_exact": 2,
    "rnai_gene": 3,
    # A designation matching this lab's own AG/COP pattern. Not yet
    # cross-referenced to a project, but unambiguously a strain.
    "lab_strain_prefix": 2,
    "project_token_exact": 2,
    "person_surname_exact": 3,
    "project_token_fuzzy": 4,
    "person_surname_fuzzy": 5,
    "path_text": 6,
}

# Documented on the authority file's Read me sheet, plus what Andres added
# about the Owoyemis. These are not guesses to be re-derived by string
# similarity - a parser that decides for itself that Hughes and Hughes-Wiles
# are two people, or that the two Owoyemis are one, produces a confident
# wrong answer with no way to tell.
SAME_PERSON = {
    # normalised surname -> canonical label
    "hughes": "Hughes-Wiles K",
    "hugheswiles": "Hughes-Wiles K",
}
AMBIGUITY_NOTES = {
    "gomez": "Gomez L and Gomez M are different people.",
    "hughes": "Hughes K and Hughes-Wiles K are the same person.",
    "hugheswiles": "Hughes K and Hughes-Wiles K are the same person.",
    # TWO PEOPLE, AND THE ROUTE TO THAT MATTERS MORE THAN THE ANSWER.
    # An early draft encoded Owoyemi T and K as twins on the strength of two
    # initials appearing in poster lists. That was an inference presented as
    # knowledge, and it was pulled back to UNCONFIRMED rather than encoded.
    # The lab roster then listed Kehinde Owoyemi and Taiyelolu Owoyemi as
    # separate undergraduates, each with two abstracts and an LSAMP poster
    # award, which is evidence. The original guess happened to be right; it
    # was still right to refuse it until a document said so, because the
    # identical guess about Gomez L and M would have been wrong.
    # Note the spelling: Taiyelolu, not Taylelu.
    "owoyemi": ("Owoyemi K (Kehinde) and Owoyemi T (Taiyelolu) are two "
                "separate people, listed individually on the lab roster."),
}
# Filled from given_names.csv at load time: normalised given name -> the
# authority person it identifies. The drive is organised by given name and
# the authority is keyed by surname, so without this the two never meet.
GIVEN_NAMES = {}

# Words that appear in the person-shaped position but are not people. Drawn
# from the drive's own area names; anything here is excluded from the weakest
# tier rather than proposed and then rejected 500 times by hand.
NOT_A_PERSON = {
    "data", "drive", "test", "retry", "old", "new", "backup", "copy", "temp",
    "misc", "other", "raw", "analysis", "analyzed", "analysed", "results",
    "videos", "video", "images", "image", "movies", "movie", "pics", "photos",
    "shared", "lab", "external", "drives", "duchenne", "muscular",
    "dystrophy", "proprioception", "magnetic", "transduction", "crayfish",
    "teaching", "microscopy", "archive", "archived", "done", "todo",
    "unsorted", "to", "sort", "from", "for", "and", "the", "with",
    # Observed being proposed as people in the first pass. Conditions,
    # chemicals, constructs and software are not students.
    "people", "dmso", "defl", "dmd", "hdmd", "ru", "deepcut", "deeplabcut",
    "deepcutprotraining", "training", "control", "treated", "untreated",
    "wildtype", "wt", "swim", "crawl", "burrow", "pumping", "calcium",
}
MIN_SURNAME_LEN = 4
MIN_GIVEN_LEN = 3
# A given name longer than this is a phrase, not a name -
# 'deepcutprotraining' was being proposed as a person.
MAX_GIVEN_LEN = 12
FUZZY_RATIO = 0.88
MIN_FUZZY_LEN = 6
YEAR_RANGE = (2000, 2026)
# THIS LAB'S OWN DESIGNATIONS: AG or COP followed by digits. Confirmed by
# Andres, and they are the reason the anchoring-prefix rule works at all -
# 41921 is 19 April 2021 and cop1367 is an allele, and the ONLY thing that
# separates them is the prefix. A designation matching this is a strain with
# high confidence; a bare number never is.
# AVG is the prefix for strains GENERATED IN THIS LAB. Confirmed against the
# confocal filenames on the drive: AVG60, AVG63, AVG84, AVG85. It must be
# listed before AG or a regex alternation would match the AG inside it and
# leave a stray V; anchoring the whole token avoids that, but the ordering is
# kept explicit so nobody reorders it into a bug.
# ONE digit minimum, not two. ReagentHub holds AVG1 and AVG2, and a {2,5}
# quantifier silently skips them - the two lowest-numbered strains the lab
# ever made.
LAB_STRAIN_RE = re.compile(r"^(AVG|AG|COP|VG)\d{1,5}$", re.I)
# THE STRAIN LIST IS AN AUTHORITY, NOT A PATTERN. Exported from ReagentHub,
# which holds every strain the lab has. Matching against 249 exact names beats
# any regex, and the reason is visible in what the old general pattern
# proposed as strains on this drive:
#
#   w1, w2, w3 ... w13   worm replicate numbers
#   op50                 the bacteria they eat
#   l4440                an RNAi vector
#   dys1, pezo1, unc43   gene names
#
# None of those is a strain. An exact match against the hub cannot make that
# class of mistake, so the general letters-then-digits pattern is GONE rather
# than demoted - it had no residual value once the list existed.
REAGENTHUB_CSV = Path(__file__).with_name("reagenthub_strains.csv")
KNOWN_STRAINS = {}       # normalised name -> {"strain", "genotype", "gene_name"}
BARE_NUMBER_RE = re.compile(r"^\d{4,5}$")


def normalise(text):
    """Lowercase ASCII stem. Umlauts fold to the two-letter form.

    The Read me says Gaehrs and Staedele appear with umlauts in citations and
    may be mangled in Windows paths, and to match on the ASCII stem. Mapping
    a-umlaut to 'ae' BEFORE stripping combining marks makes Gaehrs and
    Gährs the same string; stripping first would make it 'gahrs' and the two
    spellings would never meet.
    """
    text = str(text)
    for source, target in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"),
                           ("Ä", "ae"), ("Ö", "oe"), ("Ü", "ue"),
                           ("ß", "ss")):
        text = text.replace(source, target)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def token_key(text):
    return re.sub(r"[^a-z0-9]", "", normalise(text))


def phrase_key(text):
    """Normalised with single spaces, so multi-word tokens can be found."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", normalise(text))
                  ).strip()


def path_segments(path):
    return [p for p in re.split(r"[\\/]+", str(path)) if p and ":" not in p]


def _parent(row):
    segments = path_segments(row["path"])
    return "\\".join(segments[:-1])


def load_strains(csv_path=REAGENTHUB_CSV):
    """The lab's strain list, exported from ReagentHub."""
    if not Path(csv_path).exists():
        return KNOWN_STRAINS
    with open(csv_path, newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("strain") or "").strip()
            if name:
                KNOWN_STRAINS[token_key(name)] = row
    return KNOWN_STRAINS


GIVEN_NAMES_CSV = Path(__file__).with_name("given_names.csv")


def load_given_names(people, csv_path=GIVEN_NAMES_CSV):
    """Attach a given name to each authority row.

    Prefers a `given_name` column on the People sheet, which is where this
    belongs permanently. Falls back to the seed CSV beside this script until
    that column exists. Rows with no given name simply do not get one - the
    drive folder then stays unresolved rather than being matched to a guess.
    """
    seeded = {}
    if csv_path and Path(csv_path).exists():
        with open(csv_path, newline="", encoding="utf-8-sig") as handle:
            for row in csv.DictReader(handle):
                if row.get("given_name"):
                    seeded[(token_key(row["surname"]),
                            row["initials"].strip().upper())] = row
    for person in people:
        given = str(person.get("given_name", "")).strip()
        note = ""
        if not given:
            hit = seeded.get((token_key(person["surname"]),
                              str(person.get("initials", "")).strip().upper()))
            if hit:
                given = hit["given_name"]
                note = hit.get("note", "")
        person["_given"] = given
        person["_given_note"] = note
        if given:
            GIVEN_NAMES.setdefault(token_key(given), []).append(person)
        # NICKNAMES ARE NOT A NICETY HERE. The drive is organised by what
        # people are actually called, not by what a roster records. A folder
        # named `\Danny\` belongs to Damiano Marchiafava and matches nothing
        # without this. Indexed alongside the formal given name so either
        # spelling of a person resolves to the same row.
        nickname = str(person.get("nickname", "")).strip()
        if not nickname:
            hit = seeded.get((token_key(person["surname"]),
                              str(person.get("initials", "")).strip().upper()))
            nickname = (hit or {}).get("nickname", "").strip()
        person["_nickname"] = nickname
        if nickname:
            GIVEN_NAMES.setdefault(token_key(nickname), []).append(person)
    return people


def load_authority(path):
    people = xlsx_lite.read_table(path, "People")
    projects = xlsx_lite.read_table(path, "Projects")
    for person in people:
        person["_key"] = token_key(person["surname"])
    load_given_names(people)
    for project in projects:
        project["_tokens"] = [t.strip() for t in
                              str(project.get("tokens", "")).split(";")
                              if t.strip()]
        project["_strains"] = [s.strip() for s in
                               str(project.get("strains", "")).split(";")
                               if s.strip()]
    return people, projects


def scope_of(segments, index):
    """Where in the path the match was found, relative to the folder itself.

    THE BUG THIS FIXES. The first pass proposed a person for 94% of folders
    and it was one fact repeated. A single `L:\\02_Duchenne Muscular
    Dystrophy\\Monica` parent produced 475 identical proposals, because every
    descendant path contains the parent's name. Measured: all 475 hits sat at
    depth index 1, the folder itself was named `monica` exactly zero times,
    and all 475 shared one parent.

    An inherited match is not wrong - a folder under \\Monica\\ probably is
    hers - but it is ONE piece of evidence, not 475, and it must not outrank
    a match on the folder being labelled. `evidence_group` names the ancestor
    that produced it so a reviewer can accept the whole subtree in one action
    instead of 475.
    """
    leaf = len(segments) - 1
    distance = leaf - index
    if distance <= 0:
        return {"match_scope": "folder", "scope_rank": 0, "evidence_group": ""}
    return {
        "match_scope": f"ancestor-{distance}",
        "scope_rank": distance,
        "evidence_group": "\\".join(segments[:index + 1]),
    }


def _proposal(row, field, value, tier, token, where, table, rule,
              ambiguity="", evidence="", scope=None):
    record = {
        "path": row["path"],
        "folder": row.get("folder", ""),
        "area": row.get("area", ""),
        "field": field,
        "proposed_value": value,
        "confidence": tier,
        "tier_rank": TIERS[tier],
        "match_scope": "folder",
        "scope_rank": 0,
        "evidence_group": "",
        "matched_token": token,
        "matched_in": where,
        "source_table": table,
        "rule": rule,
        "ambiguity": ambiguity,
        "evidence": evidence,
    }
    if scope:
        record.update(scope)
    return record


def propose_projects(row, segments, projects):
    """Project/assay proposals from the Projects sheet tokens."""
    out = []
    seen = set()
    for index, segment in enumerate(segments):
        seg_phrase = phrase_key(segment)
        seg_tokens = seg_phrase.split()
        for project in projects:
            for token in project["_tokens"]:
                key = phrase_key(token)
                if not key:
                    continue
                if re.search(rf"(?<![a-z0-9]){re.escape(key)}(?![a-z0-9])",
                             seg_phrase):
                    mark = (project["code"], key, "exact")
                    if mark in seen:
                        continue
                    seen.add(mark)
                    out.append(_proposal(
                        row, "assay", project["code"], "project_token_exact",
                        token, segment, "Projects", "whole-word token match",
                        evidence=f"{project['label']}",
                        scope=scope_of(segments, index)))
                    continue
                # Fuzzy only for single long words: 'pezo' against 'peso' is
                # a plausible typo, 'glia' against 'gria' is noise at this
                # length and would fire on half the drive.
                if " " in key or len(key) < MIN_FUZZY_LEN:
                    continue
                for word in seg_tokens:
                    if len(word) < MIN_FUZZY_LEN:
                        continue
                    ratio = difflib.SequenceMatcher(None, key, word).ratio()
                    if ratio >= FUZZY_RATIO and key != word:
                        mark = (project["code"], key, "fuzzy")
                        if mark in seen:
                            continue
                        seen.add(mark)
                        out.append(_proposal(
                            row, "assay", project["code"],
                            "project_token_fuzzy", token, segment, "Projects",
                            f"fuzzy match on {word!r}, ratio {ratio:.2f}",
                            evidence=project["label"],
                            scope=scope_of(segments, index)))
    return out


def propose_people(row, segments, people, by_key, context=None):
    """Surname proposals from the People sheet."""
    out = []
    seen = set()
    for index, segment in enumerate(segments):
        for word in re.split(r"[^A-Za-z-]+", segment):
            key = token_key(word)
            if len(key) < MIN_SURNAME_LEN:
                continue
            if len(key) >= MIN_GIVEN_LEN and key in GIVEN_NAMES:
                # A given name from the authority's given_name column. This
                # is what actually matches this drive: surnames match zero of
                # 551 paths, given names match most of them.
                if ("given", key) in seen:
                    continue
                seen.add(("given", key))
                out.append(_person_proposal(
                    row, GIVEN_NAMES[key], key, word, segment,
                    "person_surname_exact",
                    "given name from the authority's given_name column",
                    scope=scope_of(segments, index), context=context))
                continue
            matches = by_key.get(key, [])
            if matches:
                if ("exact", key) in seen:
                    continue
                seen.add(("exact", key))
                out.append(_person_proposal(
                    row, matches, key, word, segment, "person_surname_exact",
                    "whole-token surname match",
                    scope=scope_of(segments, index), context=context))
                continue
            for candidate_key, matches in by_key.items():
                if len(candidate_key) < MIN_FUZZY_LEN or len(key) < MIN_FUZZY_LEN:
                    continue
                ratio = difflib.SequenceMatcher(None, candidate_key,
                                                key).ratio()
                if ratio >= FUZZY_RATIO:
                    if ("fuzzy", candidate_key) in seen:
                        continue
                    seen.add(("fuzzy", candidate_key))
                    out.append(_person_proposal(
                        row, matches, candidate_key, word, segment,
                        "person_surname_fuzzy",
                        f"fuzzy surname match, ratio {ratio:.2f}",
                        scope=scope_of(segments, index), context=context))
    return out


def _person_active(person, years):
    """Was this person here in any of these years?"""
    try:
        first = int(str(person.get("first_year", "")).strip())
        last = int(str(person.get("last_year", "")).strip() or first)
    except ValueError:
        return True          # no dates recorded, so no evidence either way
    return any(first <= y <= last for y in years)


def _person_proposal(row, matches, key, word, segment, tier, rule,
                     scope=None, context=None):
    """One surname may be one person under two spellings, or two people."""
    # NARROW BY THE RECORDING BEFORE GIVING UP. Two people can share a given
    # name and still be separable by when they were here or what they worked
    # on. Measured case: `\Erin\` matches both Cheeseman E and Sawilchik E,
    # but Sawilchik ran 2021-2024 on PEZO and Cheeseman 2025 on DMD_SMOOTH and
    # DMD_CALCIUM - disjoint in BOTH year and project. A folder carrying
    # either signal resolves to one of them.
    #
    # Reported as `narrowed_by` rather than silently, because a name resolved
    # by a date is weaker evidence than a name that was never ambiguous.
    narrowed_by = []
    if len(matches) > 1 and context:
        years = {int(y) for y in context.get("years", ()) if str(y).isdigit()}
        codes = {c.upper() for c in context.get("codes", ())}
        if years:
            fits = [p for p in matches if _person_active(p, years)]
            if len(fits) == 1:
                matches, _ = fits, narrowed_by.append(
                    f"the folder's year {sorted(years)} falls inside "
                    f"{fits[0]['first_year']}-{fits[0]['last_year']} and "
                    f"outside the other candidate's")
        if len(matches) > 1 and codes:
            fits = [p for p in matches
                    if codes & {c.strip().upper() for c in
                                str(p.get("project_codes", "")).split(";")}]
            if len(fits) == 1:
                matches, _ = fits, narrowed_by.append(
                    f"the folder's project {sorted(codes)} is on this "
                    f"person's lines and not the other candidate's")

    # Collapse aliases FIRST. Hughes K and Hughes-Wiles K are two authority
    # rows and one person, so a given-name match that lands on both is not an
    # ambiguity - it is one person under two spellings, and reporting it as
    # "2 people share this surname" contradicts the Read me sheet.
    canonical = {
        SAME_PERSON.get(token_key(p["surname"]),
                        f"{p['surname']} {p['initials']}".strip())
        for p in matches
    }
    keys = {token_key(p["surname"]) for p in matches} | {key}
    # Aliases of one person map to the same note; say it once.
    notes = sorted({AMBIGUITY_NOTES[k] for k in keys if k in AMBIGUITY_NOTES})
    if len(canonical) == 1:
        value = canonical.pop()
        ambiguity = "; ".join(notes)
    else:
        # Genuinely different people. Naming one would be a coin toss wearing
        # a confidence tier.
        value = " | ".join(sorted(canonical))
        ambiguity = "; ".join(notes) or (
            f"{len(canonical)} people share this name; not resolved.")
    years = sorted({p.get("first_year", "") for p in matches} |
                   {p.get("last_year", "") for p in matches})
    codes = sorted({c.strip() for p in matches
                    for c in str(p.get("project_codes", "")).split(";")
                    if c.strip()})
    # A given name the authority itself flagged as unconfirmed must carry
    # that flag into every proposal it produces.
    seed_notes = sorted({p.get("_given_note", "") for p in matches
                         if p.get("_given_note")})
    if seed_notes:
        ambiguity = "; ".join(filter(None, [ambiguity] + seed_notes))
    if narrowed_by:
        rule = f"{rule}; narrowed because " + "; ".join(narrowed_by)
    return _proposal(
        row, "person", value, tier, word, segment, "People", rule,
        ambiguity=ambiguity, scope=scope,
        evidence=f"public record {'-'.join(y for y in years if y)}; "
                 f"lines {', '.join(codes)}" if codes else "")


def propose_years(row, segments):
    """Years, including the compact dates this drive is full of.

    A bare four or five digit number is read here and ONLY here. 41921 is
    19 April 2021, not allele 41921.
    """
    out = []
    seen = set()
    low, high = YEAR_RANGE
    for index, segment in enumerate(segments):
        for word in re.split(r"[^0-9]+", segment):
            if not word:
                continue
            year = rule = None
            if len(word) == 4 and low <= int(word) <= high:
                year, rule = int(word), "four-digit year"
            elif BARE_NUMBER_RE.match(word) and len(word) in (5, 6):
                # M D YY or MM DD YY written without separators.
                suffix = int(word[-2:])
                if 0 <= suffix <= high - 2000:
                    year, rule = 2000 + suffix, (
                        f"compact date {word}, read as M/D/YY - a bare "
                        f"4-5 digit number is a date here, never an allele")
            if year and year not in seen:
                seen.add(year)
                out.append(_proposal(
                    row, "year", str(year), "path_text", word, segment,
                    "path text", rule, scope=scope_of(segments, index)))
        # Separated dates: 3_22_21, 7-7-19
        for match in re.finditer(r"\b(\d{1,2})[_\-.](\d{1,2})[_\-.](\d{2,4})\b",
                                 segment):
            tail = match.group(3)
            year = int(tail) if len(tail) == 4 else 2000 + int(tail)
            if low <= year <= high and year not in seen:
                seen.add(year)
                out.append(_proposal(
                    row, "year", str(year), "path_text", match.group(0),
                    segment, "path text", "separated date M/D/YY",
                    scope=scope_of(segments, index)))
    return out


def propose_strains(row, segments, projects, rnai_context=False):
    """Strain proposals. Requires a letter prefix, always.

    The Projects sheet's strains column is blank pending a pull from
    ReagentHub, so authority-backed strain matches - the strongest tier there
    is - cannot fire yet. Letter-prefixed designations found in the path are
    still surfaced, one tier down, because they are the thing to check.
    """
    out = []
    seen = set()
    known = {token_key(s): (p["code"], s)
             for p in projects for s in p["_strains"]}
    for index, segment in enumerate(segments):
        for word in re.split(r"[^A-Za-z0-9-]+", segment):
            key = token_key(word)
            if not key or key in seen:
                continue
            if key in known:
                seen.add(key)
                code, strain = known[key]
                out.append(_proposal(
                    row, "strain", strain, "strain_exact", word, segment,
                    "Projects", "strain listed against a project",
                    evidence=f"project {code}",
                    scope=scope_of(segments, index)))
            elif key in KNOWN_STRAINS:
                seen.add(key)
                hit = KNOWN_STRAINS[key]
                genotype = (hit.get("genotype") or "").strip()
                out.append(_proposal(
                    row, "strain", hit["strain"], "strain_exact", word,
                    segment, "ReagentHub",
                    ("the background this RNAi was performed on"
                     if rnai_context else
                     "exact match against the lab's strain list"),
                    evidence=(f"genotype {genotype[:70]}" if genotype else ""),
                    scope=scope_of(segments, index)))
            elif LAB_STRAIN_RE.match(word):
                seen.add(key)
                out.append(_proposal(
                    row, "strain", word.upper(), "lab_strain_prefix", word,
                    segment, "lab designation pattern",
                    ("the background this RNAi was performed on, and NOT in "
                     "ReagentHub" if rnai_context else
                     "matches this lab's AVG/AG/COP/VG naming but is NOT in "
                     "ReagentHub - either it is missing from the hub or the "
                     "designation is wrong. Worth resolving, because every "
                     "strain the lab has should be in there"),
                    ambiguity=("RNAi on a non-N2 background is a suppressor "
                               "screen rather than a straight knockdown"
                               if rnai_context and key != "n2" else ""),
                    scope=scope_of(segments, index)))
    return out


# RNAi VOCABULARY. A gene name in a folder name is a TREATMENT, not a strain
# and not an assay: silencing dystrophin is written `dys-1`, and it is paired
# with `L4440`, the empty vector, as the control.
#
# THE WORD "RNAi" IS NOT THE SIGNAL. Measured on this drive: 5 of 551 paths
# contain it, while `l4440` appears 164 times. The control vector is what marks
# an RNAi experiment, so the context test is whether a SIBLING folder under the
# same parent carries L4440 - not whether the word appears.
VECTOR_RE = re.compile(r"^l4+4*0$", re.I)          # l4440, and the l440/l44440 typos
GENE_RE = re.compile(r"^[a-z]{3,4}-\d{1,3}$", re.I)
WORM_NUMBER_RE = re.compile(r"^w\d{1,2}$", re.I)

# N2's ROLE DEPENDS ON THE EXPERIMENT, and getting this backwards mislabels
# the arm. L4440 is the control for an RNAi experiment; N2 is the control for
# a mutant or edited strain. But N2 is ALSO the strain RNAi is usually
# performed ON, so inside an RNAi experiment N2 is the BACKGROUND, not the
# control - the control there is L4440, and calling N2 the control would name
# the wrong arm.
#
# The same context test that decides whether a gene name is a knockdown
# therefore decides what N2 means: vector among the siblings, N2 is the
# background; no vector, N2 is the control.
#
# RNAi is not always run on N2. Suppressor screens run it on dystrophic
# backgrounds, which is why the background is reported rather than assumed -
# and why the authority's 2016 "suppressor-mutant class cohort" note exists.
CONTROLS = {
    "n2": ("N2 (wild type, control)",
           "the control for a mutant or edited strain, the counterpart of "
           "L4440 in an RNAi experiment"),
}


def propose_conditions(row, segments, rnai_context):
    """The `condition` column: RNAi treatment and its control.

    `rnai_context` says whether L4440 appears anywhere in this folder's
    sibling set. With it, a gene name is an RNAi treatment. Without it, the
    same token could equally be a mutant allele, and that ambiguity is
    reported rather than resolved - a `dys-1` folder is a dystrophin RNAi
    knockdown or a dys-1 mutant, and the difference matters.
    """
    out = []
    seen = set()
    for index, segment in enumerate(segments):
        for word in re.split(r"[^A-Za-z0-9-]+", segment):
            key = token_key(word)
            if not key or key in seen:
                continue
            if VECTOR_RE.match(word):
                seen.add(key)
                exact = word.lower() == "l4440"
                out.append(_proposal(
                    row, "condition", "L4440 (empty RNAi vector, control)",
                    "control_exact", word, segment, "RNAi vocabulary",
                    "the empty vector control for an RNAi experiment"
                    + ("" if exact else
                       f" - spelled {word!r} here, which is a typo for L4440"),
                    scope=scope_of(segments, index)))
            elif key in CONTROLS:
                seen.add(key)
                label, why = CONTROLS[key]
                if rnai_context:
                    # N2 inside an RNAi experiment is the BACKGROUND the
                    # knockdown was performed on. The control is L4440.
                    out.append(_proposal(
                        row, "condition", "RNAi performed on N2 background",
                        "rnai_gene", word, segment, "RNAi vocabulary",
                        "N2 is the strain RNAi is usually run on, so inside "
                        "an RNAi experiment it is the background, not the "
                        "control - the control here is L4440",
                        scope=scope_of(segments, index)))
                else:
                    out.append(_proposal(
                        row, "condition", label, "control_exact", word,
                        segment, "control vocabulary", why,
                        scope=scope_of(segments, index)))
            elif GENE_RE.match(word) and not LAB_STRAIN_RE.match(word):
                seen.add(key)
                gene = word.lower()
                if rnai_context:
                    out.append(_proposal(
                        row, "condition", f"{gene} RNAi", "rnai_gene", word,
                        segment, "RNAi vocabulary",
                        "gene name in a folder set that also contains L4440, "
                        "so this is a knockdown rather than a mutant",
                        scope=scope_of(segments, index)))
                else:
                    out.append(_proposal(
                        row, "condition", gene, "path_text", word, segment,
                        "path text",
                        "gene name with no L4440 anywhere in the sibling set",
                        ambiguity=(f"{gene} could be an RNAi knockdown or a "
                                   f"{gene} mutant strain - nothing here "
                                   f"distinguishes them"),
                        scope=scope_of(segments, index)))
            elif WORM_NUMBER_RE.match(word):
                seen.add(key)
                out.append(_proposal(
                    row, "note", f"worm {word[1:]}", "path_text", word,
                    segment, "path text",
                    "worm number, a replicate identifier - recorded so it is "
                    "not read as a strain",
                    scope=scope_of(segments, index)))
    return out


def propose_given_names(row, segments, people_initials):
    """The person-shaped folder, which on this drive holds a FIRST name.

    ONLY FOR NAMES THE AUTHORITY CANNOT RESOLVE. A given name that appears in
    the authority's given_name column is matched by `propose_people` and
    arrives authority-backed; this is the remainder. The lab people page
    covers about 39 of 101 rows, so the remainder is real and is the list of
    given names still to be filled in by hand.

    Measured across all 551 rows: surnames match zero path segments while
    'monica' alone matches 475, which is why the given_name column exists at
    all.
    """
    out = []
    if len(segments) < 2:
        return out
    # The folder directly under the area is where a person's name sits.
    index = 1
    candidate = segments[index]
    words = [w for w in re.split(r"[^A-Za-z]+", candidate) if w]
    if len(words) != 1:
        return out
    word = words[0]
    key = token_key(word)
    if not (MIN_GIVEN_LEN <= len(key) <= MAX_GIVEN_LEN):
        return out
    if key in NOT_A_PERSON:
        return out
    # An all-capitals token is an acronym, a condition or a construct, not a
    # given name: DEFL, DMSO. Names are capitalised, not shouted.
    if word.isupper() and len(word) <= 5:
        return out
    if key in GIVEN_NAMES:
        return out          # already proposed, and backed by the authority
    initial = key[0].upper()
    candidates = sorted(
        f"{p['surname']} {p['initials']}".strip()
        for p in people_initials.get(initial, [])
        if not p.get("_given"))
    note = (f"{len(candidates)} authority rows have initial {initial} and no "
            f"given name yet: {', '.join(candidates)}" if candidates else
            f"no authority row has initial {initial} without a given name")
    out.append(_proposal(
        row, "person", word, "path_text", word, candidate, "path text",
        "given name in the person-shaped folder, not yet in the authority's "
        "given_name column",
        ambiguity="Given name, not resolved to a person.", evidence=note,
        scope=scope_of(segments, index)))
    return out


def run(labels_path, authority_path, out_path):
    people, projects = load_authority(authority_path)
    load_strains()
    by_key = defaultdict(list)
    for person in people:
        by_key[person["_key"]].append(person)
    by_initial = defaultdict(list)
    for person in people:
        for initial in str(person.get("initials", "")).replace(" ", ""):
            by_initial[initial.upper()].append(person)

    with open(labels_path, newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "path" not in rows[0]:
        raise SystemExit(
            f"{labels_path} does not look like the label CSV: it needs a "
            f"'path' column.")

    # An RNAi experiment is marked by its control vector, not by the word
    # "RNAi" - which appears in 5 of 551 paths while L4440 appears in 164.
    # A gene name is a knockdown if any SIBLING folder carries the vector.
    rnai_parents = {}
    for row in rows:
        parent = _parent(row)
        if any(VECTOR_RE.match(w) for seg in path_segments(row["path"])
               for w in re.split(r"[^A-Za-z0-9-]+", seg) if w):
            rnai_parents[parent] = True

    proposals = []
    for row in rows:
        segments = path_segments(row["path"])
        # Projects and years first: they are the evidence that disambiguates
        # two people who share a given name (see _person_proposal).
        project_proposals = propose_projects(row, segments, projects)
        year_proposals = propose_years(row, segments)
        context = {
            "codes": {p["proposed_value"] for p in project_proposals},
            "years": {p["proposed_value"] for p in year_proposals},
        }
        proposals += project_proposals
        proposals += propose_people(row, segments, people, by_key, context)
        proposals += year_proposals
        proposals += propose_strains(row, segments, projects,
                                     rnai_parents.get(_parent(row), False))
        proposals += propose_conditions(row, segments,
                                        rnai_parents.get(_parent(row), False))
        proposals += propose_given_names(row, segments, by_initial)

    # Scope outranks tier within a folder: a fuzzy hit on the folder being
    # labelled is better evidence about THAT folder than an exact hit
    # inherited from a grandparent.
    proposals.sort(key=lambda p: (p["path"], p["scope_rank"], p["tier_rank"],
                                  p["field"]))
    fields = ["path", "folder", "area", "field", "proposed_value",
              "confidence", "tier_rank", "match_scope", "scope_rank",
              "evidence_group", "matched_token", "matched_in",
              "source_table", "rule", "ambiguity", "evidence"]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(proposals)
    return rows, proposals


def report(rows, proposals, out_path):
    print(f"\n{len(rows)} folders read, {len(proposals)} proposals written "
          f"to {out_path}\n")
    by_field = defaultdict(list)
    for p in proposals:
        by_field[p["field"]].append(p)
    covered = defaultdict(set)
    for p in proposals:
        covered[p["field"]].add(p["path"])

    print(f"{'field':10} {'folders covered':>16}  {'proposals':>10}  tiers")
    for field in ("assay", "person", "year", "strain", "condition", "note"):
        items = by_field.get(field, [])
        tiers = Counter(p["confidence"] for p in items)
        share = len(covered[field]) / len(rows) * 100 if rows else 0
        print(f"{field:10} {len(covered[field]):7} / {len(rows):<6} "
              f"{share:4.0f}%  {len(items):>10}  "
              + ", ".join(f"{k}={v}" for k, v in tiers.most_common()))

    # DISTINCT EVIDENCE, not proposal count. 475 proposals inherited from one
    # `\Monica` parent are one fact, and a summary that reports them as 475
    # is the thing that made the first pass look like 94% coverage.
    print(f"\n{'field':10} {'on the folder':>14}  {'inherited':>10}  "
          f"{'distinct facts':>15}")
    for field in ("assay", "person", "year", "strain", "condition", "note"):
        items = by_field.get(field, [])
        own = [p for p in items if p["scope_rank"] == 0]
        inherited = [p for p in items if p["scope_rank"] > 0]
        facts = {(p["evidence_group"] or p["path"], p["matched_token"],
                  p["proposed_value"]) for p in items}
        print(f"{field:10} {len(own):14}  {len(inherited):10}  "
              f"{len(facts):15}")

    unlabelled = [r for r in rows
                  if not any(p["path"] == r["path"] for p in proposals)]
    print(f"\nfolders with no proposal at all: {len(unlabelled)}")
    ambiguous = [p for p in proposals if p["ambiguity"]]
    print(f"proposals carrying an ambiguity note: {len(ambiguous)}")
    authority_backed = [p for p in proposals if p["source_table"] != "path text"]
    print(f"backed by an authority table: {len(authority_backed)} of "
          f"{len(proposals)}")
    groups = {p["evidence_group"] for p in proposals if p["evidence_group"]}
    print(f"inherited from {len(groups)} ancestor folder(s); accepting one "
          f"group accepts its whole subtree")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--labels", required=True)
    ap.add_argument("--authority", required=True)
    ap.add_argument("--out", default="label_proposals.csv")
    args = ap.parse_args()
    rows, proposals = run(args.labels, args.authority, args.out)
    report(rows, proposals, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
