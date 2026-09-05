"""
Scrape gratefuldeadtributebands.com for Dead-tribute show data across all 50 states.

Outputs:
  data/gdtb-events.json — array of {id, band, bandSlug, date, time, venue, city, state, lat, lng, url, source}
  data/gdtb-bands.json  — array of {slug, name, source, state} for bands not in artists.json
  data/geocode-cache.json — city,state → {lat, lng} cache (kept across runs, do NOT delete)

Run manually:
  python scripts/scrape_gdtb.py

Polite to both gratefuldeadtributebands.com and Nominatim:
  - 1s delay between state page fetches
  - 1.1s delay between Nominatim geocodes (their policy)
  - Cached geocodes are reused indefinitely (cities don't move)
"""

import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)

STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

UA = "dead-shows scraper (paulmichaelrenzi@gmail.com)"


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("latin-1", errors="replace")


def slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def parse_state_page(html, state):
    """Yield (band, date_str, desc, city) tuples from one state page."""
    text = re.sub(r"<script.*?</script>", "", html, flags=re.S | re.I)
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I)
    for r in rows:
        tds = re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)
        if len(tds) < 4:
            continue
        # td[0]: band cell (has band name + Gig Info link + image)
        # td[1]: date/time
        # td[2]: description (venue + extra text)
        # td[3]: city
        def clean(s):
            s = re.sub(r"<[^>]+>", " ", s)
            s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'").replace("&quot;", '"')
            s = re.sub(r"\s+", " ", s).strip()
            # Strip leading "Gig Info" leftovers
            s = re.sub(r"^Gig Info\s*", "", s)
            return s

        # Extract band name from first td — first text outside any nested link, or first link text
        band_match = re.search(r'<a[^>]*>(?:<[^>]+>)*\s*([^<]+?)\s*</', tds[0])
        band = clean(band_match.group(1)) if band_match else clean(tds[0]).split("Gig Info")[0].strip()
        # Sometimes band cell ends with "Gig Info" before image
        band = re.sub(r"\s*Gig Info\s*$", "", band).strip()

        date_str = clean(tds[1])
        desc = clean(tds[2])
        city = clean(tds[3])

        # The band cell also carries the band's own site/Facebook link, the
        # per-gig "Gig Info" link, and the band logo image. All three were
        # being thrown away — the logo is the best photo source we have and
        # the gig link is the only real per-show URL.
        band_url = None
        gig_url = None
        for href in re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', tds[0]):
            if href.startswith("#") or "addmedia" in href.lower():
                continue
            if "/events/" in href or "gig" in href.lower():
                gig_url = gig_url or href
            elif band_url is None:
                band_url = href
        for onclick in re.findall(r"goPage\(['\"]([^'\"]+)['\"]", tds[0]):
            band_url = band_url or onclick
        logo_m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', tds[0])
        logo = logo_m.group(1) if logo_m else None

        if not (band and date_str and city):
            continue
        # Skip header-ish rows
        if "band" in band.lower() and "date" in date_str.lower():
            continue
        if not re.search(r"[A-Z][a-z]{2}\s+\d{1,2}", date_str):
            continue
        # A city cell that swallowed markup (stray unclosed tag upstream) is
        # not a city — take the band-cell text as junk and skip the row's
        # geocode rather than minting "and The Band <https://..., MD".
        if "http" in city or "<" in city or len(city) > 60:
            city = ""
        yield {
            "band": band, "date_str": date_str, "desc": desc, "city": city,
            "band_url": band_url, "gig_url": gig_url, "logo": logo,
        }


WEEKDAYS = {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def parse_date_time(date_str, today):
    """'Fri May 29 / 7 PM' → ('2026-05-29', '7 PM') with year inferred."""
    parts = date_str.split("/")
    dpart = parts[0].strip()
    tpart = parts[1].strip() if len(parts) > 1 else ""
    tokens = re.split(r"\s+", dpart)
    # Strip optional weekday
    if tokens and tokens[0][:3].lower() in WEEKDAYS:
        tokens = tokens[1:]
    if len(tokens) < 2:
        return (None, None)
    mon = MONTHS.get(tokens[0][:3].lower())
    try:
        day = int(re.sub(r"\D", "", tokens[1]))
    except ValueError:
        return (None, None)
    if not (mon and 1 <= day <= 31):
        return (None, None)
    # Year inference: pick the next future occurrence within 1 year
    for year in (today.year, today.year + 1):
        try:
            d = date(year, mon, day)
        except ValueError:
            continue
        if d >= today - timedelta(days=1):
            return (d.isoformat(), tpart)
    return (None, None)


def extract_venue(desc, city):
    """Try to pull venue name out of the description blob. Falls back to whole desc."""
    # Often the format is "Band ft Guest at Venue Date - Venue City"
    # Easiest robust extract: text after the last " - " is "Venue City"; trim the city off
    if " - " in desc:
        tail = desc.rsplit(" - ", 1)[1]
        # remove city from tail
        if city and tail.lower().endswith(city.lower()):
            tail = tail[: -len(city)].strip()
        if tail:
            return tail
    # Fallback: text before any date number
    head = re.split(r"\d{1,2}/\d{1,2}", desc)[0].strip(" -")
    return head or desc[:80]


def load_cache(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# Fallback pins so a show is never dropped just because Nominatim shrugged at
# its city. Approximate state centroids — good enough to keep the show in the
# feed and on the map at a sane zoom.
STATE_CENTROIDS = {
    "AL": (32.81, -86.79), "AK": (61.37, -152.40), "AZ": (33.73, -111.43),
    "AR": (34.97, -92.37), "CA": (36.12, -119.68), "CO": (39.06, -105.31),
    "CT": (41.60, -72.76), "DE": (39.32, -75.51), "FL": (27.77, -81.69),
    "GA": (33.04, -83.64), "HI": (21.09, -157.50), "ID": (44.24, -114.48),
    "IL": (40.35, -88.99), "IN": (39.85, -86.26), "IA": (42.01, -93.21),
    "KS": (38.53, -96.73), "KY": (37.67, -84.67), "LA": (31.17, -91.87),
    "ME": (44.69, -69.38), "MD": (39.06, -76.80), "MA": (42.23, -71.53),
    "MI": (43.33, -84.54), "MN": (45.69, -93.90), "MS": (32.74, -89.68),
    "MO": (38.46, -92.29), "MT": (46.92, -110.45), "NE": (41.13, -98.27),
    "NV": (38.31, -117.06), "NH": (43.45, -71.56), "NJ": (40.30, -74.52),
    "NM": (34.84, -106.25), "NY": (42.17, -74.95), "NC": (35.63, -79.81),
    "ND": (47.53, -99.78), "OH": (40.39, -82.76), "OK": (35.57, -96.93),
    "OR": (44.57, -122.07), "PA": (40.59, -77.21), "RI": (41.68, -71.51),
    "SC": (33.86, -80.95), "SD": (44.30, -99.44), "TN": (35.75, -86.69),
    "TX": (31.05, -97.56), "UT": (40.15, -111.86), "VT": (44.05, -72.71),
    "VA": (37.77, -78.17), "WA": (47.40, -121.49), "WV": (38.49, -80.95),
    "WI": (44.27, -89.62), "WY": (42.76, -107.30),
}


def geocode_city(city, state, cache):
    key = f"{city.lower()}, {state.lower()}"
    if key in cache:
        return cache[key]
    q = f"{city}, {state}, USA"
    url = f"https://nominatim.openstreetmap.org/search?format=json&limit=1&q={urllib.parse.quote(q)}"
    try:
        raw = fetch(url, timeout=15)
        arr = json.loads(raw)
        if arr:
            cache[key] = {"lat": float(arr[0]["lat"]), "lng": float(arr[0]["lon"])}
        else:
            cache[key] = None
    except Exception as e:
        print(f"  geocode FAIL {q}: {e}", file=sys.stderr)
        cache[key] = None
    time.sleep(1.1)  # Nominatim policy
    return cache[key]


def main():
    cache_path = DATA / "geocode-cache.json"
    geocache = load_cache(cache_path)

    # Load curated artist slugs for cross-reference
    artists_path = ROOT / "artists.json"
    curated_slugs = set()
    curated_by_lower_name = {}
    if artists_path.exists():
        adata = json.loads(artists_path.read_text(encoding="utf-8"))
        for a in adata.get("artists", []):
            curated_slugs.add(a["slug"])
            curated_by_lower_name[a["name"].lower()] = a["slug"]
            curated_by_lower_name[a["searchKeyword"].lower()] = a["slug"]

    today = date.today()
    all_shows = []
    discovered_bands = {}
    band_links = {}
    dropped = {"no_date": 0, "no_geo": 0}

    for st in STATES:
        url = f"http://www.gratefuldeadtributebands.com/showBandData.php?state={st}"
        try:
            html = fetch(url)
        except Exception as e:
            print(f"FETCH FAIL {st}: {e}", file=sys.stderr)
            continue
        count = 0
        approx = 0
        for row in parse_state_page(html, st):
            band, date_str, desc, city = row["band"], row["date_str"], row["desc"], row["city"]
            iso, t = parse_date_time(date_str, today)
            if not iso:
                dropped["no_date"] += 1
                continue
            venue = extract_venue(desc, city)
            geo = geocode_city(city, st, geocache) if city else None
            approximate = False
            if not geo:
                # Never drop a show over a geocode miss — pin it to the state
                # and mark it so the UI can say the location is approximate.
                cen = STATE_CENTROIDS.get(st)
                if not cen:
                    dropped["no_geo"] += 1
                    continue
                geo = {"lat": cen[0], "lng": cen[1]}
                approximate = True
                approx += 1
            slug = curated_by_lower_name.get(band.lower()) or slugify(band)
            if slug not in curated_slugs:
                discovered_bands.setdefault(slug, {
                    "slug": slug,
                    "name": band,
                    "source": "gratefuldeadtributebands.com",
                    "state": st,
                })
            if row.get("band_url"):
                band_links.setdefault(slug, {})["url"] = row["band_url"]
            if row.get("logo"):
                band_links.setdefault(slug, {})["logo"] = (
                    urllib.parse.urljoin("http://www.gratefuldeadtributebands.com/", row["logo"])
                )
            show_id = f"gdtb-{st}-{slug}-{iso}-{slugify(venue)[:30]}"
            all_shows.append({
                "id": show_id,
                "name": band + (f" — {venue}" if venue else ""),
                "band": band,
                "bandSlug": slug,
                "venue": venue,
                "city": city,
                "state": st,
                "lat": geo["lat"],
                "lng": geo["lng"],
                "approxLocation": approximate,
                "date": iso,
                "time": t,
                "url": row.get("gig_url") or url,
                "listingUrl": url,
                "bandUrl": row.get("band_url"),
                "source": "gdtb",
                "attractions": [band],
            })
            count += 1
        # Save cache progressively so a crash doesn't lose geocodes
        save_json(cache_path, geocache)
        print(f"  {st}: {count} shows" + (f" ({approx} approx-located)" if approx else ""))
        time.sleep(1)  # polite to gratefuldeadtributebands.com

    # A scrape that half-failed (site down mid-run, network flap) must not
    # quietly commit a shrunken feed over a good one. Refuse below 60% of the
    # previous run and leave the existing data in place.
    events_path = DATA / "gdtb-events.json"
    prev = load_cache(events_path) if events_path.exists() else []
    if isinstance(prev, list) and len(prev) and len(all_shows) < 0.6 * len(prev):
        print(
            f"REFUSING to write: scraped {len(all_shows)} shows vs {len(prev)} previously "
            f"({len(all_shows) / len(prev):.0%}). Source likely partial — keeping old data.",
            file=sys.stderr,
        )
        return 2

    save_json(events_path, all_shows)
    save_json(DATA / "gdtb-bands.json", list(discovered_bands.values()))
    save_json(DATA / "gdtb-band-links.json", band_links)
    save_json(cache_path, geocache)
    print(
        f"\nDone. {len(all_shows)} shows, {len(discovered_bands)} new bands, "
        f"{len(band_links)} band links/logos. Dropped: {dropped}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
