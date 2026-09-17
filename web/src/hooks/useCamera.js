/**
 * Dual-camera scanning with automatic failover
 * ============================================
 * The backup scanner, on the browser side.
 *
 * The requirement is simple to state and easy to get wrong: if one camera
 * fails, the other must take over without anybody noticing. A camera "fails" in
 * more ways than most code accounts for, so this hook watches for all of them:
 *
 *  - **It refuses to start.** Another application holds it, or permission was
 *    denied for that specific device.
 *  - **It stops mid-session.** A USB camera is unplugged; the track ends.
 *  - **It is muted.** Another application took it while it was running.
 *  - **It runs but sees nothing.** The most common and most annoying case: the
 *    camera is live, the picture looks fine, and nothing decodes because the
 *    lens is fixed-focus and the barcode is a blur. No error is ever raised,
 *    so a watchdog timer is the only way to notice.
 *
 * Failover is deliberately not silent. It reports which camera is live and why
 * it switched, because an operator who cannot see that the backup took over
 * will keep presenting labels to a camera that has already given up.
 *
 * Why enumeration is done here rather than by html5-qrcode
 * -------------------------------------------------------
 * `Html5Qrcode.getCameras()` **always** calls `getUserMedia({video: true})` to
 * unlock the device labels, then stops the tracks it opened. On Windows a UVC
 * webcam is frequently exclusive-access, and the OS releases it *after* the
 * promise settles -- so the very next `getUserMedia` for that exact deviceId
 * lands while the device is still held and fails with `NotReadableError`. That
 * is why the phone camera worked and every USB and built-in webcam did not.
 *
 * So this hook enumerates itself. `navigator.mediaDevices.enumerateDevices()`
 * needs no stream at all once permission has been granted once, which means on
 * every visit after the first there is no grab-and-release at all, and the
 * device is free when we ask for it. When labels *are* blank -- the genuine
 * first run -- it unlocks once, stops the tracks explicitly, and waits for the
 * device to settle before opening the one it actually wants.
 *
 * Two further things that were wrong and are load-bearing now
 * ----------------------------------------------------------
 * `startCamera` used to read the `cameras` React state through its closure. On
 * the first `start()` that state was still the empty first-render array, so it
 * enumerated a *second* time, microseconds after the first -- doubling the
 * grab-and-release race above. Everything now reads `camerasRef`.
 *
 * The three fallback configurations used to share one `Html5Qrcode` instance. A
 * rejected `start()` leaves a stray `<video>` in the container and the instance
 * mid-transition, so attempts two and three were failing for a reason that had
 * nothing to do with the camera. Each attempt now gets a fresh instance and a
 * cleared container.
 *
 * `useCamera.js` reads the live `MediaStreamTrack` off the `<video>` element
 * that html5-qrcode renders. **This is deliberate and load-bearing**:
 * html5-qrcode has no `getRunningTrack()` method, and the earlier code called
 * one -- optional chaining swallowed the miss, so the disconnect listener was
 * never attached and the unplugged-camera failover never fired at all.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/api";
import { stationId } from "@/lib/station";

// Loaded lazily: html5-qrcode is a large bundle and only the scanner page
// needs it, so it should not sit in the initial download for every screen.
let Html5QrcodeModule = null;
async function loadScanner() {
  if (!Html5QrcodeModule) Html5QrcodeModule = await import("html5-qrcode");
  return Html5QrcodeModule;
}

/** Formats to look for.
 *
 * Listing them explicitly matters: left unset, the decoder tries every format
 * on every frame, which starves the 1-D readers and makes barcodes feel broken
 * while QR codes keep working.
 */
function supportedFormats(Html5QrcodeSupportedFormats) {
  const F = Html5QrcodeSupportedFormats;
  return [
    F.QR_CODE,
    F.EAN_13,
    F.EAN_8,
    F.UPC_A,
    F.UPC_E,
    F.CODE_128,
    F.CODE_39,
    F.CODE_93,
    F.ITF,
    F.CODABAR,
  ];
}

/**
 * The MediaStreamTrack currently feeding the viewport.
 *
 * html5-qrcode owns the getUserMedia call and does not expose the track, so it
 * is read back off the <video> element it renders into our container. This is
 * the only way to observe a real disconnect: the library surfaces no event for
 * it, and a camera that vanishes raises nothing anywhere else.
 */
function trackFrom(elementId) {
  const video = document.getElementById(elementId)?.querySelector("video");
  const stream = video?.srcObject;
  return stream?.getVideoTracks?.()[0] || null;
}

function videoFrom(elementId) {
  return document.getElementById(elementId)?.querySelector("video") || null;
}

const settle = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function stopStream(stream) {
  try {
    stream?.getTracks?.().forEach((t) => t.stop());
  } catch {
    /* the stream was already dead; nothing to release */
  }
}

/**
 * Work out what actually went wrong.
 *
 * The browser raises a `DOMException` with a meaningful `name`, but
 * html5-qrcode stringifies it ("Error getting userMedia, error = NotReadableError:
 * Could not start video source"), so the name has to be recovered from the text
 * as well. Without this every failure read as one undifferentiated "would not
 * start", and the two most common causes -- another application holding the
 * camera, and a stale deviceId -- need opposite responses.
 */
const CAMERA_ERRORS = {
  NotReadableError: {
    retry: true,
    advice:
      "Another application is using it. Close Teams, Zoom or the Camera app and try again.",
  },
  TrackStartError: {
    retry: true,
    advice: "The camera was still busy. Close anything else using it and try again.",
  },
  AbortError: { retry: true, advice: "The camera did not start in time. Try again." },
  NotAllowedError: {
    retry: false,
    advice:
      "Permission was refused. Allow camera access for this site in the browser's address bar.",
  },
  PermissionDeniedError: {
    retry: false,
    advice: "Permission was refused. Allow camera access for this site.",
  },
  OverconstrainedError: {
    retry: false,
    advice: "The camera cannot deliver the requested resolution.",
  },
  ConstraintNotSatisfiedError: {
    retry: false,
    advice: "The camera cannot deliver the requested resolution.",
  },
  NotFoundError: {
    retry: false,
    advice: "That camera is no longer attached. Re-detect cameras.",
  },
  DevicesNotFoundError: {
    retry: false,
    advice: "That camera is no longer attached. Re-detect cameras.",
  },
  SecurityError: {
    retry: false,
    advice:
      "Cameras need a secure page. Use https, or run the server with --https for a phone.",
  },
};

function classify(err) {
  const text = String(err?.message || err || "");
  const name =
    err?.name && CAMERA_ERRORS[err.name]
      ? err.name
      : Object.keys(CAMERA_ERRORS).find((key) => text.includes(key)) || "";
  const known = CAMERA_ERRORS[name];
  return {
    name: name || "CameraError",
    retry: Boolean(known?.retry),
    advice: known?.advice || "",
    message: text || "The camera would not start.",
  };
}

/**
 * Returned by `startCamera` when another start is already in flight.
 *
 * It must not be `false`. Every caller treated a falsy return as "this camera
 * is dead" and escalated: a second click on Start while the first was still
 * opening produced a Vision Agent failover, a dialog announcing the switch, six
 * authenticated POSTs, and finally "No camera on this machine would start" --
 * having torn down the camera that was in the middle of opening successfully.
 */
const BUSY = "busy";

/**
 * How long the live decoder may come up empty before the server is asked.
 *
 * A stalled scan has two quite different causes and they need opposite
 * responses. The camera may genuinely be failing -- and that is what the
 * failover is for. Or the camera may be working perfectly and pointed at a 1-D
 * barcode, which the live decoder *cannot* read at any distance: html5-qrcode
 * sizes its decode canvas from the CSS width of the viewport element, so a
 * 1920-wide frame reaches it at roughly 570 pixels, under two pixels per module
 * for an EAN-13 where the floor is about four.
 *
 * Switching cameras in the second case is worse than useless: it interrupts the
 * operator, blames hardware that is fine, and the new camera fails identically.
 * So before the watchdog is allowed to call it a camera fault, the full-
 * resolution frame goes to the server decoder once. Comfortably shorter than
 * the failover patience, so this always gets its turn first.
 */
const SERVER_READ_AFTER_SECONDS = 3;

/** Never leave more than this between server attempts, however wide the
 *  duplicate window is set. A label held in frame should be read promptly. */
const SERVER_READ_MAX_GAP_SECONDS = 2.5;

/**
 * Attempts at the quick cadence before it slows down, and what it slows to.
 *
 * Each attempt posts the frame at full resolution -- around 300 KB for a 1080p
 * camera -- and costs the server real single-threaded CPU. That is a fair price
 * while someone is holding a label up, and not a fair price for a scanner left
 * open and pointed at an empty bench, which is most of a working day. The first
 * few seconds of a stall are when a label is most likely to be present, so the
 * quick cadence covers those and then backs off until something reads.
 */
const SERVER_READ_QUICK_ATTEMPTS = 6;
const SERVER_READ_IDLE_GAP_SECONDS = 6;

/**
 * How long a successful server read keeps the quick cadence running.
 *
 * Without this the reads DOUBLE-COUNT, and the reason is not obvious. A
 * successful read resets the idle clock, which is what stops the failover -- but
 * the trigger above it is "idle longer than SERVER_READ_AFTER_SECONDS", so the
 * next attempt cannot come sooner than that. Three seconds is longer than the
 * two-second duplicate window, so a label still sitting in front of the lens
 * lands OUTSIDE the window and is counted a second time, and a third, for as
 * long as it stays there. The per-attempt gap does not save it: the watchdog
 * gate dominates.
 *
 * So once a read succeeds, keep polling at the quick cadence for a few seconds
 * rather than waiting to go idle again. Repeats then land inside the duplicate
 * window, where the gate suppresses them and slides forward, which is exactly
 * how a label held in frame stays one unit. When the label leaves, the reads
 * start missing, the hold lapses, and the idle trigger takes over again.
 */
const SERVER_READ_HOLD_SECONDS = 4;

export const CAMERA_STATUS = {
  IDLE: "idle",
  STARTING: "starting",
  RUNNING: "running",
  FAILING_OVER: "failing-over",
  TESTING: "testing",
  ERROR: "error",
};

/** Which live device a configured camera row refers to.
 *
 * The deviceId is checked first because it is exact when it is still valid.
 * `device_label` is the fallback the camera store keeps specifically for the
 * case the id was reissued -- a browser profile reset, or a new origin -- and
 * without using it a re-registered camera silently loses its test history and
 * its role.
 */
/**
 * Cameras that exist but can never read a label.
 *
 * A virtual camera with no source produces black frames; an infrared sensor
 * produces a washed-out IR image. Both open successfully and raise no error, so
 * nothing but the watchdog ever notices -- twelve seconds per attempt, on the
 * camera the operator is most likely to be given by default on Windows.
 */
const SYNTHETIC = /\b(obs|virtual|nvidia|broadcast|infrared|\bir\b|snap camera|droidcam|manycam|xsplit|windows hello)\b/i;

function isSyntheticCamera(label) {
  return SYNTHETIC.test(label || "");
}

function matchesDevice(row, device) {
  if (!row || !device) return false;
  if (row.device_id && row.device_id === device.id) return true;
  if (row.device_label && device.label && row.device_label === device.label) return true;
  if (row.group_id && device.groupId && row.group_id === device.groupId) return true;
  return false;
}

export function useCamera({
  onDecode,
  failoverSeconds = 12,
  // The caller's duplicate-read window, in seconds. The automatic server read
  // has to repeat faster than this while a label sits in frame: the gate that
  // stops one label becoming several units slides forward on every suppressed
  // read, so attempts landing INSIDE the window are counted once, and attempts
  // landing outside it are counted again. Reading it from the caller rather
  // than assuming two seconds means changing the setting cannot silently turn
  // the scanner into a double-counter.
  duplicateWindowSeconds = 2,
} = {}) {
  const [cameras, setCameras] = useState([]);
  const [activeIndex, setActiveIndex] = useState(0);
  const [failoverNotice, setFailoverNotice] = useState(null);
  const [status, setStatus] = useState(CAMERA_STATUS.IDLE);
  const [error, setError] = useState("");
  const [events, setEvents] = useState([]);
  const [capabilities, setCapabilities] = useState({ zoom: null, torch: false });
  const [decodeCount, setDecodeCount] = useState(0);
  const [configuredReady, setConfiguredReady] = useState(false);
  // Everything enumerateDevices reported, before roles or exclusions are
  // applied. `cameras` is the scan order and deliberately omits disabled
  // cameras; this is the answer to "what is physically plugged in".
  const [devices, setDevices] = useState([]);
  // A measurement spans several awaits during which status legitimately leaves
  // TESTING (stop -> IDLE -> STARTING -> RUNNING), so status alone cannot gate
  // the Test button and a second press could start a competing measurement.
  const [measuring, setMeasuring] = useState(false);

  const scannerRef = useRef(null);
  const trackRef = useRef(null);
  // The watchdog and the track listeners outlive the render that created them,
  // so everything they read has to come from a ref. Reading `cameras` straight
  // from the closure made the first session's watchdog believe there was never
  // a backup camera.
  const camerasRef = useRef([]);
  const activeIndexRef = useRef(0);
  const reportRef = useRef(() => {});
  const decodeCountRef = useRef(0);
  const startWatchdogRef = useRef(() => {});
  const elementId = useRef("scanner-viewport");
  const watchdogRef = useRef(null);
  const lastDecodeRef = useRef(0);
  const runningRef = useRef(false);
  const triedRef = useRef(new Set());
  const onDecodeRef = useRef(onDecode);
  onDecodeRef.current = onDecode;
  const failoverSecondsRef = useRef(failoverSeconds);
  failoverSecondsRef.current = failoverSeconds;
  const duplicateWindowRef = useRef(duplicateWindowSeconds);
  duplicateWindowRef.current = duplicateWindowSeconds;
  // readBarcode is defined far below this point and the watchdog is created
  // above it, so the watchdog reaches it through a ref for the same reason
  // startCamera does.
  const readBarcodeRef = useRef(async () => ({ ok: false }));
  // One automatic server read at a time, and not immediately after the last.
  // The frame is ~300 KB and the decode is pure-Python, so overlapping attempts
  // would queue behind each other and arrive describing a frame long gone.
  const serverReadRef = useRef({ busy: false, at: 0, misses: 0, hitAt: 0, seenDecodes: 0 });
  // Configured rows from the server, keyed by nothing in particular -- they are
  // matched onto live devices, because only the browser knows what is attached
  // and only the server knows which of them a manager designated as the backup.
  const configuredRef = useRef({ order: [], excluded: [] });
  // Decode attempts, counted from html5-qrcode's per-frame failure callback.
  // This is the only honest denominator for a decode rate: it counts frames the
  // decoder actually looked at, not frames the camera produced.
  const framesRef = useRef(0);
  const measuringRef = useRef(null);
  // Two calls to startCamera must never overlap. `clearElement()` detaches the
  // <video> but does NOT stop its tracks, so an in-flight getUserMedia that
  // resolves after its element was wiped leaves a live MediaStream with nothing
  // left holding a reference to it -- the device stays open for the life of the
  // tab and every later open of it fails with NotReadableError. Double-clicking
  // Start was enough to do this, because the button stays on screen while the
  // status is STARTING.
  const startingRef = useRef(false);
  // startCamera is referenced from report(), which is memoised without it. A
  // ref keeps that reference current; the previous code captured the very first
  // render's startCamera forever, so every failover re-probed the default
  // camera before it would touch the camera it was failing over to.
  const startCameraRef = useRef(async () => false);
  // Failover recursion has to be bounded. When enumeration fails while cameras
  // exist, report() and startCamera() used to call each other indefinitely,
  // firing a getUserMedia probe and an authenticated POST on every turn.
  const failoverDepthRef = useRef(0);
  const MAX_FAILOVER_DEPTH = 6;

  const log = useCallback((level, message) => {
    setEvents((prev) =>
      [{ at: new Date().toISOString(), level, message }, ...prev].slice(0, 25)
    );
  }, []);

  // -- what the manager configured for this machine ---------------------
  /**
   * The order the scanner should try cameras in, decided by the server.
   *
   * The ordering rule lives in `store/cameras.scanner_order` and stays there:
   * primary first, then the manager's order, then better-graded cameras before
   * untested ones. Re-deriving it here would be a second copy that drifts.
   */
  const loadConfigured = useCallback(async () => {
    try {
      const data = await api.cameraOrder(stationId());
      configuredRef.current = {
        order: data.cameras || [],
        excluded: data.excluded || [],
      };
    } catch {
      // Not configured yet, or the operator cannot read the list. Auto-detect
      // still works -- configuration makes failover deliberate, not possible.
      configuredRef.current = { order: [], excluded: [] };
    }
    setConfiguredReady(true);
    return configuredRef.current;
  }, []);

  /**
   * Merge what is attached with what was configured.
   *
   * A configured camera that is not attached cannot be opened, so it is left
   * out. An attached camera that was never configured is still usable and is
   * appended after the configured ones -- refusing to scan on an unregistered
   * webcam would be a worse failure than scanning on it.
   */
  const merge = useCallback((devices, configured) => {
    const { order, excluded } = configured;
    const used = new Set();
    const slots = [];

    for (const row of order) {
      if (row.kind === "network") {
        // A network camera has no deviceId and is not a MediaStream. It is
        // carried through so the operator can see it is configured, and the
        // scanner reports plainly that it cannot open one rather than
        // pretending the slot is empty.
        slots.push({
          id: `network:${row.id}`,
          label: row.name,
          name: row.name,
          role: row.role,
          kind: "network",
          configured: true,
          cameraId: row.id,
          streamUrl: row.stream_url,
          grade: row.last_test?.grade || "",
          score: row.last_test?.score ?? null,
          attached: false,
        });
        continue;
      }
      // Strongest match wins, not the earliest device in enumeration order.
      // `find` returned whichever device satisfied ANY of the three predicates
      // first, so a weak label or group match on the built-in camera could
      // claim a row whose exact deviceId belonged to the USB camera listed
      // after it -- silently swapping the two cameras' names, roles and
      // measurement histories.
      const device =
        devices.find((d) => !used.has(d.id) && row.device_id && d.id === row.device_id) ||
        devices.find(
          (d) => !used.has(d.id) && row.device_label && d.label === row.device_label
        ) ||
        devices.find((d) => !used.has(d.id) && row.group_id && d.groupId === row.group_id);
      if (!device) continue;
      used.add(device.id);
      slots.push({
        id: device.id,
        label: device.label || row.name,
        name: row.name,
        role: row.role,
        kind: "device",
        configured: true,
        cameraId: row.id,
        groupId: device.groupId,
        grade: row.last_test?.grade || "",
        score: row.last_test?.score ?? null,
        wantWidth: row.want_width,
        wantHeight: row.want_height,
        attached: true,
      });
    }

    const offIds = new Set();
    for (const row of excluded) {
      const device = devices.find((d) => matchesDevice(row, d));
      if (device) offIds.add(device.id);
    }

    for (const device of devices) {
      if (used.has(device.id)) continue;
      if (offIds.has(device.id)) continue;      // deliberately turned off
      slots.push({
        id: device.id,
        label: device.label || "Camera",
        name: "",
        role: "",
        kind: "device",
        configured: false,
        cameraId: null,
        groupId: device.groupId,
        grade: "",
        score: null,
        attached: true,
      });
    }
    return slots;
  }, []);

  // -- enumerate ------------------------------------------------------
  /**
   * List the attached cameras.
   *
   * Enumerates directly rather than through `Html5Qrcode.getCameras()`, which
   * always opens and closes the default camera first. See the module comment:
   * that grab-and-release is what made USB webcams fail to start on Windows.
   */
  const refreshCameras = useCallback(
    async ({ unlock = true } = {}) => {
      if (!navigator.mediaDevices?.enumerateDevices) {
        setError(
          "This browser cannot list cameras. Cameras need a secure page -- use https, or run the server with --https."
        );
        log("error", "mediaDevices is unavailable on this origin.");
        return [];
      }

      try {
        let found = (await navigator.mediaDevices.enumerateDevices()).filter(
          (d) => d.kind === "videoinput"
        );

        // Labels are blank until camera permission has been granted at least
        // once, and a blank label is useless in a picker. Unlock once, then let
        // the device settle: Windows releases a UVC camera *after* the promise
        // resolves, and opening it again too soon is the NotReadableError this
        // whole path exists to avoid.
        const blank = found.length === 0 || found.some((d) => !d.label);
        if (blank && unlock) {
          let stream = null;
          try {
            stream = await navigator.mediaDevices.getUserMedia({ video: true });
            stopStream(stream);
            await settle(300);
            found = (await navigator.mediaDevices.enumerateDevices()).filter(
              (d) => d.kind === "videoinput"
            );
          } catch (err) {
            // THE most important line in this file.
            //
            // `{video: true}` opens whatever Windows calls the default camera,
            // which is usually the built-in one. If Teams holds it, or the
            // privacy shutter is closed, or Windows camera permission is off,
            // this throws -- and the old code let that throw abandon the whole
            // enumeration, so a perfectly free USB webcam plugged in next to it
            // reported "No camera was found on this device."
            //
            // A blank label is a cosmetic problem. Losing the device list is a
            // functional one. Keep the list.
            stopStream(stream);
            log(
              "warn",
              `The default camera could not be opened (${classify(err).name}), so camera names may be blank. Other cameras are still usable.`
            );
          }
        }

        // Firefox reports a placeholder entry with an empty id before
        // permission; it cannot be opened, so it must not occupy a slot.
        const devices = [];
        const seen = new Set();
        for (const d of found) {
          if (!d.deviceId || seen.has(d.deviceId)) continue;
          seen.add(d.deviceId);
          devices.push({ id: d.deviceId, label: d.label, groupId: d.groupId });
        }

        setDevices(devices);
        const slots = merge(devices, configuredRef.current);
        setCameras(slots);
        camerasRef.current = slots;

        const usable = slots.filter((s) => s.attached);
        if (usable.length === 0) {
          setError("No camera was found on this device.");
          log("error", "No cameras detected.");
        } else {
          setError("");
          const named = usable.filter((s) => s.configured).length;
          log(
            "info",
            `${usable.length} camera${usable.length === 1 ? "" : "s"} available` +
              (named ? `, ${named} configured for this machine.` : ".") +
              (usable.length === 1
                ? " With only one camera there is no failover; photo and manual entry remain."
                : "")
          );
        }
        return slots;
      } catch (err) {
        const info = classify(err);
        setError(
          info.advice ||
            "Camera access was refused. Allow it in the browser, or use photo or manual entry."
        );
        log("error", `Could not list cameras: ${info.message}`);
        return [];
      }
    },
    [log, merge]
  );

  // -- watchdog -------------------------------------------------------
  const clearWatchdog = useCallback(() => {
    if (watchdogRef.current) {
      clearInterval(watchdogRef.current);
      watchdogRef.current = null;
    }
  }, []);

  /**
   * Watch for the failure that raises no error at all: the camera is running,
   * frames are arriving, and nothing decodes. Only elapsed time can catch it,
   * which is why this exists at all.
   *
   * Everything it reads comes from a ref. The previous version closed over
   * `cameras`, which was still the empty first-render array, so it believed
   * there was never a backup to switch to.
   */
  /**
   * Ask the server to read the current frame, because the browser could not.
   *
   * This is the same full-resolution read the "Read barcode" button performs,
   * fired automatically. It succeeds only for a 1-D barcode -- the case the
   * live decoder structurally cannot handle -- so a success here is positive
   * evidence that the camera is fine and the failover must not run.
   *
   * The decoded code goes out through the ordinary decode callback, tagged
   * "barcode" rather than as deliberate input, so it passes the duplicate guard
   * exactly like a live read. Anything else would let a label sitting in frame
   * become a unit every few seconds.
   */
  const tryServerRead = useCallback(() => {
    const state = serverReadRef.current;
    if (state.busy) return;
    // Fast enough to land inside the duplicate window while a label is present,
    // then slower once several attempts in a row have found nothing.
    const quickGap = Math.min(
      SERVER_READ_MAX_GAP_SECONDS,
      Math.max(0.8, (duplicateWindowRef.current || 0) * 0.6)
    );
    const gapMs = (state.misses >= SERVER_READ_QUICK_ATTEMPTS
      ? SERVER_READ_IDLE_GAP_SECONDS
      : quickGap) * 1000;
    const now = Date.now();
    if (now - state.at < gapMs) return;
    state.busy = true;
    state.at = now;

    Promise.resolve()
      .then(() => readBarcodeRef.current({ quiet: true }))
      .then((result) => {
        // The camera may have been stopped or put into a measurement while the
        // frame was in flight; a decode arriving after that is not stock.
        if (!runningRef.current || measuringRef.current) return;
        if (!result?.code) {
          serverReadRef.current.misses += 1;
          return;
        }
        serverReadRef.current.misses = 0;
        // Hold the quick cadence open, so the next attempt lands inside the
        // duplicate window instead of after it. See SERVER_READ_HOLD_SECONDS.
        serverReadRef.current.hitAt = Date.now();
        // Treat this exactly as a live decode: it resets the idle clock, so the
        // watchdog stops counting down towards a failover that would have
        // blamed a camera that was working the whole time.
        lastDecodeRef.current = Date.now();
        decodeCountRef.current += 1;
        setDecodeCount((n) => n + 1);
        onDecodeRef.current?.(
          result.code,
          "barcode",
          camerasRef.current[activeIndexRef.current]
        );
      })
      .catch(() => {
        // readBarcode already logs. Count it as a miss so an unreachable or
        // failing server backs the cadence off instead of being retried at
        // full speed for as long as the scanner is open.
        serverReadRef.current.misses += 1;
      })
      .finally(() => {
        serverReadRef.current.busy = false;
      });
  }, []);

  const startWatchdog = useCallback(() => {
    clearWatchdog();
    watchdogRef.current = setInterval(() => {
      if (!runningRef.current || measuringRef.current) return;
      const idle = (Date.now() - lastDecodeRef.current) / 1000;

      // Before the camera can be blamed, rule out the failure that is not the
      // camera's fault. This runs well before the failover threshold, so a 1-D
      // barcode is read rather than answered with a camera switch.
      // Two ways in. Either the live decoder has been silent long enough to
      // suspect a barcode, or the server read is already succeeding and must
      // keep its cadence up so repeats stay inside the duplicate window.
      const sinceHit = (Date.now() - serverReadRef.current.hitAt) / 1000;
      if (idle > SERVER_READ_AFTER_SECONDS || sinceHit < SERVER_READ_HOLD_SECONDS) {
        tryServerRead();
      }

      // Clear the backoff only when something actually READ, never merely
      // because the idle clock looks healthy. report("no_decode") resets that
      // clock itself every failover cycle, so keying off it meant the backoff
      // was wiped every twelve seconds and could never engage -- leaving the
      // scanner posting a full-resolution frame every couple of seconds at an
      // empty bench, which is the whole thing the backoff exists to stop.
      if (decodeCountRef.current !== serverReadRef.current.seenDecodes) {
        serverReadRef.current.seenDecodes = decodeCountRef.current;
        serverReadRef.current.misses = 0;
      }

      if (idle > failoverSecondsRef.current) {
        // Ask once, then reset the clock so a "keep waiting" answer does not
        // turn into a request every two seconds.
        lastDecodeRef.current = Date.now();
        reportRef.current("no_decode");
      }
    }, 1000);
  }, [clearWatchdog, tryServerRead]);
  startWatchdogRef.current = startWatchdog;

  // -- stop -----------------------------------------------------------
  /**
   * Stop the running camera and release the device.
   *
   * `stop()` is raced against a timeout because it can hang outright: when a
   * USB camera is unplugged the stream can be left with no video tracks, and
   * html5-qrcode's close path then never resolves. Since `startCamera` begins
   * by awaiting this, a hang there deadlocks the whole camera subsystem with no
   * error and no change on screen -- which looks exactly like "the webcam just
   * will not attach".
   *
   * The belt-and-braces track stop afterwards matters for the same reason: if
   * the library's own teardown did not run, the device is still held, and every
   * later attempt to open it fails with NotReadableError.
   */
  const stop = useCallback(async () => {
    clearWatchdog();
    runningRef.current = false;
    const scanner = scannerRef.current;
    const track = trackRef.current || trackFrom(elementId.current);
    scannerRef.current = null;
    trackRef.current = null;
    if (scanner) {
      try {
        await Promise.race([scanner.stop(), settle(1500)]);
      } catch {
        /* already stopped, or it threw rather than rejected: either is fine */
      }
      try {
        await Promise.race([scanner.clear(), settle(500)]);
      } catch {
        /* the element may already be gone */
      }
    }
    try {
      track?.stop?.();
    } catch {
      /* the track was already ended */
    }
    setStatus(CAMERA_STATUS.IDLE);
    setCapabilities({ zoom: null, torch: false });
  }, [clearWatchdog]);

  // -- start one specific camera ---------------------------------------
  const startCamera = useCallback(
    async (index, reason = "") => {
      // Never let two starts overlap. See startingRef: an orphaned MediaStream
      // holds a USB camera open for the life of the tab, and after that every
      // attempt to open it fails permanently.
      if (startingRef.current) {
        log("info", "A camera is already starting; ignoring the second request.");
        return BUSY;
      }
      startingRef.current = true;
      try {
        // camerasRef, never the `cameras` state: on the first start() the state
        // is still the empty first-render array, and reading it made this
        // enumerate a second time -- doubling the grab-and-release that stops a
        // USB camera opening at all.
        let devices = camerasRef.current;
        if (!devices.length) devices = await refreshCameras();
        const openable = devices.filter((d) => d.attached);
        if (!openable.length) return false;

        const target = devices[index % devices.length] || openable[0];
        // Mark it tried FIRST. If this returns without doing so, the Vision
        // Agent recommends the same camera again on the next report and the two
        // call each other forever. It is removed again on success below --
        // `tried` means "failed this session", and leaving a working camera in
        // it meant that after two ordinary switches every camera looked
        // exhausted and the operator was told nothing worked.
        triedRef.current.add(target.id);
        if (!target.attached) {
          log(
            "error",
            `"${target.name || target.label}" is a network camera. The scanner opens device cameras only.`
          );
          return false;
        }

        await stop();
        // Windows hands a UVC device back asynchronously: stop() resolves long
        // before the driver has released it. Opening the next camera without
        // this pause is the single most reproducible way to get
        // NotReadableError on a machine whose cameras are all working.
        await settle(150);
        setStatus(CAMERA_STATUS.STARTING);
        setError("");

      const { Html5Qrcode, Html5QrcodeSupportedFormats } = await loadScanner();
      const formats = supportedFormats(Html5QrcodeSupportedFormats);

      const handleDecode = (text, result) => {
        lastDecodeRef.current = Date.now();
        framesRef.current += 1;
        decodeCountRef.current += 1;
        setDecodeCount((n) => n + 1);
        let format = "qr";
        try {
          format = result?.result?.format?.formatName || "qr";
        } catch {
          /* format is a nicety, not worth failing a scan over */
        }
        const measuring = measuringRef.current;
        if (measuring) {
          // frames is EVERY frame the decoder examined, and a decoded frame is
          // one of them. Counting only the misses made decode_rate come out as
          // decodes/misses -- which exceeds 1.0 the moment a camera reads well,
          // and is 0/0 for a camera that reads every frame. The best camera on
          // site was being graded "unusable"; the fake camera in testing, which
          // decodes nothing, hid it completely.
          measuring.frames += 1;
          measuring.decodes += 1;
          if (measuring.firstMs === null) measuring.firstMs = performance.now() - measuring.startedAt;
          if (format && !measuring.formats.includes(format)) measuring.formats.push(format);
          // A measurement run must not also move stock. The operator is
          // pointing the camera at a test label, not receiving goods.
          return;
        }
        onDecodeRef.current?.(text, format, target);
      };

      // Every frame the decoder looked at and could not read arrives here. It
      // is noise for scanning but it is the denominator for a decode rate, and
      // the camera test is worthless without it.
      //
      // This fires exactly once per frame only because `disableFlip` is set
      // below. Left at its default, html5-qrcode re-scans a mirrored copy of
      // every frame that failed and calls this a second time, so a miss counted
      // double and every measured decode rate came out roughly half what the
      // camera actually managed.
      const handleMiss = () => {
        framesRef.current += 1;
        if (measuringRef.current) measuringRef.current.frames += 1;
      };

      const wantWidth = target.wantWidth || 1920;
      const wantHeight = target.wantHeight || 1080;

      // No qrbox: decode the whole frame. A cropped box is the single most
      // common reason 1-D barcodes fail -- a wide label rarely sits fully
      // inside it, and a partly-cropped barcode can never decode, while a
      // square QR always fitted and hid the problem.
      //
      // The ladder walks from "exactly this camera at full resolution" down to
      // "exactly this camera, however it likes". It never falls back to a
      // *different* camera: an operator who picked the USB scanner and silently
      // got the laptop's built-in lens would have no way to tell.
      // disableFlip: a warehouse label is printed the right way round, and a
      // front camera mirrors only its CSS preview, never the captured frames.
      // Leaving the flip on made html5-qrcode scan every failed frame twice --
      // halving the real scan rate and double-counting misses in the measurement.
      const attempts = [
        {
          fps: 12,
          disableFlip: true,
          videoConstraints: {
            deviceId: { exact: target.id },
            width: { ideal: wantWidth },
            height: { ideal: wantHeight },
          },
        },
        {
          fps: 10,
          disableFlip: true,
          videoConstraints: {
            deviceId: { exact: target.id },
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
        },
        { fps: 10, disableFlip: true, videoConstraints: { deviceId: { exact: target.id } } },
        // Last resort: `ideal` rather than `exact`. A deviceId goes stale when
        // browser storage is cleared or the camera is re-enumerated on a
        // different USB port, and `exact` fails outright where `ideal` still
        // opens the closest match.
        { fps: 10, disableFlip: true, videoConstraints: { deviceId: { ideal: target.id } } },
      ];

      let lastInfo = null;
      for (let i = 0; i < attempts.length; i += 1) {
        // A fresh instance per attempt. A rejected start() leaves a stray
        // <video> in the container and the instance mid-transition, so reusing
        // it made every later attempt fail for a reason that had nothing to do
        // with the camera.
        const scanner = new Html5Qrcode(elementId.current, {
          formatsToSupport: formats,
          verbose: false,
        });
        scannerRef.current = scanner;
        try {
          await scanner.start(
            { deviceId: { exact: target.id } },
            attempts[i],
            handleDecode,
            handleMiss
          );
        } catch (err) {
          lastInfo = classify(err);
          try {
            await scanner.clear();
          } catch {
            /* the container is being reused by the next attempt anyway */
          }
          scannerRef.current = null;
          // Windows hands a UVC camera back asynchronously. When the complaint
          // is "could not start video source", waiting briefly and asking again
          // is what actually works -- retrying immediately fails identically.
          if (lastInfo.retry && i < attempts.length - 1) await settle(400);
          continue;
        }

        runningRef.current = true;
        // It opened, so it has not failed. See the note above triedRef.add.
        triedRef.current.delete(target.id);
        activeIndexRef.current = index % devices.length;
        setActiveIndex(index % devices.length);
        lastDecodeRef.current = Date.now();
        startWatchdogRef.current();      // survives every failover
        setStatus(CAMERA_STATUS.RUNNING);
        const shown = target.name || target.label || `camera ${index + 1}`;
        log(
          reason ? "warn" : "info",
          reason ? `Switched to "${shown}" -- ${reason}` : `Started "${shown}".`
        );

        // Read the live track. html5-qrcode has NO getRunningTrack() method
        // -- the earlier code called one and optional chaining swallowed the
        // miss, so the disconnect listener below was never attached and the
        // unplugged-camera failover never once fired. The library does put a
        // real <video> in our container, so take the track from there.
        const track = trackFrom(elementId.current);
        trackRef.current = track;

        try {
          const caps =
            track?.getCapabilities?.() || scanner.getRunningTrackCapabilities?.() || {};
          setCapabilities({
            zoom: caps.zoom && caps.zoom.max > (caps.zoom.min || 1) ? caps.zoom : null,
            torch: Boolean(caps.torch),
          });
        } catch {
          /* capabilities are optional across browsers */
        }

        // A track that ends on its own means the device went away -- the
        // unplugged-USB-camera case. React immediately rather than waiting
        // out the whole watchdog period.
        if (track) {
          track.addEventListener("ended", () => {
            if (runningRef.current) reportRef.current("track_ended");
          });
          // Some platforms mute a track instead of ending it when another
          // application takes the camera.
          track.addEventListener("mute", () => {
            if (runningRef.current) reportRef.current("stalled");
          });
        }
        return true;
      }

      // Every attempt failed. Say which camera and why, rather than the bare
      // "would not start" the old code logged: "another application is using
      // it" and "that camera is no longer attached" need opposite responses
      // from the operator.
      const shown = target.name || target.label || target.id;
      log("error", `"${shown}" would not start. ${lastInfo?.advice || lastInfo?.message || ""}`.trim());
      if (lastInfo?.advice) setError(lastInfo.advice);
      // Leave a status that reflects reality. Callers that do not escalate --
      // switchTo, and measure when it gives up -- used to leave the screen
      // reading "Starting" forever, with a spinner and no camera behind it.
      // An escalating caller overwrites this with FAILING_OVER a moment later.
      setStatus(CAMERA_STATUS.ERROR);
      return false;
      } finally {
        startingRef.current = false;
      }
    },
    // failover is declared below; the reference is resolved at call time.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [refreshCameras, stop, log]
  );
  // Keep the ref pointing at the current startCamera. report() reaches it
  // through here rather than closing over it, because a closure captured on
  // first render never sees a later camera list.
  startCameraRef.current = startCamera;

  // -- failover, decided by the Vision Agent ---------------------------
  /**
   * Report a symptom and do what the agent decides.
   *
   * The browser is the only thing that can see the camera, so it observes; the
   * Vision Agent weighs the symptom against the cameras available and decides
   * whether to switch, wait, or give up on cameras entirely. Its reasoning
   * comes back with the decision and is shown to the operator, because a
   * silent failover is indistinguishable from a camera that never worked.
   *
   * The camera list sent up now carries each camera's configured role and its
   * last measured grade, so the agent can prefer the camera a manager
   * designated as the backup over whichever one happens to be next in the list.
   */
  const report = useCallback(
    async (symptom) => {
      const devices = camerasRef.current;
      const active = activeIndexRef.current;
      const idle = (Date.now() - lastDecodeRef.current) / 1000;

      // The camera being reported on is the one that just failed, so record it
      // before asking. Without this the agent can recommend switching straight
      // back to it -- it is no longer `active` once we move away, and a
      // successful start now clears it from `tried`.
      if (devices[active]?.id) triedRef.current.add(devices[active].id);

      // Bound the recursion. When enumeration fails while cameras exist, this
      // and startCamera used to call each other without end, firing a
      // getUserMedia probe and an authenticated POST on every turn while the
      // screen sat on "Switching camera" and the camera light flickered.
      if (failoverDepthRef.current >= MAX_FAILOVER_DEPTH) {
        failoverDepthRef.current = 0;
        await stop();
        setStatus(CAMERA_STATUS.ERROR);
        setError(
          "No camera on this machine would start. Use a photo or type the code in."
        );
        log("error", "Stopped trying cameras after too many failed switches.");
        return false;
      }
      failoverDepthRef.current += 1;

      let verdict;
      try {
        verdict = await api.visionFailover({
          symptom,
          cameras: devices.map((d) => ({
            id: d.id,
            label: d.name || d.label,
            role: d.role || "",
            grade: d.grade || "",
            score: d.score,
            configured: Boolean(d.configured),
            attached: Boolean(d.attached),
            kind: d.kind || "device",
          })),
          active_index: active,
          tried: devices
            .map((d, i) => (triedRef.current.has(d.id) && i !== active ? i : -1))
            .filter((i) => i >= 0),
          idle_seconds: idle,
          decodes: decodeCountRef.current,
        });
      } catch {
        // The agent is unreachable. Falling back to the local rule keeps the
        // line running: a warehouse must not stop scanning because the
        // decision service is down.
        const next = devices.findIndex(
          (d, i) => i !== active && d.attached && !triedRef.current.has(d.id)
        );
        verdict = {
          action: next >= 0 ? "switch" : "fallback",
          target: next >= 0 ? next : active,
          reasons: ["The camera stopped working and the Vision Agent could not be reached."],
        };
      }

      if (verdict.action === "keep") {
        failoverDepthRef.current = 0;
        return false;
      }

      if (verdict.action === "switch") {
        setStatus(CAMERA_STATUS.FAILING_OVER);
        const label = verdict.target_label || `camera ${verdict.target + 1}`;
        log("warn", `Switching to ${label}: ${(verdict.reasons || [])[0] || symptom}`);
        setFailoverNotice({
          symptom,
          action: "switch",
          from: devices[active]?.name || devices[active]?.label || "the camera",
          to: label,
          reasons: verdict.reasons || [],
          at: Date.now(),
        });
        // Through the ref, never the closure: a startCamera captured on first
        // render re-probes the default camera before touching the target, so
        // failing over to a working USB camera used to be gated on first
        // succeeding with the broken one.
        // The agent answers with an INDEX, resolved against the list we sent
        // it. A devicechange between the POST and the reply re-orders that list,
        // so translate back through the id we actually meant.
        const wanted = devices[verdict.target]?.id;
        const now = camerasRef.current;
        let targetIndex = wanted ? now.findIndex((c) => c.id === wanted) : verdict.target;
        if (targetIndex < 0 || targetIndex >= now.length) {
          log("warn", "The camera list changed while the agent was deciding.");
          failoverDepthRef.current = 0;
          return false;
        }

        let ok = false;
        try {
          ok = await startCameraRef.current(
            targetIndex,
            "the Vision Agent switched to it"
          );
        } catch (err) {
          // Without this the depth counter stayed high and the NEXT genuine
          // failover was refused as "too many failed switches".
          failoverDepthRef.current = 0;
          log("error", `Switching camera failed: ${classify(err).message}`);
          setStatus(CAMERA_STATUS.ERROR);
          return false;
        }
        if (ok === BUSY) {
          // Something else is already opening a camera. Stand down rather than
          // fighting it for the device.
          failoverDepthRef.current = 0;
          return false;
        }
        if (ok) {
          failoverDepthRef.current = 0;
          return true;
        }
        // The backup would not start either. Ask again; the agent now knows it
        // has been tried and will move on rather than recommending it twice.
        return report("start_failed");
      }

      // No camera left worth trying.
      failoverDepthRef.current = 0;
      await stop();
      setStatus(CAMERA_STATUS.ERROR);
      setError(
        (verdict.reasons || []).slice(-1)[0] ||
          "No camera on this device is working. Use a photo or type the code in."
      );
      setFailoverNotice({
        symptom,
        action: "fallback",
        from: devices[active]?.name || devices[active]?.label || "the camera",
        reasons: verdict.reasons || [],
        at: Date.now(),
      });
      log("error", (verdict.reasons || []).join(" "));
      return false;
    },
    // startCamera is intentionally omitted: it is referenced through the ref
    // below, so this callback never goes stale when the camera list changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [log, stop]
  );
  reportRef.current = report;

  /** Switch by hand, without consulting the agent. */
  const failover = useCallback(
    (reason) => report(reason === "you asked to switch" ? "start_failed" : "no_decode"),
    [report]
  );

  // -- start (with watchdog) --------------------------------------------
  const start = useCallback(async () => {
    // Guard here too, not only inside startCamera. start() resets triedRef and
    // re-enumerates before it ever reaches that guard, so a second click wiped
    // the record of which cameras had already failed.
    if (startingRef.current) {
      log("info", "A camera is already starting.");
      return false;
    }
    triedRef.current = new Set();
    await loadConfigured();
    const devices = await refreshCameras();
    if (!devices.some((d) => d.attached)) {
      setStatus(CAMERA_STATUS.ERROR);
      return false;
    }

    // The configured order already carries the manager's intent -- primary
    // first, then position, then measured grade -- so when anything has been
    // configured for this machine, index 0 is the primary and there is nothing
    // to guess. Only when nothing is configured does the old heuristic apply:
    // prefer a rear-facing lens, because on a phone that is the usable one.
    let startIndex = 0;
    if (!devices[0]?.configured) {
      const rear = devices.findIndex(
        (d) => d.attached && /back|rear|environment/i.test(d.label || "")
      );
      startIndex =
        rear >= 0
          ? rear
          : // On Windows no label says "back", so index 0 always won -- and
            // index 0 there is frequently OBS Virtual Camera, NVIDIA Broadcast
            // or a Windows Hello infrared sensor. All three open cleanly, raise
            // no error, and decode nothing ever, so only the watchdog notices
            // twelve seconds later. Prefer a real camera when one is listed.
            devices.findIndex((d) => d.attached && !isSyntheticCamera(d.label)) >= 0
            ? devices.findIndex((d) => d.attached && !isSyntheticCamera(d.label))
            : devices.findIndex((d) => d.attached);
    }

    const ok = await startCamera(Math.max(0, startIndex));
    if (ok === BUSY) return false;
    if (!ok) return reportRef.current("start_failed");

    startWatchdog();
    return true;
  }, [loadConfigured, refreshCameras, startCamera, startWatchdog]);

  const switchTo = useCallback(
    (index) => startCamera(index, "you selected it"),
    [startCamera]
  );

  const applyZoom = useCallback(async (value) => {
    // Zoom is the single most effective camera-side fix for 1-D codes: it puts
    // more pixels across each bar without moving the label, which a fixed-focus
    // webcam cannot do.
    try {
      await scannerRef.current?.applyVideoConstraints({ advanced: [{ zoom: value }] });
    } catch {
      /* the device withdrew the capability; nothing to recover */
    }
  }, []);

  const applyTorch = useCallback(async (on) => {
    try {
      await scannerRef.current?.applyVideoConstraints({ advanced: [{ torch: on }] });
    } catch {
      /* torch is phone-only and often unavailable */
    }
  }, []);

  /** Decode a still photo. A phone photo is far sharper than a webcam frame,
   *  so this reads barcodes a fixed-focus laptop camera never will. */
  const scanFile = useCallback(
    async (file) => {
      const { Html5Qrcode, Html5QrcodeSupportedFormats } = await loadScanner();
      const wasRunning = runningRef.current;
      const wasIndex = activeIndexRef.current;
      if (wasRunning) await stop();
      const fileScanner = new Html5Qrcode(elementId.current, {
        formatsToSupport: supportedFormats(Html5QrcodeSupportedFormats),
        verbose: false,
      });
      try {
        const text = await fileScanner.scanFile(file, true);
        log("info", "Decoded from a photo.");
        onDecodeRef.current?.(text, "photo", { label: "photo" });
        return text;
      } finally {
        try {
          await fileScanner.clear();
        } catch {
          /* nothing to clean up */
        }
        // Put the camera back. Reading one photo used to leave the scanner
        // dark with no explanation, and the operator's next instinct is to
        // present a label to a camera that is no longer running.
        if (wasRunning) await startCamera(wasIndex, "the photo has been read");
      }
    },
    [stop, log, startCamera]
  );

  // -- server-side barcode read ------------------------------------------
  /**
   * Read a 1-D barcode from the live camera at FULL resolution.
   *
   * The scanner library never sees the camera's real resolution. It sizes its
   * decode canvas from the CSS width of the element and draws the frame into
   * it, so a 1920-wide frame reaches the decoder at roughly 570 pixels. An
   * EAN-13 is 95 modules; that is under two pixels per module, and the measured
   * floor is about four. A QR of the same physical size keeps four times the
   * pixel budget, is found by its finder patterns at any angle, and repairs the
   * rest with error correction -- which is exactly why QR codes read and
   * barcodes do not, on the same frame at the same distance.
   *
   * So this bypasses the library entirely: it takes the frame from the <video>
   * element at `videoWidth`, keeps a horizontal band through the middle (a 1-D
   * decoder never needs more), converts it to one byte per pixel, and posts it
   * to the Python decoder, which has no real-time budget to worry about and can
   * afford many scanlines in both directions.
   */
  const readBarcode = useCallback(
    async ({ bandHeight = 160, quiet = false } = {}) => {
      const video = videoFrom(elementId.current);
      if (!video || !video.videoWidth) {
        return { ok: false, reason: "The camera is not running." };
      }

      const width = video.videoWidth;
      const height = video.videoHeight;
      const band = Math.min(bandHeight, height);
      const top = Math.max(0, Math.floor((height - band) / 2));

      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = band;
      const context = canvas.getContext("2d", { willReadFrequently: true });
      if (!context) return { ok: false, reason: "Could not read the frame." };

      // Source rectangle is the middle band at native resolution; destination
      // is the same size, so nothing is scaled. That is the entire point.
      context.drawImage(video, 0, top, width, band, 0, 0, width, band);

      let rgba;
      try {
        rgba = context.getImageData(0, 0, width, band).data;
      } catch {
        // A tainted canvas cannot happen here (same-origin MediaStream), but a
        // browser that refuses is not worth crashing the scanner over.
        return { ok: false, reason: "This browser would not release the frame." };
      }

      // RGBA to luma, integer approximation of Rec. 601. One byte per pixel is
      // a third of the bytes and exactly what the decoder wants.
      const grey = new Uint8Array(width * band);
      for (let i = 0, p = 0; p < grey.length; i += 4, p += 1) {
        grey[p] = (77 * rgba[i] + 150 * rgba[i + 1] + 29 * rgba[i + 2]) >> 8;
      }

      try {
        const result = await api.decodeImage(grey, width, band);
        // The automatic read runs every second or two and misses most of the
        // time, by design -- there is usually no barcode in front of the lens.
        // Logging each miss would push the failover events, which are the
        // reason this log exists, out of the twenty-five it keeps.
        if (result.decoded || !quiet) {
          log(
            result.decoded ? "info" : "warn",
            result.decoded
              ? `Read ${result.code} server-side at ${result.module_pixels} px per module.`
              : `Server could not read a barcode: ${result.reason || "no match"}.`
          );
        }
        return result;
      } catch (err) {
        if (!quiet) log("error", `Server decode failed: ${err.message || err}`);
        return { ok: false, reason: err.message || "The server could not be reached." };
      }
    },
    [log]
  );
  // The watchdog is created above this point and calls it through a ref.
  readBarcodeRef.current = readBarcode;

  // -- measure a camera --------------------------------------------------
  /**
   * Run a camera for a few seconds and measure what it can actually do.
   *
   * Only the browser can do this: the server has never seen a camera. It sends
   * the raw measurement up and the *server* scores it, so the same camera earns
   * the same grade whichever machine tested it, and the scoring rule can be
   * changed in one place.
   *
   * Decodes are counted but deliberately not submitted as stock -- the operator
   * is holding a test label in front of the lens, not receiving goods.
   */
  const measure = useCallback(
    async (index, seconds = 6) => {
      const devices = camerasRef.current;
      const target = devices[index];
      if (!target?.attached) {
        return { ok: false, error: "That camera is not attached to this machine." };
      }

      const wasRunning = runningRef.current;
      const wasIndex = activeIndexRef.current;
      setStatus(CAMERA_STATUS.TESTING);
      setMeasuring(true);

      const run = {
        startedAt: performance.now(),
        frames: 0,
        decodes: 0,
        firstMs: null,
        formats: [],
      };
      measuringRef.current = run;

      let result;
      try {
        const started = await startCamera(index, "measuring it");
        if (started === BUSY) {
          return { ok: false, error: "A camera is already starting. Try again in a moment." };
        }
        if (!started) {
          result = {
            ok: false,
            error: "The camera would not start, so it could not be measured.",
            width: 0,
            height: 0,
            fps: 0,
            frames: 0,
            decodes: 0,
            first_ms: null,
            formats: [],
            capabilities: {},
            engine: "html5-qrcode",
          };
        } else {
          run.startedAt = performance.now();
          setStatus(CAMERA_STATUS.TESTING);
          await settle(seconds * 1000);

          const track = trackRef.current || trackFrom(elementId.current);
          const s = track?.getSettings?.() || {};
          const video = videoFrom(elementId.current);
          const caps = track?.getCapabilities?.() || {};
          const elapsed = (performance.now() - run.startedAt) / 1000;

          result = {
            ok: true,
            width: s.width || video?.videoWidth || 0,
            height: s.height || video?.videoHeight || 0,
            // The reported frameRate is what the camera claims. The frames the
            // decoder actually looked at, over the wall clock, is what it
            // delivered -- and that is the number worth grading.
            fps: elapsed > 0 ? Number((run.frames / elapsed).toFixed(2)) : 0,
            frames: run.frames,
            decodes: run.decodes,
            first_ms: run.firstMs === null ? null : Math.round(run.firstMs),
            formats: run.formats,
            capabilities: {
              zoom: Boolean(caps.zoom),
              torch: Boolean(caps.torch),
              focus: Boolean(caps.focusMode),
              claimed_fps: s.frameRate || null,
            },
            engine: "html5-qrcode",
          };
        }
      } catch (err) {
        const info = classify(err);
        result = {
          ok: false,
          error: info.message,
          width: 0,
          height: 0,
          fps: 0,
          frames: 0,
          decodes: 0,
          first_ms: null,
          formats: [],
          capabilities: {},
          engine: "html5-qrcode",
        };
      } finally {
        measuringRef.current = null;
        setMeasuring(false);
        if (wasRunning && wasIndex !== index) {
          await startCamera(wasIndex, "the test finished");
        } else if (!wasRunning) {
          await stop();
        } else {
          setStatus(runningRef.current ? CAMERA_STATUS.RUNNING : CAMERA_STATUS.IDLE);
        }
      }

      log(
        result.ok ? "info" : "error",
        result.ok
          ? `Measured "${target.name || target.label}": ${result.width}x${result.height}, ` +
            `${result.decodes}/${result.frames} frames decoded.`
          : `Could not measure "${target.name || target.label}": ${result.error}`
      );
      return result;
    },
    [startCamera, stop, log]
  );

  // -- devices coming and going -----------------------------------------
  /**
   * Plugging a USB camera in after the page loaded used to do nothing at all:
   * the list was read once and never again, so the new camera was invisible
   * until a reload. It is exactly the camera an operator plugs in *because* the
   * built-in one is not working, which made this the worst possible thing to
   * miss.
   */
  useEffect(() => {
    if (!navigator.mediaDevices?.addEventListener) return undefined;
    const onChange = () => {
      // Never unlock here: a devicechange fires while another application may
      // be opening the camera, and grabbing it back would fight for it.
      refreshCameras({ unlock: false }).then((slots) => {
        const attached = slots.filter((s) => s.attached).length;
        log("info", `Camera list changed -- ${attached} now attached.`);
      });
    };
    navigator.mediaDevices.addEventListener("devicechange", onChange);
    return () => navigator.mediaDevices.removeEventListener("devicechange", onChange);
  }, [refreshCameras, log]);

  // Load the configured order once, so the picker can show roles and grades
  // before anybody presses Start.
  useEffect(() => {
    loadConfigured().then(() => refreshCameras({ unlock: false }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(
    () => () => {
      clearWatchdog();
      // `Html5Qrcode.stop()` THROWS when the scanner is not running -- it does
      // not reject -- so the `.catch()` that used to be here never ran. On a
      // machine where the camera would not attach, navigating away from the
      // Scanner threw during unmount and the routed ErrorBoundary showed it,
      // turning a camera problem into an apparent application crash.
      const scanner = scannerRef.current;
      scannerRef.current = null;
      try {
        scanner?.stop?.()?.catch?.(() => {});
      } catch {
        /* it was not running: nothing to stop */
      }
      // Release the device even if the library's teardown did not run. A track
      // left open holds a USB camera for the life of the tab.
      try {
        trackRef.current?.stop?.();
      } catch {
        /* already ended */
      }
      trackRef.current = null;
    },
    [clearWatchdog]
  );

  const attached = cameras.filter((c) => c.attached);
  const activeCamera = cameras[activeIndex] || null;

  return {
    elementId: elementId.current,
    cameras,
    devices,
    attachedCount: attached.length,
    failoverNotice,
    dismissFailoverNotice: () => setFailoverNotice(null),
    activeCamera,
    activeIndex,
    status,
    error,
    events,
    capabilities,
    decodeCount,
    // A backup only counts if it is actually attached: a configured camera on
    // another machine, or one that has been unplugged, cannot take over.
    hasBackup: attached.length > 1,
    backupCamera: attached.find((c) => c !== activeCamera) || null,
    configured: cameras.filter((c) => c.configured),
    configuredReady,
    station: stationId(),
    start,
    stop,
    switchTo,
    failover,
    refreshCameras,
    reloadConfigured: loadConfigured,
    applyZoom,
    applyTorch,
    scanFile,
    measure,
    readBarcode,
    isRunning: status === CAMERA_STATUS.RUNNING,
    isTesting: status === CAMERA_STATUS.TESTING || measuring,
  };
}
