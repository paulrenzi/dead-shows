// Dead Shows — frontend
// Edit WORKER_URL after deploying the Cloudflare Worker.
const WORKER_URL = "https://dead-shows.paulmichaelrenzi.workers.dev";

const KOP = { lat: 40.0890, lng: -75.3960, label: "King of Prussia, PA" };

let map, centerMarker, radiusCircle;
let eventMarkers = [];
let currentCenter = { ...KOP };

function initMap() {
  map = L.map("map").setView([KOP.lat, KOP.lng], 9);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "© OpenStreetMap",
    maxZoom: 18,
  }).addTo(map);
  drawCenter();
}

function drawCenter() {
  if (centerMarker) map.removeLayer(centerMarker);
  if (radiusCircle) map.removeLayer(radiusCircle);
  centerMarker = L.marker([currentCenter.lat, currentCenter.lng], {
    title: currentCenter.label || "Search center",
  }).addTo(map).bindPopup(`<b>${currentCenter.label || "Center"}</b>`);
  const miles = parseInt(document.getElementById("radius").value, 10);
  radiusCircle = L.circle([currentCenter.lat, currentCenter.lng], {
    radius: miles * 1609.34,
    color: "#d32027",
    weight: 1,
    fillOpacity: 0.05,
  }).addTo(map);
}

function clearEventMarkers() {
  eventMarkers.forEach(m => map.removeLayer(m));
  eventMarkers = [];
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

function setDefaultDates() {
  const today = new Date();
  const ninety = new Date(today);
  ninety.setDate(ninety.getDate() + 90);
  document.getElementById("start-date").value = today.toISOString().slice(0, 10);
  document.getElementById("end-date").value = ninety.toISOString().slice(0, 10);
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
    currentCenter = { ...KOP };
    return;
  }
  const setStatus = document.getElementById("status");
  setStatus.textContent = `Looking up "${txt}"…`;
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
  return r.json();
}

function renderEvents(events) {
  const list = document.getElementById("list");
  const status = document.getElementById("status");
  list.innerHTML = "";
  clearEventMarkers();

  if (!events.length) {
    status.textContent = "No shows in that window. Try a wider radius or date range.";
    return;
  }

  events.sort((a, b) => new Date(a.date) - new Date(b.date));
  status.textContent = `${events.length} show${events.length === 1 ? "" : "s"} found.`;

  events.forEach((ev, idx) => {
    const dist = haversineMiles(currentCenter.lat, currentCenter.lng, ev.lat, ev.lng);
    ev._distance = dist;

    const marker = L.marker([ev.lat, ev.lng]).addTo(map)
      .bindPopup(`<b>${ev.name}</b><br>${ev.venue}<br>${formatDate(ev.date)}<br><a href="${ev.url}" target="_blank">Tickets</a>`);
    eventMarkers.push(marker);

    const li = document.createElement("li");
    li.dataset.idx = idx;
    li.innerHTML = `
      <div class="event-name">${escapeHtml(ev.name)}</div>
      <div class="event-meta">
        <span class="distance">${dist.toFixed(0)} mi</span>
        <span class="date">${formatDate(ev.date)}</span> · ${escapeHtml(ev.venue)}, ${escapeHtml(ev.city || "")}
      </div>
      <a class="event-link" href="${ev.url}" target="_blank" rel="noopener">Tickets →</a>
    `;
    li.addEventListener("click", (e) => {
      if (e.target.tagName === "A") return;
      map.setView([ev.lat, ev.lng], 11);
      marker.openPopup();
      document.querySelectorAll("#list li").forEach(x => x.classList.remove("active"));
      li.classList.add("active");
    });
    list.appendChild(li);
  });

  // fit map to all markers + center
  const group = L.featureGroup([centerMarker, ...eventMarkers]);
  map.fitBounds(group.getBounds().pad(0.1));
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

async function runSearch() {
  const status = document.getElementById("status");
  const btn = document.getElementById("search");
  btn.disabled = true;
  try {
    await resolveCenter();
    drawCenter();
    map.setView([currentCenter.lat, currentCenter.lng], 9);
    status.textContent = "Searching Ticketmaster…";
    const events = await fetchEvents();
    renderEvents(events);
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    console.error(err);
  } finally {
    btn.disabled = false;
  }
}

function wireControls() {
  document.getElementById("radius").addEventListener("input", (e) => {
    document.getElementById("radius-val").textContent = e.target.value;
    drawCenter();
  });
  document.getElementById("search").addEventListener("click", runSearch);
  document.getElementById("locate").addEventListener("click", () => {
    if (!navigator.geolocation) {
      alert("Geolocation not available");
      return;
    }
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        currentCenter = { lat: pos.coords.latitude, lng: pos.coords.longitude, label: "My location" };
        document.getElementById("center").value = "";
        drawCenter();
        map.setView([currentCenter.lat, currentCenter.lng], 10);
      },
      (err) => alert(`Location error: ${err.message}`),
    );
  });
  document.getElementById("center").addEventListener("keydown", (e) => {
    if (e.key === "Enter") runSearch();
  });
}

initMap();
setDefaultDates();
wireControls();
