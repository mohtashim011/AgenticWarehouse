import * as React from "react";
import { Cpu, Loader2, Activity, ShieldCheck, RefreshCw } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Stat, Progress } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { cn, percent, timeAgo, groupBy } from "@/lib/utils";

const LAYER_INFO = {
  security: "Who may act, and on what.",
  perception: "Turning what the camera saw into something the warehouse understands.",
  operations: "The stock itself, and whether the books hold up.",
  planning: "What happens next: running out, and what to order.",
  learning: "Keeping the models honest as the product range changes.",
  administration: "People and permissions.",
  assistance: "Answering questions in plain language.",
};

const STATUS_VARIANT = {
  healthy: "success",
  idle: "muted",
  degraded: "warning",
  failing: "destructive",
};

export default function Agents() {
  const [data, setData] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  const [error, setError] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      setData(await api.agents());
      setError("");
    } catch (err) {
      // Previously this threw past the caller and `data` stayed null, so the
      // destructure below crashed and took the whole app to a blank page.
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!data) {
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <p className="text-sm text-muted-foreground">
          {error || "The agent roster could not be loaded."}
        </p>
        <Button className="mt-4" variant="outline" onClick={load}>
          <RefreshCw className="h-4 w-4" />
          Try again
        </Button>
      </div>
    );
  }

  const byLayer = groupBy(data.agents, (a) => a.layer);
  const { summary } = data;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">The agents</h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Every component that reaches a decision is an independent agent. None of them can
            stop the pipeline: an agent that fails returns a degraded decision and the work
            carries on without it.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={load}>
          <RefreshCw className={cn("h-4 w-4", loading && "animate-spin")} />
          Refresh
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={Cpu} label="Agents" value={summary.agents} hint={`${Object.keys(byLayer).length} layers`} />
        <Stat icon={Activity} label="Decisions made" value={summary.total_calls} />
        <Stat
          icon={ShieldCheck}
          label="Reliability"
          value={summary.total_calls === 0 ? "—" : percent(summary.reliability, 2)}
          tone={summary.reliability >= 0.99 ? "success" : "warning"}
          hint={summary.total_calls === 0 ? "no decisions yet" : undefined}
        />
        <Stat
          icon={Cpu}
          label="Failures"
          value={summary.total_failures}
          tone={summary.total_failures ? "warning" : "default"}
          hint="contained, never fatal"
        />
      </div>

      {Object.entries(byLayer).map(([layer, agents]) => (
        <div key={layer} className="space-y-2">
          <div>
            <h3 className="text-sm font-semibold capitalize">{layer}</h3>
            <p className="text-xs text-muted-foreground">{LAYER_INFO[layer]}</p>
          </div>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {agents.map((a) => (
              <Card key={a.name}>
                <CardHeader className="pb-3">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-sm leading-tight">{a.name}</CardTitle>
                    <Badge variant={STATUS_VARIANT[a.status]}>{a.status}</Badge>
                  </div>
                  <CardDescription className="text-xs">{a.role}</CardDescription>
                </CardHeader>
                <CardContent className="space-y-3">
                  <div className="rounded-md bg-muted/50 px-2 py-1.5">
                    <p className="text-[11px] uppercase tracking-wide text-muted-foreground">
                      Method
                    </p>
                    <p className="text-xs">{a.method}</p>
                  </div>

                  <div className="grid grid-cols-3 gap-2 text-center">
                    <div>
                      <p className="tnum text-sm font-semibold">{a.calls}</p>
                      <p className="text-[11px] text-muted-foreground">calls</p>
                    </div>
                    <div>
                      <p className="tnum text-sm font-semibold">{a.avg_ms.toFixed(1)}</p>
                      <p className="text-[11px] text-muted-foreground">avg ms</p>
                    </div>
                    <div>
                      <p
                        className={cn(
                          "tnum text-sm font-semibold",
                          a.failures > 0 && "text-[hsl(var(--warning))]"
                        )}
                      >
                        {a.failures}
                      </p>
                      <p className="text-[11px] text-muted-foreground">failures</p>
                    </div>
                  </div>

                  {/* An agent that has never run has no measured reliability.
                      Showing a full green 100% bar for it claims a track record
                      that does not exist. */}
                  <div>
                    <div className="mb-1 flex justify-between text-[11px] text-muted-foreground">
                      <span>Reliability</span>
                      <span className="tnum">
                        {a.calls === 0 ? "not measured yet" : percent(a.reliability, 1)}
                      </span>
                    </div>
                    <Progress
                      value={a.calls === 0 ? 0 : a.reliability * 100}
                      tone={a.reliability >= 0.99 ? "success" : "warning"}
                    />
                  </div>

                  <div className="flex flex-wrap items-center gap-1.5 text-[11px] text-muted-foreground">
                    {a.critical && <Badge variant="destructive">critical path</Badge>}
                    {a.degradations > 0 && (
                      <Badge variant="warning">{a.degradations} degraded</Badge>
                    )}
                    {a.last_run_at && <span>last ran {timeAgo(a.last_run_at)}</span>}
                  </div>

                  {a.last_error && (
                    <p className="rounded-md border border-destructive/30 bg-destructive/5 p-2 text-[11px] text-destructive">
                      {a.last_error}
                    </p>
                  )}
                </CardContent>
              </Card>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
