// Firecloud static map: reads the published manifests and grid sidecars and
// draws them on one canvas. No framework, no build step, same-origin files only.
"use strict";

const INDEX_URL = "products/latest/index.json";
const MISSING_COLOR = "#bdbdbd";

const ui = {
  product: document.getElementById("product"),
  date: document.getElementById("date"),
  event: document.getElementById("event"),
  message: document.getElementById("message"),
  canvas: document.getElementById("map"),
  fallback: document.getElementById("fallback"),
  legend: document.getElementById("legend"),
  readout: document.getElementById("readout"),
};

// products: key -> {label, items: [{date, event, url, manifest, metadata, endsAt}]}
const products = new Map();
let current = null; // {manifest, url, grid, metadata, view}
// Index ranges left off the map, keyed by their lower bound ("0.00") or "missing".
// The choice carries across products, which share the same classes.
const hiddenRanges = new Set(["0.00"]);

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-cache" });
  if (!response.ok) throw new Error(`${url}: HTTP ${response.status}`);
  return response.json();
}

function titleCase(text) {
  return text.replace(/[-_]+/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function productKey(manifest) {
  if (manifest.scope !== "point") return { key: "national", label: "China (national screening)" };
  const name = titleCase(manifest.location_name || manifest.location_slug || "point");
  return { key: `${manifest.region || "china"}:${manifest.location_slug}`, label: `${name} (local)` };
}

function setMessage(text) {
  ui.message.textContent = text || "";
  ui.message.hidden = !text;
}

// When the event has finished everywhere on the map, in ms. Null if unknown.
function eventEnd(metadata) {
  if (!metadata) return null;
  const last = metadata.event_range_utc ? metadata.event_range_utc[1] : metadata.event_time_utc;
  return last ? Date.parse(last) : null;
}

function fillSelect(select, values, label) {
  const previous = select.value;
  select.replaceChildren(...values.map((value) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label ? label(value) : value;
    return option;
  }));
  if (values.includes(previous)) select.value = previous;
}

async function loadCatalog() {
  let index;
  try {
    index = await getJSON(INDEX_URL);
  } catch (error) {
    setMessage("No published forecast found.");
    ui.canvas.hidden = true;
    return false;
  }
  const paths = [...(index.manifests || [])];
  for (const list of Object.values(index.regional || {})) paths.push(...list);
  const base = new URL(INDEX_URL, document.baseURI);
  const loaded = await Promise.all(paths.map(async (path) => {
    const url = new URL(path, base);
    let manifest;
    try {
      manifest = await getJSON(url);
    } catch (error) {
      console.warn("Skipping manifest", path, error);
      return null;
    }
    let metadata = null;
    try {
      metadata = await getJSON(new URL(manifest.artifacts.metadata.path, url));
    } catch (error) {
      console.warn("Metadata unavailable", path, error);
    }
    return { url, manifest, metadata };
  }));
  for (const entry of loaded) {
    if (!entry) continue;
    const { key, label } = productKey(entry.manifest);
    if (!products.has(key)) products.set(key, { label, items: [] });
    products.get(key).items.push({
      date: entry.manifest.target_date,
      event: entry.manifest.event,
      url: entry.url,
      manifest: entry.manifest,
      metadata: entry.metadata,
      endsAt: eventEnd(entry.metadata),
    });
  }
  if (!products.size) {
    setMessage("No published forecast found.");
    ui.canvas.hidden = true;
    return false;
  }
  const keys = [...products.keys()].sort((a, b) => (a === "national" ? -1 : b === "national" ? 1 : a.localeCompare(b)));
  fillSelect(ui.product, keys, (key) => products.get(key).label);
  return true;
}

function refreshChoices(target) {
  const items = products.get(ui.product.value).items;
  const dates = [...new Set(items.map((item) => item.date))].sort();
  fillSelect(ui.date, dates);
  if (target) ui.date.value = target.date;
  const events = ["sunrise", "sunset"].filter((event) => items.some((item) => item.date === ui.date.value && item.event === event));
  fillSelect(ui.event, events);
  if (target) ui.event.value = target.event;
}

// The selected event if it is still ahead, else the next one, else the latest.
function upcomingItem() {
  const now = Date.now();
  const timed = products.get(ui.product.value).items
    .filter((item) => item.endsAt !== null)
    .sort((a, b) => a.endsAt - b.endsAt);
  const kept = timed.find((item) => item.date === ui.date.value && item.event === ui.event.value && item.endsAt > now);
  return kept || timed.find((item) => item.endsAt > now) || timed[timed.length - 1] || null;
}

function selectedItem() {
  return products.get(ui.product.value).items.find(
    (item) => item.date === ui.date.value && item.event === ui.event.value,
  );
}

async function show(target) {
  refreshChoices(target);
  const item = selectedItem();
  ui.readout.textContent = "Click a cell.";
  if (!item) return;
  const { manifest, url, metadata } = item;
  const lines = [];
  if (manifest.valid_until && Date.parse(manifest.valid_until) < Date.now()) {
    lines.push(`This forecast is out of date (generated ${utcText(manifest.generated_at)} UTC).`);
  }
  const artifacts = manifest.artifacts || {};
  if (!artifacts.grid) {
    lines.push("Cell values are not available for this product.");
    setMessage(lines.join(" "));
    ui.canvas.hidden = true;
    ui.fallback.hidden = false;
    ui.fallback.src = new URL(artifacts.image.path, url).href;
    ui.legend.textContent = "";
    current = null;
    return;
  }
  setMessage(lines.join(" "));
  let grid;
  try {
    grid = await getJSON(new URL(artifacts.grid.path, url));
  } catch (error) {
    // Never leave the previous product on screen under the new selection.
    lines.push("Cell values could not be loaded for this product.");
    setMessage(lines.join(" "));
    current = null;
    ui.canvas.hidden = true;
    ui.fallback.hidden = false;
    ui.fallback.src = new URL(artifacts.image.path, url).href;
    ui.legend.textContent = "";
    return;
  }
  ui.fallback.hidden = true;
  ui.canvas.hidden = false;
  current = { manifest, url, grid, metadata, view: null };
  draw();
  drawLegend(grid);
}

// Cell edges halfway between sample centres, as the PNG draws them.
function edges(centres) {
  const n = centres.length;
  if (n === 1) return [centres[0] - 0.125, centres[0] + 0.125];
  const out = [centres[0] - (centres[1] - centres[0]) / 2];
  for (let i = 0; i < n - 1; i += 1) out.push((centres[i] + centres[i + 1]) / 2);
  out.push(centres[n - 1] + (centres[n - 1] - centres[n - 2]) / 2);
  return out;
}

function inDomain(grid, j, i) {
  return !grid.in_domain || grid.in_domain[j][i];
}

// The legend class of a value: its key and colour.
function rangeOf(value, grid) {
  if (value === null || value === undefined) return ["missing", grid.no_data_color || MISSING_COLOR];
  let found = grid.colors[0];
  for (const stop of grid.colors) if (value >= stop[0]) found = stop;
  return [found[0].toFixed(2), found[1]];
}

function colorFor(value, grid) {
  const [key, color] = rangeOf(value, grid);
  return hiddenRanges.has(key) ? "#ffffff" : color;
}

function draw() {
  const { grid } = current;
  const latEdges = edges(grid.lats);
  const lonEdges = edges(grid.lons);
  const south = latEdges[0];
  const north = latEdges[latEdges.length - 1];
  const west = lonEdges[0];
  const east = lonEdges[lonEdges.length - 1];
  // Equirectangular with the standard parallel at the map's middle latitude.
  const kx = Math.cos(((south + north) / 2) * Math.PI / 180);
  // The canvas content box, not its parent: padding or borders would scale it.
  const cssWidth = ui.canvas.clientWidth;
  if (!cssWidth) return;
  const scale = cssWidth / ((east - west) * kx);
  const cssHeight = (north - south) * scale;
  const ratio = window.devicePixelRatio || 1;
  ui.canvas.width = Math.round(cssWidth * ratio);
  ui.canvas.height = Math.round(cssHeight * ratio);
  ui.canvas.style.height = `${cssHeight}px`;
  const px = (lon) => (lon - west) * kx * scale * ratio;
  const py = (lat) => (north - lat) * scale * ratio;
  current.view = { west, north, kx, scale, ratio, latEdges, lonEdges };

  const ctx = ui.canvas.getContext("2d");
  ctx.fillStyle = "#ffffff";
  ctx.fillRect(0, 0, ui.canvas.width, ui.canvas.height);
  for (let j = 0; j < grid.lats.length; j += 1) {
    const y0 = py(latEdges[j + 1]);
    const y1 = py(latEdges[j]);
    for (let i = 0; i < grid.lons.length; i += 1) {
      const x0 = px(lonEdges[i]);
      const x1 = px(lonEdges[i + 1]);
      // Cells outside the product's coverage stay blank, as in the PNG.
      ctx.fillStyle = inDomain(grid, j, i) ? colorFor(grid.index[j][i], grid) : "#ffffff";
      // Round outward so neighbouring cells leave no hairline gaps.
      ctx.fillRect(Math.floor(x0), Math.floor(y0), Math.ceil(x1) - Math.floor(x0), Math.ceil(y1) - Math.floor(y0));
    }
  }
  ctx.strokeStyle = "#000000";
  ctx.lineWidth = ratio;
  for (const line of grid.lines || []) {
    ctx.beginPath();
    line.forEach(([lon, lat], k) => (k ? ctx.lineTo(px(lon), py(lat)) : ctx.moveTo(px(lon), py(lat))));
    ctx.stroke();
  }
  if (grid.center) {
    const x = px(grid.center[1]);
    const y = py(grid.center[0]);
    const r = 5 * ratio;
    ctx.beginPath();
    ctx.moveTo(x - r, y);
    ctx.lineTo(x + r, y);
    ctx.moveTo(x, y - r);
    ctx.lineTo(x, y + r);
    ctx.stroke();
  }
}

// One checkbox per index range; an unticked range is drawn blank.
function legendEntry(key, color, text) {
  const label = document.createElement("label");
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = !hiddenRanges.has(key);
  box.addEventListener("change", () => {
    if (box.checked) hiddenRanges.delete(key);
    else hiddenRanges.add(key);
    if (current) draw();
  });
  const swatch = document.createElement("span");
  swatch.style.background = color;
  label.append(box, swatch, text);
  return label;
}

function drawLegend(grid) {
  const parts = [document.createTextNode("Show: ")];
  grid.colors.forEach(([bound, hex], k) => {
    const upper = k + 1 < grid.colors.length ? grid.colors[k + 1][0] : 1;
    parts.push(legendEntry(bound.toFixed(2), hex, `${bound.toFixed(2)}–${upper.toFixed(2)}`));
  });
  parts.push(legendEntry("missing", grid.no_data_color || MISSING_COLOR, "missing"));
  ui.legend.replaceChildren(...parts);
}

// Index of the cell whose edges contain value (edges ascending).
function cellIndex(edgeList, value) {
  if (value < edgeList[0] || value > edgeList[edgeList.length - 1]) return -1;
  let k = 0;
  while (k < edgeList.length - 2 && value >= edgeList[k + 1]) k += 1;
  return k;
}

function utcText(iso) {
  if (!iso) return "-";
  return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
}

function clock(iso) {
  return iso ? iso.slice(11, 16) : "-";
}

function eventLine(grid, metadata, event) {
  if (metadata && metadata.event_time_local) {
    const local = metadata.event_time_local;
    const zone = metadata.event_timezone_abbreviation || "local";
    return `${event} ${local.slice(0, 10)} ${clock(local)} ${zone} (${clock(metadata.event_time_utc)} UTC)`;
  }
  if (grid.event_time_utc) return `${event} ${utcText(grid.event_time_utc)} UTC`;
  if (metadata && metadata.event_range_utc) {
    const [first, last] = metadata.event_range_utc;
    return `${event}, varies by place: ${utcText(first)} to ${clock(last)} UTC`;
  }
  return event;
}

function gfsLine(grid, metadata) {
  const timing = metadata && metadata.gfs_timing;
  if (timing && timing.initialization_time_utc) {
    const run = timing.initialization_time_utc;
    return `${run.slice(0, 10)} ${run.slice(11, 13)}Z, forecast hour f${String(timing.forecast_hour).padStart(2, "0")}`;
  }
  const label = (metadata && metadata.source_label) || grid.source_label || "";
  const found = [...label.matchAll(/gfs@(\d{4}-\d{2}-\d{2})T(\d{2})Z\+f(\d+)/g)];
  if (!found.length) return "-";
  const runs = [...new Set(found.map((m) => `${m[1]} ${m[2]}Z`))];
  const hours = [...new Set(found.map((m) => `f${m[3].padStart(2, "0")}`))];
  return `${runs.join(", ")}, forecast hour ${hours.join(", ")}`;
}

function row(label, value) {
  return `${label.padEnd(12)}${value}`;
}

function onClick(clickEvent) {
  if (!current || !current.view) return;
  const { grid, metadata, manifest, view } = current;
  // Map through bitmap pixels, the same space draw() painted in.
  const rect = ui.canvas.getBoundingClientRect();
  const bx = (clickEvent.clientX - rect.left) * (ui.canvas.width / rect.width);
  const by = (clickEvent.clientY - rect.top) * (ui.canvas.height / rect.height);
  const lon = view.west + bx / (view.kx * view.scale * view.ratio);
  const lat = view.north - by / (view.scale * view.ratio);
  const i = cellIndex(view.lonEdges, lon);
  const j = cellIndex(view.latEdges, lat);
  if (i < 0 || j < 0) return;
  if (!inDomain(grid, j, i)) {
    ui.readout.textContent = [
      row("lat, lon", `${grid.lats[j].toFixed(2)}, ${grid.lons[i].toFixed(2)}`),
      row("index", "outside coverage"),
    ].join("\n");
    return;
  }
  const value = grid.index[j][i];
  const notes = [];
  if (grid.label) notes.push(grid.label);
  if (grid.refined && grid.refined[j][i]) notes.push("ray traced");
  if (grid.nowcast_adjusted && grid.nowcast_adjusted[j][i]) notes.push("nowcast adjusted");
  const lines = [
    row("lat, lon", `${grid.lats[j].toFixed(2)}, ${grid.lons[i].toFixed(2)}`),
    row("index", value === null ? "missing" : value.toFixed(3)),
    row("event", eventLine(grid, metadata, manifest.event)),
    row("GFS run", gfsLine(grid, metadata)),
  ];
  if (grid.scope === "point") {
    const limiting = grid.limiting ? grid.limiting[j][i] : null;
    lines.push(row("limiting", limiting || "-"));
  }
  lines.push(row("note", notes.length ? notes.join(" | ") : "-"));
  ui.readout.textContent = lines.join("\n");
}

async function main() {
  if (!(await loadCatalog())) return;
  ui.product.addEventListener("change", () => show(upcomingItem()));
  ui.date.addEventListener("change", () => show());
  ui.event.addEventListener("change", () => show());
  ui.canvas.addEventListener("click", onClick);
  let pending = 0;
  window.addEventListener("resize", () => {
    clearTimeout(pending);
    pending = setTimeout(() => current && draw(), 150);
  });
  await show(upcomingItem());
}

main();
