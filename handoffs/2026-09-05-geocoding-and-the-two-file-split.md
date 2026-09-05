# Handoff — 2026-09-05 (evening) — geocoding, and the file we had been reading

Live and verified in both colour schemes:
- dead-shows <https://paulrenzi.github.io/dead-shows/> · master `948555d` · assets `?v=22`
- happy-hour-finder <https://paulrenzi.github.io/happy-hour-finder/> · master `dd8d93c`

Follow-on from `2026-09-05-venue-names-and-happy-hour.md`. That handoff closed
with two blockers. **Both were bugs in our own reading, not facts about the
world**, and both are fixed.

---

## What the last handoff got wrong, and why it looked right

> "only **1 of the 476** deal venues in `board-by-lid.json` carries a `lat`/`lng`.
> That is a Happy Hour Finder-side geocoding gap."

> "**0 of the 18** matched venues publishes a happy-hour window."

Happy Hour Finder ships **two files per zone**, and neither name says which is
which:

```
web/data/zone-<id>.json     the BOARD — venues that HAVE a published window   (471)
web/data/venues-<id>.json   every other licensed premises, deals: []        (3,108)
```

`link_happy_hour.py` read only `venues-*.json`. So:

- the join was **structurally incapable** of matching a venue with a happy
  hour, and reported that honestly on every run. "0 of 18 publish a window" is
  necessarily true of a file *defined* as the venues with no window.
- and the coordinate count came from the same place. 441 of 472 deal venues
  carried a coordinate all along.

> 🔑 **This is the failure mode to watch for: a query against the wrong source
> that returns a well-formed answer instead of an error.** It cost two
> sessions, and both times the wrong answer was written down as a finding
> about the world (music rooms don't publish happy hours; Happy Hour Finder
> has a geocoding gap) rather than about the file. Neither was ever
> falsifiable from inside the code that produced it.

Now documented at the top of both READMEs and in `PLAYBOOK-NIGHT-OUT.md`
§ Traps. **Any consumer must read both, deal-bearing first.**

---

## What shipped

### 1. `happy-hour-finder/ingest/geocode_missing.py` — the coordinates
`geocode_venues.py` reads `data/deals_seed.json` and keys on that file's slug,
so it can only ever reach the 387-row seed corpus. Everything the PLCB base
and the zone expansions added was **outside its reach** — not unresolvable,
unreachable. The new script works off the published bundles and the venue base
and keys on **LID**, because the base is regenerated wholesale from Places and
would drop a coordinate stored against anything else.

**30 of 31 resolved. 470 of 471 board venues can now be ranked by distance.**

What was actually blocking them:
- a house-number range with **more than one hyphen**. `strip_range()` handled
  `30-32` and left `10-14 E Gay St` behind — four misses were on one block of
  West Chester's Gay Street.
- the suite. `Bldg 19 Ste E`, `Suite 300` — how the mail finds a venue, and
  not something OSM has heard of.

> 🔑 **A wrong coordinate is worse than a missing one** — it puts a bar in a
> town it is not in and the reader cannot tell. A hit is recorded only if the
> ZIP Nominatim resolves **matches the one asked for**; where the licensee and
> the post office genuinely disagree about a boundary building (Estia Taverna
> is 19085 on its licence and 19087 to the post office, same door), it is
> accepted only if it still lands within 5 miles of its zone's **median**
> venue. Median, not mean — one bad answer would drag a mean far enough to
> start admitting others. Those three are flagged `zip_mismatch` on the record.

Still missing: **Chickies & Petes**, `675 Shannondell Blvd Audubon Sq` — the
shopping-centre name is inline in the street. Needs a hand entry, not another
query.

### 2. The sw cache name could not see this build
It was `date + deal count + shell digest`. Filling in 30 coordinates changed 11
zone bundles and **none of those three**, so the stamp came out identical and
every device with a warm service worker would have gone on serving the venues
with no coordinate. `data_digest()` now covers the shipped bundles too.

### 3. The happy-hour link opened nothing — silently
All 13 links were dead. `#v=<lid>` with no zone **cannot** resolve: the board
boots only the deal bundles, a venue without hours arrives with its zone's
base, and the app fetches that base only when the hash names a zone.
`openVenue()` looked the id up in a list it was never in and `return`ed. The
reader lands on the default board and concludes the button is broken — which
is exactly what was reported.

Now: on the board → `#z=<zone>&v=<lid>`, which opens the venue's sheet. Off it
→ `#z=<zone>`, that town's board.

And the label distinguishes three things it used to flatten into one:

| | |
|---|---|
| `Happy hour 4–6pm` | this venue, this night |
| `Happy hour here` | on the board, no window on the show's day |
| `Happy hours in Ardmore / Bryn Mawr` | we can place the town, not the venue |

**23 shows now match (was 18); 5 carry a real published window** — Free Will
Brewing, Troubles End Brewing, Crooked Eye Brewery. Crooked Eye is one of the
30 geocoded today.

---

## Verification — both sites RUN, in both schemes

`scratchpad/hhf_link_check.py` opens **every link dead-shows emits** on the
live board. All 15, both schemes: the 3 venue links open their sheet with the
right heading; the 12 town links land on the right zone with cards. 0 errors.

Live dead-shows (`venue_check.py --live`), both schemes: 23 happy-hour links,
**0 carrying no zone**, no card saying "See happy hour", 133 address sublines,
`styles.css?v=22`, 0 page errors, 0 failed requests. `band.html` 8 cards, same.

> 🛑 **The app reads the hash once, at boot — there is no `hashchange`
> listener.** My first link check reused one page across 15 URLs; `goto()` to
> the same document with a different hash is a same-document navigation, so
> every result after the first described the **first** link's zone and 12 of 15
> "failed". Harmless for real links (each opens a fresh tab), fatal to a
> checker. **Open a fresh page per link.**

> 🛑 And a `<dialog>` is in the DOM whether it is open or not. Reading
> `hidden`/`display` on `#sheet` says "closed" always; `.open` is the only
> honest reading.

---

## Where the nearby-happy-hour feature actually stands

**It is computable now.** With 470 coordinated deal venues, matching every show
against every deal venue by distance:

| radius | shows | distinct venues |
|---|---|---|
| 0.25 mi | 27 | 18 |
| **0.5 mi** | **30** | **21** |
| 1.0 mi | 36 | 25 |
| 2.0 mi | 40 | 29 |

Brickette Lounge has **21** deal venues within half a mile; Ardmore Music Hall
4; World Cafe Live 3. The ceiling is Happy Hour Finder's coverage area, not
the geocoding — most of this feed is nowhere near the western Philly suburbs.

## Next session — the ask, in Paul's words

> "when you click on that, it should show you a list for that town sorted by
> distance from the venue"

The pieces are all in place. Shape it as: `link_happy_hour.py` computes the
nearby deal venues per show at build time (both sides now have coordinates) and
writes them into `hhf-links.json`; the card renders the nearest two or three
with their windows and distance. Falling back to the town board link only when
nothing is within range.

Open question worth deciding first: **whether the list belongs on the dead-shows
card or on the Happy Hour Finder board.** A `#z=<zone>&near=<lat>,<lng>` sort
on their side is the smaller change and helps every other consumer; building it
into the card keeps the reader on one page. No coordinate work is needed either
way.

## Files touched

happy-hour-finder: `ingest/geocode_missing.py` (new), `ingest/build_bundles.py`,
`data/venue_coords_lid.json` (new), `web/data/zone-*.json` (11), `web/sw.js`,
`README.md`, `PLAYBOOK-NIGHT-OUT.md`.

dead-shows: `scripts/link_happy_hour.py`, `app.js`, `band.js`, `index.html`,
`band.html`, `data/hhf-links.json`, `data/gdtb-events.json`, `README.md`.

All 578 happy-hour-finder tests pass, plus its render/search/picker checks.
