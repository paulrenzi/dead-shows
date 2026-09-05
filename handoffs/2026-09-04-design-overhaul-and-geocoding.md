# Handoff — 2026-09-04 — design overhaul, band enrichment, geocode cache fix

Live and verified: https://paulrenzi.github.io/dead-shows/ · master @ `e49d883`

**Next session's goal: redesign this site with the Claude design tool (DesignSync) and make it
genuinely beautiful. Read "For next session" at the bottom first — there is a prerequisite that
must be done from an interactive session.**

---

## What shipped this session

### Design (done directly in the site files, not via DesignSync — see the blocker)
- **Marker clustering** (Leaflet.markercluster 1.5.3 from unpkg). The map carried 926 individual
  markers, which made it unusable on a phone. Clustered rather than capping the list, so the full
  feed the previous session opened stays open. Cluster size classes `sm`/`md`/`lg` at 10/60.
- **Stealie-palette pins** — red `--pin-core` (Dead family), blue `--pin-tribute`; a pulsing
  center marker for King of Prussia.
- **Card hover → pin flash.** Hovering a card flashes its pin, or its *enclosing cluster* when the
  pin is collapsed. 🛑 A clustered marker has **no DOM element** and `openPopup()` on one is a
  **silent no-op** — that is why "Show on map" wraps its `setView`/`openPopup` in
  `revealMarker(marker, cb)` (`getVisibleParent` + `zoomToShowLayer`). Do not simplify this away.
- **Full dark theme** via `prefers-color-scheme` token redefinition, `.sr-only`, skeleton loading
  cards replacing the old spinner, and a `prefers-reduced-motion` block.
- **Logo-aware card media.** `object-fit: cover` on a 16:10 card was lopping the top and bottom off
  square wordmarks. `.card-media--logo` uses `contain` on a plate blurred from the image's own
  colours, hover-zoom off.
- **Approximate-distance disclosure.** `PRECISION_NOTES` in `app.js` renders the distance pill as
  `distance--approx` (dashed border, asterisk, `title` tooltip) when `ev.locationPrecision` is
  `city` or `state`. Closes the last open item from the previous handoff. Degrades cleanly when the
  field is absent — which it currently is; see "Unfinished" below.

### 🛑 The basemap must stay keyless OSM
I switched to `basemaps.cartocdn.com` light/dark and the dark screenshot showed **every tile
watermarked "API KEY REQUIRED"**. Hosted "muted" basemaps now want a key. Reverted to
`tile.openstreetmap.org` and recoloured with a CSS `filter` on `.map .leaflet-tile-pane` **only** —
filtering the whole `.map` drags pins, popups and controls through it too.

```css
.map .leaflet-tile-pane { filter: saturate(0.32) brightness(1.06) contrast(0.92); }
@media (prefers-color-scheme: dark) {
  .map .leaflet-tile-pane { filter: invert(1) hue-rotate(185deg) saturate(0.32) brightness(0.92) contrast(0.9); }
}
```

### Band enrichment
`scripts/enrich_bands.py` (new) walks each band's homepage from `data/gdtb-band-links.json` and
extracts `og_image`, `og_description` and socials into `data/band-info.json`, probe-version cached
in `data/enrich-cache.json`.
- **232 entries — 213 og:image, 221 og:description, 230 socials.**
- `band.js` no longer gives all 247 tribute acts the identical blurb; it prefers `og_description`,
  links the real website, and pushes real socials, with Spotify/YouTube *search* links only as
  fallbacks.
- `fetch_band_photos.py` gained a `src_bandsite` rung reading `og_image`, inserted after `gdtb`;
  `PROBE_VERSION` 2 → 3 so past misses re-probe.
- Photo coverage **90% → 92% (262/286)**. Honest and modest: the og:image lever mostly missed
  because the photo-less bands largely lack og:image too. 3 shared-placeholder images were
  correctly dropped.

### 🚨 The geocode cache was poisoning itself — fixed
`_nominatim_lookup` cached `None` on **any** exception. Nominatim started returning **HTTP 429**
(two agents hammering it concurrently) and every transient failure was written as
*"this place does not exist"*, indistinguishable from a genuine miss and never retried.
**425 of 608 venue keys and 31 city keys were poisoned** — those venues would have sat on a city
centroid forever.

Fixed: the lookup now caches **only a definitive answer**, backs off 20/40/60s on a 429, and leaves
anything unresolved **out** of the cache so the next run retries it. Purged all 456 nulls
(2012 → 1556 entries, 183 genuine venue hits surviving). The scraper saves the cache **per state**,
so a killed run keeps its progress.

> 🔑 General rule worth carrying: **never cache a negative you cannot distinguish from a failure.**

---

## Unfinished — venue-level geocoding

`scripts/scrape_gdtb.py` has the new `geocode_venue` / `haversine_miles` / `geocode_city`, writes
`locationPrecision` per row, carries `firstSeen` forward, and appends vanished ids to
`data/gdtb-archive.json`. **None of that has run to completion yet.**

State right now:
- `data/gdtb-events.json` is still the **old 875-row file**; `locationPrecision` is on **0 rows**.
- `data/gdtb-archive.json` **does not exist yet**.
- Geocode cache: **1655 entries, 281 venue-keyed** (up from 183 — the run did make progress before
  it was killed at a session boundary, and that progress is committed).

**This finishes itself.** The daily Action (`.github/workflows/refresh-data.yml`, 09:15 UTC) runs
the scraper; cached venues are skipped and unresolved ones retry, so precision improves over
successive days. Nothing is broken in the meantime — the front end handles a missing
`locationPrecision` by simply not showing the asterisk.

**One real issue to watch:** some GDTB `venue` values are already full addresses, producing queries
like `118 North Wayne Avenue Wayne PA United States Pennsylvania 19087, Wayne, PA, USA`. The
30-mile sanity gate rejects bad matches from these (so it degrades to the city pin rather than
landing somewhere wrong), but it caps the resolve rate. Normalising the venue string before
querying is the obvious next improvement.

**Numbers still owed** once a full run lands: total events vs 875 with the shrinkage guard not
tripping; distinct venues vs distinct coordinates (was 672/480); the full `locationPrecision`
breakdown; `firstSeen` row count; whether the archive file was created; and 5 named well-known
venues spot-checked against their real addresses.

## Bandsintown — NO-GO, killed at the probe
`rest.bandsintown.com` returns **403 from AWS API Gateway** for any non-allowlisted `app_id` — an
infrastructure deny, not an invalid key. The legacy v2 host no longer resolves. Their ToS scopes
each key to a single self-managed artist. Do not re-litigate this without new information.

---

## Verification (the standing rule: a page is verified by RUNNING it, never by an HTTP 200)

Live, headless Chromium, **both** colour schemes, after the Pages deploy completed:

| | dark | light |
|---|---|---|
| cards | 924 | 919 |
| clusters | 8 | 8 |
| center pin | 1 | 1 |
| css | `styles.css?v=18` | `styles.css?v=18` |
| body bg | `rgb(16,13,18)` | `rgb(247,243,235)` |
| flash on hover | 1 | 1 |
| **console errors** | **0** | **0** |

Scripts live in the session scratchpad: `live_check.py` (live), `render_check.py` (local),
`map_shot.py`, `band_check.py`.

> ⚠️ **Locally you will always see exactly 4 console errors and no Ticketmaster shows.** The
> Cloudflare Worker is CORS-locked to the GitHub Pages origin, so local dev always exercises the
> degraded path. **That is expected, not an outage.** Live gets ~924 shows vs ~863 locally.
>
> ⚠️ Bump the `?v=` cache-buster in **`index.html` AND `band.html`** together. `band.html` sat at
> `v=17` this session and would have served stale CSS, leaving that whole page unthemed.

---

## For next session — redesign with the Claude design tool

🛑 **Prerequisite, must be done first, from an interactive Claude Code session:** run
**`/design-login`**. DesignSync `list_projects` currently fails with a design-system authorization
error and the OAuth flow **cannot run in a non-interactive session**. That is why this session's
design work was done by hand instead. Until that login happens, the tool is unavailable and the
session will just repeat the same pivot.

*(Also unauthorized, unrelated: the Gmail / Google Calendar / Google Drive MCP connectors need
authorizing in claude.ai connector settings.)*

**Design debt worth attacking, visible in `live-dark.png`:**
1. The **default-photo tile reads as an empty black rectangle** in dark mode — the fallback SVG
   nearly vanishes against the card. ~24 bands have no photo, so this is common.
2. **"All upcoming" fits map bounds so wide the view lands on Central America** (Seattle + Hawaii
   shows drag the box). Bounds should probably be weighted to the radius or clamped to CONUS.
3. The map is a squat letterbox between the filter bar and the cards — it reads as an afterthought
   rather than the centrepiece it should be.
4. Card grid, typography scale, and the filter bar are functional but plain. This is where a real
   design pass earns the most.

**Constraints any redesign must respect:** vanilla JS, no framework, no build step, GitHub Pages
static hosting, Leaflet + markercluster, keyless OSM tiles, and the CORS-locked Worker.

## Files touched
`app.js`, `index.html`, `band.html`, `band.js`, `styles.css` (781 → ~990 lines),
`scripts/scrape_gdtb.py`, `scripts/fetch_band_photos.py`, `scripts/enrich_bands.py` (new),
`data/band-info.json` (new), `data/enrich-cache.json` (new), `data/geocode-cache.json`,
`data/band-photos.json`, `data/photo-cache.json`, 4 new band images.

## Process note
Both Sonnet subagents repeatedly **parked themselves** ("waiting for the background task to
finish") and nothing wakes a parked subagent. Both had to be `TaskStop`ped and their work finished
by hand. Their concurrent Nominatim calls are also what triggered the 429 storm that poisoned the
cache. If delegating pipeline work again: **forbid `run_in_background`, `Monitor`, and nested
subagents explicitly, and never run two geocoding jobs at once.**
