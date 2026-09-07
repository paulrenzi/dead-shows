"""Cross-link shows to Happy Hour Finder venues.

Both sites are static and both are published from paulrenzi.github.io, so the
join happens here, at build time, against Happy Hour Finder's own published
JSON. Nothing is fetched at page load and neither site gains a runtime
dependency on the other.

Two things come out of a match:
  - a licensed business NAME for a show listed only as a street address, which
    beats the OpenStreetMap guess because it is a PLCB licence record, and
  - the venue's happy-hour windows, so a card can say "happy hour until 6"
    for the night of the show and link straight to that venue on the board.

Outputs:
  data/hhf-links.json — audit trail: every match, how it was made
  data/gdtb-events.json — gains an `hhf` block in place

Run:
  python scripts/link_happy_hour.py [--local PATH_TO_HHF_REPO]

Matching is address-first and city-gated. An address key carries the city and
the state, so "101 Walnut St, Montclair NJ" cannot pick up "101 Walnut St,
Green Lane PA" — an ungated key does exactly that, and did.
"""

import json
import re
import sys
import time
import urllib.request
from urllib.parse import quote
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from venuetext import STATE_NAMES, address_key, clean_venue, venue_key  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = "dead-shows hhf linker (paulmichaelrenzi@gmail.com)"

HHF_BASE = "https://paulrenzi.github.io/happy-hour-finder"
HHF_DATA = HHF_BASE + "/data"

# A name match still has to be the same building. Where both sides publish a
# coordinate, anything past this is two businesses that share a name.
MAX_MATCH_MILES = 0.4


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def load_json(path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return default
    return default


def save_json(path, data):
    tmp = path.with_suffix(path.suffix + ".new")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


BIZ_SUFFIX = ("co", "inc", "llc", "ltd", "company")


def despace(s):
    """venue_key()'s tokens run together, minus the business suffix.

    The join key a person's spelling survives: "von C Brewing Co" and "Vonc
    Brewing" are the same eleven characters once the spaces and the "Co" are
    gone, and no amount of token-wise comparison will ever see that.
    """
    toks = [t for t in venue_key(s).split() if t not in BIZ_SUFFIX]
    return "".join(toks)


def haversine_miles(a, b):
    lat1, lng1, lat2, lng2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * 3958.8 * atan2(sqrt(h), sqrt(1 - h))


STATE_BY_NAME = {v.lower(): k for k, v in STATE_NAMES.items()}


def split_address(addr):
    """'4935 River Rd, Point Pleasant PA 18950' -> ('4935 River Rd', 'Point Pleasant', 'PA')."""
    parts = [p.strip() for p in (addr or "").split(",") if p.strip()]
    if len(parts) < 2:
        return "", "", ""
    street = parts[0]
    tail = " ".join(parts[1:])
    tail = re.sub(r"\s*\d{5}(?:-\d{4})?\s*$", "", tail).strip()
    m = re.search(r"\b([A-Z]{2})$", tail)
    if m:
        return street, tail[: m.start()].strip(" ,"), m.group(1)
    words = tail.split()
    for n in (2, 1):
        if len(words) > n:
            cand = " ".join(words[-n:]).lower()
            if cand in STATE_BY_NAME:
                return street, " ".join(words[:-n]).strip(" ,"), STATE_BY_NAME[cand]
    return street, tail, ""


# Happy Hour Finder ships each zone as TWO files and the names do not say so.
# `zone-<id>.json` is the venues that HAVE a published happy hour -- the board
# itself, 472 venues. `venues-<id>.json` is the other 3,229: every licensed
# premises it knows about and has no hours for.
#
# Reading only the second one is the mistake this whole integration was built
# on. It matched 18 shows and reported that not one of them published a window,
# which was true and unfalsifiable -- the file it was reading is by definition
# the venues with no window. The same misreading produced "only 1 of 476 deal
# venues carries a coordinate," recorded as a blocker on Happy Hour Finder's
# side. 441 of them carried one all along.
ZONE_FILES = ("zone-{}.json", "venues-{}.json")


def load_hhf(local):
    """Read Happy Hour Finder's published bundles, from the web or a checkout.

    Both files per zone, deal-bearing first so that where the same venue
    appears in both it is the board's copy -- the one carrying the windows --
    that wins the key.
    """
    if local:
        base = Path(local) / "web" / "data"
        index = json.loads((base / "index.json").read_text(encoding="utf-8"))
        board = json.loads((base / "board-by-lid.json").read_text(encoding="utf-8"))
        zones = []
        for z in index.get("zones", []):
            for pattern in ZONE_FILES:
                p = base / pattern.format(z["id"])
                if p.exists():
                    zones.append((z, json.loads(p.read_text(encoding="utf-8"))))
    else:
        index = fetch_json(f"{HHF_DATA}/index.json")
        board = fetch_json(f"{HHF_DATA}/board-by-lid.json")
        zones = []
        for z in index.get("zones", []):
            for pattern in ZONE_FILES:
                zones.append((z, fetch_json(f"{HHF_DATA}/{pattern.format(z['id'])}")))
                time.sleep(0.1)
    return index, board, zones


def main(argv):
    local = None
    if "--local" in argv:
        local = argv[argv.index("--local") + 1]

    events = load_json(DATA / "gdtb-events.json", [])
    if not events:
        print("no events to link", file=sys.stderr)
        return 1

    try:
        index, board, zones = load_hhf(local)
    except Exception as e:
        # The linker must never take the feed down with it. Leaving the
        # existing links in place is strictly better than dropping them.
        print(f"could not read Happy Hour Finder data ({e}) — leaving links as they are",
              file=sys.stderr)
        return 1

    zone_name = {z["id"]: z.get("name", z["id"]) for z, _ in zones}
    by_address, by_name = {}, {}
    total = 0
    for z, bundle in zones:
        for v in bundle.get("venues", []):
            total += 1
            street, city, state = split_address(v.get("address", ""))
            if not street:
                continue
            ak = address_key(street, city, state)
            if ak:
                by_address.setdefault(ak, v)
            nk = venue_key(v.get("name", ""))
            if nk and city:
                by_name.setdefault(f"{nk}|{city.lower()}|{state.upper()}", v)
    print(f"Happy Hour Finder: {total} venues across {len({z['id'] for z, _ in zones})} "
          f"zones (built {index.get('built_at')})")

    links, matched = {}, 0
    for ev in events:
        ev.pop("hhf", None)
        city, state = ev.get("city", ""), ev.get("state", "")
        if state not in ("PA", "NJ", "DE"):
            continue  # the board only covers the western Philly suburbs
        raw = ev.get("venue", "")
        cleaned = clean_venue(raw, city, state)

        hit, how = None, None
        ak = address_key(raw, city, state)
        if ak and ak in by_address:
            hit, how = by_address[ak], "address"
        if hit is None:
            for name in (ev.get("venueName"), cleaned):
                nk = venue_key(name or "")
                if not nk:
                    continue
                cand = by_name.get(f"{nk}|{city.lower()}|{state.upper()}")
                if cand:
                    hit, how = cand, "name"
                    break
        # A directory types a venue the way a person says it, not the way the
        # licence spells it: "von C Brewing Co" for Vonc Brewing, "Shere-E-Punjab
        # Indian Restaurant" for Shere-E-Punjab. venue_key() keeps the spaces and
        # the trailing words, so both missed and both shows were dropped.
        #
        # This is deliberately NOT fuzzy. Fuzzy matching on the name alone
        # proposed "Bucks County Brewery" (Pipersville) -> "The Bucks Club"
        # (Jamison) and Tonewood Brewing (Oaklyn NJ) -> Rosewood Bar
        # (Philadelphia) -- the exact wrong-building join this file's header
        # warns about. Two things keep it honest: the SAME CITY gate the strict
        # pass already uses, and a prefix that has to be long enough to be a
        # name rather than a word. "Sellersville Theater" still does not take
        # "Sellersville Bar & Grill", because neither key prefixes the other.
        if hit is None:
            for name in (ev.get("venueName"), cleaned):
                nk = despace(name or "")
                if len(nk) < 10:
                    continue
                for key, cand in by_name.items():
                    ckey, ccity, cstate = key.rsplit("|", 2)
                    if ccity != city.lower() or cstate != state.upper():
                        continue
                    ck = despace(ckey)
                    if len(ck) < 10:
                        continue
                    if nk == ck or nk.startswith(ck) or ck.startswith(nk):
                        hit, how = cand, "name-loose"
                        break
                if hit:
                    break
        if hit is None:
            continue

        # Same name, same town, different building happens. Where both sides
        # have a pin, make them agree before claiming it is one place.
        if hit.get("lat") and ev.get("locationPrecision") == "venue":
            miles = haversine_miles((hit["lat"], hit["lng"]), (ev["lat"], ev["lng"]))
            if miles > MAX_MATCH_MILES:
                continue

        lid = str(hit.get("lid") or hit.get("id") or "")
        # The venue's own copy from the deal bundle if we matched it there;
        # board-by-lid otherwise, which also resolves a second licence at the
        # same bar (`also_lids`) that no venue row is keyed on.
        deals = []
        source = hit if hit.get("deals") else (board.get(lid) or {})
        for deal in source.get("deals", []):
            for w in deal.get("windows", []):
                if w.get("dow") and w.get("start") and w.get("end"):
                    deals.append({"dow": w["dow"], "start": w["start"], "end": w["end"]})
        zone = hit.get("zone_id") or ""
        # `#v=` alone is a dead link for most of what we match, and it fails
        # SILENTLY -- the reader lands on the default board and concludes the
        # button does nothing. Two separate reasons, both real:
        #
        #  * the board only boots the zones' DEAL bundles. A venue with no
        #    published window arrives only with its zone's base, which the app
        #    fetches only when the hash names a zone. Without `z=`, openVenue()
        #    looks the id up in a list it was never in and returns.
        #  * and for a venue with no window there is nothing to open anyway --
        #    the sheet it would show is the "tell us this venue's hours" form.
        #
        # So: on the board, deep-link the venue and carry the zone so the
        # lookup can succeed. Off the board, send the reader to that town's
        # board, which is the honest answer to "where can I get a drink near
        # this show" and the thing we can actually stand behind today.
        on_board = bool(deals)

        # "when you click on that, it should show you a list for that town
        # sorted by distance from the venue." The board already ranks by
        # distance from an origin; `near=` lets this link choose that origin,
        # so the whole feature is a coordinate and a label on the URL. No list
        # is duplicated onto the card, and every other consumer of the board
        # gets the same sort for free.
        #
        # Prefer the matched venue's own pin: it is a PLCB licence geocode of
        # the same building, whereas the event's coordinate is only trustworthy
        # at `locationPrecision == "venue"` and is otherwise the town.
        origin = None
        if hit.get("lat") is not None and hit.get("lng") is not None:
            origin = (hit["lat"], hit["lng"])
        elif ev.get("locationPrecision") == "venue" and ev.get("lat") is not None:
            origin = (ev["lat"], ev["lng"])

        near = ""
        if origin and zone:
            label = ev.get("venueName") or hit.get("name") or ""
            near = f"&near={origin[0]:.6f},{origin[1]:.6f}"
            if label:
                near += "&from=" + quote(label, safe="")

        if lid and zone and on_board:
            url = f"{HHF_BASE}/#z={zone}&v={lid}{near}"
        elif zone:
            url = f"{HHF_BASE}/#z={zone}{near}"
        else:
            url = HHF_BASE
        block = {
            "lid": lid,
            "name": hit.get("name"),
            "zone": zone,
            "zoneName": zone_name.get(zone, ""),
            "url": url,
            # Whether this venue itself publishes a window, or we are only
            # pointing at its town. The card says which; it must not imply the
            # show's own venue has a happy hour when it does not.
            "onBoard": on_board,
            "deals": deals,
            "match": how,
        }
        ev["hhf"] = block
        # A PLCB licence record beats an OpenStreetMap guess for the name.
        if hit.get("name") and (not ev.get("venueName") or ev.get("venueNameSource") == "osm"):
            from venuetext import looks_like_address
            if looks_like_address(cleaned):
                ev["venueName"] = hit["name"]
                ev["venueNameSource"] = "hhf"
        links[f"{ev['id']}"] = block
        matched += 1

    save_json(DATA / "hhf-links.json", {
        "built_at": index.get("built_at"),
        "matched": matched,
        "links": links,
    })
    save_json(DATA / "gdtb-events.json", events)

    with_deals = sum(1 for b in links.values() if b["deals"])
    by_how = {}
    for b in links.values():
        by_how[b["match"]] = by_how.get(b["match"], 0) + 1
    print(f"matched {matched} shows to a Happy Hour Finder venue {by_how}; "
          f"{with_deals} of them have published happy-hour windows")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
