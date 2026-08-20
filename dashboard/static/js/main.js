const SEVERITY_COLORS = { HIGH: "#ff5c5c", MEDIUM: "#ffb454", LOW: "#ffe27a" };

let map, markersLayer;
let charts = {};
let allDetections = [];
let allSessions = [];

async function fetchJSON(url) {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

function qs(params) {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v !== null && v !== undefined) p.append(k, v);
  }
  return p.toString();
}

function initMap() {
  map = L.map("map").setView([12.9716, 77.5946], 11); // Bengaluru center
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap contributors",
    maxZoom: 19,
  }).addTo(map);
  markersLayer = L.layerGroup().addTo(map);
}

function severityColor(sev) {
  return SEVERITY_COLORS[sev] || "#999";
}

function renderMarkers(detections) {
  markersLayer.clearLayers();
  for (const d of detections) {
    const marker = L.circleMarker([d.latitude, d.longitude], {
      radius: 6,
      color: severityColor(d.severity),
      fillColor: severityColor(d.severity),
      fillOpacity: 0.85,
      weight: 1,
    });
    marker.bindPopup(`
      <b>${d.pothole_id}</b><br>
      ${d.locality !== "Unknown" ? d.locality : d.city}, Bengaluru<br>
      Ward: ${d.ward}<br>
      Severity: <b style="color:${severityColor(d.severity)}">${d.severity}</b><br>
      Confidence: ${(d.confidence * 100).toFixed(0)}%<br>
      GPS: ${d.latitude.toFixed(5)}, ${d.longitude.toFixed(5)}<br>
      Time: ${new Date(d.timestamp).toLocaleString()}<br>
      <a href="#" onclick="openDetail('${d.pothole_id}');return false;">View evidence &rarr;</a>
    `);
    markersLayer.addLayer(marker);
  }
}

function renderStats(stats) {
  const cards = [
    { label: "Total Potholes", value: stats.total_potholes, cls: "" },
    { label: "High Severity", value: stats.high_severity, cls: "high" },
    { label: "Medium Severity", value: stats.medium_severity, cls: "medium" },
    { label: "Low Severity", value: stats.low_severity, cls: "low" },
    { label: "Today", value: stats.today, cls: "" },
    { label: "This Week", value: stats.this_week, cls: "" },
    { label: "Distance Surveyed", value: `${stats.total_distance_km} km`, cls: "" },
    { label: "Sessions", value: stats.total_sessions, cls: "" },
    { label: "Top Zone", value: stats.most_affected_zone || "—", cls: "" },
    { label: "Top Ward", value: stats.most_affected_ward || "—", cls: "" },
    { label: "Top Locality", value: stats.most_affected_locality || "—", cls: "" },
  ];
  document.getElementById("stats-grid").innerHTML = cards
    .map(c => `<div class="stat-card ${c.cls}"><div class="label">${c.label}</div><div class="value">${c.value}</div></div>`)
    .join("");
}

function makeChart(id, type, labels, data, colors) {
  const ctx = document.getElementById(id);
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(ctx, {
    type,
    data: {
      labels,
      datasets: [{ data, backgroundColor: colors || "#3ca7ff", borderRadius: 4 }],
    },
    options: {
      plugins: { legend: { display: type === "doughnut", labels: { color: "#94a0b4", boxWidth: 10 } } },
      scales: type === "bar" || type === "line" ? {
        x: { ticks: { color: "#94a0b4", font: { size: 10 } }, grid: { color: "#2a3140" } },
        y: { ticks: { color: "#94a0b4" }, grid: { color: "#2a3140" }, beginAtZero: true },
      } : {},
      maintainAspectRatio: false,
    },
  });
}

function renderAnalytics(analytics) {
  const sevOrder = ["HIGH", "MEDIUM", "LOW"];
  const sevData = sevOrder.map(s => (analytics.by_severity.find(r => r.label === s) || { count: 0 }).count);
  makeChart("chart-severity", "doughnut", sevOrder, sevData, sevOrder.map(severityColor));

  const zone = analytics.by_zone.slice(0, 10);
  makeChart("chart-zone", "bar", zone.map(r => r.label), zone.map(r => r.count));

  const ward = analytics.by_ward.slice(0, 10);
  makeChart("chart-ward", "bar", ward.map(r => r.label), ward.map(r => r.count));

  const locality = analytics.by_locality.slice(0, 10);
  makeChart("chart-locality", "bar", locality.map(r => r.label), locality.map(r => r.count));

  const time = analytics.over_time;
  makeChart("chart-time", "line", time.map(r => r.date), time.map(r => r.count));
}

function renderTable(detections) {
  document.getElementById("table-count").textContent = `(${detections.length})`;
  const rows = detections.slice(0, 500).map(d => `
    <tr onclick="openDetail('${d.pothole_id}')">
      <td>${d.pothole_id}</td>
      <td>${new Date(d.timestamp).toLocaleString()}</td>
      <td>${d.locality !== "Unknown" ? d.locality : d.city}</td>
      <td>${d.zone}</td>
      <td>${d.ward}</td>
      <td><span class="sev-tag sev-${d.severity}">${d.severity}</span></td>
      <td>${(d.confidence * 100).toFixed(0)}%</td>
      <td>${d.latitude.toFixed(4)}, ${d.longitude.toFixed(4)}</td>
      <td>${d.session_id}</td>
      <td>${d.duplicate_status}</td>
    </tr>
  `).join("");
  document.getElementById("detections-tbody").innerHTML = rows;
}

async function openDetail(potholeId) {
  const d = await fetchJSON(`/api/detections/${potholeId}`);
  const hasImage = !!d.annotated_image_path;
  document.getElementById("modal-body").innerHTML = `
    <h3>${d.pothole_id}</h3>
    ${hasImage ? `<img src="/api/evidence/${d.pothole_id}/annotated" alt="evidence">` : "<p>No evidence image recorded.</p>"}
    <div class="kv">
      <div>Timestamp</div><div>${new Date(d.timestamp).toLocaleString()}</div>
      <div>Location</div><div>${d.formatted_address !== "Unknown" ? d.formatted_address : `${d.locality}, ${d.city}`}</div>
      <div>Zone / Ward</div><div>${d.zone} / ${d.ward}</div>
      <div>GPS</div><div>${d.latitude.toFixed(6)}, ${d.longitude.toFixed(6)} (±${d.gps_accuracy}m, ${d.gps_sync_method})</div>
      <div>Confidence</div><div>${(d.confidence * 100).toFixed(1)}%</div>
      <div>Severity</div><div>${d.severity}</div>
      <div>Frames tracked</div><div>${d.frame_count}</div>
      <div>Duplicate status</div><div>${d.duplicate_status}${d.duplicate_of ? ` (of ${d.duplicate_of})` : ""}</div>
      <div>Session</div><div>${d.session_id}</div>
    </div>
    <button id="btn-delete-detection" class="btn" style="margin-top:14px;background:var(--high);color:#250000;">
      Delete this detection
    </button>
  `;
  document.getElementById("btn-delete-detection").addEventListener("click", () => deleteDetection(d.pothole_id));
  document.getElementById("detail-modal").classList.remove("hidden");
}

async function deleteDetection(potholeId) {
  if (!confirm(`Delete ${potholeId} permanently? This removes it (and its evidence photos) from the dashboard and can't be undone.`)) {
    return;
  }
  await fetch(`/api/detections/${potholeId}`, { method: "DELETE" });
  closeDetail();
  applyFilters();
}

function closeDetail() {
  document.getElementById("detail-modal").classList.add("hidden");
}

function populateSelect(id, values) {
  const el = document.getElementById(id);
  const current = el.value;
  el.innerHTML = `<option value="">All</option>` + values.map(v => `<option value="${v}">${v}</option>`).join("");
  el.value = current;
}

function uniqueSorted(detections, key) {
  return [...new Set(detections.map(d => d[key]).filter(v => v && v !== "Unknown"))].sort();
}

async function applyFilters() {
  const params = {
    zone: document.getElementById("f-zone").value,
    ward: document.getElementById("f-ward").value,
    locality: document.getElementById("f-locality").value,
    severity: document.getElementById("f-severity").value,
    session_id: document.getElementById("f-session").value,
    min_confidence: document.getElementById("f-confidence").value,
    start_date: document.getElementById("f-start-date").value,
    end_date: document.getElementById("f-end-date").value ? document.getElementById("f-end-date").value + "T23:59:59" : "",
  };
  const detections = await fetchJSON(`/api/detections?${qs(params)}`);
  renderMarkers(detections);
  renderTable(detections);
}

function resetFilters() {
  ["f-zone", "f-ward", "f-locality", "f-severity", "f-session", "f-start-date", "f-end-date"].forEach(id => document.getElementById(id).value = "");
  document.getElementById("f-confidence").value = 0;
  document.getElementById("f-confidence-val").textContent = "0.0";
  applyFilters();
}

async function init() {
  initMap();

  const [stats, analytics, detections, sessions] = await Promise.all([
    fetchJSON("/api/stats"),
    fetchJSON("/api/analytics"),
    fetchJSON("/api/detections"),
    fetchJSON("/api/sessions"),
  ]);

  allDetections = detections;
  allSessions = sessions;

  renderStats(stats);
  renderAnalytics(analytics);
  renderMarkers(detections);
  renderTable(detections);

  populateSelect("f-zone", uniqueSorted(detections, "zone"));
  populateSelect("f-ward", uniqueSorted(detections, "ward"));
  populateSelect("f-locality", uniqueSorted(detections, "locality"));
  populateSelect("f-session", [...new Set(sessions.map(s => s.session_id))]);

  document.getElementById("f-confidence").addEventListener("input", e => {
    document.getElementById("f-confidence-val").textContent = parseFloat(e.target.value).toFixed(2);
  });
  document.getElementById("btn-apply-filters").addEventListener("click", applyFilters);
  document.getElementById("btn-reset-filters").addEventListener("click", resetFilters);
  document.getElementById("modal-close").addEventListener("click", closeDetail);
  document.getElementById("detail-modal").addEventListener("click", e => { if (e.target.id === "detail-modal") closeDetail(); });
  document.getElementById("btn-export-csv").addEventListener("click", () => window.location.href = "/api/export/csv");
  document.getElementById("btn-export-json").addEventListener("click", () => window.location.href = "/api/export/json");
}

window.openDetail = openDetail;
document.addEventListener("DOMContentLoaded", init);
