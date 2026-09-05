# Session 2026-09-04 — the whole feed, and real band photos

**Live**: https://paulrenzi.github.io/dead-shows/
**Current cache buster**: `?v=17` — bump to `?v=18` when shipping.
**Shipped**: `9d5bcb8`. Verified on the live site, not just locally.

## What was actually wrong

The May handoff's three UX features had all shipped. Nothing was broken in the
deploy — the repo just hadn't had a *code* commit since 2026-05-24, only the
bot's daily data refreshes, which is why the GitHub page looked frozen.

The real problems were measured, not guessed:

| Symptom | Cause | Now |
|---|---|---|
| 18 of 867 shows reachable | default 20 mi / 30 days, and **no control could ask for more** — slider capped at 500 mi | radius top = **Anywhere**; new **All upcoming** chip (2 yr + Anywhere) |
| 4 shows vanished | `isDeadRelated` keyword screen ran over GDTB rows, which are Dead tributes *by construction* | GDTB rows skip the screen |
| 24 shows vanished | dedupe key was band+day+city — a band playing two rooms in one city in one day lost one | key includes venue |
| whole feed could go blank | a Ticketmaster worker error threw, taking all 875 scraped shows with it | TM failure degrades to scraped data + says so in the counter |
| 6 shows dropped per run | geocode miss = `continue` | pinned to state centroid, flagged `approxLocation` |
| photos on 27% of bands | Deezer-only, strict name match — these are small regional acts not on Deezer | source ladder, **90%** |

## The photo win, specifically

GDTB hosts a band logo for nearly every act it lists, plus the band's own site
link and a per-gig event URL. All three were being parsed past and thrown away.
The logo fetch also had a latent bug that made it look like a dead end: the path
is `/images/Band Logos/...` and the raw space makes `urlopen` raise
`InvalidURL`, so it silently returned nothing. One `quote()` on the path turned
the worst source into the best one — 170 of 258 photos now come from it.

Ladder: `manual > gdtb > deezer > itunes > wikipedia`. Cache carries a `probe`
version, so **adding a new source automatically retries every past miss** — no
`--refresh` needed. Images whose exact bytes repeat across 3+ bands are treated
as the source's generic "no photo" tile and dropped.

## Watch-outs

- The scraper now **refuses** to write `gdtb-events.json` if a run returns under
  60% of the previous count (exit 2). If the daily Action starts failing on that
  step, the source is half-down — that is the guard working, not a bug. Old data
  stays live.
- `data/gdtb-band-links.json` is new and the photo fetcher depends on it. Run
  `scrape_gdtb.py` before `fetch_band_photos.py`, which is the Action's order.
- The worker only allows `https://paulrenzi.github.io` as an origin, so local
  dev always exercises the degraded no-Ticketmaster path. That is genuinely
  useful, but don't read "ticketed listings unavailable" locally as an outage.

## Verified

Headless Chromium against the **live** site: default view 19 shows / 16 photos;
**All upcoming → 926 shows, 926 cards, 872 with a real band photo, zero console
errors.**

## Next, if you want it

- 28 bands still have no photo. The remaining lever is the band's own site — we
  now store its URL in `gdtb-band-links.json`; pull `og:image` from it.
- 926 markers is a lot of Leaflet. If mobile drags, cluster them
  (`markercluster`) rather than capping the list — capping would re-open the
  exact thing this session closed.
- `approxLocation` shows are pinned to a state centroid and the card doesn't say
  so yet. Worth a small "approximate location" note.
