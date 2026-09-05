# Handoff — 2026-09-05 — venue names, the address join, and the Happy Hour Finder link

Live and verified: https://paulrenzi.github.io/dead-shows/ · master @ `5b0d11e` (+ copy fix) · assets at `?v=21`

Follow-on from `2026-09-05-design-overhaul-map-first.md`, which closed the four
design-debt items. This session took the **content** problem that handoff left
behind: a quarter of the cards named a street, not a room.

---

## The problem, measured before touching anything

| | count |
|---|---|
| shows in the feed | 875 |
| whose "venue" was a street address | 234 |
| of those in PA / NJ / DE | 47 (38 distinct) |

The addresses also carried junk. `extract_venue` takes everything after the last
` - ` in the description cell, so the town, the state **twice** (abbreviation
and full name), the country and the ZIP came with it:

```
4935 River Road New Hope PA United States Pennsylvania 18938
101 Walnut StreetMontclair07042US
501 A1A Beach Blvd.St. Augustine Beach32080US St Augustine
```

That one string was simultaneously the card heading, the Nominatim query and
the dedupe key, so it was doing damage in three places at once.

---

## What shipped — three steps, each standing on its own

### 1. `scripts/venuetext.py` — clean the string, define the key
`clean_venue()` strips the tail. Country, ZIP and the state's full name are
always safe to remove; the **city and the bare state abbreviation only come off
when the string still carries a street number**, so a venue genuinely named for
its town keeps its name. Matching runs over both strings with punctuation
removed, which is how `Blvd.St. Augustine Beach` gives up its town.

178 of 875 venue strings changed. Nine cleaned down to a bare `/` or a lone ZIP
— those were never venues, and they now render as nothing rather than as
`19425`.

`venue_key()` collapses street suffixes (`St.` / `Street`, `Rd` / `Road`).

> 🔑 **The dedupe key used to be the raw venue squashed to 20 characters**, which
> made `1statest` and `1statestreet` two different places — the Blue Drew and
> the Magoos duplicate the last handoff flagged. `app.js` now mirrors
> `venue_key` as `venueKey`. **Change one, change both.**

> 🛑 The show id embeds the venue slug, so improving venue text **renames every
> affected show**. Without a fallback that reads as 178 shows vanishing and 178
> debuting the same day: `firstSeen` resets and the archive fills with rows for
> gigs that never moved. `scrape_gdtb.py` now falls back to a loose key
> (band slug + date + city + time) before deciding anything is new or gone.

### 2. `scripts/resolve_venue_names.py` — ask OpenStreetMap what is there
Geocodes the **cleaned** address, then asks Overpass for a named bar, brewery,
theatre, restaurant or hall within 70 m. Keyless, no account, no new dependency.

**82 of 162 addresses resolved**, giving 107 shows a real name. Examples: The
Capitol Theatre, Beachland Ballroom, Caffè Lena, Bearsville Theater, Sherman
Theater, XL Live, WOW Hall, Free Will Brewery.

> 🔑 **Ranking the tag family before distance is the wrong answer.** The first
> pass put a bar 51 m away ahead of the music hall 5 m away, because "bar" ranks
> above "theatre". Distance decides now and the family only breaks a near-tie
> (`score = metres + rank × 12`).

> 🔑 **A candidate that publishes a DIFFERENT house number is rejected outright**,
> and past 55 m nothing is accepted unless its house number matches ours. That
> gate is what stopped `23 East Lancaster Avenue` from becoming the bar four
> doors down.

> 🛑 A miss is recorded **only when Overpass answers and the answer is empty.**
> Two batches returned 429 during the first full run and were deliberately left
> unrecorded. Caching a failure as "no such place" is the trap that poisoned 425
> geocode keys once — see the comment in `_nominatim_lookup`.

`data/venue-names-manual.json` overrides anything, and is never overwritten.

### 3. `scripts/link_happy_hour.py` — the Happy Hour Finder join
Both sites publish from `paulrenzi.github.io`, so the join happens **at build
time** against Happy Hour Finder's own published JSON. Nothing is fetched at
page load; neither site gains a runtime dependency on the other.

**18 shows matched** (14 by address, 4 by name) across 13 venues: Ardmore Music
Hall, World Cafe Live, Kelly's Logan House, Bridgeport Rib House, Freight
Building, The Gem, Bye Town, Halftime Sports and Music, Brickette Lounge,
Rivet, Artifact Brewing, Shere-E-Punjab, Jdm Wayne.

> 🔑 **The PLCB licence record beats the OpenStreetMap guess.** `23 East
> Lancaster Avenue, Ardmore` is **Ardmore Music Hall** because Happy Hour Finder
> says so from a liquor licence. OSM's nearest-named-thing had offered the bar
> next door. This is the integration paying for itself.

> 🛑 **The join must be city-gated.** An address key that is only house number +
> street matches `101 Walnut St, Montclair NJ` to `101 Walnut St, Green Lane PA`
> — it did, in the trial. `address_key` carries the city and the state.

Where both sides publish a coordinate they must agree within 0.4 miles before
the match is claimed.

### On the card
The business name is the heading, the address drops to a second line, and a
happy-hour pill links to that venue on the board. Calendars, map links and
searches get **both** name and address (`venueWhere`).

---

## Also fixed: `band.js` took the whole page down when Ticketmaster failed

The Ticketmaster branch of `Promise.all` had `.then(r => r.ok ? r.json() : [])`
and **no `.catch`**. A rejected fetch — exactly what the CORS-locked Worker does
off the Pages origin — rejected the whole `Promise.all` and rendered
"Couldn't load shows." over a perfectly good GDTB feed. Each source fails on its
own now. `band.html` renders 7 cards locally where it used to render the error.

---

## Two things worth knowing before building on this

### 🛑 The happy-hour WINDOWS are almost all unreachable
`board-by-lid.json` holds 476 venues with published deals. **None of our 18
matched venues is among them** — music rooms are not the businesses publishing
happy hours. The join is correct and the pill therefore reads "See happy hour"
rather than a time.

The obvious better product — *"a happy hour within walking distance of the
show"* — is **not computable today**: only **1 of the 476** deal venues carries a
`lat`/`lng` in the published bundles. That is a Happy Hour Finder-side
geocoding gap, and closing it is what would unlock nearby-deal cards here.

### The remaining unresolved addresses
120 shows still show a bare address: 50 where Overpass answered and knows
nothing, ~27 that never got a coordinate, and the rest not yet attempted. The
daily Action chips away at 60 per run, so this improves on its own.

---

## Verification — the page was RUN, in both schemes, never an HTTP 200

Live, headless Chromium, after Pages run `33946153116` (success):

| | dark | light |
|---|---|---|
| cards ("All upcoming") | 876 | 864 |
| day groups | 91 | 88 |
| address sublines | 115 | 115 |
| happy-hour links | 18 | 18 |
| `.hh-link` colour | `rgb(240,189,114)` | `rgb(138,83,16)` |
| css | `styles.css?v=20` | `styles.css?v=20` |
| **page errors** | **0** | **0** |
| **failed requests** | **0** | **0** |

Dedupe proved in the page, both schemes:
`venueKey('1 State St.') === venueKey('1 State Street')`, and
`mergeAndDedupe` collapses the two Bristol rows to **1**.

`band.html?id=splintered-sunlight`, both schemes: 7 cards, `?v=20`, 0 errors.

> ⚠️ Dark saw 876 cards and light 864. That is the Ticketmaster feed differing
> between two separate page loads, not a scheme difference.

> 🛑 **A local `http.server` on a busy port lies.** `allow_reuse_address = True`
> let a bind "succeed" on a port another project's server already held, and the
> checks silently ran against **someone else's 404 page** — titled "System
> Compatibility Reference". The scratchpad harnesses now bind port **0** and let
> the OS assign. If a check fails inexplicably, print `pg.title()` first.

Scripts: `venue_check.py` (`--live`), `dedupe_check.py`, `shot_card.py` in the
session scratchpad.

## Files touched
`scripts/venuetext.py` (new), `scripts/resolve_venue_names.py` (new),
`scripts/link_happy_hour.py` (new), `scripts/scrape_gdtb.py`, `app.js`,
`band.js`, `styles.css`, `index.html`, `band.html`,
`.github/workflows/refresh-data.yml`, `data/venue-names.json` (new),
`data/hhf-links.json` (new).

Both new Action steps are `continue-on-error` — a rate-limited Overpass or a
Happy Hour Finder outage must never fail the daily refresh. No new
dependencies, no build step, tiles still keyless OSM.
