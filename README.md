# Dead Shows

Static GitHub Pages site that finds Grateful Dead family + tribute band shows, filtered by distance and date range. Defaults to King of Prussia, PA.

## Stack

- **Frontend**: vanilla JS + Leaflet, hosted on GitHub Pages
- **Backend**: Cloudflare Worker proxying the Ticketmaster Discovery API (hides the key)
- **Geocoding**: OpenStreetMap Nominatim (free, no key)

## One-time setup

### 1. Get a Ticketmaster API key

Sign up at https://developer-acct.ticketmaster.com/user/register — the Discovery API is on the free tier (5,000 calls/day, 5/sec).

### 2. Deploy the Cloudflare Worker

```sh
cd worker
npm install -g wrangler
wrangler login
wrangler deploy
wrangler secret put TICKETMASTER_API_KEY
# paste the key when prompted
```

Note the worker URL printed by deploy (e.g. `https://dead-shows.<your-subdomain>.workers.dev`).

### 3. Wire the frontend to the Worker

Edit `app.js` line 3 — replace `WORKER_URL` with your worker URL.

### 4. Publish to GitHub Pages

```sh
gh repo create dead-shows --public --source=. --remote=origin --push
gh api -X POST /repos/:owner/dead-shows/pages -f source[branch]=master -f source[path]=/
```

Site lives at `https://<your-username>.github.io/dead-shows/`.

### 5. (Optional) Lock CORS origin

```sh
wrangler vars put ALLOWED_ORIGIN https://<your-username>.github.io
```

## Editing the artist list

`artists.json` is the canonical curated list (for documentation), but the Worker has the list embedded in `worker/worker.js` (so it works with zero asset binding). To add an act, edit **both** files and redeploy the worker.

## Refreshing the gratefuldeadtributebands.com data

The site supplements Ticketmaster with shows from [gratefuldeadtributebands.com](http://www.gratefuldeadtributebands.com/) — a community-maintained directory of Dead tribute acts that catches tons of small-bar gigs TM misses.

**Automatic**: a GitHub Action (`.github/workflows/refresh-data.yml`) runs daily at 09:15 UTC. It scrapes GDTB, fetches any new band photos, and commits the changes back to master.

**Manual** (if you want to refresh sooner):

```sh
python scripts/scrape_gdtb.py        # writes data/gdtb-events.json + -bands.json + -band-links.json
python scripts/fetch_band_photos.py  # writes data/band-photos.json + images/bands/*.jpg
git add data/ images/bands/ && git commit -m "data: manual refresh" && git push
```

Geocodes are cached in `data/geocode-cache.json` (don't delete it; cities don't move). Photo cache in `data/photo-cache.json` records hits + misses so we don't re-probe every source daily; it carries a `probe` version so that adding a new source automatically retries past misses.

The scraper refuses to overwrite `gdtb-events.json` if a run comes back with under 60% of the previous show count — a half-failed scrape should leave yesterday's good data in place rather than quietly shipping a shrunken feed.

## Band photos

Photos come from a source ladder, best first — the first one that returns a usable image wins:

| Source | What it covers |
|--------|----------------|
| `manual` | `data/band-photos-manual.json`, always wins |
| `gdtb` | The band logo GDTB already hosts. Covers exactly this population of small regional tributes, and is by far the biggest contributor |
| `deezer` | Strict normalized name match, no key |
| `itunes` | Apple search API, no key — good on indie/self-released acts |
| `wikipedia` | REST summary thumbnail, for the notable acts (Wolf Bros, JGB) |

Current coverage is **~90% of listed bands** (258/286). Anything still missing gets the Dead-themed SVG placeholder.

Any image whose exact bytes show up for 3+ different bands is treated as the source's generic "no photo" tile and dropped — a repeated placeholder looks worse than the Stealie default.

To override a wrong photo, edit `data/band-photos-manual.json`:

```json
{
  "cubensis": { "photo": "images/bands/cubensis-manual.jpg" }
}
```

Drop the actual photo at the listed path and commit. Manual entries always win.

## Local dev

The frontend is fully static — open `index.html` in a browser or run `python -m http.server 8000`. Point `WORKER_URL` at a `wrangler dev` instance if you want to iterate on the proxy locally.

## Known limits

- The default view is deliberately narrow (20 mi / next 30 days). To see the entire feed, hit the **All upcoming** chip — it snaps the radius to **Anywhere** and the date range to two years, which is the only way to get all ~875 shows on screen at once.
- Ticketmaster misses small-venue tribute shows that only post on Bandsintown or band sites. To add coverage, layer Bandsintown (requires partner key) or scrape JamBase.
- Nominatim has a 1 req/sec policy — fine for our usage, don't abuse.
- All event data is whatever Ticketmaster says it is; venues sometimes have wrong coords.
