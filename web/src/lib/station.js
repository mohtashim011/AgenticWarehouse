/**
 * Station identity
 * ================
 * A stable name for *this browser on this machine*.
 *
 * Why this file has to exist
 * --------------------------
 * A camera's `deviceId` is minted by the browser per origin **and** per device.
 * The id for the USB camera on the goods-in laptop identifies nothing on the
 * phone in the yard, and it changes when browser storage is cleared. So
 * `store/cameras.py` scopes every camera to a *station* rather than keeping one
 * global list -- and something has to mint that station id.
 *
 * Nothing did. The camera store, its eight routes and its whole ordering model
 * were unreachable because no client ever produced the one string they all key
 * on. This is that string.
 *
 * It lives in localStorage, not a cookie and not the database: it identifies a
 * machine, not a user, and two people signing in on the same goods-in laptop
 * must see the same cameras.
 */

const ID_KEY = "aw-station";
const LABEL_KEY = "aw-station-label";

/** A short random id. `crypto.randomUUID` is not available on every browser
 *  this has to run on -- notably Safari before 15.4 and any plain-HTTP origin,
 *  which is exactly how a warehouse laptop reaches the server on a LAN. */
function mint() {
  try {
    if (globalThis.crypto?.randomUUID) return `stn-${crypto.randomUUID().slice(0, 12)}`;
    const bytes = new Uint8Array(6);
    globalThis.crypto.getRandomValues(bytes);
    return `stn-${Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("")}`;
  } catch {
    // No crypto at all. Time plus a random suffix is weak, but a station id
    // only has to be unique across the handful of machines one warehouse uses.
    return `stn-${Date.now().toString(36)}${Math.floor(Math.random() * 1e6).toString(36)}`;
  }
}

/**
 * The id for this machine, created on first use and kept afterwards.
 *
 * Private browsing and locked-down storage both make localStorage throw rather
 * than return null, so every access is guarded. A station that cannot be
 * persisted still works for the session -- the operator just re-registers the
 * camera next time, which is far better than the page failing to load.
 */
let memoryId = null;

export function stationId() {
  try {
    const existing = window.localStorage.getItem(ID_KEY);
    if (existing) return existing;
    const fresh = mint();
    window.localStorage.setItem(ID_KEY, fresh);
    return fresh;
  } catch {
    if (!memoryId) memoryId = mint();
    return memoryId;
  }
}

/** What staff call this machine, e.g. "Goods-in laptop". Defaults to something
 *  recognisable rather than blank, so the camera list is readable before
 *  anybody has renamed anything. */
export function stationLabel() {
  try {
    const saved = window.localStorage.getItem(LABEL_KEY);
    if (saved) return saved;
  } catch {
    /* storage unavailable: fall through to the guess */
  }
  return guessLabel();
}

export function setStationLabel(label) {
  const clean = (label || "").trim();
  try {
    if (clean) window.localStorage.setItem(LABEL_KEY, clean);
    else window.localStorage.removeItem(LABEL_KEY);
  } catch {
    /* nothing to do: the label is a convenience, not a requirement */
  }
  return clean || guessLabel();
}

/** A first guess at the machine name from the user agent.
 *
 *  Deliberately coarse. The point is only to tell "this phone" apart from "the
 *  goods-in laptop" in a list, and a manager renames it the moment it matters.
 */
function guessLabel() {
  const ua = navigator.userAgent || "";
  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  if (/Android/i.test(ua)) return /Mobile/i.test(ua) ? "Android phone" : "Android tablet";
  if (/Macintosh/i.test(ua)) return "Mac";
  if (/Windows/i.test(ua)) return "Windows PC";
  if (/Linux/i.test(ua)) return "Linux PC";
  return "This machine";
}

/** Everything a camera route needs to identify where it is being called from. */
export function station() {
  return { station: stationId(), station_label: stationLabel() };
}
