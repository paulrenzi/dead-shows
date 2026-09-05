"""Venue-string cleaning and the one normalized key everything joins on.

The upstream listing puts a free-text blob in the venue column. About a
quarter of the time that blob is a street address rather than a name, and it
usually drags the city, the state (twice — abbreviation AND full name), the
country and the ZIP along behind it:

    "4935 River Road New Hope PA United States Pennsylvania 18938"
    "101 Walnut StreetMontclair07042US"

`clean_venue` strips that tail. `venue_key` then normalizes what is left so
that "1 State St." and "1 State Street" are the same place — they were two
cards for one show, and they are what the address join in
`resolve_venue_names.py` and `link_happy_hour.py` both key on.

`venue_key` is mirrored in `app.js` (`venueKey`). Change one, change both.
"""

import re

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut",
    "DE": "Delaware", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon",
    "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "DC": "District of Columbia",
}

COUNTRY_TAILS = ["united states of america", "united states", "usa", "us"]

# Street-suffix and directional spellings collapsed to one form. Only the KEY
# uses these — the displayed address keeps whatever the source wrote.
SUFFIXES = {
    "st": "street", "str": "street",
    "ave": "avenue", "av": "avenue",
    "rd": "road", "dr": "drive", "drv": "drive",
    "ln": "lane", "blvd": "boulevard", "blv": "boulevard",
    "pkwy": "parkway", "pky": "parkway", "pwy": "parkway",
    "hwy": "highway", "pl": "place", "ct": "court",
    "ter": "terrace", "terr": "terrace", "sq": "square",
    "cir": "circle", "trl": "trail", "pt": "point",
    "pk": "pike", "tpke": "turnpike", "tpk": "turnpike",
    "n": "north", "s": "south", "e": "east", "w": "west",
    "ne": "northeast", "nw": "northwest",
    "se": "southeast", "sw": "southwest",
    "mt": "mount", "ft": "fort", "rte": "route",
}

ADDRESS_RE = re.compile(r"^\s*\d+\s*[-\w]*\s+\S")


def looks_like_address(venue):
    """True when the venue string opens with a street number."""
    return bool(ADDRESS_RE.match(venue or ""))


def _strip_tail(s, tail):
    """Remove `tail` from the end of `s`, glued or space-separated.

    Matching runs over both strings with punctuation and spacing removed, so
    "Blvd.St. Augustine Beach" gives up "st augustine beach" the same way a
    cleanly spaced string would.
    """
    body = s.rstrip(" ,.-")
    want = re.sub(r"[^a-z0-9]+", "", tail.lower())
    if not want:
        return s, False
    # Walk backwards over the body, collecting alphanumerics, until they spell
    # the tail. `cut` is where the tail starts in the ORIGINAL string.
    got = ""
    cut = len(body)
    for i in range(len(body) - 1, -1, -1):
        ch = body[i]
        if ch.isalnum():
            got = ch.lower() + got
            if len(got) > len(want):
                return s, False
            if got == want:
                cut = i
                break
        elif got:
            # Punctuation inside the run is fine; keep walking.
            continue
    if got != want:
        return s, False
    head = body[:cut]
    # A tail that ate the end of a real word ("...mont" out of "Fremont") is
    # not a tail. Require a boundary: a separator, a case change from the
    # glued form ("StreetMontclair"), or a digit meeting a letter.
    prev = head.rstrip()[-1:] if head.rstrip() else ""
    first = body[cut:cut + 1]
    glued_ok = (
        not prev
        or not prev.isalnum()
        or head[-1:] != prev
        or (prev.islower() and first.isupper())
        or (prev.isdigit() != first.isdigit())
    )
    if not glued_ok:
        return s, False
    return head.rstrip(" ,.-"), True


def clean_venue(venue, city="", state=""):
    """Strip the trailing city / state / country / ZIP off a venue blob.

    Country, ZIP and the state's full name are always safe to remove. The city
    and the bare state abbreviation are only removed when the string still
    carries a street number, so a venue genuinely NAMED for its town ("The
    Ardmore", in Ardmore) keeps its name.
    """
    s = re.sub(r"\s+", " ", (venue or "")).strip()
    if not s:
        return s
    addressy = looks_like_address(s)

    always = list(COUNTRY_TAILS)
    if state and STATE_NAMES.get(state):
        always.append(STATE_NAMES[state].lower())

    conditional = []
    if addressy:
        if state:
            conditional.append(state.lower())
        if city:
            c = city.lower().strip()
            conditional.append(c)
            conditional.append(re.sub(r"^township of\s+", "", c) + " twp")
            conditional.append(re.sub(r"\s+township$", " twp", c))
            conditional.append(re.sub(r"\s+township$", "", c))
            # A source that writes "St. Augustine" where the city is
            # "St. Augustine Beach" still means the town. Allow the leading
            # part of a multi-word city as its own tail.
            parts = c.split()
            for n in range(len(parts) - 1, 0, -1):
                head = " ".join(parts[:n])
                if len(head) >= 4:
                    conditional.append(head)

    tails = always + conditional
    for _ in range(12):
        before = s
        # ZIP, optionally ZIP+4, glued or spaced.
        body = s.rstrip(" ,.-")
        m = re.search(r"\d{5}(?:-\d{4})?$", body)
        if m and m.start() > 0 and len(body[: m.start()].strip(" ,.-")) >= 6:
            s = body[: m.start()].rstrip(" ,.-")
        for t in tails:
            if not t:
                continue
            cand, hit = _strip_tail(s, t)
            if hit and len(cand.strip(" ,.-")) >= 6:
                s = cand
        # Stripping a town can leave the connector that introduced it
        # ("... Rd Township of"). A trailing connector is never a venue name.
        s = re.sub(
            r"(?i)[\s,]+(?:township of|city of|town of|borough of|village of|of|in|at|near|the)$",
            "",
            s,
        ).rstrip(" ,.-")
        if s == before:
            break
    s = s.strip(" ,.-") or (venue or "").strip()
    # The upstream description cell sometimes yields a bare "/" or a lone ZIP.
    # That is not a venue, and a card is better off saying nothing than saying
    # "19425" where the room's name belongs.
    if not re.search(r"[A-Za-z]", s):
        return ""
    return s


def venue_key(venue):
    """Normalize a venue string to the token form every join uses.

    Mirrored in app.js as `venueKey` for the merge dedupe.
    """
    s = (venue or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    if not s:
        return ""
    out = []
    for tok in s.split():
        if tok in ("suite", "ste", "unit", "apt", "fl", "floor", "the"):
            continue
        out.append(SUFFIXES.get(tok, tok))
    return " ".join(out)


def address_key(venue, city="", state=""):
    """Join key for an address-like venue: house number + normalized street.

    Everything after the street name is noise that differs between sources
    ("Ste A-B", "#2329", a second copy of the town), so the key stops at the
    street name and the city carries the rest of the identity.
    """
    k = venue_key(clean_venue(venue, city, state))
    if not k:
        return ""
    m = re.match(r"^(\d+)\s+(.+)$", k)
    if not m:
        return ""
    num, rest = m.group(1), m.group(2).split()
    words = []
    for w in rest:
        words.append(w)
        if w in set(SUFFIXES.values()) and len(words) > 1:
            break
        if len(words) >= 4:
            break
    return f"{num} {' '.join(words)}|{(city or '').lower().strip()}|{(state or '').upper().strip()}"
