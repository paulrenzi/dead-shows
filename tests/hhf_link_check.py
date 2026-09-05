"""Open every happy-hour link this site emits, on the real board, and prove it lands.

The links are built here but rendered by Happy Hour Finder, so nothing in this
repo can tell you whether one works. Every previous failure was invisible from
this side: `#v=<lid>` with no zone resolved to nothing and dropped the reader on
the default board, and the "sorted by distance" link is a coordinate the OTHER
site has to read, validate and act on.

By default the check runs against a LOCAL happy-hour-finder checkout, served
through Playwright's router -- deterministic, and it tests the code about to
ship rather than whatever is deployed. `--live` runs the same assertions against
the published board, which is the one that answers "is it working right now".

  python tests/hhf_link_check.py [--hhf PATH] [--live]

Skips if the browser is not installed.
"""

import json
import mimetypes
import os
import sys
from urllib.parse import parse_qs, urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LINKS = os.path.join(ROOT, "data", "hhf-links.json")
LIVE = "https://paulrenzi.github.io/happy-hour-finder/"
BASE = "https://hhf.test/"


def main(argv):
    live = "--live" in argv
    hhf = os.path.join(os.path.dirname(ROOT), "happy-hour-finder")
    if "--hhf" in argv:
        hhf = argv[argv.index("--hhf") + 1]
    web = os.path.join(hhf, "web")
    if not live and not os.path.isdir(web):
        print(f"  (skipped: no happy-hour-finder checkout at {hhf})")
        return 0

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  (skipped: playwright not installed)")
        return 0

    links = json.load(open(LINKS, encoding="utf-8"))["links"]
    # One link per distinct URL: two shows at the same venue produce the same
    # link, and opening it twice proves nothing twice.
    seen, cases = set(), []
    for block in links.values():
        if block["url"] not in seen:
            seen.add(block["url"])
            cases.append(block)

    failures, checked = [], 0

    with sync_playwright() as pw:
        try:
            browser = pw.webkit.launch()
        except Exception as exc:
            print(f"  (skipped: webkit not installed -- {str(exc).splitlines()[0]})")
            return 0

        def serve(route):
            rel = route.request.url[len(BASE):].split("?")[0] or "index.html"
            path = os.path.join(web, *rel.split("/"))
            if not os.path.isfile(path):
                return route.fulfill(status=404, body="not found")
            ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
            if path.endswith(".js"):
                ctype = "text/javascript"
            route.fulfill(status=200, content_type=ctype,
                          body=open(path, "rb").read())

        for block in cases:
            url = block["url"]
            frag = url.split("/#", 1)[1] if "/#" in url else ""
            q = parse_qs(frag)

            # A FRESH page per link. The board reads its hash once, at boot --
            # there is no hashchange listener -- so goto()-ing between hashes on
            # one page is a same-document navigation and every result after the
            # first describes the FIRST link. That is not a hypothetical: it
            # produced 12 of 15 false failures the first time this was checked.
            page = browser.new_page(viewport={"width": 390, "height": 844})
            errs = []
            page.on("pageerror", lambda e: errs.append(str(e)))
            # The board fetches its live overlays from the submit Worker, on
            # another origin. In a sandboxed browser check that is refused by
            # CORS and surfaces as a page error on EVERY link -- a whole run of
            # false failures that says nothing about the links. Stub both, even
            # in --live mode: the overlays are not what this check is about,
            # and their two `venues` keys are different shapes (a list here, a
            # map there), so one body for both throws "{} is not iterable".
            page.route("**/live/deals.json", lambda r: r.fulfill(
                status=200, content_type="application/json",
                headers={"access-control-allow-origin": "*"},
                body='{"venues":[]}'))
            page.route("**/live/events.json", lambda r: r.fulfill(
                status=200, content_type="application/json",
                headers={"access-control-allow-origin": "*"},
                body='{"venues":{}}'))
            if live:
                page.goto(LIVE + ("#" + frag if frag else ""), wait_until="load")
            else:
                page.route(BASE + "**", serve)
                page.goto(BASE + ("#" + frag if frag else ""), wait_until="load")
            page.wait_for_timeout(4000)

            def bad(msg):
                failures.append(f"{block['name']}: {msg}\n      {url}")

            if errs:
                bad(f"page errors: {errs[:2]}")

            cards = page.eval_on_selector_all("#feed .card", "c => c.length")
            if not cards:
                bad("the board painted no cards at all")

            # The zone actually opened, not just the one we asked for.
            if q.get("z"):
                picked = page.eval_on_selector("#zone", "s => s.value")
                if picked != q["z"][0]:
                    bad(f"landed on zone {picked!r}, link asked for {q['z'][0]!r}")

            if q.get("near"):
                head = page.text_content("#sectionHeadline") or ""
                want = q.get("from", [""])[0]
                if want and want not in head:
                    bad(f"headline {head!r} does not name the origin {want!r}")
                if "near you" in head.lower():
                    bad(f"headline still says 'near you': {head!r} -- the "
                        "distances are from the show venue, not the reader")
                if page.eval_on_selector("#sort", "s => s.value") != "nearest":
                    bad("the sort control does not read 'Nearest'")
                # Ascending WITHIN each band: a bar that is open now outranks a
                # nearer one that is shut, in every sort.
                rows = page.evaluate(
                    """() => {
                         const out = []; let sec = null;
                         for (const n of document.querySelectorAll('#feed > *')) {
                           if (n.classList.contains('sec')) { sec = n.textContent; continue; }
                           if (!n.classList.contains('card')) continue;
                           const t = n.textContent || '';
                           const m = t.match(/(\\d+(?:\\.\\d+)?)\\s*mi\\b/);
                           const mi = m ? Number(m[1]) : (/\\bhere\\b/.test(t) ? 0 : null);
                           if (mi !== null) out.push([sec, mi]);
                         }
                         return out;
                       }""")
                bands = {}
                for sec, mi in rows:
                    bands.setdefault(sec, []).append(mi)
                for sec, mi in bands.items():
                    if mi != sorted(mi):
                        bad(f"{sec!r} is not in ascending distance: {mi[:8]}")
                if not rows:
                    bad("no card carried a distance, so nothing was sorted")

            # A venue deep-link has to actually open that venue's sheet.
            if q.get("v"):
                # A <dialog> is in the DOM whether it is open or not, so
                # reading `hidden` or `display` on #sheet says "closed" always.
                # `.open` is the only honest reading.
                opened = page.evaluate(
                    "() => { const d = document.querySelector('#sheet');"
                    "  return d && d.open"
                    "    ? ((d.querySelector('h3') || {}).textContent || '')"
                    "    : null; }")
                if opened is None:
                    bad("the venue sheet did not open")
                elif block["name"] and block["name"] not in opened:
                    bad(f"the sheet opened on {opened!r}, not {block['name']!r}")

            page.close()
            checked += 1

        browser.close()

    where = "live" if live else "local checkout"
    if failures:
        print(f"hhf_link_check FAILED ({where}) — {len(failures)} of {checked}")
        for f in failures:
            print("  - " + f)
        return 1
    near = sum(1 for b in cases if "near=" in b["url"])
    print(f"hhf_link_check ok ({where}): {checked} links open, "
          f"{near} sort the board around the show venue")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
