/**
 * Scanner
 * =======
 * Capture, with every fallback the requirement asks for.
 *
 * The input ladder, in order of preference and each one automatic:
 *
 *   1. primary camera
 *   2. backup camera        (automatic on error, disconnect, or a decode stall)
 *   3. still photo          (a phone photo resolves bars a webcam never will)
 *   4. manual entry         (always available, never disabled)
 *
 * Behind all four sits the Recovery Agent, which repairs a read the decoder
 * mangled. The point of the ladder is that no single failure stops the line.
 */
import * as React from "react";
import { Link } from "react-router-dom";
import {
  Camera, CameraOff, ArrowDownToLine, ArrowUpFromLine, Image as ImageIcon,
  Keyboard, RefreshCw, Zap, ZoomIn, Wrench, Video, AlertTriangle, ScanBarcode,
  CheckCircle2, Loader2, SwitchCamera, Radio, Ban, Copy, Cpu,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/misc";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useCamera, CAMERA_STATUS } from "@/hooks/useCamera";
import { ScanResultDialog } from "@/components/scanner/ScanResultDialog";
import { api } from "@/lib/api";
import { cn, percent, timeAgo } from "@/lib/utils";

/** Input formats that mean a deliberate human action rather than a camera
 *  sampling the same label repeatedly. Mirrors DELIBERATE_FORMATS on the
 *  server; repeat entry through any of these is never suppressed. */
const DELIBERATE = new Set(["manual", "sample", "photo", "recovered"]);

const SAMPLES = [
  { label: "ONT", code: "ONT,BATCH01,900001" },
  { label: "Fiber Cable", code: "Optical Fiber Cable,BATCH02,900002" },
  { label: "Martini Glass", code: "Martini Glass 225ML,27020,789076542345" },
  { label: "EAN-13", code: "7890765423458" },
  // Same product, the other symbology. The Code 128 label in labels/ carries
  // the product number without its check digit, which is exactly the pair
  // db.resolve_productno() exists to reconcile.
  { label: "Code 128", code: "789076542345" },
  { label: "Bad read", code: "78907654234S" },
];

/**
 * The scan acknowledgement.
 *
 * Deliberately small and deliberately temporary. Scanning is a two-handed job:
 * anything that has to be dismissed before the next item can be read turns a
 * one-second action into a three-second one, all day. So this states the
 * direction, the product and the new quantity, and gets out of the way.
 *
 * The full agent trace has not gone anywhere -- tapping the toast, or any row
 * under "This session", still opens it.
 */
function ScanToast({ result }) {
  const duplicate = result.final === "DUPLICATE";
  const rejected = result.final === "REJECT";
  const out = result.final === "OUT";
  const Icon = duplicate ? Copy : rejected ? Ban : out ? ArrowUpFromLine : ArrowDownToLine;
  const tone = duplicate
    ? "text-[hsl(var(--warning))]"
    : rejected
    ? "text-destructive"
    : out
    ? "text-[hsl(var(--info))]"
    : "text-[hsl(var(--success))]";
  const wordy = duplicate || rejected;

  return (
    <div className="flex items-center gap-3 p-3 pr-4">
      <Icon className={cn("h-6 w-6 shrink-0", tone)} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className={cn("text-sm font-semibold uppercase tracking-wide", tone)}>
            {result.final}
          </span>
          <span className="truncate text-sm font-medium">
            {result.name || result.code || "?"}
          </span>
        </div>
        {wordy ? (
          <p className="truncate text-xs text-muted-foreground">{result.reason}</p>
        ) : (
          <p className="text-xs text-muted-foreground">
            {result.anomaly ? "flagged · " : ""}
            now {result.qty} on hand
          </p>
        )}
      </div>
      {!wordy && typeof result.qty === "number" && (
        <span className="tnum shrink-0 text-2xl font-semibold leading-none">
          {result.qty}
        </span>
      )}
    </div>
  );
}

/**
 * The camera failover acknowledgement.
 *
 * A successful failover is *good news*: the camera died, the backup took over,
 * and scanning never stopped. It is an acknowledgement, exactly like a scan
 * result, and it belongs in the same bottom-right corner that clears itself.
 *
 * It used to be a modal in the middle of the screen. The reasoning was that an
 * operator who cannot see the backup took over will keep presenting labels to a
 * dead lens -- which is true, and is why this still appears at all. What was
 * wrong was the *form*: a box you must dismiss before the next item can be
 * scanned turns a one-second action into a three-second one, on the exact
 * screen this project's own rules say must never do that. Telling somebody
 * their scanner still works should not stop their scanner working.
 *
 * The full agent reasoning is still one tap away, the same way a scan result is.
 */
function FailoverToast({ notice }) {
  return (
    <div className="flex items-center gap-3 p-3 pr-4">
      <SwitchCamera className="h-6 w-6 shrink-0 text-[hsl(var(--warning))]" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold uppercase tracking-wide text-[hsl(var(--warning))]">
            Switched
          </span>
          <span className="truncate text-sm font-medium">{notice.to}</span>
        </div>
        <p className="truncate text-xs text-muted-foreground">
          {notice.from} stopped. Scanning continues.
        </p>
      </div>
    </div>
  );
}

export default function Scanner() {
  const toast = useToast();
  const [mode, setMode] = React.useState("IN");
  const [result, setResult] = React.useState(null);
  const [resultOpen, setResultOpen] = React.useState(false);
  const [manualOpen, setManualOpen] = React.useState(false);
  const [manualCode, setManualCode] = React.useState("");
  const [recovery, setRecovery] = React.useState(null);
  const [categories, setCategories] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [zoom, setZoom] = React.useState(1);
  const [reading, setReading] = React.useState(false);
  const [torch, setTorch] = React.useState(false);
  const [recent, setRecent] = React.useState([]);
  const fileRef = React.useRef(null);
  // The failover patience is a setting, and it used to be honoured only by the
  // server-side Vision Agent -- the browser watchdog kept its own hard-coded
  // twelve seconds. Changing the setting moved half the system.
  const [failoverSeconds, setFailoverSeconds] = React.useState(12);
  const modeRef = React.useRef(mode);
  modeRef.current = mode;
  const busyRef = React.useRef(false);
  // code -> {at, name, told}. Which codes were counted recently, so a label
  // held in frame is one unit rather than one per decoded frame.
  const gateRef = React.useRef(new Map());
  const cooldownRef = React.useRef(2);
  const [cooldown, setCooldown] = React.useState(2);

  const submit = React.useCallback(
    async (code, format) => {
      // ORDER MATTERS HERE, and it is not obvious.
      //
      // The in-flight guard has to come first, before any duplicate state is
      // touched. If a code were recorded as "seen" and then dropped because a
      // previous request was still running, it would be suppressed on every
      // later frame too and never sent at all -- turning the double-count this
      // whole gate exists to fix into a silent under-count, which is worse.
      if (busyRef.current) return;

      // A camera re-decodes ~12 times a second. Only the first read of a
      // presentation becomes stock; the rest are the same box still sitting in
      // front of the lens. Deliberate input is never gated -- typing a code
      // five times is how someone counts five boxes in.
      const deliberate = DELIBERATE.has(format);
      const now = performance.now();
      const windowMs = (cooldownRef.current || 0) * 1000;
      const key = `${modeRef.current}:${code}`;

      if (!deliberate && windowMs > 0) {
        const seen = gateRef.current.get(key);
        if (seen && now - seen.at < windowMs) {
          // Keep the window open while the label stays in frame, so holding it
          // there cannot quietly tick over into a second unit.
          seen.at = now;
          if (!seen.told) {
            seen.told = true;
            toast.custom(
              <ScanToast result={{ final: "DUPLICATE", name: seen.name || code,
                                   reason: "Already counted. Present it again to add another." }} />,
              { variant: "warning", duration: 1600 }
            );
          }
          return;
        }
      }

      const mode = modeRef.current;
      busyRef.current = true;
      setBusy(true);
      try {
        const res = await api.scan(code, mode, format);

        // The server has the last word: it also suppresses duplicates, which
        // is what covers a page reload or a second tab. Record what it decided
        // so the browser stops asking.
        if (!deliberate && windowMs > 0) {
          gateRef.current.set(key, { at: performance.now(), name: res.name, told: res.duplicate });
          if (gateRef.current.size > 64) {
            for (const [k, v] of gateRef.current) {
              if (performance.now() - v.at > windowMs * 4) gateRef.current.delete(k);
            }
          }
        }
        if (res.duplicate) {
          // Expected on this app's own labels: the QR and the barcode are two
          // strings for one product, so the second one always arrives as a
          // duplicate. Nothing to tell the operator about.
          return;
        }
        setResult(res);
        setRecent((prev) => [{ ...res, at: new Date().toISOString() }, ...prev].slice(0, 8));

        if (res.final === "REJECT") {
          // A rejection is usually NOT a bad read -- most often it is an OUT
          // with nothing on hand, and that operator needs the reason, not a
          // list of barcodes to guess between. Only the server can tell the
          // difference, so it says so explicitly.
          if (res.unresolved) {
            const rec = await api.recover(code, res.reason || "").catch(() => null);
            if (rec?.candidates?.length) {
              setRecovery({ code, ...rec });
              return;                       // the recovery dialog says enough
            }
          }
          // A refusal has to be read and acted on, so it stays until dismissed
          // rather than vanishing like an acknowledgement.
          toast.custom(<ScanToast result={res} />, {
            variant: "error", duration: 6000,
            onClick: () => { setResult(res); setResultOpen(true); },
          });
        } else {
          // A successful scan needs acknowledging, not confirming. It appears
          // bottom-right, states what happened, and clears itself so the next
          // item can be scanned without touching the screen.
          toast.custom(<ScanToast result={res} />, {
            variant: res.anomaly ? "warning" : "success",
            duration: 2000,
            onClick: () => { setResult(res); setResultOpen(true); },
          });
        }
      } catch (err) {
        // The scan never reached stock, so it must not stay gated: the operator
        // will re-present the label, and that read has to be allowed through.
        gateRef.current.delete(key);
        toast.error(err.message);
      } finally {
        busyRef.current = false;
        setBusy(false);
      }
    },
    [toast]
  );

  const camera = useCamera({
    onDecode: (text, format) => submit(text, format),
    failoverSeconds,
    // The hook fires the full-resolution server read on its own when the live
    // decoder stalls, and it has to repeat inside this window so a label left
    // in frame stays one unit. See SERVER_READ_AFTER_SECONDS in useCamera.
    duplicateWindowSeconds: cooldown,
  });

  /**
   * Read the barcode server-side, at the camera's real resolution.
   *
   * The browser decoder is handed a frame downscaled to the width of this card,
   * which leaves an EAN-13 with under two pixels per module where four are
   * needed. This sends the full-resolution band to the Python decoder instead.
   *
   * The result goes through `submit` as an ordinary camera read, NOT as
   * deliberate input, so it passes the duplicate guard exactly like any other
   * scan -- otherwise pressing this straight after a successful browser read
   * would count the same box twice.
   */
  const readBarcodeNow = React.useCallback(async () => {
    if (reading || busyRef.current) return;
    setReading(true);
    try {
      const result = await camera.readBarcode();
      if (result?.code) {
        submit(result.code, "barcode");
      } else if (result?.near_miss) {
        toast.warning(
          "Almost read it. Hold the label still and fill more of the frame, then try again."
        );
      } else {
        toast.warning(result?.reason || "No barcode found in that frame.");
      }
    } finally {
      setReading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reading, submit, toast]);

  // Which failover the operator has asked to see in full. Separate from the
  // hook's own notice, because a successful switch is acknowledged and cleared
  // without ever opening anything.
  const [failoverDetail, setFailoverDetail] = React.useState(null);
  const seenFailoverRef = React.useRef(0);

  /**
   * Route a failover to the right kind of interruption.
   *
   *   switch   -> scanning already continued somewhere else. Acknowledge it in
   *               the corner and get out of the way.
   *   fallback -> there is no camera left and scanning has genuinely stopped.
   *               The operator has to choose a photo or manual entry, so this
   *               one does take the screen: it is a decision, not a receipt.
   */
  React.useEffect(() => {
    const notice = camera.failoverNotice;
    if (!notice || notice.at === seenFailoverRef.current) return;
    seenFailoverRef.current = notice.at;

    if (notice.action === "switch") {
      toast.custom(<FailoverToast notice={notice} />, {
        variant: "warning",
        // Longer than a scan receipt: it matters more, and the operator may be
        // looking at the label rather than the screen when it appears.
        duration: 5000,
        onClick: () => setFailoverDetail(notice),
      });
      camera.dismissFailoverNotice();
    } else {
      setFailoverDetail(notice);
    }
    // `camera` is rebuilt every render, so only the notice can be a dependency;
    // the ref above is what stops this firing twice for one failover.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [camera.failoverNotice, toast]);

  const loadCategories = React.useCallback(async () => {
    try {
      const data = await api.categories();
      setCategories(data.categories || []);
    } catch {
      /* the scanner still works without the category list */
    }
    try {
      const s = await api.settings();
      const value = Number(s.settings?.double_read_window ?? 2);
      cooldownRef.current = value;
      setCooldown(value);
      setFailoverSeconds(Number(s.settings?.camera_failover_seconds ?? 12));
    } catch {
      /* the built-in default already protects against the flood */
    }
  }, []);

  React.useEffect(() => {
    loadCategories();
    return () => camera.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const statusChip = () => {
    switch (camera.status) {
      case CAMERA_STATUS.RUNNING:
        return (
          <Badge variant="success">
            <Radio className="h-3 w-3 animate-pulse-ring" />
            Live
          </Badge>
        );
      case CAMERA_STATUS.STARTING:
        return (
          <Badge variant="info">
            <Loader2 className="h-3 w-3 animate-spin" />
            Starting
          </Badge>
        );
      case CAMERA_STATUS.FAILING_OVER:
        return (
          <Badge variant="warning">
            <SwitchCamera className="h-3 w-3" />
            Switching camera
          </Badge>
        );
      case CAMERA_STATUS.ERROR:
        return (
          <Badge variant="destructive">
            <AlertTriangle className="h-3 w-3" />
            Camera failed
          </Badge>
        );
      default:
        return <Badge variant="muted">Idle</Badge>;
    }
  };

  return (
    <div className="space-y-6">
      {/* Direction: the single most consequential choice on this screen, so it
          is the largest control and is never more than one tap away. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => setMode("IN")}
          className={cn(
            "flex items-center gap-3 rounded-xl border-2 p-4 text-left transition-all",
            mode === "IN"
              ? "border-[hsl(var(--success))] bg-[hsl(var(--success))]/10"
              : "border-border bg-card hover:border-muted-foreground/40"
          )}
        >
          <ArrowDownToLine
            className={cn("h-7 w-7", mode === "IN" ? "text-[hsl(var(--success))]" : "text-muted-foreground")}
          />
          <div>
            <p className="font-semibold">Stock IN</p>
            <p className="text-sm text-muted-foreground">Items arriving</p>
          </div>
        </button>
        <button
          type="button"
          onClick={() => setMode("OUT")}
          className={cn(
            "flex items-center gap-3 rounded-xl border-2 p-4 text-left transition-all",
            mode === "OUT"
              ? "border-[hsl(var(--info))] bg-[hsl(var(--info))]/10"
              : "border-border bg-card hover:border-muted-foreground/40"
          )}
        >
          <ArrowUpFromLine
            className={cn("h-7 w-7", mode === "OUT" ? "text-[hsl(var(--info))]" : "text-muted-foreground")}
          />
          <div>
            <p className="font-semibold">Stock OUT</p>
            <p className="text-sm text-muted-foreground">Items leaving</p>
          </div>
        </button>
      </div>

      <div className="grid gap-6 lg:grid-cols-[1.4fr_1fr]">
        {/* Camera */}
        <Card>
          <CardHeader className="flex-row items-start justify-between space-y-0">
            <div>
              <CardTitle className="flex items-center gap-2">
                <Camera className="h-4 w-4" />
                Camera
              </CardTitle>
              <CardDescription>
                QR codes and 1-D barcodes. Both resolve to the same product.
              </CardDescription>
            </div>
            {statusChip()}
          </CardHeader>

          <CardContent className="space-y-3">
            <div className="scanner-frame relative aspect-video overflow-hidden rounded-lg border bg-black">
              <div id={camera.elementId} className="h-full w-full" />
              {!camera.isRunning && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 text-center">
                  <Video className="h-10 w-10 text-muted-foreground/50" />
                  <p className="max-w-xs text-sm text-muted-foreground">
                    {camera.error || "Start the camera, or use a photo or manual entry."}
                  </p>
                </div>
              )}
              {busy && (
                <div className="absolute inset-0 flex items-center justify-center bg-black/60">
                  <Loader2 className="h-8 w-8 animate-spin text-white" />
                </div>
              )}
            </div>

            <div className="flex flex-wrap gap-2">
              {camera.isRunning ? (
                <Button variant="outline" onClick={camera.stop}>
                  <CameraOff className="h-4 w-4" />
                  Stop
                </Button>
              ) : (
                <Button onClick={camera.start}>
                  <Camera className="h-4 w-4" />
                  Start camera
                </Button>
              )}
              {camera.isRunning && (
                <Button
                  variant="outline"
                  onClick={readBarcodeNow}
                  disabled={reading}
                  title="Read the barcode at full camera resolution, on the server"
                >
                  {reading ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <ScanBarcode className="h-4 w-4" />
                  )}
                  Read barcode
                </Button>
              )}
              <Button variant="outline" onClick={() => fileRef.current?.click()}>
                <ImageIcon className="h-4 w-4" />
                Scan a photo
              </Button>
              <Button variant="outline" onClick={() => setManualOpen(true)}>
                <Keyboard className="h-4 w-4" />
                Type a code
              </Button>
              <Button variant="ghost" size="icon" onClick={camera.refreshCameras} title="Re-detect cameras">
                <RefreshCw className="h-4 w-4" />
              </Button>
              <input
                ref={fileRef}
                type="file"
                accept="image/*"
                capture="environment"
                hidden
                onChange={async (e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (!file) return;
                  try {
                    await camera.scanFile(file);
                  } catch {
                    toast.error(
                      "No code could be read in that photo. Fill the frame, keep it level and in focus."
                    );
                  }
                }}
              />
            </div>

            {/* Camera selection and failover state.
                The question an operator actually has is "if this one dies, is
                something going to take over?" -- so that is answered first, by
                name, rather than left to be inferred from a dropdown. */}
            {camera.cameras.length > 0 && (
              <div className="space-y-2 rounded-lg border p-3">
                <div className="flex items-center justify-between gap-2">
                  <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                    Active camera
                  </Label>
                  {camera.hasBackup ? (
                    <Badge variant="success">
                      <CheckCircle2 className="h-3 w-3" />
                      Backup ready
                    </Badge>
                  ) : (
                    <Badge variant="warning">
                      <AlertTriangle className="h-3 w-3" />
                      No backup camera
                    </Badge>
                  )}
                </div>
                <Select
                  value={String(camera.activeIndex)}
                  onValueChange={(v) => camera.switchTo(Number(v))}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {camera.cameras.map((c, i) => (
                      <SelectItem key={c.id} value={String(i)} disabled={!c.attached}>
                        {c.name || c.label || `Camera ${i + 1}`}
                        {c.role === "primary" ? "  (primary)" : c.role === "backup" ? "  (backup)" : ""}
                        {!c.attached ? "  (not plugged in)" : ""}
                        {i === camera.activeIndex ? "  (active)" : ""}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                {/* The failover chain, in the order it will actually be tried. */}
                <div className="space-y-1">
                  {camera.cameras.slice(0, 4).map((c, i) => (
                    <div key={c.id} className="flex items-center gap-2 text-xs">
                      <span
                        className={cn(
                          "h-1.5 w-1.5 shrink-0 rounded-full",
                          i === camera.activeIndex && camera.isRunning
                            ? "bg-[hsl(var(--success))]"
                            : c.attached
                            ? "bg-muted-foreground"
                            : "bg-[hsl(var(--warning))]"
                        )}
                      />
                      <span className="min-w-0 flex-1 truncate text-muted-foreground">
                        {c.name || c.label || `Camera ${i + 1}`}
                      </span>
                      {c.grade && (
                        <span className="shrink-0 text-muted-foreground">{c.grade}</span>
                      )}
                      {!c.attached && (
                        <span className="shrink-0 text-[hsl(var(--warning))]">missing</span>
                      )}
                    </div>
                  ))}
                </div>

                {camera.hasBackup && camera.isRunning && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full"
                    onClick={() => camera.failover("you asked to switch")}
                  >
                    <SwitchCamera className="h-4 w-4" />
                    Switch to {camera.backupCamera?.name || "the backup camera"} now
                  </Button>
                )}
                <Button variant="ghost" size="sm" className="w-full" asChild>
                  <Link to="/cameras">
                    <Video className="h-4 w-4" />
                    {camera.configured.length
                      ? "Manage cameras"
                      : "Set up a backup camera"}
                  </Link>
                </Button>
              </div>
            )}

            {/* Zoom is the most effective fix for thin bars on a fixed-focus lens. */}
            {camera.isRunning && camera.capabilities.zoom && (
              <div className="space-y-1.5 rounded-lg border p-3">
                <div className="flex items-center justify-between">
                  <Label className="flex items-center gap-1.5 text-xs">
                    <ZoomIn className="h-3.5 w-3.5" />
                    Zoom
                  </Label>
                  <span className="tnum text-xs text-muted-foreground">{zoom.toFixed(1)}x</span>
                </div>
                <input
                  type="range"
                  min={camera.capabilities.zoom.min}
                  max={camera.capabilities.zoom.max}
                  step={camera.capabilities.zoom.step || 0.1}
                  value={zoom}
                  onChange={(e) => {
                    const v = Number(e.target.value);
                    setZoom(v);
                    camera.applyZoom(v);
                  }}
                  className="w-full accent-[hsl(var(--primary))]"
                />
                <p className="text-xs text-muted-foreground">
                  Zoom until the barcode fills the width. Thin bars need pixels.
                </p>
              </div>
            )}

            {camera.isRunning && camera.capabilities.torch && (
              <Button
                variant={torch ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  setTorch(!torch);
                  camera.applyTorch(!torch);
                }}
              >
                <Zap className="h-4 w-4" />
                {torch ? "Torch on" : "Torch"}
              </Button>
            )}

            <p className="text-xs text-muted-foreground">
              Barcodes are read line by line, so a tilted label never decodes. Hold it level
              and fill the frame. QR codes are rotation-proof, which is why they scan at any
              angle. The server reads EAN-13, UPC-A, EAN-8 and Code 128 &mdash; upside down is
              fine, but leave a little clear space either side of the bars.
            </p>
            <p className="text-xs text-muted-foreground">
              Hold a barcode in view and it is read within a few seconds. The live decoder
              only ever sees the picture shrunk to the width of this panel, which is too
              coarse for thin bars, so once it has come up empty for a moment the frame is
              sent at the camera&apos;s full resolution to be read on the server instead.
              <strong> Read barcode</strong> does the same thing immediately.
            </p>
          </CardContent>
        </Card>

        {/* Side column */}
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Quick test</CardTitle>
              <CardDescription>Works without a camera.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-wrap gap-2">
              {SAMPLES.map((s) => (
                <Button
                  key={s.label}
                  variant="outline"
                  size="sm"
                  onClick={() => submit(s.code, "sample")}
                >
                  {s.label}
                </Button>
              ))}
            </CardContent>
          </Card>

          {/* The failover log. An operator who cannot see that the backup took
              over will keep presenting labels to a camera that has given up. */}
          {camera.events.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">Camera log</CardTitle>
                <CardDescription>Failover events as they happen.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {camera.events.slice(0, 6).map((e, i) => (
                  <div key={i} className="flex gap-2 text-xs">
                    <span
                      className={cn(
                        "mt-1 h-1.5 w-1.5 shrink-0 rounded-full",
                        e.level === "error" && "bg-destructive",
                        e.level === "warn" && "bg-[hsl(var(--warning))]",
                        e.level === "info" && "bg-muted-foreground"
                      )}
                    />
                    <span className="text-muted-foreground">{e.message}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {recent.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-sm">This session</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {recent.map((r, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => {
                      setResult(r);
                      setResultOpen(true);
                    }}
                    className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-accent"
                  >
                    <Badge
                      variant={
                        r.final === "IN" ? "success" : r.final === "OUT" ? "info" : "destructive"
                      }
                      className="shrink-0"
                    >
                      {r.final}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate text-sm">{r.name}</span>
                    <span className="tnum shrink-0 text-xs text-muted-foreground">
                      {timeAgo(r.at)}
                    </span>
                  </button>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* Stock IN / OUT result */}
      <ScanResultDialog
        open={resultOpen}
        onOpenChange={setResultOpen}
        result={result}
        categories={categories}
        onAssignCategory={async (product, category) => {
          await api.assignCategory(product, category);
          await loadCategories();
          toast.success(`${product} filed under ${category}.`);
        }}
        onUndo={async () => {
          try {
            // Reverse the scan that is on screen, not whichever is newest.
            const res = await api.undo(result?.log_id);
            toast.success(res.message);
            setResultOpen(false);
          } catch (err) {
            toast.error(err.message);
          }
        }}
        onScanAgain={() => setResultOpen(false)}
      />

      {/* The Vision Agent's full reasoning.
          This opens for one of two reasons only: no camera is left and the
          operator has to choose another way in, or they tapped the corner
          acknowledgement to read why the switch happened. A successful failover
          never opens it by itself -- see the effect near the top of this file. */}
      <Dialog
        open={Boolean(failoverDetail)}
        onOpenChange={() => {
          setFailoverDetail(null);
          camera.dismissFailoverNotice();
        }}
      >
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {failoverDetail?.action === "switch" ? (
                <>
                  <SwitchCamera className="h-5 w-5 text-[hsl(var(--warning))]" />
                  Switched to the backup camera
                </>
              ) : (
                <>
                  <AlertTriangle className="h-5 w-5 text-destructive" />
                  No working camera
                </>
              )}
            </DialogTitle>
            <DialogDescription>
              {failoverDetail?.action === "switch"
                ? `${failoverDetail?.from} stopped working. Scanning has moved to ${failoverDetail?.to} and is still running.`
                : `${failoverDetail?.from} stopped working and there is nothing to switch to.`}
            </DialogDescription>
          </DialogHeader>

          <div className="rounded-lg border p-3">
            <p className="mb-1.5 flex items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              <Cpu className="h-3.5 w-3.5" />
              Vision Agent
            </p>
            <ul className="space-y-1">
              {(failoverDetail?.reasons || []).map((r, i) => (
                <li key={i} className="text-sm text-muted-foreground">{r}</li>
              ))}
            </ul>
          </div>

          <DialogFooter>
            {failoverDetail?.action !== "switch" && (
              <>
                <Button variant="outline" onClick={() => {
                  setFailoverDetail(null);
                  camera.dismissFailoverNotice();
                  fileRef.current?.click();
                }}>
                  <ImageIcon className="h-4 w-4" />
                  Scan a photo
                </Button>
                <Button variant="outline" onClick={() => {
                  setFailoverDetail(null);
                  camera.dismissFailoverNotice();
                  setManualOpen(true);
                }}>
                  <Keyboard className="h-4 w-4" />
                  Type a code
                </Button>
              </>
            )}
            <Button onClick={() => {
              setFailoverDetail(null);
              camera.dismissFailoverNotice();
            }}>
              {failoverDetail?.action === "switch" ? "Keep scanning" : "Close"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Manual entry */}
      <Dialog open={manualOpen} onOpenChange={setManualOpen}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Keyboard className="h-4 w-4" />
              Type a code
            </DialogTitle>
            <DialogDescription>
              A QR payload as <code>name,batch,productno</code>, or a plain barcode number.
              This always works, whatever the cameras are doing.
            </DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const code = manualCode.trim();
              if (!code) return;
              setManualOpen(false);
              setManualCode("");
              submit(code, "manual");
            }}
            className="space-y-3"
          >
            <Input
              autoFocus
              value={manualCode}
              onChange={(e) => setManualCode(e.target.value)}
              placeholder="ONT,BATCH01,900001   or   7890765423458"
            />
            <div className="rounded-lg border bg-muted/40 p-2.5">
              <p className="text-xs text-muted-foreground">
                Going {mode === "IN" ? "into" : "out of"} stock.
              </p>
            </div>
            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setManualOpen(false)}>
                Cancel
              </Button>
              <Button type="submit">Scan</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      {/* Recovery suggestions for a failed read */}
      <Dialog open={Boolean(recovery)} onOpenChange={() => setRecovery(null)}>
        <DialogContent className="sm:max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Wrench className="h-4 w-4" />
              That code matched nothing. Did you mean one of these?
            </DialogTitle>
            <DialogDescription>
              The Recovery Agent read <code className="rounded bg-muted px-1">{recovery?.code}</code>{" "}
              and tried each repair strategy in turn.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            {(recovery?.candidates || []).map((c, i) => (
              <button
                key={i}
                type="button"
                onClick={() => {
                  setRecovery(null);
                  submit(c.code, "recovered");
                }}
                className="flex w-full items-center gap-3 rounded-lg border p-3 text-left hover:border-primary hover:bg-accent"
              >
                <div className="min-w-0 flex-1">
                  <p className="tnum truncate font-medium">{c.code}</p>
                  <p className="truncate text-xs text-muted-foreground">{c.explanation}</p>
                </div>
                <div className="shrink-0 text-right">
                  <Badge variant={c.known ? "success" : "muted"}>
                    {c.known ? "in stock" : "not held"}
                  </Badge>
                  <p className="tnum mt-1 text-xs text-muted-foreground">
                    {percent(c.confidence, 0)}
                  </p>
                </div>
              </button>
            ))}
            {!recovery?.candidates?.length && (
              <p className="text-sm text-muted-foreground">
                No repair produced a code this warehouse holds. Try the backup camera, a
                still photo, or type the number in.
              </p>
            )}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRecovery(null)}>
              Close
            </Button>
            <Button
              onClick={() => {
                setRecovery(null);
                setManualOpen(true);
              }}
            >
              <Keyboard className="h-4 w-4" />
              Type it instead
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
