# Handoff — 2026-09-05 — map-first redesign, day-grouped feed, per-band plates

Live and verified: https://paulrenzi.github.io/dead-shows/ · master @ `a23d13c` · CSS/JS at `?v=19`

---

## 🛑 DesignSync is STILL unavailable — `/design-login` did not take

The previous handoff named `/design-login` as the prerequisite. Paul ran it, but
`DesignSync list_projects` in this session still returns:

> DesignSync needs design-system authorization, and /design-login cannot run in this
> non-interactive session.

So the tool was **not** used, again. **Do not open the next session by re-running
`/design-login` and hoping** — that is now two sessions lost to the same pivot.
Either establish first, in an interactive session, that `list_projects` actually
returns a project list, or plan the work as a hand redesign from the start. The
design work below was done by hand, which turned out fine: the constraints
(vanilla JS, no build step, Pages, keyless OSM tiles, CORS-locked Worker) are all
intact and nothing was added to the dependency list.

*(Gmail / Google Calendar / Google Drive MCP connectors also still need authorizing
in claude.ai connector settings. Unrelated to this work.)*

---

## What shipped — the four items of design debt, all four closed

### 1. The photo-less tile (was an empty black rectangle in dark mode)
~24 acts have no photo and shared one stealie SVG. In dark mode it nearly vanished
against the card, and the same rectangle repeated down the grid.

Each band now gets **a plate of its own**: a monogram over a gradient chosen by a
hash of the band's name from a **fixed six-colour poster palette** (`PLATE_PALETTE`
in `app.js`, mirrored in `band.js`). Fixed palette, not a free hue rotation, so
every plate still belongs to the same set.

> 🔑 `data/band-photos.json` pins **`deal`** literally at `images/default-band.svg`.
> That is the absence of a photo wearing a photo's clothes — any path ending
> `default-band.svg` is now read as *no photo*. That one entry was four identical
> tiles in a 21-card view.

The plate sits **under** the image rather than replacing it, so (a) a URL that 404s
reveals the band's own plate instead of a broken tile, and (b) a lazy image loads
over its own placeholder. `images/default-band.svg` is still used for the band-page
portrait at 220px, where it reads fine.

### 2. "All upcoming" landed on Central America
`fitBounds` over every marker spans Seattle→Honolulu→Maine, ~90° of longitude. In a
portrait column Leaflet answers that aspect ratio by zooming out until the centre
sits over Central America.

`fitToResults()` now:
- fits the **search ring** when the radius is finite (stable — one distant show
  dropping in no longer lurches the view), and
- clamps to a **mainland box** when the radius is "Anywhere", falling back to the
  honest fit if everything lands outside it.

> 🔑 Clamping alone was not enough. A landscape country in a portrait frame is
> **width-constrained**, so a plain fit left the US as a thin band between two empty
> oceans (zoom 3, Greenland to Peru). It now allows **exactly one zoom step of
> east–west crop** to buy that vertical space back, never cropping past the point
> where the latitude band itself stops fitting. Result: zoom 4, whole country.

Measured live, "All upcoming": centre **36.37N, −96.74W** (Oklahoma), zoom **4**,
bounds −124.5→−68.9. Was Central America.

### 3. The map was a squat letterbox — it is now the page
A **two-column split**: results left, map right, `position: sticky` under the filter
strip for the whole scroll, with a Dead-family / Tribute / You legend beneath it.
Height is `calc(100vh - var(--strip-h) - 5.5rem)` — **`--strip-h` is published by
`syncStripHeight()` in `app.js`** from the strip's measured height, because the
strip wraps at narrow widths and CSS cannot guess it. A `ResizeObserver` on `#map`
calls `map.invalidateSize()`.

Below 1024px the columns stack and the map goes on top at 46vh. `scrollMapIntoView()`
is now a no-op when the map is already on screen — in the split layout scrolling the
page would throw away the reader's place for nothing.

🛑 The split is scoped to `.shell--split` (index only). **`band.html` shares
`.shell`, `.map`, `.cards` and `.event-card`** and deliberately keeps the stacked
380px map.

### 4. Card grid, typography, filter bar
- **The list is grouped by day** with sticky date headings ("Tonight", "Tomorrow",
  "Friday, September 4") and a count per day. 92 groups over the full feed.
- **Cards are rows, not tiles.** The per-card date collapses to a time (the heading
  carries the date), venue and city share a line, and the pills and the actions
  share the foot. "Show on map" became an icon button beside calendar and share.
- The four date presets are **one segmented control** instead of four loose buttons.
- Strip and hero now share the results' measure (`--shell-w`), inputs tightened.

---

## Two real bugs found while verifying

### 🚨 The dark-mode component overrides never applied
The `@media (prefers-color-scheme: dark)` block sits at the **top** of `styles.css`.
Its `:root` token redefinitions won (specificity of `:root` beats nothing), but its
**component** rules — `.meta-pill.distance`, `.tier-core`, `.price`, `.card-date`,
`.toast`, `.map` — lost to the **equal-specificity light rules further down the
file**. Dark mode has been painting light-mode `#1d3f80` blue on the distance pill
against a dark card the whole time.

> 🔑 **A dark block placed above the components it overrides does not override them.**
> Those colours are **tokens** now (`--pill-dist-fg`, `--pill-core-bg`, `--toast-bg`,
> `--map-ground`, …) and the dark block redefines **only `:root`**. Confirmed live:
> the distance pill computes `rgb(198,215,255)` in dark and `rgb(29,63,128)` in light.

Light mode also had a red "Dead family" pill painted with **blue** text
(`--accent-deep`); it is `--dead-red-deep` now.

### 🚨 The card clipped its own calendar popover
`.event-card` had `overflow: hidden`, and `.card-cal-menu` opens **upward**
(`bottom: calc(100% + 6px)`). On a tall tile it was merely cut; on a short row card
it would have been invisible. The **media** clips now (rounded left corners), the
card does not. Verified the popover measures 110×76 on screen.

### And one layout trap worth remembering
> 🔑 **In a row card the media is a grid column with no height of its own, so an
> `<img>` in normal flow contributes its INTRINSIC height.** One tall portrait
> wordmark (Andy Coe Band) stretched its row to 320px against neighbours at 132px.
> `.card-media img` is `position: absolute; inset: 0` — out of flow, so the body
> alone decides how tall a row is. Card heights went from 132–320 to 132 (151 when a
> long venue wraps).

---

## Verification — the page was RUN, in both schemes, never an HTTP 200

Live, headless Chromium, after the Pages deploy completed
(run `33943220155`, success):

| | dark | light |
|---|---|---|
| cards (next30, 20mi) | 19 | 19 |
| clusters | 6 | 6 |
| centre pin | 1 | 1 |
| photo-less tiles left | **0** | **0** |
| css | `styles.css?v=19` | `styles.css?v=19` |
| body bg | `rgb(16,13,18)` | `rgb(247,243,235)` |
| **console errors** | **0** | **0** |
| **failed requests** | **0** | **0** |

Live, all four date chips clicked in turn, resting map state read each time:

| chip | cards | day groups | centre | zoom |
|---|---|---|---|---|
| Tonight | 4 | 2 | 40.09, −75.40 | 10 |
| This Weekend | 5 | 3 | 40.09, −75.40 | 10 |
| Next 30 days | 19 | 11 | 40.09, −75.40 | 10 |
| **All upcoming** | **925** | **92** | **36.37, −96.74** | **4** |

The full feed is intact — 925 live, against ~924 last session.

Live `band.html?id=splintered-sunlight`, both schemes: 8 cards, `?v=19`, 0 errors,
distance pill `rgb(198,215,255)` dark / `rgb(29,63,128)` light.

Interactions (local): card hover flashes its pin (or its cluster) — 1; show-on-map
zooms 10 → 11 and opens a popup on a **clustered** marker; calendar popover visible
at 110×76; no horizontal overflow at 390px; 0 page errors throughout.

> ⚠️ Unchanged from last session: **locally you always get console errors and no
> Ticketmaster shows** — the Worker is CORS-locked to the Pages origin, so local dev
> always exercises the degraded path. Local sees 863 shows on "All upcoming", live
> sees 925. That is expected, not an outage.
>
> ⚠️ The `?v=` cache-buster was bumped in **`index.html` and `band.html` together**
> (18 → 19), plus `app.js`/`band.js`. Keep doing both.

Scripts in the session scratchpad: `render_check.py` (`--live` flag), `chips_check.py`,
`interact_check.py`, `zoom.py`.

---

## Not touched, but seen — worth a look

1. **`band.js` fails the whole page if Ticketmaster fails.** `loadEvents` awaits
   `Promise.all([tmRes, gdtbEvs])`, so a TM rejection takes the GDTB shows down with
   it and the page renders "Couldn't load shows." Pre-existing; it is exactly what
   local dev shows every time. `index.html` degrades properly (`tmFeedFailed`);
   `band.html` does not. Settling for `Promise.allSettled` would fix it.
2. **A duplicate slipped the dedupe.** "Blue Drew and the Magoos", Bristol RI, same
   night, appears twice — `8:00 PM` / `1 State St.` and `8:00PM` / `1 State Street`.
   The dedupe key normalises the venue to 20 chars of `[a-z0-9]`, which makes
   `1statest` ≠ `1statestreet`.
3. **Zendog's photo is not the band.** It is a "ZEN DOG — white noise to calm your
   pet" thumbnail, and it repeats on all seven of their listings. A matcher problem,
   not a design one.
4. Venue-level geocoding is still finishing itself through the daily Action, exactly
   as the last handoff described. The approximate-distance pill (dashed, asterisk)
   renders correctly where `locationPrecision` is present — visible on The Big Trip
   and Zendog in the current feed.

## Files touched
`app.js`, `band.js`, `index.html`, `band.html`, `styles.css` (~990 → ~1180 lines).
No new dependencies, no build step, tiles still keyless OSM.
