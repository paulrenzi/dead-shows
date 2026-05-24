// Dead Shows — main page
const WORKER_URL = "https://dead-shows.paulmichaelrenzi.workers.dev";
const KOP = { lat: 40.0890, lng: -75.3960, label: "King of Prussia, PA" };

let map, centerMarker, radiusCircle;
let eventMarkers = [];
let markerById = new Map();
let cardById = new Map();
let currentCenter = { ...KOP };
let artistsBySlug = new Map();
let artistsByName = new Map();
let gdtbEvents = [];
let bandPhotos = {};
let lastEvents = [];
let deepLinkApplied = false;
const chipState = { date: "next30", radius25: false, deadOnly: false };
const DEFAULT_PHOTO = "images/default-band.svg";

async function loadArtists() {
  const r = await fetch("artists.json");
  const data = await r.json();
  for (const a of data.artists) {
    artistsBySlug.set(a.slug, a);
    artistsByName.set(a.name.toLowerCase(), a);
    artistsByName.set(a.searchKeyword.toLowerCase(), a);
  }
}

async function loadGdtb() {
  // gratefuldeadtributebands.com scraped data — refreshed via scripts/scrape_gdtb.py
  try {
    const [eventsRes, bandsRes, photosRes] = await Promise.all([
      fetch("data/gdtb-events.json"),
      fetch("data/gdtb-bands.json"),
      fetch("data/band-photos.json").catch(() => null),
    ]);
    if (photosRes && photosRes.ok) bandPhotos = await photosRes.json();
    if (eventsRes.ok) gdtbEvents = await eventsRes.json();
    if (bandsRes.ok) {
      const bands = await bandsRes.json();
      for (const b of bands) {
        if (artistsBySlug.has(b.slug)) continue;
        const stub = {
          slug: b.slug, name: b.name, searchKeyword: b.name,
          tier: "tribute",
          blurb: `Dead tribute act listed at gratefuldeadtributebands.com (${b.state}).`,
          wikipedia: null, website: null, source: b.source,
        };
        artistsBySlug.set(b.slug, stub);
        artistsByName.set(b.name.toLowerCase(), stub);
      }
    }
  } catch (e) {
    console.warn("GDTB data not loaded:", e);
  }
}

function matchArtist(event) {
  // Try attractions first (Ticketmaster's canonical artist data)
  for (const att of event.attractions || []) {
    const hit = artistsByName.get(att.toLowerCase());
    if (hit) return hit;
  }
  // Substring match against attractions — only with keys ≥8 chars to avoid
  // short common-word matches ("Reckoning", "Cubensis") catching unrelated events
  for (const att of event.attractions || []) {
    const lower = att.toLowerCase();
    for (const [key, artist] of artistsByName) {
      if (key.length >= 8 && lower.includes(key)) return artist;
    }
  }
  // Final fallback: event name contains any artist name (≥8 char keys only)
  const lname = (event.name || "").toLowerCase();
  for (const [key, artist] of artistsByName) {
    if (key.length >= 8 && lname.includes(key)) return artist;
  }
  return null;
}

// True if the event is actually Dead-related (matches curated artist OR
// has a Dead keyword in the name/attractions). Filters out jam-adjacent
// noise like Widespread Panic that TM returns from broad keyword matches.
const DEAD_KEYWORDS = /grateful|garcia|jerry|deadhead|dead\s+(?:night|bowl|tribute|set|show|film|performance|cover)|live\s+dead|workingman'?s\s+dead|american\s+beauty/i;
function isDeadRelated(event) {
  if (matchArtist(event)) return true;
  const t = (event.name || "") + " " + (event.attractions || []).join(" ");
  return DEAD_KEYWORDS.test(t);
}

function initMap() {
  map = L.map("map", { scrollWheelZoom: false }).setView([KOP.lat, KOP.lng], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
    maxZoom: 18,
  }).addTo(map);
  map.on("click", () => map.scrollWheelZoom.enable());
  drawCenter();
}

function drawCenter() {
  if (centerMarker) map.removeLayer(centerMarker);
  if (radiusCircle) map.removeLayer(radiusCircle);
  centerMarker = L.marker([currentCenter.lat, currentCenter.lng], {
    title: currentCenter.label || "Search center",
  }).addTo(map).bindPopup(`<strong>${escapeHtml(currentCenter.label || "Center")}</strong>`);
  const miles = parseInt(document.getElementById("radius").value, 10);
  radiusCircle = L.circle([currentCenter.lat, currentCenter.lng], {
    radius: miles * 1609.34,
    color: "#d32027",
    weight: 1.5,
    fillOpacity: 0.05,
  }).addTo(map);
}

function clearEventMarkers() {
  eventMarkers.forEach(m => map.removeLayer(m));
  eventMarkers = [];
  markerById.clear();
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

function isoLocalDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function applyDateChip(chip) {
  const today = new Date();
  let start = today;
  let end = new Date(today);
  if (chip === "tonight") {
    end = today;
  } else if (chip === "weekend") {
    const dow = today.getDay(); // 0=Sun … 6=Sat
    const daysUntilSunday = (7 - dow) % 7;
    end.setDate(end.getDate() + daysUntilSunday);
  } else { // next30
    end.setDate(end.getDate() + 30);
  }
  document.getElementById("start-date").value = isoLocalDate(start);
  document.getElementById("end-date").value = isoLocalDate(end);
  chipState.date = chip;
}

function updateChipUi() {
  document.querySelectorAll(".chip").forEach(btn => {
    const c = btn.dataset.chip;
    let active = false;
    if (c === "tonight" || c === "weekend" || c === "next30") {
      active = chipState.date === c;
    } else if (c === "radius25") {
      active = chipState.radius25;
    } else if (c === "deadOnly") {
      active = chipState.deadOnly;
    }
    btn.classList.toggle("chip--active", active);
    btn.setAttribute("aria-pressed", String(active));
  });
}

async function geocode(query) {
  const url = `https://nominatim.openstreetmap.org/search?format=json&limit=1&q=${encodeURIComponent(query)}`;
  const r = await fetch(url, { headers: { "Accept": "application/json" } });
  if (!r.ok) throw new Error("Geocode failed");
  const data = await r.json();
  if (!data.length) throw new Error("No location found");
  return {
    lat: parseFloat(data[0].lat),
    lng: parseFloat(data[0].lon),
    label: data[0].display_name.split(",").slice(0, 2).join(","),
  };
}

async function resolveCenter() {
  const txt = document.getElementById("center").value.trim();
  if (!txt) {
    if (currentCenter.label === "My location") return; // keep geolocated center
    currentCenter = { ...KOP };
    return;
  }
  currentCenter = await geocode(txt);
}

async function fetchEvents() {
  const radius = parseInt(document.getElementById("radius").value, 10);
  const startDate = document.getElementById("start-date").value;
  const endDate = document.getElementById("end-date").value;
  const params = new URLSearchParams({
    lat: currentCenter.lat.toFixed(4),
    lng: currentCenter.lng.toFixed(4),
    radius: String(radius),
    startDate,
    endDate,
  });
  const r = await fetch(`${WORKER_URL}/events?${params.toString()}`);
  if (!r.ok) {
    const text = await r.text();
    throw new Error(`Worker error ${r.status}: ${text.slice(0, 200)}`);
  }
  const tmEvents = await r.json();
  const gdtb = filterGdtb(radius, startDate, endDate);
  return mergeAndDedupe(tmEvents, gdtb);
}

function filterGdtb(radius, startDate, endDate) {
  if (!gdtbEvents.length) return [];
  const start = startDate ? new Date(startDate) : null;
  const end = endDate ? new Date(endDate + "T23:59:59") : null;
  return gdtbEvents.filter(ev => {
    const d = new Date(ev.date);
    if (start && d < start) return false;
    if (end && d > end) return false;
    const dist = haversineMiles(currentCenter.lat, currentCenter.lng, ev.lat, ev.lng);
    return dist <= radius;
  }).map(ev => ({ ...ev, source: ev.source || "gdtb" }));
}

function mergeAndDedupe(tmEvents, gdtbEvts) {
  // Dedupe by (band-lower + date YYYY-MM-DD + city-lower). TM wins ties (has images/tickets).
  const seen = new Map();
  const key = ev => {
    const band = ((ev.attractions && ev.attractions[0]) || ev.name || "").toLowerCase();
    const day = (ev.date || "").slice(0, 10);
    const city = (ev.city || "").toLowerCase();
    return `${band}|${day}|${city}`;
  };
  for (const ev of tmEvents) {
    seen.set(key(ev), { ...ev, source: ev.source || "tm" });
  }
  for (const ev of gdtbEvts) {
    if (!seen.has(key(ev))) seen.set(key(ev), ev);
  }
  return Array.from(seen.values());
}

function formatDate(iso) {
  const d = new Date(iso);
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });
}

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function eventById(id) {
  return lastEvents.find(e => e.id === id);
}

function toIcsUtc(d) {
  return d.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}/, "");
}

function icsEscape(s) {
  return String(s || "")
    .replace(/\\/g, "\\\\")
    .replace(/\r?\n/g, "\\n")
    .replace(/[,;]/g, m => "\\" + m);
}

function buildIcsDates(ev) {
  // TM events carry a UTC dateTime (ISO with "T"); GDTB events carry date-only.
  // Date-only → default 7pm floating-local with 3hr duration so calendars
  // display it correctly in venue local time.
  if (ev.date && ev.date.includes("T")) {
    const start = new Date(ev.date);
    const end = new Date(start.getTime() + 3 * 60 * 60 * 1000);
    return { dtstart: toIcsUtc(start), dtend: toIcsUtc(end), floating: false };
  }
  const dateOnly = (ev.date || "").slice(0, 10).replace(/-/g, "");
  return { dtstart: `${dateOnly}T190000`, dtend: `${dateOnly}T220000`, floating: true };
}

function buildIcs(ev) {
  const artist = matchArtist(ev);
  const displayName = artist?.name || ev.name || "Show";
  const { dtstart, dtend } = buildIcsDates(ev);
  const dtstamp = toIcsUtc(new Date());
  const where = [ev.venue, ev.city, ev.state].filter(Boolean).join(", ");
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Dead Shows//EN",
    "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:dead-shows-${icsEscape(ev.id)}@paulrenzi.github.io`,
    `DTSTAMP:${dtstamp}`,
    `DTSTART:${dtstart}`,
    `DTEND:${dtend}`,
    `SUMMARY:${icsEscape(displayName)}`,
    `LOCATION:${icsEscape(where)}`,
    ev.url ? `URL:${icsEscape(ev.url)}` : null,
    "DESCRIPTION:via Dead Shows",
    "END:VEVENT",
    "END:VCALENDAR",
  ].filter(Boolean);
  return new Blob([lines.join("\r\n")], { type: "text/calendar" });
}

function downloadIcs(ev) {
  const blob = buildIcs(ev);
  const url = URL.createObjectURL(blob);
  const artist = matchArtist(ev);
  const slug = artist?.slug || "event";
  const a = document.createElement("a");
  a.href = url;
  a.download = `${slug}-${(ev.date || "").slice(0, 10)}.ics`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { a.remove(); URL.revokeObjectURL(url); }, 500);
}

function eventShareUrl(ev) {
  const base = `${location.origin}${location.pathname}`;
  return `${base}?event=${encodeURIComponent(ev.id)}`;
}

async function shareEvent(ev) {
  const artist = matchArtist(ev);
  const displayName = artist?.name || ev.name || "Show";
  const url = eventShareUrl(ev);
  const shareData = {
    title: `${displayName} — Dead Shows`,
    text: `${displayName} at ${ev.venue} · ${formatDate(ev.date)}`,
    url,
  };
  if (navigator.share) {
    try { await navigator.share(shareData); } catch (e) {
      if (e.name !== "AbortError") console.warn("share failed:", e);
    }
    return;
  }
  try {
    await navigator.clipboard.writeText(url);
    showToast("Link copied");
  } catch (e) {
    showToast("Copy failed — long-press to copy");
    console.warn(e);
  }
}

function showToast(msg) {
  let toast = document.getElementById("toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "toast";
    toast.className = "toast";
    document.body.appendChild(toast);
  }
  toast.textContent = msg;
  toast.classList.add("toast--show");
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove("toast--show"), 2000);
}

function renderCard(ev, idx) {
  const artist = matchArtist(ev);
  const dist = haversineMiles(currentCenter.lat, currentCenter.lng, ev.lat, ev.lng);
  const displayName = artist?.name || ev.name;
  const tierClass = artist?.tier ? `tier-${artist.tier}` : "tier-tribute";
  const tierLabel = artist?.tier === "core" ? "Dead family" : "Tribute";
  const bandLink = artist
    ? `<a href="band.html?id=${encodeURIComponent(artist.slug)}">${escapeHtml(displayName)}</a>`
    : escapeHtml(displayName);

  const bandPhoto = artist ? bandPhotos[artist.slug] : null;
  const photoUrl = ev.image || bandPhoto?.photo || DEFAULT_PHOTO;
  const isDefault = photoUrl === DEFAULT_PHOTO;
  const media = `<a class="card-media${isDefault ? " card-media--default" : ""}" href="${ev.url}" target="_blank" rel="noreferrer">
       <img src="${escapeHtml(photoUrl)}" alt="${escapeHtml(displayName)}" loading="lazy"
            onerror="this.onerror=null;this.src='${DEFAULT_PHOTO}';this.parentElement.classList.add('card-media--default');">
     </a>`;

  const sourceCredit = ev.source === "gdtb"
    ? `<span class="source-credit">via <a href="${ev.url}" target="_blank" rel="noreferrer">gratefuldeadtributebands.com</a></span>`
    : "";
  const ticketsLabel = ev.source === "gdtb" ? "Details →" : "Tickets →";

  return `
    <article class="event-card" data-idx="${idx}" data-id="${ev.id}">
      ${media}
      <div class="card-body">
        <p class="card-date">${formatDate(ev.date)}${ev.time ? ` · ${escapeHtml(ev.time)}` : ""}</p>
        <h3 class="card-name">${bandLink}</h3>
        <p class="card-venue">
          ${escapeHtml(ev.venue)}<br>
          <span class="city">${escapeHtml(ev.city || "")}${ev.state ? ", " + escapeHtml(ev.state) : ""}</span>
        </p>
        <div class="card-meta">
          <span class="meta-pill ${tierClass}">${tierLabel}</span>
          <span class="meta-pill distance">${dist.toFixed(0)} mi away</span>
        </div>
        <div class="card-foot">
          <button type="button" class="show-on-map-btn" data-id="${ev.id}">Show on map</button>
          <div class="card-foot-actions">
            <button type="button" class="card-icon-btn" data-action="calendar" data-id="${ev.id}" title="Add to calendar" aria-label="Add to calendar">📅</button>
            <button type="button" class="card-icon-btn" data-action="share" data-id="${ev.id}" title="Share" aria-label="Share">↗</button>
            <a class="tickets-link" href="${ev.url}" target="_blank" rel="noreferrer">${ticketsLabel}</a>
          </div>
        </div>
        ${sourceCredit ? `<div class="card-source">${sourceCredit}</div>` : ""}
      </div>
    </article>
  `;
}

function renderEvents(events) {
  const cards = document.getElementById("cards");
  const counter = document.getElementById("result-count");
  clearEventMarkers();
  cardById.clear();

  // Drop non-Dead noise that broad TM keyword searches surfaced
  events = events.filter(isDeadRelated);
  // Client-side "Dead family only" chip filter
  if (chipState.deadOnly) {
    events = events.filter(ev => matchArtist(ev)?.tier === "core");
  }

  if (!events.length) {
    counter.textContent = "0 shows";
    cards.innerHTML = `<div class="empty-state">
      <strong>No shows in that window.</strong>
      Try a wider radius or push the date range out.
    </div>`;
    return;
  }

  events.sort((a, b) => {
    const da = new Date(a.date).getTime();
    const db = new Date(b.date).getTime();
    if (da !== db) return da - db;
    return (a.name || "").localeCompare(b.name || "");
  });
  counter.textContent = `${events.length} show${events.length === 1 ? "" : "s"} found`;

  cards.innerHTML = events.map(renderCard).join("");

  // Build inverse lookup card-by-id for marker→card sync
  cards.querySelectorAll(".event-card").forEach(el => {
    cardById.set(el.dataset.id, el);
  });

  events.forEach((ev) => {
    const artist = matchArtist(ev);
    const displayName = artist?.name || ev.name;
    const popup = `
      <strong>${escapeHtml(displayName)}</strong>
      ${escapeHtml(ev.venue)}<br>${formatDate(ev.date)}
      <a class="popup-link" href="${ev.url}" target="_blank" rel="noreferrer">Tickets →</a>
    `;
    const marker = L.marker([ev.lat, ev.lng]).addTo(map).bindPopup(popup);
    marker.on("click", () => highlightCard(ev.id, { scroll: true }));
    eventMarkers.push(marker);
    markerById.set(ev.id, marker);
  });

  // Card hover → marker popup (desktop only; pointer:fine excludes touch)
  if (window.matchMedia("(hover: hover) and (pointer: fine)").matches) {
    cards.querySelectorAll(".event-card").forEach(card => {
      const id = card.dataset.id;
      card.addEventListener("mouseenter", () => {
        const m = markerById.get(id);
        if (m) m.openPopup();
      });
      card.addEventListener("mouseleave", () => {
        const m = markerById.get(id);
        if (m) m.closePopup();
      });
    });
  }

  // Fit map to all markers + center
  const group = L.featureGroup([centerMarker, ...eventMarkers]);
  if (eventMarkers.length) map.fitBounds(group.getBounds().pad(0.12));

  // Wire show-on-map buttons
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

  // Wire per-card calendar + share icon buttons
  cards.querySelectorAll(".card-icon-btn").forEach(btn => {
    btn.addEventListener("click", (e) => {
      const id = e.currentTarget.dataset.id;
      const action = e.currentTarget.dataset.action;
      const ev = eventById(id);
      if (!ev) return;
      if (action === "calendar") downloadIcs(ev);
      else if (action === "share") shareEvent(ev);
    });
  });

  applyDeepLinkOnce();
}

function highlightCard(id, { scroll = false } = {}) {
  const card = cardById.get(id);
  if (!card) return;
  if (scroll) card.scrollIntoView({ behavior: "smooth", block: "center" });
  card.classList.add("event-card--active");
  clearTimeout(card._highlightTimer);
  card._highlightTimer = setTimeout(() => card.classList.remove("event-card--active"), 2000);
}

function applyDeepLinkOnce() {
  if (deepLinkApplied) return;
  const params = new URLSearchParams(location.search);
  const id = params.get("event");
  if (!id) return;
  const card = cardById.get(id);
  if (!card) return;
  deepLinkApplied = true;
  // defer one frame so layout has settled
  requestAnimationFrame(() => {
    card.scrollIntoView({ behavior: "smooth", block: "center" });
    card.classList.add("event-card--active");
    setTimeout(() => card.classList.remove("event-card--active"), 2500);
  });
}

async function runSearch() {
  const cards = document.getElementById("cards");
  const counter = document.getElementById("result-count");
  const btn = document.getElementById("search");
  btn.disabled = true;
  cards.innerHTML = `<div class="loading">Searching Ticketmaster</div>`;
  counter.textContent = "Loading…";
  try {
    await resolveCenter();
    drawCenter();
    map.setView([currentCenter.lat, currentCenter.lng], 9);
    lastEvents = await fetchEvents();
    renderEvents(lastEvents);
  } catch (err) {
    counter.textContent = "Error";
    cards.innerHTML = `<div class="empty-state"><strong>Something went wrong.</strong>${escapeHtml(err.message)}</div>`;
    console.error(err);
  } finally {
    btn.disabled = false;
  }
}

function wireChips() {
  document.querySelectorAll(".chip").forEach(btn => {
    btn.addEventListener("click", () => {
      const c = btn.dataset.chip;
      if (c === "tonight" || c === "weekend" || c === "next30") {
        applyDateChip(c);
        updateChipUi();
        runSearch();
      } else if (c === "radius25") {
        chipState.radius25 = !chipState.radius25;
        if (chipState.radius25) {
          const slider = document.getElementById("radius");
          slider.value = "25";
          document.getElementById("radius-val").textContent = "25";
          drawCenter();
          updateChipUi();
          runSearch();
        } else {
          updateChipUi();
        }
      } else if (c === "deadOnly") {
        chipState.deadOnly = !chipState.deadOnly;
        updateChipUi();
        // Pure client-side filter — re-render the cached results, no refetch
        renderEvents(lastEvents);
      }
    });
  });
}

function wireControls() {
  document.getElementById("radius").addEventListener("input", (e) => {
    document.getElementById("radius-val").textContent = e.target.value;
    drawCenter();
    if (chipState.radius25 && e.target.value !== "25") {
      chipState.radius25 = false;
      updateChipUi();
    }
  });
  ["start-date", "end-date"].forEach(id => {
    document.getElementById(id).addEventListener("change", () => {
      if (chipState.date !== "custom") {
        chipState.date = "custom";
        updateChipUi();
      }
    });
  });
  document.getElementById("search").addEventListener("click", runSearch);
  document.getElementById("locate").addEventListener("click", () => {
    const btn = document.getElementById("locate");
    if (!navigator.geolocation) {
      alert("Your browser doesn't support geolocation. Type a city or address instead.");
      return;
    }
    btn.disabled = true;
    btn.textContent = "…";
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        currentCenter = { lat: pos.coords.latitude, lng: pos.coords.longitude, label: "My location" };
        document.getElementById("center").value = "";
        btn.textContent = "📍";
        btn.disabled = false;
        drawCenter();
        map.setView([currentCenter.lat, currentCenter.lng], 10);
        runSearch();
      },
      (err) => {
        btn.textContent = "📍";
        btn.disabled = false;
        const reasons = {
          1: "Permission denied. Allow location access in your browser settings, or type a city/address instead.",
          2: "Location unavailable. Try again in a moment, or type a city/address.",
          3: "Location lookup timed out. Try again, or type a city/address.",
        };
        alert(reasons[err.code] || `Location error: ${err.message}`);
      },
      { enableHighAccuracy: false, timeout: 10000, maximumAge: 60000 },
    );
  });
  document.getElementById("center").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });
}

async function init() {
  initMap();
  applyDateChip("next30");
  updateChipUi();
  wireChips();
  wireControls();
  await loadArtists();
  await loadGdtb();
  // Auto-run on load so the page isn't empty
  runSearch();
}

init();
