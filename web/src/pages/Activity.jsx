import * as React from "react";
import { Download, Search, Undo2, ShieldCheck, Loader2, AlertTriangle, CheckCircle2 } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow, TableEmpty,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { actionTone, cn, formatTime } from "@/lib/utils";

const ACTIONS = ["", "IN", "OUT", "REJECT", "ADJUST", "UNDO"];

export default function Activity() {
  const toast = useToast();
  const { can } = useAuth();
  const [logs, setLogs] = React.useState([]);
  const [query, setQuery] = React.useState("");
  const [action, setAction] = React.useState("");
  const [undoable, setUndoable] = React.useState(null);
  const [audit, setAudit] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    const [l, s] = await Promise.all([api.logs(query, action, 200), api.state()]);
    setLogs(l.logs || []);
    setUndoable(s.undoable);
    setLoading(false);
  }, [query, action]);

  React.useEffect(() => {
    const t = setTimeout(() => load().catch((e) => toast.error(e.message)), 200);
    return () => clearTimeout(t);
  }, [load, toast]);

  const runAudit = async () => {
    try {
      const res = await api.audit();
      setAudit(res);
    } catch (err) {
      toast.error(err.message);
    }
  };

  return (
    <div className="space-y-6">
      <Tabs defaultValue="trail">
        <TabsList>
          <TabsTrigger value="trail">Audit trail</TabsTrigger>
          {can("audit.read") && (
            <TabsTrigger value="integrity" onClick={() => !audit && runAudit()}>
              Integrity
            </TabsTrigger>
          )}
        </TabsList>

        <TabsContent value="trail" className="space-y-4">
          {can("inventory.undo") && undoable && (
            <Card>
              <CardContent className="flex flex-wrap items-center gap-3 p-4">
                <Undo2 className="h-4 w-4 text-muted-foreground" />
                <span className="min-w-0 flex-1 text-sm">
                  Last reversible scan: <b>{undoable.action}</b> {undoable.name}
                  {undoable.batchno ? ` (batch ${undoable.batchno})` : ""}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={async () => {
                    try {
                      const res = await api.undo();
                      toast.success(res.message);
                      await load();
                    } catch (err) {
                      toast.error(err.message);
                    }
                  }}
                >
                  Undo it
                </Button>
              </CardContent>
            </Card>
          )}

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Search product, number, batch or staff"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <Select value={action} onValueChange={setAction}>
              <SelectTrigger className="w-40">
                <SelectValue placeholder="All actions" />
              </SelectTrigger>
              <SelectContent>
                {ACTIONS.map((a) => (
                  <SelectItem key={a || "all"} value={a}>
                    {a || "All actions"}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Button variant="outline" asChild>
              <a href={`/api/export/logs.csv?q=${encodeURIComponent(query)}&action=${action}`}>
                <Download className="h-4 w-4" />
                CSV
              </a>
            </Button>
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Action</TableHead>
                    <TableHead>Product</TableHead>
                    <TableHead className="hidden md:table-cell">Product no.</TableHead>
                    <TableHead className="hidden sm:table-cell">Staff</TableHead>
                    <TableHead className="text-right">When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {loading && <TableEmpty colSpan={5}><Loader2 className="mx-auto h-5 w-5 animate-spin" /></TableEmpty>}
                  {!loading && logs.map((l, i) => (
                    <TableRow key={i} className={cn(l.undone && "opacity-50")}>
                      <TableCell>
                        <span className={cn("inline-flex rounded-md border px-1.5 py-0.5 text-xs font-medium", actionTone(l.action))}>
                          {l.action}
                        </span>
                      </TableCell>
                      <TableCell className={cn("font-medium", l.undone && "line-through")}>
                        {l.name || "-"}
                        {l.batchno && (
                          <span className="ml-2 text-xs text-muted-foreground">{l.batchno}</span>
                        )}
                        {l.anomaly ? (
                          <AlertTriangle className="ml-1.5 inline h-3.5 w-3.5 text-[hsl(var(--warning))]" />
                        ) : null}
                      </TableCell>
                      <TableCell className="tnum hidden text-muted-foreground md:table-cell">
                        {l.productno || "-"}
                      </TableCell>
                      <TableCell className="hidden sm:table-cell">
                        {l.username ? (
                          <Badge variant="muted">{l.username}</Badge>
                        ) : (
                          <span className="text-xs text-muted-foreground">not recorded</span>
                        )}
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {formatTime(l.ts)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!loading && !logs.length && <TableEmpty colSpan={5}>Nothing matches.</TableEmpty>}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">
            The trail is append-only. A reversed scan stays visible, struck through, and its
            reversal is logged as its own entry — a log that quietly loses a row is not an
            audit trail.
          </p>
        </TabsContent>

        {can("audit.read") && (
          <TabsContent value="integrity" className="space-y-4">
            <Card>
              <CardHeader className="flex-row items-start justify-between space-y-0">
                <div>
                  <CardTitle className="text-base">Audit Agent</CardTitle>
                  <CardDescription>
                    Reconciles the stock figures against the log and reports drift. It never
                    repairs anything on its own.
                  </CardDescription>
                </div>
                <Button variant="outline" size="sm" onClick={runAudit}>
                  Re-run checks
                </Button>
              </CardHeader>
              <CardContent>
                {!audit && <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />}
                {audit && (
                  <div className="space-y-3">
                    <div className="flex flex-wrap gap-2">
                      <Badge variant={audit.decision.errors ? "destructive" : "success"}>
                        {audit.decision.errors} error{audit.decision.errors === 1 ? "" : "s"}
                      </Badge>
                      <Badge variant={audit.decision.warnings ? "warning" : "muted"}>
                        {audit.decision.warnings} warning{audit.decision.warnings === 1 ? "" : "s"}
                      </Badge>
                      <Badge variant="muted">{audit.decision.checks_run} checks run</Badge>
                    </div>
                    {audit.findings.length === 0 ? (
                      <div className="flex items-center gap-2 rounded-lg border border-[hsl(var(--success))]/30 bg-[hsl(var(--success))]/10 p-3 text-sm">
                        <CheckCircle2 className="h-4 w-4 text-[hsl(var(--success))]" />
                        Stock figures and the audit trail agree.
                      </div>
                    ) : (
                      <div className="space-y-2">
                        {audit.findings.map((f, i) => (
                          <div
                            key={i}
                            className={cn(
                              "rounded-lg border p-3",
                              f.severity === "error"
                                ? "border-destructive/30 bg-destructive/5"
                                : "border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/5"
                            )}
                          >
                            <div className="flex items-center gap-2">
                              <Badge variant={f.severity === "error" ? "destructive" : "warning"}>
                                {f.check}
                              </Badge>
                            </div>
                            <p className="mt-1 text-sm text-muted-foreground">{f.detail}</p>
                          </div>
                        ))}
                      </div>
                    )}
                    <div className="rounded-lg border p-3">
                      <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                        Agent reasoning
                      </p>
                      <ul className="space-y-0.5">
                        {audit.decision.rationale.map((r, i) => (
                          <li key={i} className="text-sm text-muted-foreground">{r}</li>
                        ))}
                      </ul>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>
    </div>
  );
}
