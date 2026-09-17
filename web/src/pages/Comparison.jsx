/**
 * Comparison
 * ==========
 * How this system stands against what a warehouse could buy instead.
 *
 * Deliberately not the same screen as Report. That one compares this system
 * with the project it replaces; this one compares it with the market — paper,
 * barcode hardware, scanning SDKs, enterprise WMS platforms, RFID, and the
 * computer-vision and multi-agent work being published now.
 *
 * The design rule here is the same one the data follows: **losses are shown in
 * the same table as the wins**. A comparison that wins every row is a brochure,
 * and a reader who spots one unearned claim stops believing the earned ones. So
 * the filter defaults to everything, the loss count sits in the headline beside
 * the win count, and every row states what the other systems do well before it
 * says what they cannot do.
 */
import * as React from "react";
import {
  Scale, Loader2, RefreshCw, Check, X, Minus, Info, ChevronDown, Printer,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator, Stat } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import { cn, percent } from "@/lib/utils";

/** How a verdict reads. A module-level map, not inline ternaries: there are
 *  three cases and they appear in four different places. */
const VERDICT = {
  win: {
    label: "Ahead",
    icon: Check,
    variant: "success",
    tint: "border-[hsl(var(--success))]/25 bg-[hsl(var(--success))]/5",
  },
  loss: {
    label: "Behind",
    icon: X,
    variant: "destructive",
    tint: "border-destructive/25 bg-destructive/5",
  },
  scope: {
    label: "Different scope",
    icon: Minus,
    variant: "muted",
    tint: "border-border",
  },
};

const GROUP_LABEL = {
  identification: "Identifying stock",
  resilience: "Capture resilience",
  transparency: "Decisions and transparency",
  learning: "Learning",
  security: "Security and access",
  deployment: "Deployment and cost",
  evidence: "Quality of evidence",
  scale: "Scale and depth",
};

const EVIDENCE_VARIANT = {
  measured: "success",
  "vendor-published": "info",
  "industry-typical": "muted",
  structural: "muted",
  academic: "info",
};

export default function Comparison() {
  const [data, setData] = React.useState(null);
  const [error, setError] = React.useState("");
  const [filter, setFilter] = React.useState("all");

  const load = React.useCallback(() => {
    setError("");
    api
      .marketComparison()
      .then((r) => setData(r.comparison))
      .catch((err) => setError(err.message));
  }, []);

  React.useEffect(() => {
    load();
  }, [load]);

  /**
   * Open every disclosure before printing, and put back what the reader had.
   *
   * The print stylesheet forces them open too, but browsers disagree about
   * whether a closed <details> can be revealed by CSS alone, and the one thing
   * this page cannot ship is a printout showing our position with the
   * alternatives folded away. Setting the attribute is the only reliable way.
   */
  React.useEffect(() => {
    const openAll = () => {
      const closed = [...document.querySelectorAll("details:not([open])")];
      closed.forEach((d) => d.setAttribute("open", ""));
      return closed;
    };
    let reopened = [];
    const before = () => {
      reopened = openAll();
    };
    const after = () => {
      reopened.forEach((d) => d.removeAttribute("open"));
      reopened = [];
    };
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);

  if (!data) {
    // Without this the page spins forever on any failure, with no message and
    // nothing to press.
    return error ? (
      <div className="mx-auto max-w-md py-16 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button className="mt-4" variant="outline" onClick={load}>
          <RefreshCw className="h-4 w-4" />
          Try again
        </Button>
      </div>
    ) : (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const h = data.headline;
  const shown = data.dimensions.filter((d) => filter === "all" || d.verdict === filter);
  const groups = data.groups.filter((g) => shown.some((d) => d.group === g));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Against existing systems</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            Measured against what a warehouse could buy instead, across{" "}
            <span className="tnum font-medium">{h.tiers}</span> tiers of existing
            system. Every figure describing this system is measured here and re-derived
            by the self-test. Every figure describing another system is attributed, and
            no accuracy percentage is claimed for any named commercial product.
          </p>
        </div>
        <Button variant="outline" className="no-print" onClick={() => window.print()}>
          <Printer className="h-4 w-4" />
          Print
        </Button>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          icon={Check}
          label="Ahead"
          value={h.wins}
          hint={`of ${h.dimensions} dimensions`}
          tone="success"
        />
        <Stat
          icon={X}
          label="Behind"
          value={h.losses}
          hint="stated, not buried"
          tone="destructive"
        />
        <Stat icon={Minus} label="Different scope" value={h.scope} hint="not a contest" />
        <Stat
          icon={Scale}
          label="Classifier accuracy"
          value={percent(h.accuracy)}
          hint={`${h.model}, macro-F1 ${percent(h.macro_f1)}`}
          tone="info"
        />
      </div>

      {/* The claim this whole screen rests on, said once and plainly. */}
      <Card className="border-dashed">
        <CardContent className="flex gap-3 p-4">
          <Info className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            Where this system leads, it leads on <strong>what happens around the
            read</strong> — recovering a bad one, refusing a duplicate, deciding which
            camera to use, and recording who decided what and why. Where it is behind,
            it is behind on <strong>the read itself and everything after the
            warehouse</strong> — range, ruggedness, bulk throughput, enterprise
            integration and production track record. Both halves are below.
          </p>
        </CardContent>
      </Card>

      <Tabs value={filter} onValueChange={setFilter}>
        <TabsList>
          <TabsTrigger value="all">All {data.dimensions.length}</TabsTrigger>
          <TabsTrigger value="win">Ahead {h.wins}</TabsTrigger>
          <TabsTrigger value="loss">Behind {h.losses}</TabsTrigger>
          <TabsTrigger value="scope">Scope {h.scope}</TabsTrigger>
        </TabsList>

        <TabsContent value={filter} className="space-y-6">
          {groups.map((group) => (
            <div key={group} className="space-y-3">
              <h3 className="text-sm font-semibold uppercase tracking-wide text-muted-foreground">
                {GROUP_LABEL[group] || group}
              </h3>
              {shown
                .filter((d) => d.group === group)
                .map((d) => (
                  <DimensionCard key={d.dimension} d={d} tiers={data.tiers} />
                ))}
            </div>
          ))}
        </TabsContent>
      </Tabs>

      {/* The alternatives, on their own terms. Stating what each tier is
          genuinely good at is what earns the right to say what it cannot do. */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">The systems being compared</CardTitle>
          <CardDescription>
            What each one is genuinely good at, and what is architecturally absent from
            it — not what it merely does less well.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.tiers.map((t) => (
            <details key={t.key} className="group rounded-lg border p-3">
              <summary className="flex cursor-pointer list-none items-center gap-2">
                <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground transition-transform group-open:rotate-180" />
                <span className="min-w-0 flex-1 font-medium">{t.name}</span>
                <Badge variant={EVIDENCE_VARIANT[t.evidence] || "muted"}>
                  {t.evidence}
                </Badge>
              </summary>
              <div className="mt-3 space-y-3 pl-6">
                <p className="text-sm text-muted-foreground">{t.identifies_by}</p>
                <p className="text-xs text-muted-foreground">
                  For example: {t.exemplars.join(", ")}
                </p>
                <Separator />
                <div className="grid gap-3 sm:grid-cols-2">
                  <div>
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[hsl(var(--success))]">
                      Genuine strengths
                    </p>
                    <ul className="space-y-1">
                      {t.strengths.map((s, i) => (
                        <li key={i} className="text-sm text-muted-foreground">
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                  <div>
                    <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      Structurally absent
                    </p>
                    <ul className="space-y-1">
                      {t.limits.map((s, i) => (
                        <li key={i} className="text-sm text-muted-foreground">
                          {s}
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              </div>
            </details>
          ))}
        </CardContent>
      </Card>

      {/* How to read the evidence labels, and what this comparison does not claim. */}
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">What each evidence label means</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            {Object.entries(data.evidence_key).map(([key, meaning]) => (
              <div key={key} className="flex gap-2">
                <Badge variant={EVIDENCE_VARIANT[key] || "muted"} className="shrink-0">
                  {key}
                </Badge>
                <span className="text-sm text-muted-foreground">{meaning}</span>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">What this does not claim</CardTitle>
            <CardDescription>
              The limits of the comparison, stated by the system that produced it.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2">
              {data.caveats.map((c, i) => (
                <li key={i} className="flex gap-2 text-sm text-muted-foreground">
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-muted-foreground" />
                  {c}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

/** One dimension: our position, why it matters, and what each other tier does. */
function DimensionCard({ d, tiers }) {
  const meta = VERDICT[d.verdict] || VERDICT.scope;
  const Icon = meta.icon;
  return (
    <Card className={cn("print-keep", meta.tint)}>
      <CardHeader className="flex-row items-start justify-between space-y-0 gap-3">
        <CardTitle className="text-base">{d.dimension}</CardTitle>
        <Badge variant={meta.variant} className="shrink-0">
          <Icon className="h-3 w-3" />
          {meta.label}
        </Badge>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            This system
          </p>
          <p className="text-sm">{d.ours}</p>
          <p className="mt-1 font-mono text-[11px] text-muted-foreground">
            {d.ours_evidence}
          </p>
        </div>

        {/* Open by default, and open when printed.
            Our position was always visible while every competitor's was folded
            away behind a click. On a page whose whole claim is even-handedness
            that is not a layout choice, it is a thumb on the scale -- a reader
            who never expands one of these sees only the flattering half. */}
        <details className="group" open>
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">
            <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
            The alternatives
          </summary>
          <dl className="mt-2 space-y-1.5">
            {tiers.map((t) => (
              <div key={t.key} className="grid gap-0.5 sm:grid-cols-[10rem_1fr] sm:gap-3">
                <dt className="text-xs font-medium text-muted-foreground">{t.name}</dt>
                <dd className="text-sm text-muted-foreground">{d.tiers[t.key]}</dd>
              </div>
            ))}
          </dl>
        </details>

        <div className="rounded-lg border bg-muted/40 p-2.5">
          <p className="text-xs text-muted-foreground">{d.why_it_matters}</p>
        </div>
      </CardContent>
    </Card>
  );
}
