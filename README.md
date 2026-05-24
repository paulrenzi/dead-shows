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

```sh
python scripts/scrape_gdtb.py
# writes data/gdtb-events.json + data/gdtb-bands.json + caches geocodes
git add data/ && git commit -m "data: refresh gdtb scrape" && git push
```

Run this whenever you want to refresh — recommended weekly. Geocodes are cached in `data/geocode-cache.json` (don't delete it; cities don't move).

## Local dev

The frontend is fully static — open `index.html` in a browser or run `python -m http.server 8000`. Point `WORKER_URL` at a `wrangler dev` instance if you want to iterate on the proxy locally.

## Known limits

- Ticketmaster misses small-venue tribute shows that only post on Bandsintown or band sites. To add coverage, layer Bandsintown (requires partner key) or scrape JamBase.
- Nominatim has a 1 req/sec policy — fine for our usage, don't abuse.
- All event data is whatever Ticketmaster says it is; venues sometimes have wrong coords.
