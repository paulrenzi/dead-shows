# Handoff — 2026-09-05 (late) — the happy-hour link now sorts a town around the show venue

Live and verified, local and live, both sites:
- dead-shows <https://paulrenzi.github.io/dead-shows/> · master `bce90a8`
- happy-hour-finder <https://paulrenzi.github.io/happy-hour-finder/> · master `8c98585`

Follow-on from `2026-09-05-geocoding-and-the-two-file-split.md`, which left one
question open and everything else in place.

---

## The open question, and why it answered itself

> whether the list belongs on the dead-shows card or on the Happy Hour Finder board

Paul's own words settle it:

> "when you click on that, it should show you a list for that town sorted by
> distance from the venue"

The list appears **after a click**, and it is **that town's list**. That is the
board. Building it onto the card would put the list *before* the click and
duplicate a board that already exists.

So the whole feature is **an origin the link gets to choose**:

```
#z=<zone>&near=<lat>,<lng>&from=<venue name>
```

The board already ranked by distance from `state.origin`; `near=` sets it, and
`from=` names it. No list is copied between sites, and every other consumer of
the board gets the same sort for free.

**20 of 23 links now carry an origin.** The other three fall back to the plain
town board, correctly — see below.

---

## What this turned up: "Nearest" was not a distance sort

The find that matters, and it was not visible from either site's surface.

For any row on a **future day** — which is nearly every row a show links to —
`score()` ranks `within = near * 0.9 + unsure * 0.09`, and then adds
`unsure * 0.009` again on the way out. `near` is a fraction of **two hundred
miles**, so half a mile is `0.00225` of it, while the two confidence terms reach
`0.081` and `0.0081`.

> 🔑 **The tiebreak outweighed the thing being sorted on by ~36×.** "Nearest"
> actually meant "best sourced, then nearest": a bar **0.2 mi** from the venue
> sorted below one **fifteen miles** away, for being better sourced. Nobody asks
> a distance sort to weigh sourcing.

It is invisible because both orderings look plausible on screen — there is no
error, no gap, and the list is still *an* order. It only shows up if you assert
the order.

Fixed by making the tiebreak weight depend on the sort it is breaking ties in:
`unsure * (sort === "nearest" ? 0.00001 : 0.009)`. Distance leads; confidence
now breaks exact ties only. The other sorts lead on the clock or on value, where
`0.009` genuinely is below the resolution, so they keep it.

> 🔑 **A normalisation scale is a claim about what differences matter.** Scaling
> distance over 200 miles on a board whose venues are tenths of a mile apart
> discards the entire signal before any weight is applied.

---

## The three things that had to be true, and only the first was

1. **The board sorts from the link's coordinate.** (Wiring.)
2. **The headline says what it measured from.** "Happy hours near you" is a
   promise about *whose feet* the distances are from. Every "0.4 mi" on that
   page is from a concert hall the reader may be nowhere near, and nothing else
   on the board would have said so. It now reads **"Happy hours near Ardmore
   Music Hall"**, and reverts the moment the reader taps Near me.
3. **A stored location must not win.** `restoreLocation()` runs *after*
   `readHash()` at boot, so a reader who had used Near me in the last 12 hours
   would have opened the link and got the board ranked from their own kitchen —
   with the headline still naming the venue. Silent, and wrong in the exact way
   the link exists to prevent.

Plus: `near=` survives `writeHash()`, which rewrites the URL wholesale on the
first control change; and a junk `near=` is refused rather than ranked from
(0, 0) in the Gulf of Guinea.

---

## Where a link has no origin — and why that is the right answer

Three of sixteen (Brickette Lounge, Artifact Brewing, Jdm Wayne) fall back to the
plain town board. Both coordinate sources genuinely fail: they matched into
`venues-*.json`, whose rows carry **no** `lat`/`lng` (only the 471 **board**
venues were geocoded), and their show pin is `locationPrecision: "city"`.

> 🛑 A centroid would have produced a confident **"Happy hours near Brickette
> Lounge"** over a list actually sorted from downtown West Chester. **A wrong
> coordinate is worse than a missing one** — the reader cannot tell.

⚠️ **This also puts a caveat on the previous handoff's radius table** ("Brickette
Lounge has 21 deal venues within half a mile"). Those counts were computed from
each show's own coordinate, and many shows are city-precision — so an unknown
share of that table is measuring from a **town centroid**, not a venue. Treat
the numbers as an upper bound until they are recomputed on venue-precision pins
only.

**If you want those three:** run `geocode_missing.py` over the venue **base**,
not just the board. It keys on LID and the machinery already exists.

---

## Verification — both sites RUN, and the links are opened on the real board

- `happy-hour-finder/tests/near_check.py` (new, wired into `tests/run.sh`):
  headline, sort control, ascending distance **within each band**, `near=`
  survives a control change, a stored origin does not override the link, the
  plain board is unchanged, a junk coordinate is refused.
- `dead-shows/tests/hhf_link_check.py` (new, durable — the old one lived in
  `scratchpad/` and was gone): opens **every** link this site emits, against a
  local checkout by default and `--live` against the published board.
  **16 links open, 13 sort around the venue — local and live, 0 errors.**
- happy-hour-finder: **578 tests OK**, plus render / search / picker / chrome /
  stale-clock checks. `sw.js` restamped (the shell changed, so the cache name
  must — that gate fired and was honoured).

> 🛑 **Ascending *within each band*, not globally.** The board bands rows by when
> the deal is on ("Live now", "Later today", "Monday") and ranks by distance
> inside each. A bar that is open now outranks a nearer one that is shut, in
> every sort. Asserting one globally ascending list asserts a product decision
> nobody made, and fails against a board behaving correctly.

> 🛑 Two traps re-confirmed, both already in the log: **a fresh page per link**
> (the app reads its hash once at boot, so `goto()` between hashes is a
> same-document navigation and every result after the first describes the
> first), and **stub the cross-origin `/live/*` fetches** — unstubbed they fail
> CORS and paint a page error on *every* link, a whole run of false failures.
> The two overlays have **different shapes**: `deals.json`'s `venues` is a list,
> `events.json`'s is a map. One body for both throws `{} is not iterable`.

---

## 🛑 A session ate my work — the shared checkout, again

Mid-session, `C:\Users\paulm\happy-hour-finder` moved under me: another session
committed its own `styles.css` fix (`1ff3709`), restamped `sw.js` (`6dfb3ad`),
then ran **`reset: moving to origin/master`** — which **discarded my uncommitted
`app.js` / `index.html` edits**. Nothing errored; the files simply read as
pristine.

The known hook was that a shared checkout makes `git push` a silent no-op. This
is the sharper edge of the same thing: **a shared checkout can destroy
uncommitted work in another session.** Everything after that point was done in
`git worktree --detach origin/master` and landed with `git push origin
HEAD:master`, which is what should have happened from the first edit.

`happy-hour-finder` has **eight** worktrees and several concurrent `codex/*`
branches. Assume the main checkout is shared and never leave work uncommitted in
it.

---

## Files touched

happy-hour-finder (`8c98585`): `web/app.js`, `web/lib.js`, `web/index.html`,
`web/sw.js` (restamp), `tests/near_check.py` (new), `tests/run.sh`.

dead-shows (`bce90a8`): `scripts/link_happy_hour.py`,
`tests/hhf_link_check.py` (new), `data/hhf-links.json`, `data/gdtb-events.json`.

## Next

- The card copy is unchanged and still accurate ("Happy hours in Ardmore / Bryn
  Mawr"); the destination now names the origin itself. Worth deciding whether
  the card should say "near Ardmore Music Hall" instead.
- Geocode the venue **base** to recover the last three links.
- Recompute the radius table on venue-precision pins only.
