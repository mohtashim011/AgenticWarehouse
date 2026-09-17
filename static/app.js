/* Agentic Warehouse MVP — frontend logic
 * Camera decode (QR + barcode) runs in-browser via html5-qrcode; the decoded
 * string is POSTed to the multi-agent pipeline and the agent trace is rendered.
 * Icons are drawn with Lucide (vendored, offline).
 */
"use strict";

let mode = "IN";
let scanner = null;
let running = false;
let lastCode = null;
let lastTime = 0;

const $ = (id) => document.getElementById(id);

/* re-render any <i data-lucide> nodes added to the DOM */
function icons() { if (window.lucide) lucide.createIcons(); }

/* Lucide icon name per agent + outcome */
const AGENT_ICON = {
  "Scanner Agent": "scan-line",
  "Classifier Agent": "tags",
  "Inventory Agent": "boxes",
  "Anomaly Agent": "shield-alert",
  "Forecast Agent": "trending-up",
};
const ACTION_ICON = {
  IN: "arrow-down-to-line",
  OUT: "arrow-up-from-line",
  REJECT: "ban",
  ADJUST: "pencil",
  UNDO: "undo-2",
};

/* ---------- mode toggle ---------- */
$("modeIn").addEventListener("click", () => setMode("IN"));
$("modeOut").addEventListener("click", () => setMode("OUT"));
function setMode(m) {
  mode = m;
  $("modeIn").classList.toggle("active", m === "IN");
  $("modeOut").classList.toggle("active", m === "OUT");
}

/* ---------- camera ---------- */
$("startBtn").addEventListener("click", startCamera);
$("stopBtn").addEventListener("click", stopCamera);

/* Formats to look for. Listing them explicitly matters: left unset the decoder
 * tries every format on every frame, which starves the 1-D readers. */
function supportedFormats() {
  if (!window.Html5QrcodeSupportedFormats) return undefined;
  const F = Html5QrcodeSupportedFormats;
  return [
    F.QR_CODE,
    F.EAN_13, F.EAN_8,            // retail barcodes
    F.UPC_A, F.UPC_E,
    F.CODE_128, F.CODE_39, F.CODE_93,
    F.ITF, F.CODABAR,
  ];
}

/* Chrome's native BarcodeDetector is only worth using if it actually covers 1-D
 * retail barcodes. On Windows/Linux desktop it is usually absent, and enabling
 * it blindly can leave QR working while barcodes quietly never decode — so we
 * ask it what it supports instead of assuming. */
async function nativeDetectorUsable() {
  if (!("BarcodeDetector" in window)) return false;
  try {
    const f = await window.BarcodeDetector.getSupportedFormats();
    return f.includes("ean_13") && f.includes("code_128");
  } catch (e) {
    return false;
  }
}

/* The camera selector must have EXACTLY ONE key — 'facingMode' or 'deviceId'.
 * The library rejects anything else outright. Resolution and other media
 * constraints belong in `videoConstraints` on the scan config, not here. */
const CAMERA = { facingMode: "environment" };

async function startCamera() {
  if (running) return;
  const useNative = await nativeDetectorUsable();
  scanner = new Html5Qrcode("reader", {
    formatsToSupport: supportedFormats(),
    experimentalFeatures: { useBarCodeDetectorIfSupported: useNative },
    verbose: false,
  });

  // NO qrbox: decode the WHOLE frame. A cropped box was the main reason
  // barcodes failed — a wide 1-D label rarely sits fully inside it, and a
  // partly-cropped barcode can never decode, while a square QR always fitted.
  const preferred = {
    fps: 10,
    videoConstraints: {
      facingMode: "environment",
      width: { ideal: 1920 },
      height: { ideal: 1080 },
    },
  };
  const mid = {
    fps: 10,
    videoConstraints: {
      facingMode: "environment",
      width: { ideal: 1280 },
      height: { ideal: 720 },
    },
  };
  // Plainest config that can work, for cameras that refuse the constraints.
  const basic = { fps: 10 };

  for (const config of [preferred, mid, basic]) {
    try {
      await scanner.start(CAMERA, config, onDecode, () => {});
      running = true;
      $("startBtn").disabled = true;
      $("stopBtn").disabled = false;
      setupCameraControls(useNative);
      return;
    } catch (err) {
      try { await scanner.stop(); } catch (e) {}   // leave nothing half-started
      if (config === basic) {
        alert(
          "Could not start the camera.\n\n" +
            "• On a laptop: allow camera access, and close any other app using the webcam.\n" +
            "• On a phone: the page must be opened via https:// or localhost (see README).\n\n" +
            "You can still test using the manual box / sample chips below.\n\n" +
            err
        );
      }
    }
  }
}

/* Optical zoom is the single most effective camera-side fix for 1-D codes:
 * it puts more pixels across each bar without moving the label closer, which
 * a fixed-focus webcam cannot do. Shown only when the camera supports it. */
function setupCameraControls(useNative) {
  let settings = {};
  let caps = {};
  try { settings = scanner.getRunningTrackSettings() || {}; } catch (e) {}
  try { caps = scanner.getRunningTrackCapabilities() || {}; } catch (e) {}

  const zoomRow = $("zoomRow");
  if (caps.zoom && caps.zoom.max > (caps.zoom.min || 1)) {
    const z = caps.zoom;
    const range = $("zoomRange");
    range.min = z.min;
    range.max = z.max;
    range.step = z.step || 0.1;
    range.value = z.min;
    $("zoomVal").textContent = Number(z.min).toFixed(1) + "x";
    zoomRow.hidden = false;
  } else {
    zoomRow.hidden = true;
  }

  // Report what we actually got — if barcodes still fail, this says why.
  const res = settings.width && settings.height
    ? `${settings.width}x${settings.height}` : "resolution unknown";
  $("camStatus").innerHTML =
    `<b>Camera:</b> ${res} &middot; <b>decoder:</b> ${useNative ? "native BarcodeDetector" : "ZXing"} ` +
    `&middot; <b>zoom:</b> ${zoomRow.hidden ? "not supported" : "available"} ` +
    `&middot; scanning the full frame`;
  $("camStatus").hidden = false;
}

$("zoomRange").addEventListener("input", (e) => {
  const v = Number(e.target.value);
  $("zoomVal").textContent = v.toFixed(1) + "x";
  if (scanner && running) {
    scanner.applyVideoConstraints({ advanced: [{ zoom: v }] }).catch(() => {});
  }
});

/* Decode a still photo. A phone photo is far sharper and higher-resolution
 * than a webcam frame, so this reads barcodes a fixed-focus webcam never will. */
$("photoInput").addEventListener("change", async (e) => {
  const file = e.target.files && e.target.files[0];
  e.target.value = "";               // allow picking the same file again
  if (!file) return;
  if (running) await stopCamera();
  const fileScanner = new Html5Qrcode("reader", {
    formatsToSupport: supportedFormats(),
    verbose: false,
  });
  try {
    const text = await fileScanner.scanFile(file, true);
    submitScan(text, "photo");
  } catch (err) {
    alert(
      "No code could be read in that photo.\n\n" +
        "• Fill the frame with the barcode and keep it level.\n" +
        "• Make sure it is in focus and evenly lit, with no glare.\n\n" +
        err
    );
  } finally {
    try { await fileScanner.clear(); } catch (e2) {}
  }
});

async function stopCamera() {
  if (scanner && running) {
    await scanner.stop();
    await scanner.clear();
    running = false;
    $("startBtn").disabled = false;
    $("stopBtn").disabled = true;
  }
}

function onDecode(text, result) {
  const now = Date.now();
  if (text === lastCode && now - lastTime < 2500) return; // debounce repeated frames
  lastCode = text;
  lastTime = now;
  let fmt = "qr";
  try { fmt = (result.result.format && result.result.format.formatName) || "qr"; } catch (e) {}
  submitScan(text, fmt);
}

/* ---------- manual + samples ---------- */
$("manualBtn").addEventListener("click", () => {
  const v = $("manualCode").value.trim();
  if (v) submitScan(v, "manual");
});
$("manualCode").addEventListener("keydown", (e) => { if (e.key === "Enter") $("manualBtn").click(); });
document.querySelectorAll(".samples .chip").forEach((c) =>
  c.addEventListener("click", () => submitScan(c.dataset.code, "sample"))
);

/* ---------- submit a scan ---------- */
async function submitScan(code, fmt) {
  try {
    const res = await fetch("/api/scan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, mode, format: fmt }),
    });
    const data = await res.json();
    renderVerdict(data);
    renderTrace(data.trace || []);
    if (data.state) {
      updateStats(data.state.stats);
      updateInventory(data.state.inventory);
      updateLowStock(data.state.low_stock);
    }
    refreshLogs();
    refreshCategories();   // a new product may now be waiting for a category
  } catch (e) {
    alert("Scan failed: " + e);
  }
}

/* ---------- render ---------- */
function renderVerdict(d) {
  const v = $("verdict");
  const final = d.final || "REJECT";
  v.className = "verdict " + final;

  // Quantity is the headline now: show what the stock level became.
  const qty = d.qty != null ? ` <span class="qty-chip">qty ${d.qty}</span>` : "";

  // When nothing matched, show what was actually decoded — otherwise a
  // check-digit mismatch is invisible and just looks like a broken scan.
  const rawCode =
    d.name === "Unknown Item" && d.code
      ? `<small class="raw-code">decoded: <b>${escapeHtml(d.code)}</b> — not a known product number</small>`
      : "";

  let html =
    `<i data-lucide="${ACTION_ICON[final] || "ban"}"></i>` +
    `<span class="vmain"><b>${final} &mdash; ${escapeHtml(d.name || "?")}${qty}</b>` +
    `<small>${escapeHtml(d.reason || "")}${d.anomaly ? " · anomaly flagged" : ""}</small>` +
    rawCode;

  // Unseen product: let the user file it on the spot.
  if (d.needs_category && d.name && d.name !== "Unknown Item") {
    const sug = d.suggestion && d.suggestion.category;
    const opts = categories
      .map((c) => `<option value="${escapeHtml(c.name)}"${c.name === sug ? " selected" : ""}>${escapeHtml(c.name)}</option>`)
      .join("");
    html +=
      `<span class="assign-row">` +
      `<i data-lucide="tag"></i>` +
      `<span>Category for <b>${escapeHtml(d.name)}</b>?` +
      (sug ? ` <em>suggested: ${escapeHtml(sug)} (${Math.round(d.suggestion.confidence * 100)}%)</em>` : "") +
      `</span>` +
      `<select id="assignSel">${opts}</select>` +
      `<button id="assignBtn" class="btn primary sm"><i data-lucide="check"></i> Save</button>` +
      `</span>`;
  }
  v.innerHTML = html + "</span>";

  const btn = $("assignBtn");
  if (btn) {
    btn.addEventListener("click", () =>
      assignCategory(d.name, $("assignSel").value)
    );
  }
  icons();
}

/* ---------- categories ---------- */
let categories = [];

async function refreshCategories() {
  try {
    const res = await fetch("/api/categories");
    const d = await res.json();
    applyCategoryData(d);
  } catch (e) {}
}

function applyCategoryData(d) {
  if (d.categories) categories = d.categories;
  renderCategories(d.categories || categories, d.uncategorised || []);
}

function renderCategories(cats, uncat) {
  const tb = $("catTable").querySelector("tbody");
  tb.innerHTML = cats
    .map((c) => {
      const locked = c.name === "Uncategorised";
      const actions = locked
        ? `<span class="muted">built-in</span>`
        : `<button class="linkbtn" data-act="rename" data-cat="${escapeHtml(c.name)}">rename</button>` +
          `<button class="linkbtn danger" data-act="delete" data-cat="${escapeHtml(c.name)}">delete</button>`;
      return `<tr><td>${escapeHtml(c.name)}</td><td class="num">${c.products}</td>` +
             `<td class="num">${c.units}</td><td class="num">${actions}</td></tr>`;
    })
    .join("");

  tb.querySelectorAll("button[data-act]").forEach((b) =>
    b.addEventListener("click", () => {
      const name = b.dataset.cat;
      if (b.dataset.act === "rename") {
        const next = prompt(`Rename category "${name}" to:`, name);
        if (next && next !== name) postCategory("/api/categories/rename", { old: name, new: next });
      } else if (confirm(`Delete "${name}"? Its products move to Uncategorised.`)) {
        postCategory("/api/categories/delete", { name });
      }
    })
  );

  // products with no category yet
  const box = $("uncatBox");
  const ub = $("uncatTable").querySelector("tbody");
  box.hidden = uncat.length === 0;
  ub.innerHTML = uncat
    .map((p) => {
      const opts = cats
        .filter((c) => c.name !== "Uncategorised")
        .map((c) => `<option value="${escapeHtml(c.name)}">${escapeHtml(c.name)}</option>`)
        .join("");
      return `<tr><td>${escapeHtml(p.name)}</td><td class="num">${p.qty}</td>` +
             `<td><select data-prod="${escapeHtml(p.name)}">${opts}</select> ` +
             `<button class="linkbtn" data-assign="${escapeHtml(p.name)}">assign</button></td></tr>`;
    })
    .join("");

  ub.querySelectorAll("button[data-assign]").forEach((b) =>
    b.addEventListener("click", () => {
      const prod = b.dataset.assign;
      const sel = ub.querySelector(`select[data-prod="${CSS.escape(prod)}"]`);
      if (sel && sel.value) assignCategory(prod, sel.value);
    })
  );
  icons();
}

async function postCategory(url, body) {
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const d = await res.json();
    showCatMsg(d.message, d.ok);
    applyCategoryData(d);
    if (d.stats) updateStats(d.stats);
    if (d.inventory) updateInventory(d.inventory);
    return d.ok;
  } catch (e) {
    showCatMsg("Request failed: " + e, false);
    return false;
  }
}

async function assignCategory(product, category) {
  const ok = await postCategory("/api/categories/assign", { product, category });
  if (ok) {
    const row = document.querySelector(".assign-row");
    if (row) row.innerHTML = `<i data-lucide="check-circle"></i> <span>Filed under ${escapeHtml(category)}.</span>`;
    icons();
    refreshLogs();
  }
}

function showCatMsg(text, ok) {
  const el = $("catMsg");
  el.textContent = text || "";
  el.className = "cat-msg " + (ok ? "ok" : "bad");
  setTimeout(() => { el.textContent = ""; el.className = "cat-msg"; }, 4000);
}

$("addCatBtn").addEventListener("click", async () => {
  const v = $("newCat").value.trim();
  if (!v) return;
  if (await postCategory("/api/categories/add", { name: v })) $("newCat").value = "";
});
$("newCat").addEventListener("keydown", (e) => { if (e.key === "Enter") $("addCatBtn").click(); });

function badgeFor(step) {
  if (step.agent === "Inventory Agent") return step.decision === "ACCEPT" ? "ok" : "bad";
  if (step.agent === "Anomaly Agent") return step.flagged ? "warn" : "ok";
  return "info";
}
function badgeText(step) {
  if (step.agent === "Scanner Agent") return step.ok ? "parsed" : "failed";
  if (step.agent === "Classifier Agent") return step.category;
  if (step.agent === "Inventory Agent") return step.decision;
  if (step.agent === "Anomaly Agent") return step.flagged ? "flagged" : "clean";
  if (step.agent === "Forecast Agent")
    return step.days_to_stockout != null ? step.days_to_stockout + "d left" : "n/a";
  return "";
}

function renderTrace(trace) {
  const box = $("trace");
  box.innerHTML = "";
  trace.forEach((step) => {
    const notes = step.notes || step.reasons || (step.reason ? [step.reason] : []);
    const icon = AGENT_ICON[step.agent] || "circle";
    const div = document.createElement("div");
    div.className = "astep";
    div.innerHTML =
      `<div class="ah"><span class="who"><i data-lucide="${icon}"></i>${escapeHtml(step.agent)}</span>` +
      `<span class="badge ${badgeFor(step)}">${escapeHtml(badgeText(step))}</span></div>` +
      (notes.length ? "<ul>" + notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("") + "</ul>" : "");
    box.appendChild(div);
  });
  icons();
}

function updateStats(s) {
  if (!s) return;
  $("statbar").innerHTML =
    `<div class="s"><b>${s.in_stock}</b><span>In stock</span></div>` +
    `<div class="s"><b>${s.total_scans}</b><span>Scans</span></div>` +
    `<div class="s"><b>${s.categories}</b><span>Categories</span></div>` +
    `<div class="s"><b>${s.anomalies}</b><span>Anomalies</span></div>`;
  // The IN/OUT split is two numbers — a stat tile, not a two-slice pie.
  if ($("tileIn")) $("tileIn").textContent = s.scans_in ?? 0;
  if ($("tileOut")) $("tileOut").textContent = s.scans_out ?? 0;
}

function updateInventory(inv) {
  if (!inv) return;
  const tb = $("invTable").querySelector("tbody");
  if (inv.rows.length === 0) {
    tb.innerHTML = `<tr><td colspan="4" class="muted">No stock yet &mdash; scan an item IN.</td></tr>`;
    return;
  }
  tb.innerHTML = inv.rows
    .map((r) => {
      // Each batch quantity is editable — this is how a miscount gets corrected.
      const batches =
        `<div class="batches">` +
        (r.batches || [])
          .map(
            (b) =>
              `<span class="batch-edit" title="Correct the counted quantity">` +
              `<label>${b.batchno ? escapeHtml(b.batchno) : "no batch"}</label>` +
              `<input class="batchqty" type="number" min="0" value="${b.qty}" ` +
              `data-pn="${escapeHtml(b.productno)}" data-bn="${escapeHtml(b.batchno || "")}" /></span>`
          )
          .join("") +
        `</div>`;
      // An unnamed barcode product can be given a real name, after which every
      // future scan of that barcode matches it instead of staying "unknown".
      const pn0 = (r.batches[0] || {}).productno || "";
      const nameCell =
        r.name === "Unknown Item"
          ? `${escapeHtml(r.name)} <small class="codeno">${escapeHtml(pn0)}</small>` +
            ` <button class="linkbtn" data-name-pn="${escapeHtml(pn0)}">name it</button>` +
            ` <button class="linkbtn" data-link-code="${escapeHtml(pn0)}">link to product</button>`
          : escapeHtml(r.name);
      return (
        `<tr class="${r.low ? "row-low" : ""}">` +
        `<td>${nameCell}${batches}</td>` +
        `<td>${escapeHtml(r.category || "-")}</td>` +
        `<td class="num">${r.qty}${r.low ? ' <i data-lucide="triangle-alert" class="flag-warn"></i>' : ""}</td>` +
        `<td class="num"><input class="minqty" type="number" min="0" value="${r.min_qty || 0}" ` +
        `data-prod="${escapeHtml(r.name)}" title="0 = no alert" /></td></tr>`
      );
    })
    .join("");

  tb.querySelectorAll("input.minqty").forEach((el) => {
    const save = () => setReorder(el.dataset.prod, el.value);
    el.addEventListener("change", save);
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") el.blur(); });
  });
  tb.querySelectorAll("input.batchqty").forEach((el) => {
    el.addEventListener("change", () => adjustStock(el.dataset.pn, el.dataset.bn, el.value));
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") el.blur(); });
  });
  // Link an unrecognised code to a product already in stock.
  tb.querySelectorAll("button[data-link-code]").forEach((b) =>
    b.addEventListener("click", async () => {
      const code = b.dataset.linkCode;
      const known = (inv.rows || [])
        .filter((x) => x.name !== "Unknown Item")
        .map((x) => ({ name: x.name, pn: (x.batches[0] || {}).productno || "" }))
        .filter((x) => x.pn);
      if (!known.length) return alert("No named products to link to yet.");
      const menu = known.map((k, i) => `${i + 1}. ${k.name} (${k.pn})`).join("\n");
      const pick = prompt(`Link code ${code} to which product?\n\n${menu}\n\nEnter a number:`, "1");
      const idx = Number(pick) - 1;
      if (!(idx >= 0 && idx < known.length)) return;
      try {
        const res = await fetch("/api/link", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ code, productno: known[idx].pn }),
        });
        const d = await res.json();
        applyStateBundle(d);
        alert(d.message);
      } catch (e) {
        alert("Could not link the code: " + e);
      }
    })
  );
  tb.querySelectorAll("button[data-name-pn]").forEach((b) =>
    b.addEventListener("click", async () => {
      const pn = b.dataset.namePn;
      const name = prompt(`Name for product no. ${pn}:`, "");
      if (!name) return;
      try {
        const res = await fetch("/api/rename", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ productno: pn, name }),
        });
        const d = await res.json();
        applyStateBundle(d);
        if (!d.ok) alert(d.message);
      } catch (e) {
        alert("Could not name the product: " + e);
      }
    })
  );
  icons();
}

/* ---------- manual correction + undo ---------- */
async function adjustStock(productno, batchno, qty) {
  try {
    const res = await fetch("/api/adjust", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ productno, batchno, qty: Number(qty) }),
    });
    const d = await res.json();
    applyStateBundle(d);
    if (!d.ok) alert(d.message);
  } catch (e) {
    alert("Could not save the correction: " + e);
  }
}

$("undoBtn").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/undo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    });
    const d = await res.json();
    applyStateBundle(d);
    if (!d.ok) alert(d.message);
  } catch (e) {
    alert("Undo failed: " + e);
  }
});

/* Apply a response that carries a full state bundle (adjust / undo). */
function applyStateBundle(d) {
  if (d.stats) updateStats(d.stats);
  if (d.inventory) updateInventory(d.inventory);
  updateLowStock(d.low_stock);
  if (d.logs) updateLogs(d.logs);
  updateUndo(d.undoable);
  refreshLogs();   // pulls fresh chart data too
}

/* ---------- log search / filter / export ---------- */
function logFilterActive() {
  return Boolean($("logSearch").value.trim() || $("logAction").value);
}

async function refreshFilteredLogs() {
  const q = $("logSearch").value.trim();
  const action = $("logAction").value;
  try {
    const res = await fetch(
      `/api/logs?q=${encodeURIComponent(q)}&action=${encodeURIComponent(action)}&limit=100`
    );
    const d = await res.json();
    updateLogs(d.logs);
    // Keep the CSV download scoped to whatever is on screen.
    $("exportLogs").href =
      `/api/export/logs.csv?q=${encodeURIComponent(q)}&action=${encodeURIComponent(action)}`;
  } catch (e) {}
}

let searchTimer = null;
$("logSearch").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    logFilterActive() ? refreshFilteredLogs() : refreshLogs();
  }, 200);
});
$("logAction").addEventListener("change", () =>
  logFilterActive() ? refreshFilteredLogs() : refreshLogs()
);

function updateUndo(u) {
  const btn = $("undoBtn");
  const what = $("undoWhat");
  btn.disabled = !u;
  if (!u) {
    what.textContent = "Nothing to undo.";
    return;
  }
  const batch = u.batchno ? ` (batch ${u.batchno})` : "";
  what.textContent = `Will reverse: ${u.action} ${u.name}${batch}`;
}

function updateLowStock(alerts) {
  const card = $("lowStockCard");
  if (!alerts) return;
  card.hidden = alerts.length === 0;
  $("lowCount").textContent = alerts.length ? alerts.length : "";
  $("lowTable").querySelector("tbody").innerHTML = alerts
    .map(
      (a) =>
        `<tr><td>${escapeHtml(a.name)}</td><td>${escapeHtml(a.category || "-")}</td>` +
        `<td class="num">${a.qty}</td><td class="num">${a.min_qty}</td>` +
        `<td><span class="pill ${a.status === "OUT" ? "REJECT" : "warn"}">` +
        `${a.status === "OUT" ? "out of stock" : "reorder"}</span></td></tr>`
    )
    .join("");
  icons();
}

async function setReorder(product, minQty) {
  try {
    const res = await fetch("/api/reorder", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product, min_qty: Number(minQty) }),
    });
    const d = await res.json();
    if (d.inventory) updateInventory(d.inventory);
    updateLowStock(d.low_stock);
    if (!d.ok) alert(d.message);
  } catch (e) {
    alert("Could not save the reorder level: " + e);
  }
}

function updateLogs(logs) {
  const tb = $("logTable").querySelector("tbody");
  tb.innerHTML =
    !logs || logs.length === 0
      ? `<tr><td colspan="4" class="muted">No activity yet.</td></tr>`
      : logs
          .map((l) => {
            // A reversed scan stays in the trail, struck through — an audit log
            // must never quietly lose an entry.
            const reversed = l.undone && (l.action === "IN" || l.action === "OUT");
            const batch = l.batchno ? ` <small class="muted">${escapeHtml(l.batchno)}</small>` : "";
            return (
              `<tr class="${reversed ? "log-undone" : ""}">` +
              `<td><span class="pill ${l.action}"><i data-lucide="${ACTION_ICON[l.action] || "dot"}"></i>${l.action}</span></td>` +
              `<td>${escapeHtml(l.name || "-")}${batch}</td><td>${escapeHtml(l.productno || "-")}</td>` +
              `<td class="num">${l.anomaly ? '<i data-lucide="alert-triangle" class="flag-warn"></i>' : ""}</td></tr>`
            );
          })
          .join("");
  icons();
}

/* ---------- charts (hand-drawn inline SVG, no libraries) ----------
 * Palette roles come from the validated data-viz reference set, checked against
 * this dashboard's white card surface. Stock-by-category is a single hue on
 * purpose: the axis already names each bar, so colouring each one differently
 * would encode bar length twice and waste the only free channel.
 */
const VIZ = {
  series1: "#2a78d6",   // categorical slot 1 — bars, and Stock IN
  series2: "#008300",   // categorical slot 2 — Stock OUT
  grid: "#e1e0d9",
  axis: "#c3c2b7",
  muted: "#898781",
  ink: "#0b0b0b",
};

/* A bar whose data-end is rounded and whose baseline end stays square. */
function barPath(x0, y, w, h, r) {
  r = Math.max(0, Math.min(r, w));
  if (w <= 0) return "";
  const x1 = x0 + w;
  return (
    `M${x0},${y} H${x1 - r} A${r},${r} 0 0 1 ${x1},${y + r} ` +
    `V${y + h - r} A${r},${r} 0 0 1 ${x1 - r},${y + h} H${x0} Z`
  );
}

function renderCategoryChart(rows) {
  const box = $("catChart");
  if (!rows || rows.length === 0) {
    box.innerHTML = `<p class="chart-empty">No stock yet &mdash; scan an item IN.</p>`;
    return;
  }
  const GUTTER = 104, X0 = 108, XMAX = 362, ROW = 26, BAR = 10;
  const max = Math.max(...rows.map((r) => r.qty), 1);
  const H = 10 + rows.length * ROW;

  const bars = rows
    .map((r, i) => {
      const y = 10 + i * ROW;
      const w = Math.max((r.qty / max) * (XMAX - X0), 2);
      const label = r.category || "Uncategorised";
      // Long category names are truncated with an ellipsis rather than
      // overflowing into the plot; the full name stays in the tooltip.
      const short = label.length > 16 ? label.slice(0, 15) + "…" : label;
      return (
        `<g class="cbar" data-label="${escapeHtml(label)}" data-qty="${r.qty}">` +
        `<rect x="0" y="${y - 5}" width="400" height="${ROW - 2}" fill="transparent"/>` +
        `<text x="${GUTTER}" y="${y + BAR - 2}" text-anchor="end" font-size="11" ` +
        `fill="${VIZ.muted}">${escapeHtml(short)}</text>` +
        `<path d="${barPath(X0, y, w, BAR, 4)}" fill="${VIZ.series1}"/>` +
        `<text x="${X0 + w + 6}" y="${y + BAR - 2}" font-size="11" ` +
        `fill="${VIZ.ink}">${r.qty}</text></g>`
      );
    })
    .join("");

  box.innerHTML =
    `<svg viewBox="0 0 400 ${H}" width="100%" height="auto" role="img" ` +
    `aria-label="Units on hand per category">` +
    `<line x1="${X0}" y1="4" x2="${X0}" y2="${H - 4}" stroke="${VIZ.axis}" stroke-width="1"/>` +
    bars +
    `</svg><div class="tip" hidden></div>`;

  const tip = box.querySelector(".tip");
  box.querySelectorAll(".cbar").forEach((g) => {
    g.addEventListener("mousemove", (e) => showTip(box, tip, e,
      `<b>${escapeHtml(g.dataset.label)}</b><br>${g.dataset.qty} units`));
    g.addEventListener("mouseleave", () => { tip.hidden = true; });
  });
}

function renderActivityChart(days) {
  const box = $("actChart");
  if (!days || days.length === 0) {
    box.innerHTML = `<p class="chart-empty">No activity yet.</p>`;
    return;
  }
  const L = 30, R = 10, T = 12, B = 26, W = 400, H = 170;
  const pw = W - L - R, ph = H - T - B;
  const max = Math.max(1, ...days.map((d) => Math.max(d.in, d.out)));
  const n = days.length;
  const xAt = (i) => (n === 1 ? L + pw / 2 : L + (i * pw) / (n - 1));
  const yAt = (v) => T + ph - (v / max) * ph;

  // Whole-number ticks only — fractional scan counts would be nonsense.
  const ticks = max <= 2 ? [0, max] : [0, Math.round(max / 2), max];
  const grid = ticks
    .map(
      (t) =>
        `<line x1="${L}" y1="${yAt(t)}" x2="${W - R}" y2="${yAt(t)}" ` +
        `stroke="${VIZ.grid}" stroke-width="1"/>` +
        `<text x="${L - 6}" y="${yAt(t) + 3.5}" text-anchor="end" font-size="10" ` +
        `fill="${VIZ.muted}">${t}</text>`
    )
    .join("");

  const line = (key, color) => {
    const pts = days.map((d, i) => `${xAt(i)},${yAt(d[key])}`).join(" ");
    const dots = days
      .map((d, i) => `<circle cx="${xAt(i)}" cy="${yAt(d[key])}" r="4" fill="${color}" ` +
                     `stroke="#fff" stroke-width="2"/>`)
      .join("");
    return `<polyline points="${pts}" fill="none" stroke="${color}" stroke-width="2" ` +
           `stroke-linejoin="round" stroke-linecap="round"/>${dots}`;
  };

  const xlabels = days
    .map((d, i) => {
      // Only label the ends and the middle, so ticks never collide.
      if (n > 3 && i !== 0 && i !== n - 1 && i !== Math.floor(n / 2)) return "";
      const dt = d.day.slice(5);   // MM-DD
      const anchor = i === 0 ? "start" : i === n - 1 ? "end" : "middle";
      return `<text x="${xAt(i)}" y="${H - 8}" text-anchor="${anchor}" font-size="10" ` +
             `fill="${VIZ.muted}">${dt}</text>`;
    })
    .join("");

  // Invisible hit columns, far wider than the 8px markers.
  const hits = days
    .map((d, i) => {
      const cw = pw / n;
      return `<rect class="hit" data-i="${i}" x="${xAt(i) - cw / 2}" y="${T}" ` +
             `width="${cw}" height="${ph}" fill="transparent"/>`;
    })
    .join("");

  box.innerHTML =
    `<svg viewBox="0 0 ${W} ${H}" width="100%" height="auto" role="img" ` +
    `aria-label="Scans per day over the last 7 days">` +
    grid +
    `<line x1="${L}" y1="${T + ph}" x2="${W - R}" y2="${T + ph}" stroke="${VIZ.axis}" stroke-width="1"/>` +
    line("out", VIZ.series2) + line("in", VIZ.series1) +
    xlabels + hits +
    `</svg><div class="tip" hidden></div>`;

  const tip = box.querySelector(".tip");
  box.querySelectorAll(".hit").forEach((rect) => {
    rect.addEventListener("mousemove", (e) => {
      const d = days[Number(rect.dataset.i)];
      showTip(box, tip, e,
        `<b>${d.day}</b><br><i class="swatch s-in"></i>IN ${d.in}` +
        `<br><i class="swatch s-out"></i>OUT ${d.out}`);
    });
    rect.addEventListener("mouseleave", () => { tip.hidden = true; });
  });
}

function showTip(box, tip, evt, html) {
  const r = box.getBoundingClientRect();
  tip.innerHTML = html;
  tip.hidden = false;
  // Keep the tooltip inside the card rather than letting it clip.
  const x = Math.min(Math.max(evt.clientX - r.left + 12, 4), r.width - tip.offsetWidth - 4);
  tip.style.left = x + "px";
  tip.style.top = Math.max(evt.clientY - r.top - tip.offsetHeight - 10, 4) + "px";
}

function renderCharts(charts) {
  if (!charts) return;
  renderCategoryChart(charts.categories);
  renderActivityChart(charts.activity);
}

/* ---------- assistant ---------- */
$("askBtn").addEventListener("click", ask);
$("askInput").addEventListener("keydown", (e) => { if (e.key === "Enter") ask(); });
document.querySelectorAll(".ask-suggestions .chip").forEach((c) =>
  c.addEventListener("click", () => { $("askInput").value = c.dataset.q; ask(); })
);
async function ask() {
  const q = $("askInput").value.trim();
  if (!q) return;
  $("answer").innerHTML = '<i data-lucide="loader"></i> Thinking...';
  icons();
  try {
    const res = await fetch("/api/assistant", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q }),
    });
    const d = await res.json();
    const tag = d.mode === "local" ? "answered offline" : "answered by Claude";
    $("answer").innerHTML =
      `<i data-lucide="corner-down-right"></i><span>${escapeHtml(d.answer)}<br><small style="color:#5c6675">(${tag})</small></span>`;
    icons();
  } catch (e) {
    $("answer").textContent = "Error: " + e;
  }
}

/* ---------- helpers ---------- */
function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

async function refreshLogs() {
  try {
    const res = await fetch("/api/state");
    const d = await res.json();
    updateStats(d.stats);
    updateInventory(d.inventory);
    updateLowStock(d.low_stock);
    renderCharts(d.charts);
    updateUndo(d.undoable);
    // A search/filter in effect must survive a refresh, so it wins over
    // the unfiltered log list that came back with the state bundle.
    if (logFilterActive()) refreshFilteredLogs();
    else updateLogs(d.logs);
  } catch (e) {}
}

/* initial load */
icons();        // render the static icons already in the HTML
refreshCategories();
refreshLogs();
