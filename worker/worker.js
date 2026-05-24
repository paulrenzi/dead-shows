// Cloudflare Worker — Ticketmaster proxy for dead-shows
// Env: TICKETMASTER_API_KEY (secret), ALLOWED_ORIGIN (var, e.g. https://paulrenzi.github.io)
// Bind asset: artists.json (or hard-code the list; here we embed it for zero-config deploy)

const ARTISTS = [
  "Dead & Company",
  "Bob Weir",
  "Wolf Bros",
  "Phil Lesh",
  "Phil Lesh & Friends",
  "Mickey Hart Band",
  "Bill Kreutzmann",
  "Billy & The Kids",
  "Melvin Seals",
  "Grahame Lesh",
  "Dark Star Orchestra",
  "Joe Russo's Almost Dead",
  "JRAD",
  "Splintered Sunlight",
  "China Cats",
  "Cubensis",
  "Half Step",
  "Stella Blue's Band",
  "Shakedown",
  "The Schwag",
  "Terrapin Flyer",
  "Cosmic Charlie",
  "Garcia Birthday Band",
  "Reckoning",
  "Grateful Shred",
  "Dead On Live",
  "Box of Rain",
  "Better Off Dead",
  "Bearly Dead",
  "Cosmic Jerry Band",
  "Friends of Jerry",
  "Playing Dead",
  "Steely Dead",
  "Not Fade Away",
];

const KEYWORDS = ["grateful dead tribute", "grateful dead"];

const TM_BASE = "https://app.ticketmaster.com/discovery/v2/events.json";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    const corsHeaders = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "*",
      "Access-Control-Allow-Methods": "GET, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type",
    };

    if (request.method === "OPTIONS") {
      return new Response(null, { headers: corsHeaders });
    }

    if (url.pathname !== "/events") {
      return new Response("Not found", { status: 404, headers: corsHeaders });
    }

    const lat = url.searchParams.get("lat");
    const lng = url.searchParams.get("lng");
    const radius = url.searchParams.get("radius") || "100";
    const startDate = url.searchParams.get("startDate");
    const endDate = url.searchParams.get("endDate");

    if (!lat || !lng) {
      return json({ error: "lat and lng required" }, 400, corsHeaders);
    }
    if (!env.TICKETMASTER_API_KEY) {
      return json({ error: "Server missing TICKETMASTER_API_KEY" }, 500, corsHeaders);
    }

    const startDateTime = startDate ? `${startDate}T00:00:00Z` : undefined;
    const endDateTime = endDate ? `${endDate}T23:59:59Z` : undefined;

    const queries = [...ARTISTS, ...KEYWORDS];

    try {
      const results = await Promise.all(
        queries.map(q => fetchTicketmaster({
          keyword: q,
          lat, lng, radius,
          startDateTime, endDateTime,
          apiKey: env.TICKETMASTER_API_KEY,
        }))
      );

      const seen = new Map();
      for (const evs of results) {
        for (const ev of evs) {
          if (!seen.has(ev.id)) seen.set(ev.id, ev);
        }
      }

      const events = Array.from(seen.values());
      return json(events, 200, corsHeaders);
    } catch (err) {
      return json({ error: err.message }, 502, corsHeaders);
    }
  },
};

async function fetchTicketmaster({ keyword, lat, lng, radius, startDateTime, endDateTime, apiKey }) {
  const params = new URLSearchParams({
    apikey: apiKey,
    keyword,
    latlong: `${lat},${lng}`,
    radius,
    unit: "miles",
    size: "100",
    sort: "date,asc",
  });
  if (startDateTime) params.set("startDateTime", startDateTime);
  if (endDateTime) params.set("endDateTime", endDateTime);

  const r = await fetch(`${TM_BASE}?${params.toString()}`);
  if (!r.ok) {
    // 429s and similar shouldn't kill the whole search; log and return empty.
    console.warn(`Ticketmaster ${r.status} for "${keyword}"`);
    return [];
  }
  const data = await r.json();
  const events = data?._embedded?.events || [];
  return events.map(normalize).filter(Boolean);
}

function normalize(ev) {
  const venue = ev?._embedded?.venues?.[0];
  if (!venue?.location?.latitude || !venue?.location?.longitude) return null;
  const date = ev.dates?.start?.dateTime || ev.dates?.start?.localDate;
  if (!date) return null;
  const attractions = (ev._embedded?.attractions || []).map(a => a.name).filter(Boolean);
  return {
    id: ev.id,
    name: ev.name,
    venue: venue.name || "",
    venueUrl: venue.url || null,
    venueAddress: venue.address?.line1 || "",
    city: venue.city?.name || "",
    state: venue.state?.stateCode || "",
    lat: parseFloat(venue.location.latitude),
    lng: parseFloat(venue.location.longitude),
    date,
    url: ev.url,
    image: (ev.images || []).find(i => i.ratio === "16_9" && i.width > 500)?.url || ev.images?.[0]?.url,
    attractions,
  };
}

function json(body, status, headers) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });
}
