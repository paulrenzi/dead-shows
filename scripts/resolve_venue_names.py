"""Turn address-only venues into the business that sits at the address.

About a quarter of the shows arrive with a street address where the room's
name belongs. This asks OpenStreetMap (Overpass, keyless, no account) what
named bar / brewery / restaurant / theatre stands on that spot and records it
as `venueName`, leaving `venue` as the address for the second line of the card.

Outputs:
  data/venue-names.json — address key -> {name, osm, distance_m, resolved}
  data/venue-names-manual.json — hand overrides, same shape, never overwritten
  data/gdtb-events.json — gains `venueName` / `venueNameSource` in place

Run:
  python scripts/resolve_venue_names.py            # only unresolved keys
  python scripts/resolve_venue_names.py --recheck  # also retry recorded misses
  python scripts/resolve_venue_names.py --limit 40 # cap the Overpass work

A miss is only recorded when Overpass ANSWERS and the answer is empty. A
timeout, a 429 or a gateway error is left unrecorded so the next run asks
again — a cached failure is indistinguishable from "no such place" and would
pin these venues to a bare address forever.
"""

import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date
from math import atan2, cos, radians, sin, sqrt
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from venuetext import address_key, clean_venue, looks_like_address  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
UA = "dead-shows venue resolver (paulmichaelrenzi@gmail.com)"

OVERPASS = "https://overpass-api.de/api/interpreter"
NOMINATIM = "https://nominatim.openstreetmap.org/search"

# How far from the geocoded point a candidate may sit. A street geocode lands
# on the centreline, so the building is routinely 30-50m away.
RADIUS_M = 70
BATCH = 30

# Distance decides, and the tag family only breaks a near-tie. Ranking first
# put a bar 51m away ahead of the music hall 5m away, which is exactly the
# wrong answer. A candidate whose own addr:housenumber matches the listing is
# worth more than either signal.
RANK_PENALTY_M = 12
HOUSENUMBER_BONUS_M = 45
CONFIDENT_M = 55

# Tag families worth a venue name, best first. A show is in a bar or a room,
# not at the dentist next door, so the ranking decides ties before distance.
TAG_RANK = [
    ("amenity", {"bar", "pub", "nightclub", "biergarten"}),
    ("craft", {"brewery", "distillery", "winery"}),
    ("amenity", {"events_venue", "theatre", "arts_centre", "casino", "restaurant"}),
    ("leisure", {"bowling_alley", "dance", "sports_centre", "club", "amusement_arcade"}),
    ("amenity", {"cafe", "fast_food", "community_centre", "social_facility", "place_of_worship"}),
    ("tourism", {"hotel", "attraction", "museum"}),
    ("shop", {"alcohol", "wine", "deli"}),
    ("leisure", {"park", "pitch", "stadium"}),
]

OVERPASS_FILTERS = [
    '[name][amenity~"^(bar|pub|nightclub|biergarten|events_venue|theatre|arts_centre|casino|restaurant|cafe|fast_food|community_centre|social_facility|place_of_worship)$"]',
    '[name][craft~"^(brewery|distillery|winery)$"]',
    '[name][leisure~"^(bowling_alley|dance|sports_centre|club|amusement_arcade|park|pitch|stadium)$"]',
    '[name][tourism~"^(hotel|attraction|museum)$"]',
    '[name][shop~"^(alcohol|wine|deli)$"]',
]


def fetch(url, data=None, timeout=90):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


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


def haversine_m(a, b):
    lat1, lng1, lat2, lng2 = map(radians, (a[0], a[1], b[0], b[1]))
    h = sin((lat2 - lat1) / 2) ** 2 + cos(lat1) * cos(lat2) * sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371000 * atan2(sqrt(h), sqrt(1 - h))


def house_number(s):
    """Leading house number of an address, or of an addr:housenumber tag.

    "208-210" and "208" are the same building; keep only the first run.
    """
    m = re.match(r"\s*(\d+)", s or "")
    return m.group(1) if m else ""


def rank_of(tags):
    for i, (k, vals) in enumerate(TAG_RANK):
        if tags.get(k) in vals:
            return i
    return len(TAG_RANK)


def geocode_address(addr, city, state, cache):
    """Pin the cleaned street address itself, not the town centre.

    The scraper already caches a city-level and a venue-level lookup; this adds
    a third key so a street address gets its own coordinate without disturbing
    either. Only a definitive answer is cached.
    """
    key = f"addr|{addr.lower()}|{city.lower()}, {state.lower()}"
    if key in cache:
        return cache[key]
    q = f"{addr}, {city}, {state}, USA"
    url = f"{NOMINATIM}?format=json&limit=1&q={urllib.parse.quote(q)}"
    for attempt in range(3):
        try:
            arr = json.loads(fetch(url, timeout=30))
            cache[key] = (
                {"lat": float(arr[0]["lat"]), "lng": float(arr[0]["lon"])} if arr else None
            )
            time.sleep(1.1)
            return cache[key]
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            break
        except Exception:
            time.sleep(2)
    time.sleep(1.1)
    return None


def overpass_batch(points):
    """One Overpass call for up to BATCH points. Returns elements with centres.

    Raises on any transport failure — the caller must NOT record misses for a
    batch that never answered.
    """
    parts = ["[out:json][timeout:120];", "("]
    for lat, lng in points:
        for filt in OVERPASS_FILTERS:
            parts.append(f"nwr(around:{RADIUS_M},{lat:.6f},{lng:.6f}){filt};")
    parts.append(");")
    parts.append("out center tags;")
    body = urllib.parse.urlencode({"data": "\n".join(parts)}).encode()
    raw = fetch(OVERPASS, data=body, timeout=180)
    return json.loads(raw).get("elements", [])


def main(argv):
    recheck = "--recheck" in argv
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])

    events = load_json(DATA / "gdtb-events.json", [])
    if not events:
        print("no events to resolve", file=sys.stderr)
        return 1

    resolved = load_json(DATA / "venue-names.json", {})
    manual = load_json(DATA / "venue-names-manual.json", {})
    geocache = load_json(DATA / "geocode-cache.json", {})
    today = date.today().isoformat()

    # One entry per distinct address, carrying the best coordinate we have.
    targets = {}
    for ev in events:
        venue = clean_venue(ev.get("venue", ""), ev.get("city", ""), ev.get("state", ""))
        if not looks_like_address(venue):
            continue
        key = address_key(ev.get("venue", ""), ev.get("city", ""), ev.get("state", ""))
        if not key:
            continue
        t = targets.setdefault(key, {
            "address": venue,
            "city": ev.get("city", ""),
            "state": ev.get("state", ""),
            "shows": 0,
            "geo": None,
        })
        t["shows"] += 1
        if ev.get("locationPrecision") == "venue" and t["geo"] is None:
            t["geo"] = (ev["lat"], ev["lng"])

    todo = []
    for key, t in targets.items():
        if key in manual:
            continue
        rec = resolved.get(key)
        if rec and (rec.get("name") or not recheck):
            continue
        todo.append((key, t))
    todo.sort(key=lambda kt: -kt[1]["shows"])
    if limit:
        todo = todo[:limit]

    print(f"{len(targets)} distinct addresses, {len(todo)} to look up")

    # Make sure every address has a coordinate of its own before asking OSM.
    ready = []
    for key, t in todo:
        geo = t["geo"]
        if geo is None:
            g = geocode_address(t["address"], t["city"], t["state"], geocache)
            if g:
                geo = (g["lat"], g["lng"])
        if geo:
            ready.append((key, t, geo))
    save_json(DATA / "geocode-cache.json", geocache)
    print(f"{len(ready)} have a coordinate to search around")

    hits = misses = 0
    for i in range(0, len(ready), BATCH):
        chunk = ready[i:i + BATCH]
        try:
            elements = overpass_batch([g for _, _, g in chunk])
        except Exception as e:
            print(f"  overpass batch {i // BATCH} FAILED ({e}) — not recorded", file=sys.stderr)
            time.sleep(30)
            continue
        for key, t, geo in chunk:
            want_num = house_number(t["address"])
            best = None
            for el in elements:
                c = el.get("center") or el
                lat, lon = c.get("lat"), c.get("lon")
                if lat is None or lon is None:
                    continue
                d = haversine_m(geo, (lat, lon))
                if d > RADIUS_M:
                    continue
                tags = el.get("tags", {})
                if not tags.get("name"):
                    continue
                theirs = house_number(tags.get("addr:housenumber", ""))
                # A neighbour that publishes a DIFFERENT number is not our
                # venue, however close it sits or however well it is tagged.
                if want_num and theirs and theirs != want_num:
                    continue
                # Past this distance the answer is a neighbour unless the
                # element publishes our own house number.
                if d > CONFIDENT_M and not (want_num and theirs == want_num):
                    continue
                score = d + rank_of(tags) * RANK_PENALTY_M
                if want_num and theirs == want_num:
                    score -= HOUSENUMBER_BONUS_M
                cand = (score, round(d), tags.get("name"), el.get("type"), el.get("id"))
                if best is None or cand[0] < best[0]:
                    best = cand
            if best:
                resolved[key] = {
                    "name": best[2],
                    "osm": f"{best[3]}/{best[4]}",
                    "distance_m": best[1],
                    "address": t["address"],
                    "city": t["city"],
                    "state": t["state"],
                    "resolved": today,
                }
                hits += 1
                print(f"  {t['address']}, {t['city']} -> {best[2]} ({best[1]}m)")
            else:
                # Overpass answered and knows nothing here. Safe to record.
                resolved[key] = {"name": None, "checked": today}
                misses += 1
        save_json(DATA / "venue-names.json", resolved)
        time.sleep(4)  # polite to the public Overpass instance

    applied = apply_names(events, resolved, manual)
    save_json(DATA / "gdtb-events.json", events)
    print(f"\nresolved {hits} new, {misses} answered-empty. {applied} shows now carry a venue name.")
    return 0


def apply_names(events, resolved, manual):
    """Write venueName onto every event whose address is known. Idempotent."""
    n = 0
    for ev in events:
        raw = ev.get("venue", "")
        cleaned = clean_venue(raw, ev.get("city", ""), ev.get("state", ""))
        if cleaned != raw:
            ev["venue"] = cleaned
        ev.pop("venueName", None)
        ev.pop("venueNameSource", None)
        if not looks_like_address(cleaned):
            continue
        key = address_key(raw, ev.get("city", ""), ev.get("state", ""))
        rec = manual.get(key) or resolved.get(key)
        if rec and rec.get("name"):
            ev["venueName"] = rec["name"]
            ev["venueNameSource"] = "manual" if key in manual else "osm"
            n += 1
    return n


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
