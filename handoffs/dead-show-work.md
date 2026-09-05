# Dead Show Work

Handoff — 2026-09-05 · branch `claude/grateful-dead-github-link-heplu2`

> **Status: pushed, never executed.** Three commits are on this branch. Nothing is merged to
> master, and not one line has been run — no scrape, no coverage check, not even a syntax check.
> The session that wrote this had no working shell. Treat the branch as reviewed-but-unproven.

| | |
|---|---|
| Commits on branch | **3** |
| Merged to master | **no** |
| Code executed | **0** |
| Artists added | **+12** (39 → 51) |

## What is on the branch

1. **`artists: add 12 Delaware Valley Dead tribute acts`** — `artists.json` 39 → 51.
   `worker/worker.js` gets 8 of the 12 as Ticketmaster keywords.
2. **`ci: fail the refresh when coverage collapses`** — new `scripts/check_coverage.py` and
   `data/coverage-canaries.json`, wired into `refresh-data.yml` before the commit step.
3. **`scrape: read the JamBase feed as well as the band feed`** — `scripts/scrape_gdtb.py`.

## Why this work exists

The app had two sources and both missed its own back yard. A Cloudflare Worker searches
Ticketmaster for names on a curated list; a daily Action scrapes gratefuldeadtributebands.com.
The map centres on King of Prussia at `40.0890, -75.3960`.

**The three nearest venues booking Dead tributes are all Tixr, not Ticketmaster:**

| Venue | Distance | Sells on |
|---|---|---|
| Upper Merion Twp Building Park, KoP | 2 mi | Tixr / free |
| 118 North, Wayne | 6 mi | Tixr |
| Ardmore Music Hall | 11 mi | Tixr |
| Philadelphia, South Street circuit | 20 mi | venue-direct |
| Arden Gild Hall, Wilmington DE | 35 mi | venue-direct |
| Anchor Rock Club, Atlantic City | 75 mi | venue-direct |

A free township concert has no ticketing at all, so the Ticketmaster path cannot see it by
construction. Clearest case: **Splintered Sunlight, Upper Merion Township Building Park,
5 Sep 2026, free** — two miles from the map centre, invisible to both sources.

## Verify before trusting

- **The JamBase feed's column order is an assumption.** `parse_state_page` is reused unchanged and
  that page was never loaded. Run the scrape once and inspect `feed: "jambase"` rows — a mismatch
  shows as venue and city landing in the wrong fields. The new `0 parseable rows` warning is there
  to make it loud.
- **`check_coverage.py` has never run.** Its floors (PA ≥ 4, PA/NJ/DE ≥ 8, national ≥ 250) were set
  from a truncated read of the events file, not a measured one. Expect to tune them on first run.
- **Four names are deliberately absent from `worker.js`:** Dead Band, Deadband, Lovelight, Local
  Honey. Each also belongs to unrelated non-Dead acts and the Worker does a bare keyword search
  with no artist-ID filter. They are in `artists.json` so the GDTB scrape still maps them to a
  curated slug. Re-add only alongside result filtering.
- **Deadband and Dead Band may be one act.** Listed separately pending confirmation; merge if so.

## Traps — do not repeat

- **WebFetch truncates `data/gdtb-events.json`.** ~1,121 entries; the fetch cuts off around `FL`,
  exactly where the alphabetical state loop would sever. This produced a confident, false reading
  that the feed has no PA shows. It does.
- **GitHub code search does not index that file.** Over the size limit, so absence proves nothing.
  Control: searching the repo for `Logan House` returns zero despite the string being present.
- **WebFetch also silently drops content from source files.** Its rendering of `scrape_gdtb.py`
  omitted the module docstring entirely. Use the GitHub contents API for anything you intend to
  rewrite whole.
- **Resale SEO sites fabricate dates.** `readingtickets.net`, `americanarenas.com`. A 25 Nov Ardmore
  show was discarded for having no other source. Trust Tixr group pages, JamBase show pages,
  Bandsintown, venue calendars.

## Next steps

1. **Run the Action on this branch** (`workflow_dispatch`). The runner has open internet; its logs
   give real per-state, per-feed counts and the first honest measurement of what the JamBase feed
   adds. `refresh-data.yml` commits to `github.ref_name`, so it touches only this branch.
2. **Inspect the `feed: "jambase"` rows** for column drift before merging.
3. **Tune the canary floors** to whatever the real numbers turn out to be.
4. **Redeploy the Worker** so the 8 new keywords take effect — the embedded list ships with the
   Worker, not the site.
5. **Consider Tixr properly.** `studio.tixr.com/v1/groups/<id>/events` needs a CPK and secret — a
   real integration, but the only thing that reaches the three nearest venues. Scope separately.

## Dated leads

| Act | Date | Where | Confidence |
|---|---|---|---|
| Splintered Sunlight | 5 Sep 2026 | Upper Merion Twp Park, KoP — free | good |
| The Dead Alchemists | 25 Oct 2026 | Shakedown South Street Vol. 3, Philadelphia | snippet only |
| Splintered Sunlight | 27 Dec 2026 | Ardmore Music Hall | snippet only |

Acts and venues are solid; upcoming dates are not. Search snippets skew to past shows because those
have stable indexed pages.
