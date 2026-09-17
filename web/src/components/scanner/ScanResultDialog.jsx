/**
 * Stock IN / Stock OUT result dialog
 * ==================================
 * What the operator sees the instant a scan lands.
 *
 * The verdict and the new quantity are the headline, readable at arm's length,
 * because that is the only thing most scans need. Everything else -- which
 * agent decided what, how confident it was, why -- is one tap away rather than
 * gone: a system that asks people to trust it has to be able to show its work.
 */
import * as React from "react";
import {
  ArrowDownToLine, ArrowUpFromLine, Ban, CheckCircle2, AlertTriangle,
  ChevronDown, Wrench, Tag, Undo2, ScanLine,
} from "lucide-react";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { cn, percent } from "@/lib/utils";

const VERDICT = {
  IN: {
    icon: ArrowDownToLine,
    title: "Stock in",
    tone: "text-[hsl(var(--success))]",
    ring: "border-[hsl(var(--success))]/35 bg-[hsl(var(--success))]/10",
  },
  OUT: {
    icon: ArrowUpFromLine,
    title: "Stock out",
    tone: "text-[hsl(var(--info))]",
    ring: "border-[hsl(var(--info))]/35 bg-[hsl(var(--info))]/10",
  },
  REJECT: {
    icon: Ban,
    title: "Rejected",
    tone: "text-destructive",
    ring: "border-destructive/35 bg-destructive/10",
  },
};

const VERDICT_TONE = {
  ACCEPT: "success",
  REJECT: "destructive",
  FLAG: "warning",
  DEGRADED: "warning",
  INFO: "muted",
};

function AgentStep({ step }) {
  const [open, setOpen] = React.useState(false);
  const notes = step.rationale || step.notes || step.reasons || [];
  const verdict = step.verdict || "INFO";

  return (
    <div className="rounded-lg border">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="min-w-0 flex-1 truncate text-sm font-medium">{step.agent}</span>
        {step.degraded && (
          <Badge variant="warning" className="shrink-0">
            degraded
          </Badge>
        )}
        <Badge variant={VERDICT_TONE[verdict] || "muted"} className="shrink-0">
          {verdict.toLowerCase()}
        </Badge>
        <span className="tnum shrink-0 text-xs text-muted-foreground">
          {percent(step.confidence, 0)}
        </span>
        <ChevronDown
          className={cn("h-3.5 w-3.5 shrink-0 text-muted-foreground transition-transform", open && "rotate-180")}
        />
      </button>
      {open && (
        <div className="space-y-1.5 border-t px-3 py-2">
          {step.method && (
            <p className="text-xs text-muted-foreground">
              Method: <span className="text-foreground">{step.method}</span>
              {typeof step.elapsed_ms === "number" && (
                <span className="tnum"> &middot; {step.elapsed_ms.toFixed(1)} ms</span>
              )}
            </p>
          )}
          <ul className="space-y-1">
            {notes.map((note, i) => (
              <li key={i} className="text-sm text-muted-foreground">
                {note}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export function ScanResultDialog({
  open, onOpenChange, result, categories = [], onAssignCategory, onUndo, onScanAgain,
}) {
  const [category, setCategory] = React.useState("");
  const [assigning, setAssigning] = React.useState(false);
  const [assigned, setAssigned] = React.useState(false);
  const [traceOpen, setTraceOpen] = React.useState(false);

  React.useEffect(() => {
    if (!result) return;
    setAssigned(false);
    setTraceOpen(false);
    setCategory(result.suggestion?.category || "");
  }, [result]);

  if (!result) return null;

  const meta = VERDICT[result.final] || VERDICT.REJECT;
  const Icon = meta.icon;
  const needsCategory =
    result.needs_category && result.name && result.name !== "Unknown Item" && !assigned;

  const assign = async () => {
    if (!category) return;
    setAssigning(true);
    try {
      await onAssignCategory(result.name, category);
      setAssigned(true);
    } finally {
      setAssigning(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="sr-only">{meta.title}</DialogTitle>
        </DialogHeader>

        {/* Headline: readable from arm's length. */}
        <div className={cn("rounded-xl border p-4", meta.ring)}>
          <div className="flex items-start gap-3">
            <Icon className={cn("mt-0.5 h-6 w-6 shrink-0", meta.tone)} />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-x-2">
                <span className={cn("text-lg font-semibold", meta.tone)}>{meta.title}</span>
                <span className="truncate text-lg font-semibold">{result.name || "?"}</span>
              </div>
              <p className="mt-1 text-sm text-muted-foreground">{result.reason}</p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {result.productno && (
                  <Badge variant="muted" className="tnum">
                    {result.productno}
                  </Badge>
                )}
                {result.batchno && <Badge variant="muted">batch {result.batchno}</Badge>}
                {result.category && <Badge variant="outline">{result.category}</Badge>}
                {result.anomaly && (
                  <Badge variant="warning">
                    <AlertTriangle className="h-3 w-3" />
                    anomaly
                  </Badge>
                )}
              </div>
            </div>
            {typeof result.qty === "number" && (
              <div className="shrink-0 text-right">
                <div className="tnum text-3xl font-semibold leading-none">{result.qty}</div>
                <div className="text-xs text-muted-foreground">on hand</div>
              </div>
            )}
          </div>
        </div>

        {/* A repaired read must be visible, never silent. */}
        {result.recovery?.repaired && (
          <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/10 p-3">
            <Wrench className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--warning))]" />
            <div className="min-w-0 text-sm">
              <p className="font-medium">The read was repaired before it was used</p>
              <p className="text-muted-foreground">
                <code className="rounded bg-muted px-1">{result.code}</code> was corrected
                to <code className="rounded bg-muted px-1">{result.recovery.repaired}</code>{" "}
                by the <b>{result.recovery.strategy}</b> strategy at{" "}
                {percent(result.recovery.confidence, 0)} confidence.
              </p>
            </div>
          </div>
        )}

        {result.anomaly && result.anomaly_reasons?.length > 0 && (
          <div className="rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/10 p-3">
            <p className="text-sm font-medium">Why this was flagged</p>
            <ul className="mt-1 space-y-0.5">
              {result.anomaly_reasons.map((r, i) => (
                <li key={i} className="text-sm text-muted-foreground">
                  {r}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* An unseen product: file it here, while it is in front of the person
            who just handled it and knows what it is. */}
        {needsCategory && (
          <div className="rounded-lg border p-3">
            <div className="flex items-center gap-2">
              <Tag className="h-4 w-4 text-muted-foreground" />
              <p className="text-sm font-medium">
                Which category does <b>{result.name}</b> belong to?
              </p>
            </div>
            {result.suggestion && (
              <p className="mt-1 text-xs text-muted-foreground">
                The classifier suggests <b>{result.suggestion.category}</b> at{" "}
                {percent(result.suggestion.confidence, 0)} confidence. It is filed as
                Uncategorised until you decide.
              </p>
            )}
            <div className="mt-2 flex gap-2">
              <Select value={category} onValueChange={setCategory}>
                <SelectTrigger className="flex-1">
                  <SelectValue placeholder="Choose a category" />
                </SelectTrigger>
                <SelectContent>
                  {categories
                    .filter((c) => c.name !== "Uncategorised")
                    .map((c) => (
                      <SelectItem key={c.name} value={c.name}>
                        {c.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              <Button onClick={assign} disabled={!category || assigning}>
                {assigning ? "Saving..." : "Save"}
              </Button>
            </div>
          </div>
        )}

        {assigned && (
          <div className="flex items-center gap-2 rounded-lg border border-[hsl(var(--success))]/30 bg-[hsl(var(--success))]/10 p-3 text-sm">
            <CheckCircle2 className="h-4 w-4 text-[hsl(var(--success))]" />
            Filed under {category}. The classifier will learn from this.
          </div>
        )}

        {/* The agent trace. Collapsed by default: most scans do not need it,
            and every scan should be able to prove itself when they do. */}
        <div>
          <button
            type="button"
            onClick={() => setTraceOpen((o) => !o)}
            className="flex w-full items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
          >
            <ChevronDown className={cn("h-4 w-4 transition-transform", traceOpen && "rotate-180")} />
            {traceOpen ? "Hide" : "Show"} how the agents decided ({result.trace?.length || 0} steps)
          </button>
          {traceOpen && (
            <div className="mt-2 space-y-1.5">
              {(result.trace || []).map((step, i) => (
                <AgentStep key={i} step={step} />
              ))}
            </div>
          )}
        </div>

        {/* This dialog is no longer in the scanning path -- a scan acknowledges
            itself with a toast and the camera stays ready. It opens only when
            someone asks to look at a scan, so it closes rather than advances. */}
        <DialogFooter>
          {(result.final === "IN" || result.final === "OUT") && (
            <Button variant="outline" onClick={onUndo}>
              <Undo2 className="h-4 w-4" />
              Undo this
            </Button>
          )}
          <Button onClick={onScanAgain}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
