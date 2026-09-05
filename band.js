// Dead Shows — band detail page
const WORKER_URL = "https://dead-shows.paulmichaelrenzi.workers.dev";
const KOP = { lat: 40.0890, lng: -75.3960 };

let map;
let eventMarkers = [];
let markerById = new Map();
let bandPhotos = {};
let bandInfo = {};
const DEFAULT_PHOTO = "images/default-band.svg";
const SOCIAL_LABELS = {
  facebook: "Facebook",
  instagram: "Instagram",
  bandcamp: "Bandcamp",
  spotify: "Spotify",
  youtube: "YouTube",
};

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

function haversineMiles(lat1, lng1, lat2, lng2) {
  const R = 3958.8;
  const toRad = d => d * Math.PI / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a = Math.sin(dLat/2) ** 2 +
            Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) *
            Math.sin(dLng/2) ** 2;
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function getSlug() {
  const params = new URLSearchParams(location.search);
  return params.get("id");
}

function renderBandHero(artist) {
  document.getElementById("page-title").textContent = `${artist.name} — Dead Shows`;
  document.getElementById("page-desc").setAttribute("content", artist.blurb || `Upcoming ${artist.name} shows.`);
  document.getElementById("band-tier").textContent = artist.tier === "core" ? "Dead family · core artist" : "Grateful Dead tribute";
  document.getElementById("band-name").textContent = artist.name;
  document.getElementById("band-blurb").textContent = artist.blurb || "";

  const portrait = document.getElementById("band-portrait");
  if (portrait) {
    const photo = bandPhotos[artist.slug]?.photo || DEFAULT_PHOTO;
    portrait.src = photo;
    portrait.alt = artist.name;
    if (photo === DEFAULT_PHOTO) portrait.classList.add("band-portrait--default");
    portrait.onerror = () => {
      portrait.onerror = null;
      portrait.src = DEFAULT_PHOTO;
      portrait.classList.add("band-portrait--default");
    };
  }

  const linksEl = document.getElementById("band-links");
  const links = [];
  if (artist.website) links.push({ label: "Official site", href: artist.website });
  if (artist.wikipedia) links.push({ label: "Wikipedia", href: artist.wikipedia });
  // Real profiles scraped off the band's own homepage beat a search box.
  const socials = (bandInfo[artist.slug] || {}).socials || {};
  for (const [key, label] of Object.entries(SOCIAL_LABELS)) {
    if (socials[key]) links.push({ label, href: socials[key] });
  }
  if (!socials.spotify) links.push({ label: "Search Spotify", href: `https://open.spotify.com/search/${encodeURIComponent(artist.name)}` });
  if (!socials.youtube) links.push({ label: "Search YouTube", href: `https://www.youtube.com/results?search_query=${encodeURIComponent(artist.name)}` });
  linksEl.innerHTML = links.map(l =>
    `<a class="band-link" href="${escapeHtml(l.href)}" target="_blank" rel="noreferrer">${escapeHtml(l.label)} →</a>`
  ).join("");
}

function initMap() {
  map = L.map("map", { scrollWheelZoom: false }).setView([KOP.lat, KOP.lng], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
    maxZoom: 18,
  }).addTo(map);
  map.on("click", () => map.scrollWheelZoom.enable());
}

function matchesArtist(event, artist) {
  const k = artist.searchKeyword.toLowerCase();
  const n = artist.name.toLowerCase();
  for (const att of event.attractions || []) {
    if (att.toLowerCase().includes(k) || att.toLowerCase().includes(n)) return true;
  }
  const en = (event.name || "").toLowerCase();
  return en.includes(k) || en.includes(n);
}

async function fetchEvents(artist) {
  // Search wide: 500mi from KoP, next 12 months — band pages aren't geo-scoped
  const today = new Date();
  const yearOut = new Date(today);
  yearOut.setFullYear(yearOut.getFullYear() + 1);
  const params = new URLSearchParams({
    lat: KOP.lat.toFixed(4),
    lng: KOP.lng.toFixed(4),
    radius: "500",
    startDate: today.toISOString().slice(0, 10),
    endDate: yearOut.toISOString().slice(0, 10),
  });

  // Fetch both sources in parallel
  // The Ticketmaster branch had no catch, so a rejected fetch — which is what
  // the CORS-locked Worker does off the Pages origin — rejected the whole
  // Promise.all and rendered "Couldn't load shows." over a perfectly good
  // GDTB feed. Each source now fails on its own.
  const [tmRes, gdtbEvs] = await Promise.all([
    fetch(`${WORKER_URL}/events?${params.toString()}`)
      .then(r => r.ok ? r.json() : [])
      .catch(() => []),
    fetch("data/gdtb-events.json").then(r => r.ok ? r.json() : []).catch(() => []),
  ]);

  const tmFiltered = tmRes.filter(ev => matchesArtist(ev, artist)).map(ev => ({ ...ev, source: "tm" }));
  const gdtbFiltered = gdtbEvs.filter(ev => ev.bandSlug === artist.slug || ev.band.toLowerCase() === artist.name.toLowerCase());

  // Dedupe by (date + city)
  const seen = new Map();
  const key = ev => `${(ev.date || "").slice(0, 10)}|${(ev.city || "").toLowerCase()}`;
  for (const ev of tmFiltered) seen.set(key(ev), ev);
  for (const ev of gdtbFiltered) {
    if (!seen.has(key(ev))) seen.set(key(ev), { ...ev, source: "gdtb" });
  }
  return Array.from(seen.values());
}

// Same fixed poster palette the main page uses, so a photo-less card is a
// plate belonging to this site rather than an empty rectangle. Keyed on the
// venue here: on a single band's page the artist photo is the same every row,
// so the venue is the only thing left that varies.
const PLATE_PALETTE = [
  ["#d9313a", "#5c0f18"],
  ["#2f5fbe", "#131c48"],
  ["#e08a26", "#6d2a10"],
  ["#3f9b74", "#0f3a2c"],
  ["#7f43ab", "#231046"],
  ["#c9a52c", "#553112"],
];

function platePlaceholder(name) {
  let h = 0;
  const s = String(name || "");
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  const [from, to] = PLATE_PALETTE[h % PLATE_PALETTE.length];
  const words = s.trim().split(/\s+/).filter(w => /[a-z0-9]/i.test(w));
  const mark = (words.slice(0, 2).map(w => w[0]).join("") || s.slice(0, 2) || "?").toUpperCase();
  return `<span class="card-plate" style="--plate-from:${from};--plate-to:${to}" aria-hidden="true">
            <span class="card-plate-mark">${escapeHtml(mark)}</span>
          </span>`;
}

// Shared with the main page: a street address in the venue column is not a
// venue name, so show what actually stands there and demote the address.
function venueTitle(ev) {
  return ev.venueName || ev.venue || ev.city || "Venue TBA";
}

function venueSubline(ev) {
  return ev.venueName && ev.venue && ev.venueName !== ev.venue ? ev.venue : "";
}

function isoDow(iso) {
  const [y, m, d] = String(iso || "").slice(0, 10).split("-").map(Number);
  if (!y) return 0;
  const js = new Date(y, m - 1, d).getDay();
  return js === 0 ? 7 : js; // bundles use ISO 1=Mon..7=Sun, JS uses 0=Sun
}

function clockLabel(hhmm) {
  const [h, m] = String(hhmm || "").split(":").map(Number);
  if (Number.isNaN(h)) return "";
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${ampm}` : `${h12} ${ampm}`;
}

function happyHourNote(ev) {
  const hhf = ev.hhf;
  if (!hhf || !hhf.url) return "";
  const win = (hhf.deals || []).find(d => d.dow === isoDow(ev.date));
  const label = win
    ? `Happy hour ${clockLabel(win.start)}–${clockLabel(win.end)}`
    : "Happy hour info";
  return `<p class="card-hh"><a class="hh-link" href="${escapeHtml(hhf.url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a></p>`;
}

function renderCard(ev, artistPhoto) {
  const dist = haversineMiles(KOP.lat, KOP.lng, ev.lat, ev.lng);
  // The shared placeholder SVG is the absence of a photo, not a photo.
  const rawPhoto = ev.image || artistPhoto || "";
  const photoUrl = rawPhoto.endsWith("default-band.svg") ? "" : rawPhoto;
  const plate = platePlaceholder(venueTitle(ev) || ev.name);
  const img = photoUrl
    ? `<img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(ev.name)}" loading="lazy"
            onerror="this.onerror=null;this.remove();this.closest('.card-media').classList.add('card-media--plate');">`
    : "";
  const media = `<a class="card-media${photoUrl ? "" : " card-media--plate"}" href="${ev.url}" target="_blank" rel="noreferrer" tabindex="-1" aria-hidden="true">
       ${plate}${img}
     </a>`;
  return `
    <article class="event-card" data-id="${ev.id}">
      ${media}
      <div class="card-body">
        <p class="card-date">${formatDate(ev.date)}</p>
        <h3 class="card-name">${escapeHtml(venueTitle(ev))}</h3>
        <p class="card-venue">
          ${escapeHtml(ev.city || "")}${ev.state ? ", " + escapeHtml(ev.state) : ""}
          ${venueSubline(ev) ? "<br><span class=\"city\">" + escapeHtml(venueSubline(ev)) + "</span>" : ""}
          ${ev.venueAddress ? "<br><span class=\"city\">" + escapeHtml(ev.venueAddress) + "</span>" : ""}
        </p>
        ${happyHourNote(ev)}
        <div class="card-meta">
          <span class="meta-pill distance">${dist.toFixed(0)} mi from KoP</span>
        </div>
        <div class="card-foot">
          <button type="button" class="show-on-map-btn" data-id="${ev.id}">Show on map</button>
          <a class="tickets-link" href="${ev.url}" target="_blank" rel="noreferrer">Tickets →</a>
        </div>
      </div>
    </article>
  `;
}

function renderEvents(events, artist) {
  const cards = document.getElementById("cards");
  const counter = document.getElementById("result-count");
  eventMarkers.forEach(m => map.removeLayer(m));
  eventMarkers = [];
  markerById.clear();

  if (!events.length) {
    counter.textContent = "0 shows on the books";
    cards.innerHTML = `<div class="empty-state">
      <strong>No upcoming ${escapeHtml(artist.name)} shows in Ticketmaster.</strong>
      Could mean they're between tours, or they're on a non-Ticketmaster platform like Bandsintown — check the band's website above.
    </div>`;
    document.getElementById("map").style.display = "none";
    return;
  }

  events.sort((a, b) => {
    const da = new Date(a.date).getTime();
    const db = new Date(b.date).getTime();
    if (da !== db) return da - db;
    return (a.venue || "").localeCompare(b.venue || "");
  });
  counter.textContent = `${events.length} upcoming show${events.length === 1 ? "" : "s"}`;
  const artistPhoto = bandPhotos[artist.slug]?.photo;
  cards.innerHTML = events.map(ev => renderCard(ev, artistPhoto)).join("");

  const bounds = [];
  events.forEach(ev => {
    const popup = `<strong>${escapeHtml(ev.venue)}</strong>${escapeHtml(ev.city)}<br>${formatDate(ev.date)}<a class="popup-link" href="${ev.url}" target="_blank" rel="noreferrer">Tickets →</a>`;
    const marker = L.marker([ev.lat, ev.lng]).addTo(map).bindPopup(popup);
    eventMarkers.push(marker);
    markerById.set(ev.id, marker);
    bounds.push([ev.lat, ev.lng]);
  });
  if (bounds.length === 1) {
    map.setView(bounds[0], 9);
  } else {
    map.fitBounds(L.latLngBounds(bounds).pad(0.15));
  }

  cards.querySelectorAll(".show-on-map-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const id = e.currentTarget.dataset.id;
      const marker = markerById.get(id);
      if (marker) {
        map.setView(marker.getLatLng(), 11);
        marker.openPopup();
        document.getElementById("map").scrollIntoView({ behavior: "smooth", block: "nearest" });
      }
    });
  });
}

async function init() {
  const slug = getSlug();
  if (!slug) {
    document.body.innerHTML = `<main class="shell"><div class="empty-state"><strong>No band specified.</strong><a href="index.html">Back to shows →</a></div></main>`;
    return;
  }
  // Try curated artists first, then discovered gdtb bands
  const [aRes, gRes, pRes, iRes, lRes] = await Promise.all([
    fetch("artists.json").then(r => r.json()),
    fetch("data/gdtb-bands.json").then(r => r.ok ? r.json() : []).catch(() => []),
    fetch("data/band-photos.json").then(r => r.ok ? r.json() : {}).catch(() => ({})),
    fetch("data/band-info.json").then(r => r.ok ? r.json() : {}).catch(() => ({})),
    fetch("data/gdtb-band-links.json").then(r => r.ok ? r.json() : {}).catch(() => ({})),
  ]);
  bandPhotos = pRes;
  bandInfo = iRes;
  let artist = aRes.artists.find(a => a.slug === slug);
  if (!artist) {
    const g = gRes.find(b => b.slug === slug);
    if (g) {
      const info = iRes[g.slug] || {};
      artist = {
        slug: g.slug, name: g.name, searchKeyword: g.name, tier: "tribute",
        // Every tribute page used to carry the same one-line sentence. Prefer
        // whatever the band says about itself on its own site.
        blurb: info.og_description ||
          `Dead tribute act listed at gratefuldeadtributebands.com (${g.state}).`,
        wikipedia: null,
        website: (lRes[g.slug] || {}).url || null,
      };
    }
  }
  if (!artist) {
    document.body.innerHTML = `<main class="shell"><div class="empty-state"><strong>Unknown band: ${escapeHtml(slug)}</strong><a href="index.html">Back to shows →</a></div></main>`;
    return;
  }
  renderBandHero(artist);
  initMap();
  try {
    const events = await fetchEvents(artist);
    renderEvents(events, artist);
  } catch (err) {
    document.getElementById("cards").innerHTML = `<div class="empty-state"><strong>Couldn't load shows.</strong>${escapeHtml(err.message)}</div>`;
    console.error(err);
  }
}

init();
