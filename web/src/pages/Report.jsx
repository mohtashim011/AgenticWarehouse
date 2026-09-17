import * as React from "react";
import {
  BarChart3, Loader2, ArrowRight, CheckCircle2, Info, Printer, TrendingUp,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Progress, Separator, Stat } from "@/components/ui/misc";
import { api } from "@/lib/api";
import { percent, cn } from "@/lib/utils";

export default function Report() {
  const [data, setData] = React.useState(null);

  const [error, setError] = React.useState("");

  const load = React.useCallback(() => {
    setError("");
    api.reportComparison()
      .then((r) => setData(r.comparison))
      .catch((err) => setError(err.message));
  }, []);

  React.useEffect(() => { load(); }, [load]);

  if (!data) {
    // Without this the page span forever on any failure, with no message and
    // nothing to press.
    return error ? (
      <div className="mx-auto max-w-md py-16 text-center">
        <p className="text-sm text-muted-foreground">{error}</p>
        <Button className="mt-4" variant="outline" onClick={load}>Try again</Button>
      </div>
    ) : (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const h = data.headline;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Where this system stands</h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            The evidence for the claim that this improves on AUTOWARE, the centralised
            rule-based system it replaces. Every number here is measured, not estimated.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => window.print()}>
          <Printer className="h-4 w-4" />
          Print
        </Button>
      </div>

      {/* Headline: the one figure a reader will remember. */}
      <Card className="overflow-hidden border-[hsl(var(--success))]/30">
        <CardContent className="p-6">
          <div className="flex flex-wrap items-end gap-x-8 gap-y-4">
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Before</p>
              <p className="tnum text-3xl font-semibold text-muted-foreground">
                {percent(h.classification_accuracy.before, 0)}
              </p>
              <p className="text-xs text-muted-foreground">
                {h.training_data.before} samples, {h.categories_covered.before} categories
              </p>
            </div>
            <ArrowRight className="mb-4 h-6 w-6 text-muted-foreground" />
            <div>
              <p className="text-xs uppercase tracking-wide text-muted-foreground">Now</p>
              <p className="tnum text-4xl font-semibold text-[hsl(var(--success))]">
                {percent(h.classification_accuracy.after)}
              </p>
              <p className="text-xs text-muted-foreground">
                {h.training_data.after} samples, {h.categories_covered.after} categories
              </p>
            </div>
            <div className="ml-auto flex gap-6">
              <div className="text-right">
                <p className="tnum text-2xl font-semibold">
                  +{(h.classification_accuracy.gain * 100).toFixed(1)}
                </p>
                <p className="text-xs text-muted-foreground">points gained</p>
              </div>
              <div className="text-right">
                <p className="tnum text-2xl font-semibold text-[hsl(var(--success))]">
                  {percent(h.classification_accuracy.error_reduction, 0)}
                </p>
                <p className="text-xs text-muted-foreground">fewer errors</p>
              </div>
            </div>
          </div>
          <Progress value={h.classification_accuracy.after * 100} tone="success" className="mt-5" />
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={TrendingUp} label="Models evaluated" value={`1 → ${h.models_evaluated.after}`} />
        <Stat icon={BarChart3} label="Training samples" value={`${h.training_data.before} → ${h.training_data.after}`} />
        <Stat icon={CheckCircle2} label="Categories" value={`${h.categories_covered.before} → ${h.categories_covered.after}`} />
        <Stat icon={Info} label="Dimensions compared" value={data.dimensions.length} />
      </div>

      {/* Dimension-by-dimension */}
      <div className="space-y-3">
        <h3 className="text-sm font-semibold">What changed, and why it matters</h3>
        {data.dimensions.map((d) => (
          <Card key={d.dimension}>
            <CardHeader className="pb-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <CardTitle className="text-base">{d.dimension}</CardTitle>
                {d.metric && (
                  <Badge variant={d.measurable ? "success" : "muted"}>{d.metric}</Badge>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="grid gap-3 md:grid-cols-2">
                <div className="rounded-lg border bg-muted/30 p-3">
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
                    AUTOWARE (before)
                  </p>
                  <p className="text-sm text-muted-foreground">{d.before}</p>
                </div>
                <div className="rounded-lg border border-[hsl(var(--success))]/25 bg-[hsl(var(--success))]/5 p-3">
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-[hsl(var(--success))]">
                    This system (now)
                  </p>
                  <p className="text-sm">{d.after}</p>
                </div>
              </div>
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Why it matters. </span>
                {d.why_it_matters}
              </p>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* The raw numbers, so a reader can check the claims. */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">The measurements behind these claims</CardTitle>
          <CardDescription>
            {data.measured.folds}-fold stratified cross-validation, seed {data.measured.seed}, on{" "}
            {data.measured.dataset.total} labelled product names.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {data.measured.models.map((m) => (
            <div key={m.model} className="flex flex-wrap items-center gap-3">
              <span
                className={cn(
                  "w-56 shrink-0 truncate text-sm",
                  m.selected && "font-semibold"
                )}
              >
                {m.model}
                {m.selected && (
                  <Badge variant="success" className="ml-2">selected</Badge>
                )}
              </span>
              <Progress
                value={m.cv_accuracy * 100}
                tone={m.selected ? "success" : "primary"}
                className="min-w-[120px] flex-1"
              />
              <span className="tnum w-16 shrink-0 text-right text-sm">
                {percent(m.cv_accuracy)}
              </span>
              <span className="tnum hidden w-24 shrink-0 text-right text-xs text-muted-foreground sm:block">
                F1 {percent(m.macro_f1)}
              </span>
            </div>
          ))}
          <Separator />
          <p className="text-sm text-muted-foreground">{data.measured.selection_reason}</p>
        </CardContent>
      </Card>

      {/* Caveats belong in the report, not in a footnote nobody reads. */}
      <Card className="border-dashed">
        <CardHeader>
          <CardTitle className="text-base">What these numbers do not say</CardTitle>
          <CardDescription>
            A comparison that only lists its strengths is not evidence.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-2">
            {data.caveats.map((c, i) => (
              <li key={i} className="flex gap-2 text-sm text-muted-foreground">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                {c}
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}
