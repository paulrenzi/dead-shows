"""
Fetch band photos for everything in artists.json + data/gdtb-bands.json.

Source ladder, best first. The first one that yields a usable image wins:

  1. manual    — data/band-photos-manual.json, always beats everything
  2. gdtb      — the band logo gratefuldeadtributebands.com already hosts for
                 the act (data/gdtb-band-links.json). Covers exactly this
                 population of small regional tributes, which is why Deezer
                 alone only ever reached ~27%.
  3. deezer    — strict normalized name match (no key needed)
  4. itunes    — Apple's search API (no key), strong on indie/self-released acts
  5. wikipedia — REST summary thumbnail, for the notable acts (Wolf Bros, JGB)

Generic placeholders are rejected by content hash: any image whose bytes repeat
across 3+ different bands is the source's "no photo" tile, not a band photo.

Output:
  images/bands/{slug}.jpg  — downloaded photo
  data/band-photos.json    — { slug: {photo, source, matchedName?} }
  data/photo-cache.json    — { slug: {tried, matched, probe} } so we don't re-probe daily

Run manually:
  python scripts/fetch_band_photos.py            # incremental
  python scripts/fetch_band_photos.py --refresh  # re-probe everything
"""

import argparse
import hashlib
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
IMG_DIR = ROOT / "images" / "bands"
IMG_DIR.mkdir(parents=True, exist_ok=True)

UA = "dead-shows photo fetcher (paulmichaelrenzi@gmail.com)"

PHOTOS_PATH = DATA / "band-photos.json"
CACHE_PATH = DATA / "photo-cache.json"
MANUAL_PATH = DATA / "band-photos-manual.json"
LINKS_PATH = DATA / "gdtb-band-links.json"

# Bump when the source ladder changes — cached misses probed under an older
# ladder get retried automatically instead of being skipped forever.
PROBE_VERSION = 2

MIN_BYTES = 2000  # smaller than this is a spacer gif, not a photo


def normalize(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def fetch_bytes(url, timeout=20):
    # GDTB serves logos from "/images/Band Logos/..." — a raw space in the path
    # makes urlopen raise InvalidURL, which silently cost us the single best
    # photo source. Encode the path (only) before asking.
    parts = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path)))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url, timeout=20):
    return json.loads(fetch_bytes(url, timeout).decode("utf-8", errors="replace"))


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------- sources


def src_gdtb(name, slug, links):
    entry = links.get(slug) or {}
    url = entry.get("logo")
    return (url, name) if url else (None, None)


def src_deezer(name, slug, links):
    q = urllib.parse.quote(name)
    try:
        d = fetch_json(f"https://api.deezer.com/search/artist?q={q}&limit=5")
    except Exception as e:
        print(f"    deezer ERR: {e}", file=sys.stderr)
        return None, None
    target = normalize(name)
    for a in d.get("data", []):
        if normalize(a.get("name", "")) == target:
            pic = a.get("picture_xl") or a.get("picture_big") or a.get("picture")
            if pic:
                return pic, a.get("name")
    return None, None


def src_itunes(name, slug, links):
    q = urllib.parse.quote(name)
    url = f"https://itunes.apple.com/search?term={q}&entity=musicArtist&limit=5"
    try:
        d = fetch_json(url)
    except Exception as e:
        print(f"    itunes ERR: {e}", file=sys.stderr)
        return None, None
    target = normalize(name)
    for a in d.get("results", []):
        if normalize(a.get("artistName", "")) != target:
            continue
        # musicArtist rows carry no artwork; go back for one of their albums.
        aid = a.get("artistId")
        if not aid:
            continue
        try:
            alb = fetch_json(
                f"https://itunes.apple.com/lookup?id={aid}&entity=album&limit=1"
            )
        except Exception:
            return None, None
        for r in alb.get("results", []):
            art = r.get("artworkUrl100")
            if art:
                return art.replace("100x100bb", "600x600bb"), a.get("artistName")
    return None, None


def src_wikipedia(name, slug, links):
    title = urllib.parse.quote(name.replace(" ", "_"))
    url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
    try:
        d = fetch_json(url)
    except Exception:
        return None, None
    if d.get("type", "").endswith("not_found"):
        return None, None
    # Only accept a page that is actually about a band, not a song of the name
    extract = (d.get("extract") or "").lower()
    if not re.search(r"\b(band|group|ensemble|musician|duo|trio)\b", extract):
        return None, None
    thumb = (d.get("originalimage") or d.get("thumbnail") or {}).get("source")
    return (thumb, d.get("title")) if thumb else (None, None)


SOURCES = [
    ("gdtb", src_gdtb, 0.2),
    ("deezer", src_deezer, 0.6),
    ("itunes", src_itunes, 0.5),
    ("wikipedia", src_wikipedia, 0.3),
]


def collect_bands():
    """Return list of (slug, name). artists.json first, then gdtb-bands.json."""
    out = []
    seen = set()
    a_path = ROOT / "artists.json"
    if a_path.exists():
        for a in load_json(a_path, {"artists": []}).get("artists", []):
            if a["slug"] not in seen:
                out.append((a["slug"], a["name"]))
                seen.add(a["slug"])
    for b in load_json(DATA / "gdtb-bands.json", []):
        if b["slug"] not in seen:
            out.append((b["slug"], b["name"]))
            seen.add(b["slug"])
    return out


def prune_placeholders(photos):
    """Drop any photo whose bytes are shared by 3+ bands — that is the source's
    generic 'no image' tile, and showing it is worse than the Stealie default."""
    digests = {}
    for slug, entry in photos.items():
        p = ROOT / entry["photo"]
        if entry.get("source") == "manual" or not p.exists():
            continue
        digests[slug] = hashlib.sha256(p.read_bytes()).hexdigest()
    counts = Counter(digests.values())
    dropped = []
    for slug, dg in digests.items():
        if counts[dg] >= 3:
            dropped.append(slug)
            (ROOT / photos[slug]["photo"]).unlink(missing_ok=True)
            del photos[slug]
    return dropped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-probe even cached misses")
    ap.add_argument("--only", help="comma-separated slugs to fetch (skip the rest)")
    args = ap.parse_args()

    bands = collect_bands()
    if args.only:
        only = set(args.only.split(","))
        bands = [b for b in bands if b[0] in only]

    photos = load_json(PHOTOS_PATH, {})
    cache = load_json(CACHE_PATH, {})
    manual = load_json(MANUAL_PATH, {})
    links = load_json(LINKS_PATH, {})

    for slug, entry in manual.items():
        if not isinstance(entry, dict) or "photo" not in entry:
            continue
        photos[slug] = {"photo": entry["photo"], "source": "manual"}

    today = date.today().isoformat()
    hits = Counter()
    misses = 0

    for slug, name in bands:
        if slug in manual:
            continue
        if slug in photos and photos[slug].get("source") != "manual":
            if (ROOT / photos[slug]["photo"]).exists():
                continue
        cached = cache.get(slug)
        if (
            not args.refresh
            and cached
            and not cached.get("matched")
            and cached.get("probe", 1) >= PROBE_VERSION
        ):
            continue

        print(f"  {slug} ({name})")
        got = False
        for src_name, fn, delay in SOURCES:
            pic_url, matched_name = fn(name, slug, links)
            time.sleep(delay)
            if not pic_url:
                continue
            try:
                data = fetch_bytes(pic_url)
            except Exception as e:
                print(f"    {src_name} download ERR: {e}", file=sys.stderr)
                continue
            if len(data) < MIN_BYTES:
                continue
            dest = IMG_DIR / f"{slug}.jpg"
            dest.write_bytes(data)
            photos[slug] = {
                "photo": f"images/bands/{slug}.jpg",
                "source": src_name,
                "matchedName": matched_name,
            }
            cache[slug] = {"tried": today, "matched": True, "probe": PROBE_VERSION,
                           "source": src_name, "name": matched_name}
            hits[src_name] += 1
            print(f"    -> {src_name}")
            got = True
            break

        if not got:
            cache[slug] = {"tried": today, "matched": False, "probe": PROBE_VERSION}
            misses += 1

        if (sum(hits.values()) + misses) % 10 == 0:
            save_json(PHOTOS_PATH, photos)
            save_json(CACHE_PATH, cache)

    dropped = prune_placeholders(photos)
    if dropped:
        print(f"\nDropped {len(dropped)} shared-placeholder images: {dropped[:8]}")
        for slug in dropped:
            cache[slug] = {"tried": today, "matched": False, "probe": PROBE_VERSION,
                           "reason": "placeholder"}

    save_json(PHOTOS_PATH, photos)
    save_json(CACHE_PATH, cache)
    # Coverage is over the bands we actually list today — photos left behind by
    # acts that have dropped off the source must not inflate it past 100%.
    current = {s for s, _ in collect_bands()}
    covered = len(current & set(photos))
    print(
        f"\nDone. New: {dict(hits)} ({sum(hits.values())} photos), {misses} misses. "
        f"Coverage: {covered}/{len(current)} = {100 * covered / max(len(current), 1):.0f}% "
        f"({len(set(photos) - current)} stale entries for delisted bands)"
    )


if __name__ == "__main__":
    main()
