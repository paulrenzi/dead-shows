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
const chipState = { date: "next30" };
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
    const active = chipState.date === btn.dataset.chip;
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

// Inline Feather-style SVGs — monochrome, inherit currentColor, no emoji
// rendering inconsistencies between iOS / Android / desktop.
const ICON_CALENDAR = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><rect x="3" y="4" width="18" height="18" rx="2"></rect><line x1="16" y1="2" x2="16" y2="6"></line><line x1="8" y1="2" x2="8" y2="6"></line><line x1="3" y1="10" x2="21" y2="10"></line></svg>`;
const ICON_SHARE = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false"><path d="M4 12v8a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-8"></path><polyline points="16 6 12 2 8 6"></polyline><line x1="12" y1="2" x2="12" y2="15"></line></svg>`;

function formatPrice(price) {
  if (!price || typeof price.min !== "number") return null;
  const sym = price.currency === "USD" ? "$" : (price.currency || "");
  const fmt = n => Number.isInteger(n) ? String(n) : n.toFixed(2);
  if (price.min === 0 && (!price.max || price.max === 0)) return "Free";
  if (price.min === 0) return "From free";
  return `From ${sym}${fmt(price.min)}`;
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

function buildIcsText(ev) {
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
  return lines.join("\r\n");
}

const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
               (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

function appleCalendarHref(ev) {
  // iOS Safari: a data: URL with no `download` attribute opens the native
  // "Add to Calendar" sheet. With `download`, iOS routes it to Files instead.
  // Desktop/Android: blob: URL + download attribute → normal file save.
  const text = buildIcsText(ev);
  if (IS_IOS) {
    const b64 = btoa(unescape(encodeURIComponent(text)));
    return { href: `data:text/calendar;charset=utf-8;base64,${b64}`, download: null };
  }
  const blob = new Blob([text], { type: "text/calendar" });
  const slug = matchArtist(ev)?.slug || "event";
  return {
    href: URL.createObjectURL(blob),
    download: `${slug}-${(ev.date || "").slice(0, 10)}.ics`,
  };
}

function googleCalendarUrl(ev) {
  const artist = matchArtist(ev);
  const title = (artist?.name || ev.name || "Show").trim();
  const where = [ev.venue, ev.city, ev.state].filter(Boolean).join(", ");
  const { dtstart, dtend } = buildIcsDates(ev);
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: title,
    dates: `${dtstart}/${dtend}`,
    location: where,
    details: `via Dead Shows${ev.url ? "\n" + ev.url : ""}`,
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
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

  const priceLabel = formatPrice(ev.price);
  const showTickets = isTicketUrl(ev);

  const googleHref = googleCalendarUrl(ev);
  const apple = appleCalendarHref(ev);
  const appleAttrs = apple.download
    ? ` download="${escapeHtml(apple.download)}"`
    : "";

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
          ${priceLabel ? `<span class="meta-pill price">${escapeHtml(priceLabel)}</span>` : ""}
        </div>
        <div class="card-foot">
          <button type="button" class="show-on-map-btn" data-id="${ev.id}">Show on map</button>
          <div class="card-foot-actions">
            <div class="card-cal">
              <button type="button" class="card-icon-btn card-cal-toggle" data-id="${ev.id}" aria-haspopup="true" aria-expanded="false" title="Add to calendar" aria-label="Add to calendar">${ICON_CALENDAR}</button>
              <div class="card-cal-menu" role="menu" hidden>
                <a class="card-cal-link" role="menuitem" target="_blank" rel="noopener" href="${escapeHtml(googleHref)}">Google</a>
                <a class="card-cal-link" role="menuitem" href="${escapeHtml(apple.href)}"${appleAttrs}>Apple</a>
              </div>
            </div>
            <button type="button" class="card-icon-btn" data-action="share" data-id="${ev.id}" title="Share" aria-label="Share">${ICON_SHARE}</button>
            ${showTickets ? `<a class="tickets-link" href="${ev.url}" target="_blank" rel="noreferrer">Tickets →</a>` : ""}
          </div>
        </div>
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
    const tm = isTicketUrl(ev);
    const popupHref = tm ? ev.url : venueGoogleMapsUrl(ev);
    const popupLabel = tm ? "Tickets →" : "Venue info →";
    const popup = `
      <strong>${escapeHtml(displayName)}</strong>
      ${escapeHtml(ev.venue)}<br>${formatDate(ev.date)}
      <a class="popup-link" href="${escapeHtml(popupHref)}" target="_blank" rel="noreferrer">${popupLabel}</a>
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
        scrollMapIntoView();
      }
    });
  });

  // Calendar popover toggle (Google/Apple chooser per card)
  cards.querySelectorAll(".card-cal-toggle").forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const menu = btn.nextElementSibling;
      const wasHidden = menu.hidden;
      closeAllCalendarMenus();
      if (wasHidden) {
        menu.hidden = false;
        btn.setAttribute("aria-expanded", "true");
      }
    });
  });
  // Closing the menu after the user picks one is desirable; the link still navigates
  cards.querySelectorAll(".card-cal-link").forEach(link => {
    link.addEventListener("click", () => closeAllCalendarMenus());
  });

  // Share button
  cards.querySelectorAll('.card-icon-btn[data-action="share"]').forEach(btn => {
    btn.addEventListener("click", (e) => {
      const id = e.currentTarget.dataset.id;
      const ev = eventById(id);
      if (ev) shareEvent(ev);
    });
  });

  applyDeepLinkOnce();
}

function scrollMapIntoView() {
  // The strip is position: sticky at the top — scrollIntoView({block: "nearest"})
  // lands the map under it. Compute the strip's visible height and offset by it.
  const mapEl = document.getElementById("map");
  const strip = document.querySelector(".strip");
  const stripH = strip ? strip.getBoundingClientRect().height : 0;
  const targetTop = mapEl.getBoundingClientRect().top + window.scrollY - stripH - 12;
  window.scrollTo({ top: Math.max(0, targetTop), behavior: "smooth" });
}

function venueGoogleMapsUrl(ev) {
  const q = [ev.venue, ev.city, ev.state].filter(Boolean).join(" ");
  return `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`;
}

// TM events have a real ticket URL; GDTB items point at the band's directory
// page (not the venue), so for those we link to the venue on Google Maps.
function isTicketUrl(ev) {
  if (ev.source === "gdtb") return false;
  if (!ev.url) return false;
  return !/gratefuldeadtributebands\.com/i.test(ev.url);
}

function closeAllCalendarMenus() {
  document.querySelectorAll(".card-cal-menu").forEach(m => {
    if (!m.hidden) {
      m.hidden = true;
      const btn = m.previousElementSibling;
      if (btn) btn.setAttribute("aria-expanded", "false");
    }
  });
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
      applyDateChip(btn.dataset.chip);
      updateChipUi();
      runSearch();
    });
  });
}

function wireControls() {
  document.getElementById("radius").addEventListener("input", (e) => {
    document.getElementById("radius-val").textContent = e.target.value;
    drawCenter();
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
  // Close any open calendar popover on outside click / Escape
  document.addEventListener("click", closeAllCalendarMenus);
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeAllCalendarMenus(); });
  await loadArtists();
  await loadGdtb();
  // Auto-run on load so the page isn't empty
  runSearch();
}

init();
