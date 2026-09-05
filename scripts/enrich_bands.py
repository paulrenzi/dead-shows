"""
Enrich bands from their own homepages.

data/gdtb-band-links.json gives 263 bands' {url, logo} — url is the band's OWN
site (or, for some, a Facebook page), completely unexploited until now. This
walks each url, fetches the homepage HTML, and extracts:

  - og:image           (absolutised against the page URL)
  - og:description     (falls back to <meta name="description">)
  - social links found anywhere in the page: facebook, instagram, bandcamp,
    spotify, youtube, x/twitter

Many of these are small band sites: some are dead, some time out, some are not
HTML at all (redirects to a PDF, a parked-domain page, etc). All of that is
handled by skipping the entry, not by raising.

Output:
  data/band-info.json   — { slug: {og_image, og_description, socials{}} }
  data/enrich-cache.json — { slug: {tried, ok, probe} } so the daily GitHub
                            Action isn't re-fetching all 263 sites every morning

Run manually:
  python scripts/enrich_bands.py            # incremental
  python scripts/enrich_bands.py --refresh  # re-probe everything
"""

import argparse
import html
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

UA = "dead-shows band enrichment (paulmichaelrenzi@gmail.com)"

LINKS_PATH = DATA / "gdtb-band-links.json"
INFO_PATH = DATA / "band-info.json"
CACHE_PATH = DATA / "enrich-cache.json"

# Bump when the extraction changes so cached misses get retried automatically.
PROBE_VERSION = 1

DELAY = 0.5  # politeness delay between fetches

SOCIAL_DOMAINS = {
    "facebook": r"facebook\.com",
    "instagram": r"instagram\.com",
    "bandcamp": r"bandcamp\.com",
    "spotify": r"spotify\.com",
    "youtube": r"youtube\.com|youtu\.be",
    "x": r"twitter\.com|x\.com",
}


def fetch_bytes(url, timeout=20):
    # A raw space in a URL path makes urlopen raise InvalidURL — the same bug
    # that previously cost fetch_band_photos.py its best photo source.
    parts = urllib.parse.urlsplit(url)
    url = urllib.parse.urlunsplit(parts._replace(path=urllib.parse.quote(parts.path)))
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype.lower() and ctype:
            raise ValueError(f"non-HTML content-type: {ctype}")
        return r.read(), r.geturl()


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def extract_meta(page_html, attr, key, name):
    pattern = re.compile(
        r'<meta[^>]+' + attr + r'=["\']' + re.escape(key) + r'["\'][^>]*>',
        re.IGNORECASE,
    )
    m = pattern.search(page_html)
    if not m:
        return None
    tag = m.group(0)
    cm = re.search(r'content=["\']([^"\']*)["\']', tag, re.IGNORECASE)
    return html.unescape(cm.group(1).strip()) if cm else None


def extract_og_image(page_html, base_url):
    val = extract_meta(page_html, "property", "og:image", None)
    if not val:
        return None
    return urllib.parse.urljoin(base_url, val)


def extract_og_description(page_html):
    val = extract_meta(page_html, "property", "og:description", None)
    if val:
        return val
    return extract_meta(page_html, "name", "description", None)


def extract_socials(page_html):
    socials = {}
    hrefs = re.findall(r'href=["\']([^"\']+)["\']', page_html, re.IGNORECASE)
    for href in hrefs:
        for key, pat in SOCIAL_DOMAINS.items():
            if key in socials:
                continue
            if re.search(pat, href, re.IGNORECASE):
                socials[key] = href
    return socials


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-probe even cached misses")
    args = ap.parse_args()

    links = load_json(LINKS_PATH, {})
    info = load_json(INFO_PATH, {})
    cache = load_json(CACHE_PATH, {})

    today = date.today().isoformat()
    fetched = 0
    responded = 0
    got_image = 0
    got_desc = 0
    got_social = 0

    for slug, entry in links.items():
        url = entry.get("url")
        if not url:
            continue

        cached = cache.get(slug)
        if (
            not args.refresh
            and cached
            and cached.get("probe", 0) >= PROBE_VERSION
        ):
            continue

        print(f"  {slug} ({url})")
        fetched += 1
        try:
            raw, final_url = fetch_bytes(url)
        except Exception as e:
            print(f"    ERR: {e}", file=sys.stderr)
            cache[slug] = {"tried": today, "ok": False, "probe": PROBE_VERSION}
            time.sleep(DELAY)
            continue

        try:
            html = raw.decode("utf-8", errors="replace")
        except Exception:
            html = raw.decode("latin-1", errors="replace")

        responded += 1
        og_image = extract_og_image(html, final_url)
        og_description = extract_og_description(html)
        socials = extract_socials(html)

        if og_image:
            got_image += 1
        if og_description:
            got_desc += 1
        if socials:
            got_social += 1

        record = {}
        if og_image:
            record["og_image"] = og_image
        if og_description:
            record["og_description"] = og_description
        if socials:
            record["socials"] = socials

        if record:
            info[slug] = record
        cache[slug] = {"tried": today, "ok": bool(record), "probe": PROBE_VERSION}

        time.sleep(DELAY)

        if fetched % 20 == 0:
            save_json(INFO_PATH, info)
            save_json(CACHE_PATH, cache)

    save_json(INFO_PATH, info)
    save_json(CACHE_PATH, cache)

    print(
        f"\nDone. Probed: {fetched}, responded: {responded}, "
        f"og:image: {got_image}, og:description: {got_desc}, "
        f"social links: {got_social}. Total enriched: {len(info)}/{len(links)}."
    )


if __name__ == "__main__":
    main()
