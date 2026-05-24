"""
Fetch band photos for everything in artists.json + data/gdtb-bands.json.

Strategy: Deezer artist search (free, no key). Require strict name-match
(normalized: lowercase, alnum-only) to avoid garbage hits like "Easy Jim" →
"Easykid" or "Jim Brickman". Manual overrides in data/band-photos-manual.json
beat everything.

Output:
  images/bands/{slug}.jpg  — downloaded photo (1000x1000 jpeg from Deezer)
  data/band-photos.json    — { slug: {photo: "images/bands/{slug}.jpg", source: "deezer"|"manual"} }
  data/photo-cache.json    — { slug: {tried: ISO, matched: bool, name?: str} } so we don't re-probe daily

Run manually:
  python scripts/fetch_band_photos.py            # incremental: skip already-tried
  python scripts/fetch_band_photos.py --refresh  # re-probe all (use sparingly)
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
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


def normalize(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def fetch_bytes(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def fetch_json(url, timeout=20):
    return json.loads(fetch_bytes(url, timeout).decode("utf-8"))


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def deezer_search(name):
    """Return picture URL if a strict-name-match artist exists on Deezer, else None."""
    q = urllib.parse.quote(name)
    url = f"https://api.deezer.com/search/artist?q={q}&limit=3"
    try:
        d = fetch_json(url)
    except Exception as e:
        print(f"    deezer ERR: {e}", file=sys.stderr)
        return None, None
    n_target = normalize(name)
    for a in d.get("data", []):
        if normalize(a.get("name", "")) == n_target:
            pic = a.get("picture_xl") or a.get("picture_big") or a.get("picture")
            return pic, a.get("name")
    return None, None


def download_photo(url, dest):
    data = fetch_bytes(url)
    if len(data) < 500:
        return False
    dest.write_bytes(data)
    return True


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
    g_path = DATA / "gdtb-bands.json"
    for b in load_json(g_path, []):
        if b["slug"] not in seen:
            out.append((b["slug"], b["name"]))
            seen.add(b["slug"])
    return out


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

    # Manual overrides always win
    for slug, entry in manual.items():
        photos[slug] = {"photo": entry["photo"], "source": "manual"}

    today = date.today().isoformat()
    new_hits = 0
    new_misses = 0

    for slug, name in bands:
        # Skip if manual override exists
        if slug in manual:
            continue
        # Skip if we already have a downloaded photo and it still exists
        if slug in photos and photos[slug].get("source") == "deezer":
            existing = ROOT / photos[slug]["photo"]
            if existing.exists():
                continue
        # Skip cached miss unless refreshing
        if not args.refresh and slug in cache and not cache[slug].get("matched"):
            continue

        print(f"  {slug} ({name})")
        pic_url, matched_name = deezer_search(name)
        time.sleep(0.6)  # polite to Deezer

        if not pic_url:
            cache[slug] = {"tried": today, "matched": False}
            new_misses += 1
            continue

        dest = IMG_DIR / f"{slug}.jpg"
        try:
            ok = download_photo(pic_url, dest)
        except Exception as e:
            print(f"    download ERR: {e}", file=sys.stderr)
            cache[slug] = {"tried": today, "matched": False}
            continue

        if not ok:
            cache[slug] = {"tried": today, "matched": False}
            continue

        photos[slug] = {
            "photo": f"images/bands/{slug}.jpg",
            "source": "deezer",
            "matchedName": matched_name,
        }
        cache[slug] = {"tried": today, "matched": True, "name": matched_name}
        new_hits += 1

        # Save incrementally so crashes don't lose progress
        if (new_hits + new_misses) % 10 == 0:
            save_json(PHOTOS_PATH, photos)
            save_json(CACHE_PATH, cache)

    save_json(PHOTOS_PATH, photos)
    save_json(CACHE_PATH, cache)
    print(f"\nDone. {new_hits} new photos, {new_misses} new misses. Total cataloged: {len(photos)}")


if __name__ == "__main__":
    main()
