/**
 * Cameras
 * =======
 * Which cameras this machine scans with, in what order, and how well each one
 * actually performs.
 *
 * Why this screen is per-machine
 * ------------------------------
 * A browser `deviceId` is meaningless on another machine: it is minted per
 * origin and per device, and it changes when browser storage is cleared. So
 * cameras are registered against a *station* -- a stable id this browser keeps
 * for itself -- and this page only ever shows the cameras of the machine it is
 * open on. A camera on the goods-in laptop is not something the phone in the
 * yard can open, and offering it would be a lie.
 *
 * Detected versus configured
 * --------------------------
 * The browser knows what is plugged in. The server knows which one a manager
 * chose as the primary and which is the backup. Neither knows both, so this
 * screen is the join: attached cameras that are not registered can be added,
 * registered cameras that are not attached are shown as missing rather than
 * quietly dropped, and the scanner is told the resulting order.
 *
 * Measuring is the point
 * ----------------------
 * "Is the backup ready?" cannot be answered by asking whether a row exists. A
 * camera can be registered, enabled, plugged in and still be a fixed-focus lens
 * that has never resolved a barcode in its life. So a camera is measured --
 * resolution, delivered frame rate, decode rate, time to first read -- and the
 * *server* scores it, which is what makes two machines' grades comparable.
 */
import * as React from "react";
import {
  Video, VideoOff, Loader2, Plus, Trash2, ArrowUp, ArrowDown, Activity,
  RefreshCw, CheckCircle2, AlertTriangle, Star, Shield, Ban, Globe, Monitor,
  Gauge, History, Save,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Separator, Stat } from "@/components/ui/misc";
import {
  Table, TableHeader, TableBody, TableHead, TableRow, TableCell, TableEmpty,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/useAuth";
import { useCamera } from "@/hooks/useCamera";
import { api } from "@/lib/api";
import { stationId, stationLabel, setStationLabel } from "@/lib/station";
import { cn, formatTime, timeAgo } from "@/lib/utils";

/** How a measured grade is shown. A module-level map rather than a chain of
 *  ternaries, because there are more than two cases. */
const GRADE_VARIANT = {
  excellent: "success",
  good: "success",
  marginal: "warning",
  unusable: "destructive",
};

const ROLE_META = {
  primary: { label: "Primary", icon: Star, variant: "default",
             hint: "Tried first every time the scanner starts." },
  backup: { label: "Backup", icon: Shield, variant: "info",
            hint: "Takes over automatically when the primary fails." },
  disabled: { label: "Off", icon: Ban, variant: "muted",
              hint: "Never opened, even if it is plugged in." },
};

export default function Cameras() {
  const toast = useToast();
  const { can } = useAuth();
  const editable = can("settings.manage");

  const [rows, setRows] = React.useState(null);
  const [summary, setSummary] = React.useState({});
  const [label, setLabel] = React.useState(stationLabel());
  const [busyId, setBusyId] = React.useState(null);
  const [testing, setTesting] = React.useState(null);
  const [history, setHistory] = React.useState(null);
  const [networkOpen, setNetworkOpen] = React.useState(false);

  // The camera hook is used here for one reason: only the browser can see what
  // is attached, and only the browser can measure one.
  const camera = useCamera({ onDecode: () => {} });

  const load = React.useCallback(async () => {
    const data = await api.cameras(stationId());
    setRows(data.cameras || []);
    setSummary(data.summary || {});
  }, []);

  React.useEffect(() => {
    load().catch((err) => toast.error(err.message));
  }, [load, toast]);

  /** Refresh both halves: the server's rows and the browser's device list. */
  const refreshAll = React.useCallback(async () => {
    await camera.reloadConfigured();
    await camera.refreshCameras();
    await load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [load]);

  const mutate = async (fn) => {
    try {
      const res = await fn();
      toast.success(res.message);
      await refreshAll();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    } finally {
      setBusyId(null);
    }
  };

  if (!rows) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  // Which detected devices are not yet registered on this machine.
  const unregistered = camera.cameras.filter((c) => c.attached && !c.configured);

  /** Is a configured row plugged in right now?
   *
   *  Answered against `camera.devices` -- everything the browser enumerated --
   *  and NOT against `camera.cameras`, which is the scan order and deliberately
   *  omits disabled cameras. Asking the scan order meant every camera set to
   *  "Off" was reported as "not plugged in" and could never be measured, so
   *  turning a camera off made it impossible to test before turning it back on.
   *
   *  A label match only counts when exactly ONE attached device carries that
   *  label: two identical webcams report byte-identical labels, and matching
   *  the first would report an unplugged camera as attached.
   */
  const isAttached = (row) => {
    if (row.kind === "network") return null;   // unknowable from here
    if (row.device_id && camera.devices.some((d) => d.id === row.device_id)) return true;
    if (!row.device_label) return false;
    const byLabel = camera.devices.filter((d) => d.label === row.device_label);
    return byLabel.length === 1;
  };

  const enabled = rows.filter((r) => r.enabled);
  const primary = rows.find((r) => r.role === "primary");
  const backups = enabled.filter((r) => r.role === "backup");

  // "Ready" has to mean the scanner can actually open it.
  //
  // `isAttached` returns null for a network camera, meaning "unknowable from
  // here" -- and `null !== false` is true, so an IP camera used to satisfy this
  // and the banner announced that failover would work. It cannot: no browser
  // opens an http stream as a MediaStream, so the scanner can never fail over
  // to one. Announcing readiness that does not exist is worse than announcing
  // none, because nobody checks a camera the screen already called ready.
  const canTakeOver = (row) => row.kind !== "network" && isAttached(row) === true;
  const primaryLive = Boolean(primary) && canTakeOver(primary);
  const liveBackup = backups.find(canTakeOver);
  const ready = primaryLive && Boolean(liveBackup);
  const networkBackups = backups.filter((b) => b.kind === "network");

  const addDevice = (device, role) =>
    mutate(() =>
      api.addCamera({
        station: stationId(),
        station_label: label,
        name: device.label || "Camera",
        kind: "device",
        device_id: device.id,
        device_label: device.label || "",
        group_id: device.groupId || "",
        facing: /back|rear|environment/i.test(device.label || "") ? "environment" : "",
        role,
      })
    );

  const move = (index, delta) => {
    const order = enabled.map((r) => r.id);
    const to = index + delta;
    if (to < 0 || to >= order.length) return;
    [order[index], order[to]] = [order[to], order[index]];
    mutate(() => api.reorderCameras(stationId(), order));
  };

  /** Measure a camera and send the raw numbers up to be scored. */
  const runTest = async (row) => {
    const index = camera.cameras.findIndex(
      (c) => c.cameraId === row.id || (row.device_id && c.id === row.device_id)
    );
    if (index < 0) {
      toast.error("That camera is not attached to this machine, so it cannot be measured.");
      return;
    }
    setTesting({ row, phase: "running" });
    // Wait for the viewport to be painted before measuring.
    //
    // html5-qrcode reads `element.clientWidth` inside start(), and the card
    // below is display:none until `testing` is set. A display:none element
    // reports 0, so the library silently falls back to its default width and
    // the video is laid out against a box that is not on screen. Two frames is
    // the reliable way to know React has committed and the browser has painted.
    await new Promise((resolve) =>
      requestAnimationFrame(() => requestAnimationFrame(resolve))
    );
    try {
      const measurement = await camera.measure(index, 6);
      const res = await api.testCamera(row.id, measurement);
      setTesting({ row, phase: "done", result: res.result });
      toast.success(res.message);
      await load();
    } catch (err) {
      setTesting(null);
      toast.error(err.message);
    }
  };

  const openHistory = async (row) => {
    try {
      const res = await api.cameraTests(row.id, 20);
      setHistory({ row, tests: res.tests || [] });
    } catch (err) {
      toast.error(err.message);
    }
  };

  return (
    <div className="space-y-6">
      {/* Readiness. The one question this screen exists to answer, stated
          before any of the detail that supports it. */}
      <Card
        className={cn(
          ready
            ? "border-[hsl(var(--success))]/30 bg-[hsl(var(--success))]/5"
            : "border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/5"
        )}
      >
        <CardContent className="flex flex-wrap items-center gap-4 p-5">
          {ready ? (
            <CheckCircle2 className="h-7 w-7 shrink-0 text-[hsl(var(--success))]" />
          ) : (
            <AlertTriangle className="h-7 w-7 shrink-0 text-[hsl(var(--warning))]" />
          )}
          <div className="min-w-0 flex-1">
            <p className="font-semibold">
              {ready
                ? "Both cameras are ready. Failover will work."
                : "There is no working backup camera on this machine."}
            </p>
            <p className="text-sm text-muted-foreground">
              {ready
                ? `${primary?.name} is tried first; if it stops decoding, the Vision Agent moves scanning to ${liveBackup?.name} without anyone touching the screen.`
                : !primary
                ? "Nothing is registered as the primary camera yet. Add one below."
                : !backups.length
                ? "Add a second camera and mark it as the backup. Until then a camera failure ends in a photo or manual entry."
                : !primaryLive
                ? "The primary camera is not plugged in to this machine."
                : networkBackups.length === backups.length
                ? "The only backup is a network camera. No browser can open an IP stream as a live camera, so the scanner cannot fail over to it -- add a second USB or built-in camera."
                : "A backup is configured but is not plugged in. Reconnect it to restore automatic failover."}
            </p>
          </div>
          <Button variant="outline" onClick={() => refreshAll().catch((e) => toast.error(e.message))}>
            <RefreshCw className="h-4 w-4" />
            Re-detect
          </Button>
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={Video} label="Configured" value={summary.total ?? 0} hint="on this machine" />
        <Stat
          icon={Activity}
          label="Attached now"
          value={camera.attachedCount}
          hint="visible to the browser"
        />
        <Stat
          icon={Gauge}
          label="Measured good"
          value={summary.usable ?? 0}
          hint={`${summary.untested ?? 0} never tested`}
          tone={summary.usable ? "success" : "warning"}
        />
        <Stat
          icon={Shield}
          label="Best score"
          value={summary.best_score ?? 0}
          hint="out of 100"
        />
      </div>

      {/* This machine */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Monitor className="h-4 w-4" />
            This machine
          </CardTitle>
          <CardDescription>
            Cameras are registered against the machine that can see them, because a
            camera id issued by one browser means nothing in another.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-end gap-3">
            <div className="space-y-1.5">
              <Label htmlFor="station-label">Name for this machine</Label>
              <Input
                id="station-label"
                className="w-64"
                value={label}
                disabled={!editable}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. Goods-in laptop"
              />
            </div>
            {editable && (
              <Button
                variant="outline"
                onClick={() => {
                  const saved = setStationLabel(label);
                  setLabel(saved);
                  toast.success(`This machine is now called "${saved}".`);
                }}
              >
                <Save className="h-4 w-4" />
                Save name
              </Button>
            )}
          </div>
          <p className="tnum text-xs text-muted-foreground">
            Station id <code className="rounded bg-muted px-1">{stationId()}</code>
          </p>
        </CardContent>
      </Card>

      {/* Detected but not registered */}
      {unregistered.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Plus className="h-4 w-4" />
              Detected, not yet configured
            </CardTitle>
            <CardDescription>
              These are plugged in and usable now. Registering one lets you give it a
              name, decide whether it is the primary or the backup, and measure it.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {unregistered.map((device) => (
              <div
                key={device.id}
                className="flex flex-wrap items-center gap-3 rounded-lg border p-3"
              >
                <Video className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-sm font-medium">
                  {device.label || "Unnamed camera"}
                </span>
                {editable && (
                  <>
                    <Button size="sm" variant="outline" onClick={() => addDevice(device, "primary")}>
                      <Star className="h-4 w-4" />
                      Set as primary
                    </Button>
                    <Button size="sm" onClick={() => addDevice(device, "backup")}>
                      <Shield className="h-4 w-4" />
                      Add as backup
                    </Button>
                  </>
                )}
              </div>
            ))}
            {!editable && (
              <p className="text-sm text-muted-foreground">
                An administrator can register these.
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Configured cameras */}
      <Card>
        <CardHeader className="flex-row items-start justify-between space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Video className="h-4 w-4" />
              Configured cameras
            </CardTitle>
            <CardDescription>
              Tried top to bottom. The primary is always first; the rest follow this
              order, and a measured camera is preferred over an untested one.
            </CardDescription>
          </div>
          {editable && (
            <Button variant="outline" size="sm" onClick={() => setNetworkOpen(true)}>
              <Globe className="h-4 w-4" />
              Add network camera
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Camera</TableHead>
                <TableHead>Role</TableHead>
                <TableHead className="hidden md:table-cell">Attached</TableHead>
                <TableHead className="hidden md:table-cell">Last measured</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.length === 0 && (
                <TableEmpty colSpan={6}>
                  No camera is configured for this machine yet. Anything plugged in
                  appears above.
                </TableEmpty>
              )}
              {rows.map((row) => {
                const meta = ROLE_META[row.role] || ROLE_META.backup;
                const RoleIcon = meta.icon;
                const attached = isAttached(row);
                const test = row.last_test;
                // Position within the *enabled* cameras, which is what the
                // order is expressed in. Using the row index disabled the
                // wrong arrow whenever a disabled camera sat above.
                const rank = enabled.findIndex((r) => r.id === row.id);
                return (
                  <TableRow key={row.id} className={cn(!row.enabled && "opacity-60")}>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        {row.kind === "network" ? (
                          <Globe className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        ) : (
                          <Video className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                        )}
                        <div className="min-w-0">
                          <p className="truncate font-medium">{row.name}</p>
                          <p className="truncate text-xs text-muted-foreground">
                            {row.kind === "network"
                              ? row.stream_url
                              : row.device_label || "no label reported"}
                          </p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell>
                      {editable ? (
                        <Select
                          value={row.role}
                          onValueChange={(v) => {
                            setBusyId(row.id);
                            mutate(() => api.updateCamera(row.id, { role: v }));
                          }}
                        >
                          <SelectTrigger className="w-32">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="primary">Primary</SelectItem>
                            <SelectItem value="backup">Backup</SelectItem>
                            <SelectItem value="disabled">Off</SelectItem>
                          </SelectContent>
                        </Select>
                      ) : (
                        <Badge variant={meta.variant}>
                          <RoleIcon className="h-3 w-3" />
                          {meta.label}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {attached === null ? (
                        <Badge variant="muted">network</Badge>
                      ) : !row.enabled ? (
                        // "Off" and "unplugged" are different problems with
                        // different fixes, and conflating them sent people to
                        // check a cable that was fine.
                        <Badge variant="muted">
                          <Ban className="h-3 w-3" />
                          turned off
                        </Badge>
                      ) : attached ? (
                        <Badge variant="success">
                          <CheckCircle2 className="h-3 w-3" />
                          yes
                        </Badge>
                      ) : (
                        <Badge variant="warning">
                          <VideoOff className="h-3 w-3" />
                          not plugged in
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      {test ? (
                        <div>
                          <Badge variant={GRADE_VARIANT[test.grade] || "muted"}>
                            {test.grade}
                          </Badge>
                          <p className="tnum mt-1 text-xs text-muted-foreground">
                            {test.width}x{test.height} · {timeAgo(test.ts)}
                          </p>
                        </div>
                      ) : (
                        <Badge variant="muted">never measured</Badge>
                      )}
                    </TableCell>
                    <TableCell className="tnum text-right">
                      {test ? `${test.score}/100` : "-"}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-1">
                        <Button
                          size="icon"
                          variant="ghost"
                          disabled={
                            busyId === row.id ||
                            camera.isTesting ||
                            testing !== null ||
                            row.kind === "network" ||
                            !row.enabled ||
                            attached !== true
                          }
                          title={
                            row.kind === "network"
                              ? "A network camera cannot be opened by the browser"
                              : !row.enabled
                              ? "Turned off. Set it to Primary or Backup to measure it."
                              : attached !== true
                              ? "Not plugged in to this machine"
                              : "Measure this camera"
                          }
                          onClick={() => runTest(row)}
                        >
                          <Gauge className="h-4 w-4" />
                        </Button>
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Measurement history"
                          onClick={() => openHistory(row)}
                        >
                          <History className="h-4 w-4" />
                        </Button>
                        {editable && (
                          <>
                            <Button
                              size="icon"
                              variant="ghost"
                              title="Try this one earlier"
                              disabled={!row.enabled || rank <= 0}
                              onClick={() => move(rank, -1)}
                            >
                              <ArrowUp className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              title="Try this one later"
                              disabled={!row.enabled || rank < 0 || rank >= enabled.length - 1}
                              onClick={() => move(rank, 1)}
                            >
                              <ArrowDown className="h-4 w-4" />
                            </Button>
                            <Button
                              size="icon"
                              variant="ghost"
                              title="Remove this camera"
                              onClick={() => {
                                if (
                                  !window.confirm(
                                    `Remove "${row.name}"? Its measurement history is deleted with it.`
                                  )
                                )
                                  return;
                                setBusyId(row.id);
                                mutate(() => api.deleteCamera(row.id));
                              }}
                            >
                              <Trash2 className="h-4 w-4" />
                            </Button>
                          </>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      {/* The viewport a measurement needs. It has to be in the document for
          html5-qrcode to render into, and it is only worth looking at while a
          test is running. */}
      <div className={cn(testing?.phase === "running" ? "block" : "hidden")}>
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Gauge className="h-4 w-4" />
              Measuring {testing?.row?.name}
            </CardTitle>
            <CardDescription>
              Hold a printed label in front of this camera until the test finishes. The
              decode rate is the share of frames that produced a read, so a camera that
              sees nothing scores nothing.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="scanner-frame relative aspect-video overflow-hidden rounded-lg border bg-black">
              <div id={camera.elementId} className="h-full w-full" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Camera log, straight from the hook. The reason a camera would not
          start is the single most useful thing on this screen when one won't. */}
      {camera.events.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Camera log</CardTitle>
            <CardDescription>What the browser reported, most recent first.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-1.5">
            {camera.events.slice(0, 8).map((e, i) => (
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

      <TestResultDialog testing={testing} onClose={() => setTesting(null)} />
      <HistoryDialog history={history} onClose={() => setHistory(null)} />
      <NetworkCameraDialog
        open={networkOpen}
        onOpenChange={setNetworkOpen}
        label={label}
        onAdd={(payload) => mutate(() => api.addCamera(payload))}
      />
    </div>
  );
}

/** What a measurement found, and what it means. */
function TestResultDialog({ testing, onClose }) {
  const done = testing?.phase === "done";
  const r = testing?.result;
  return (
    <Dialog open={Boolean(done)} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Gauge className="h-5 w-5" />
            {testing?.row?.name}
          </DialogTitle>
          <DialogDescription>
            Measured in this browser and scored on the server, so the same camera earns
            the same grade whichever machine tested it.
          </DialogDescription>
        </DialogHeader>
        {r && (
          <div className="space-y-3">
            <div className="flex items-center justify-between rounded-lg border p-3">
              <span className="text-sm font-medium">Grade</span>
              <div className="flex items-center gap-2">
                <Badge variant={GRADE_VARIANT[r.grade] || "muted"}>{r.grade}</Badge>
                <span className="tnum text-lg font-semibold">{r.score}/100</span>
              </div>
            </div>
            <dl className="grid grid-cols-2 gap-2 text-sm">
              <Measure name="Resolution" value={`${r.width}x${r.height}`} />
              <Measure name="Delivered frame rate" value={`${r.fps} fps`} />
              <Measure
                name="Decode rate"
                value={`${Math.round((r.decode_rate || 0) * 100)}%`}
              />
              <Measure
                name="Time to first read"
                value={r.first_ms === null ? "never decoded" : `${Math.round(r.first_ms)} ms`}
              />
              <Measure name="Frames examined" value={r.frames} />
              <Measure name="Reads" value={r.decodes} />
            </dl>
            {r.formats?.length > 0 && (
              <p className="text-xs text-muted-foreground">
                Decoded: {r.formats.join(", ")}
              </p>
            )}
            {r.error && <p className="text-sm text-destructive">{r.error}</p>}
            {!r.error && r.decodes === 0 && (
              <p className="text-sm text-muted-foreground">
                This camera produced frames but never read a code. That is the failure
                that raises no error anywhere -- it is exactly what the failover
                watchdog exists to catch.
              </p>
            )}
          </div>
        )}
        <DialogFooter>
          <Button onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function Measure({ name, value }) {
  return (
    <div className="rounded-md border p-2">
      <dt className="text-xs text-muted-foreground">{name}</dt>
      <dd className="tnum text-sm font-medium">{value}</dd>
    </div>
  );
}

/** Every measurement ever taken of one camera.
 *
 *  Kept rather than overwritten on purpose: a camera that used to pass and now
 *  does not is the single most useful thing this table can show. */
function HistoryDialog({ history, onClose }) {
  return (
    <Dialog open={Boolean(history)} onOpenChange={onClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <History className="h-5 w-5" />
            {history?.row?.name}
          </DialogTitle>
          <DialogDescription>
            Results are appended, never replaced. A camera that used to pass and now
            does not is worth seeing.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-80 overflow-y-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>When</TableHead>
                <TableHead>Grade</TableHead>
                <TableHead className="text-right">Score</TableHead>
                <TableHead className="text-right">Decode</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(history?.tests || []).length === 0 && (
                <TableEmpty colSpan={4}>This camera has never been measured.</TableEmpty>
              )}
              {(history?.tests || []).map((t) => (
                <TableRow key={t.id}>
                  <TableCell className="tnum text-xs">{formatTime(t.ts)}</TableCell>
                  <TableCell>
                    <Badge variant={GRADE_VARIANT[t.grade] || "muted"}>{t.grade}</Badge>
                  </TableCell>
                  <TableCell className="tnum text-right">{t.score}</TableCell>
                  <TableCell className="tnum text-right">
                    {Math.round((t.decode_rate || 0) * 100)}%
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** An IP camera, reached over HTTP.
 *
 *  A browser cannot open an RTSP stream at all, which is the single most common
 *  thing people try, so the form says so before the attempt rather than after. */
function NetworkCameraDialog({ open, onOpenChange, label, onAdd }) {
  const [name, setName] = React.useState("");
  const [url, setUrl] = React.useState("");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Globe className="h-4 w-4" />
            Add a network camera
          </DialogTitle>
          <DialogDescription>
            An IP camera reachable over HTTP, as an MJPEG stream or a still-image
            snapshot URL.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={async (e) => {
            e.preventDefault();
            // Await it. Closing the dialog and clearing the fields before the
            // server answered threw away every refusal -- an rtsp:// URL or a
            // duplicate produced a toast against a form that no longer existed,
            // so the camera silently was not added.
            const ok = await onAdd({
              station: stationId(),
              station_label: label,
              name: name.trim(),
              kind: "network",
              stream_url: url.trim(),
              role: "backup",
            });
            if (!ok) return;
            setName("");
            setUrl("");
            onOpenChange(false);
          }}
        >
          <div className="space-y-1.5">
            <Label htmlFor="net-name">Name</Label>
            <Input
              id="net-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. Dock door camera"
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="net-url">Stream or snapshot URL</Label>
            <Input
              id="net-url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="http://192.168.1.50/snapshot.jpg"
              required
            />
          </div>
          <div className="rounded-lg border bg-muted/40 p-2.5">
            <p className="text-xs text-muted-foreground">
              It must be http:// or https://. No browser can play an rtsp:// stream
              without a converting server in front of it, so an RTSP address will be
              refused rather than silently failing later.
            </p>
          </div>
          <Separator />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">Add camera</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
