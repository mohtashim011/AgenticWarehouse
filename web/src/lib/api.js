/**
 * API client
 * ==========
 * One place that talks to the Python server.
 *
 * Two things it guarantees, so no screen has to think about them:
 *
 *  - **Errors arrive as exceptions with a readable message.** The server sends
 *    `{ok: false, error: "..."}` with a real status code; this turns that into
 *    an `ApiError` carrying the message the server wrote, because the server is
 *    the only thing that knows why something was refused.
 *  - **A 401 means the session ended.** Rather than every screen handling that,
 *    the client raises a flagged error and the auth provider redirects once.
 *
 * Session cookies are HttpOnly, so there is no token to attach by hand --
 * `credentials: "same-origin"` is all that is needed, and it is also why a
 * script on the page cannot steal the session.
 */

export class ApiError extends Error {
  constructor(message, status, payload) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.payload = payload || {};
    this.unauthenticated = status === 401;
    this.forbidden = status === 403;
  }
}

async function request(path, { method = "GET", body, signal } = {}) {
  let response;
  try {
    response = await fetch(path, {
      method,
      signal,
      credentials: "same-origin",
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (err) {
    if (err.name === "AbortError") throw err;
    // Distinguish "the server is not there" from "the server said no": they
    // need completely different reactions from the person reading the message.
    throw new ApiError(
      "Cannot reach the server. Check that it is still running.",
      0,
      {}
    );
  }

  const isJson = (response.headers.get("Content-Type") || "").includes(
    "application/json"
  );
  const payload = isJson ? await response.json().catch(() => ({})) : {};

  if (!response.ok) {
    throw new ApiError(
      payload.error || payload.message || `Request failed (${response.status}).`,
      response.status,
      payload
    );
  }
  return payload;
}

const get = (path, opts) => request(path, opts);
const post = (path, body, opts) => request(path, { ...opts, method: "POST", body });
const put = (path, body, opts) => request(path, { ...opts, method: "PUT", body });
const del = (path, opts) => request(path, { ...opts, method: "DELETE" });

export const api = {
  // -- session -------------------------------------------------------
  session: () => get("/api/auth/session"),
  login: (username, password) => post("/api/auth/login", { username, password }),
  logout: () => post("/api/auth/logout", {}),
  changePassword: (current_password, new_password) =>
    post("/api/auth/password", { current_password, new_password }),

  // -- scanning ------------------------------------------------------
  scan: (code, mode, format) => post("/api/scan", { code, mode, format }),
  recover: (code, reason) => post("/api/scan/recover", { code, reason }),
  visionFailover: (payload) => post("/api/vision/failover", payload),
  /** Decode a 1-D barcode server-side from a full-resolution grayscale band.
   *
   *  Sent raw rather than as JSON: it is one byte per pixel and base64 would
   *  add a third for nothing. This is the only route in the app that posts a
   *  body which is not JSON, which is why it does not go through `post()`.
   */
  decodeImage: (band, width, height) =>
    fetch(`/api/scan/decode-image?w=${width}&h=${height}`, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/octet-stream" },
      body: band,
    }).then(async (r) => {
      const payload = await r.json().catch(() => ({}));
      if (!r.ok) throw new ApiError(payload.error || "Could not decode that frame.", r.status, payload);
      return payload;
    }),
  adjust: (productno, batchno, qty) =>
    post("/api/adjust", { productno, batchno, qty }),
  undo: (log_id) => post("/api/undo", log_id ? { log_id } : {}),
  rename: (productno, name) => post("/api/rename", { productno, name }),
  link: (code, productno) => post("/api/link", { code, productno }),
  unlink: (code) => post("/api/unlink", { code }),
  codes: () => get("/api/codes"),

  // -- cameras -------------------------------------------------------
  // Every one of these is scoped to a station: a browser deviceId means
  // nothing on another machine, so a global camera list would be wrong
  // everywhere but the machine that created it. See @/lib/station.
  cameras: (station) =>
    get(`/api/cameras${station ? `?station=${encodeURIComponent(station)}` : ""}`),
  cameraOrder: (station) =>
    get(`/api/cameras/order?station=${encodeURIComponent(station)}`),
  addCamera: (payload) => post("/api/cameras", payload),
  updateCamera: (id, payload) => put(`/api/cameras/${id}`, payload),
  deleteCamera: (id) => del(`/api/cameras/${id}`),
  reorderCameras: (station, order) => post("/api/cameras/reorder", { station, order }),
  // The browser is the only thing that can measure a camera, so it sends the
  // measurement and the server scores it -- the grade is then the same
  // whichever machine ran the test.
  testCamera: (id, result) => post(`/api/cameras/${id}/test`, result),
  cameraTests: (id, limit = 20) => get(`/api/cameras/${id}/tests?limit=${limit}`),

  // -- products (CRUD) -----------------------------------------------
  products: () => get("/api/products"),
  product: (productno) => get(`/api/products/${encodeURIComponent(productno)}`),
  createProduct: (payload) => post("/api/products", payload),
  updateProduct: (productno, payload) =>
    put(`/api/products/${encodeURIComponent(productno)}`, payload),
  deleteProduct: (productno, force = false) =>
    del(`/api/products/${encodeURIComponent(productno)}${force ? "?force=1" : ""}`),
  createBatch: (productno, batchno, qty) =>
    post(`/api/products/${encodeURIComponent(productno)}/batches`, { batchno, qty }),
  deleteBatch: (productno, batchno) =>
    del(`/api/products/${encodeURIComponent(productno)}/batches/${encodeURIComponent(batchno)}`),

  // -- reporting -----------------------------------------------------
  dailyReport: ({ days = 30, from, to } = {}) => {
    const params = new URLSearchParams();
    if (from) params.set("from", from);
    if (to) params.set("to", to);
    if (!from) params.set("days", String(days));
    return get(`/api/reports/daily?${params.toString()}`);
  },

  // -- inventory -----------------------------------------------------
  state: () => get("/api/state"),
  logs: (q = "", action = "", limit = 100) =>
    get(`/api/logs?q=${encodeURIComponent(q)}&action=${encodeURIComponent(action)}&limit=${limit}`),
  setReorder: (product, min_qty) => post("/api/reorder", { product, min_qty }),
  procurement: () => get("/api/procurement"),
  audit: () => get("/api/audit"),

  // -- categories ----------------------------------------------------
  categories: () => get("/api/categories"),
  addCategory: (name) => post("/api/categories/add", { name }),
  renameCategory: (oldName, newName) =>
    post("/api/categories/rename", { old: oldName, new: newName }),
  deleteCategory: (name) => post("/api/categories/delete", { name }),
  assignCategory: (product, category) =>
    post("/api/categories/assign", { product, category }),

  // -- staff ---------------------------------------------------------
  staff: () => get("/api/staff"),
  createStaff: (payload) => post("/api/staff", payload),
  updateStaff: (id, payload) => put(`/api/staff/${id}`, payload),
  deleteStaff: (id) => del(`/api/staff/${id}`),
  resetStaffPassword: (id, password) =>
    post(`/api/staff/${id}/password`, { password }),
  unlockStaff: (id) => post(`/api/staff/${id}/unlock`, {}),
  staffEvents: (limit = 100) => get(`/api/staff/events?limit=${limit}`),

  // -- agents and models ---------------------------------------------
  agents: () => get("/api/agents"),
  models: () => get("/api/models"),
  trainModels: (deep = false) => post("/api/models/train", { deep }),
  predict: (name) => get(`/api/models/predict?name=${encodeURIComponent(name)}`),
  reportComparison: () => get("/api/report/comparison"),
  // How this system stands against what a warehouse could buy instead, as
  // opposed to against the project it replaces.
  marketComparison: () => get("/api/report/market"),

  // -- misc ----------------------------------------------------------
  ask: (question) => post("/api/assistant", { question }),
  settings: () => get("/api/settings"),
  saveSettings: (settings) => post("/api/settings", { settings }),
};
