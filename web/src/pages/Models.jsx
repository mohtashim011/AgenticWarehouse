import * as React from "react";
import {
  Brain, Loader2, Play, Trophy, Download, FlaskConical, Sparkles, TrendingUp,
} from "lucide-react";
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Cell,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Stat, Progress, Separator } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { cn, percent, seriesColor, formatTime } from "@/lib/utils";

export default function Models() {
  const toast = useToast();
  const { can } = useAuth();
  const [data, setData] = React.useState(null);
  const [training, setTraining] = React.useState(false);
  const [testName, setTestName] = React.useState("");
  const [testResult, setTestResult] = React.useState(null);

  const load = React.useCallback(async () => {
    setData(await api.models());
  }, []);

  React.useEffect(() => {
    load().catch((e) => toast.error(e.message));
  }, [load, toast]);

  const train = async (deep) => {
    setTraining(true);
    try {
      const res = await api.trainModels(deep);
      toast.success("Models retrained and compared.");
      (res.decision?.rationale || []).slice(0, 3).forEach((r) => toast.info(r));
      await load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setTraining(false);
    }
  };

  if (!data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const { comparison } = data;
  const models = comparison.models || [];
  const winner = models[0];
  const chartData = models.map((m) => ({
    name: m.name.replace(/\s*\(.*\)/, "").replace("Multinomial ", "").replace("Character ", "Char "),
    accuracy: Number((m.cv_accuracy * 100).toFixed(1)),
    f1: Number((m.macro_f1 * 100).toFixed(1)),
    key: m.key,
  }));
  const labels = comparison.labels || [];
  const matrix = winner?.confusion?.matrix || {};

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">AI models</h2>
          <p className="max-w-2xl text-sm text-muted-foreground">
            Five classifiers, all written from scratch, trained on the same data and measured
            the same way. The best one runs.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" asChild>
            <a href="/api/export/models.json">
              <Download className="h-4 w-4" />
              Export
            </a>
          </Button>
          {can("models.train") && (
            <Button size="sm" onClick={() => train(false)} disabled={training}>
              {training ? <Loader2 className="h-4 w-4 animate-spin" /> : <Play className="h-4 w-4" />}
              Retrain
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          icon={Trophy}
          label="Selected model"
          value={percent(winner?.cv_accuracy)}
          hint={winner?.name}
          tone="success"
        />
        <Stat icon={Brain} label="Macro F1" value={percent(winner?.macro_f1)} hint="every category counts equally" />
        <Stat
          icon={FlaskConical}
          label="Training data"
          value={comparison.dataset.total}
          hint={`${comparison.dataset.classes} categories`}
        />
        <Stat
          icon={TrendingUp}
          label="Against baseline"
          value={`+${(comparison.baseline.absolute_gain * 100).toFixed(1)} pts`}
          tone="success"
          hint={`${percent(comparison.baseline.error_reduction, 0)} fewer errors`}
        />
      </div>

      <Tabs defaultValue="comparison">
        <TabsList>
          <TabsTrigger value="comparison">Comparison</TabsTrigger>
          <TabsTrigger value="detail">Per category</TabsTrigger>
          <TabsTrigger value="confusion">Confusion</TabsTrigger>
          <TabsTrigger value="try">Try it</TabsTrigger>
        </TabsList>

        <TabsContent value="comparison" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Cross-validated accuracy</CardTitle>
              <CardDescription>
                {comparison.folds}-fold stratified cross-validation, seed {comparison.seed}. The
                vectoriser is fitted inside each fold, so no test vocabulary leaks into
                training.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={chartData} margin={{ left: -12, right: 12 }}>
                  <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="name" stroke="hsl(var(--muted-foreground))" fontSize={11} interval={0} angle={-12} textAnchor="end" height={60} />
                  <YAxis domain={[0, 100]} stroke="hsl(var(--muted-foreground))" fontSize={11} />
                  <Tooltip
                    contentStyle={{
                      background: "hsl(var(--popover))",
                      border: "1px solid hsl(var(--border))",
                      borderRadius: 8,
                      fontSize: 12,
                    }}
                    formatter={(v) => `${v}%`}
                  />
                  <Bar dataKey="accuracy" radius={[4, 4, 0, 0]}>
                    {chartData.map((d, i) => (
                      <Cell
                        key={d.key}
                        fill={i === 0 ? seriesColor(1) : seriesColor(0)}
                        fillOpacity={i === 0 ? 1 : 0.55}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Model</TableHead>
                    <TableHead className="hidden md:table-cell">Family</TableHead>
                    <TableHead className="text-right">Accuracy</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">± std</TableHead>
                    <TableHead className="text-right">Macro F1</TableHead>
                    <TableHead className="text-right">Score</TableHead>
                    <TableHead className="hidden text-right lg:table-cell">Train</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {models.map((m, i) => (
                    <TableRow key={m.key} className={cn(i === 0 && "bg-[hsl(var(--success))]/5")}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {i === 0 && <Trophy className="h-3.5 w-3.5 text-[hsl(var(--success))]" />}
                          <span className="font-medium">{m.name}</span>
                        </div>
                        <p className="mt-0.5 max-w-md text-xs text-muted-foreground">{m.description}</p>
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        <Badge variant="muted">{m.family}</Badge>
                      </TableCell>
                      <TableCell className="tnum text-right font-semibold">
                        {percent(m.cv_accuracy)}
                      </TableCell>
                      <TableCell className="tnum hidden text-right text-muted-foreground sm:table-cell">
                        {m.cv_std.toFixed(3)}
                      </TableCell>
                      <TableCell className="tnum text-right">{percent(m.macro_f1)}</TableCell>
                      <TableCell className="tnum text-right">{m.score.toFixed(4)}</TableCell>
                      <TableCell className="tnum hidden text-right text-muted-foreground lg:table-cell">
                        {m.train_ms.toFixed(0)} ms
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base">How the winner was chosen</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-sm text-muted-foreground">{comparison.selection.reason}</p>
              <Separator />
              <div className="space-y-1 text-sm">
                <p className="font-medium">Selection score</p>
                <p className="text-muted-foreground">
                  {comparison.selection.weights.cv_accuracy} × accuracy +{" "}
                  {comparison.selection.weights.macro_f1} × macro F1 +{" "}
                  {comparison.selection.weights.consistency} × consistency
                </p>
                <p className="text-xs text-muted-foreground">
                  Macro F1 carries as much weight as accuracy on purpose: with categories of
                  different sizes, accuracy alone would let a model win by neglecting a small
                  one. The consistency term breaks ties in favour of the model whose score
                  does not swing between folds.
                </p>
              </div>
              <Separator />
              <p className="text-xs text-muted-foreground">
                Last trained {formatTime(comparison.trained_at)} ·{" "}
                {comparison.dataset.built_in} built-in examples +{" "}
                {comparison.dataset.learned} learned from your category assignments.
              </p>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="detail" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">{winner?.name} — per category</CardTitle>
              <CardDescription>
                Precision is "when it said this, how often was it right". Recall is "of the
                real ones, how many did it find".
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Precision</TableHead>
                    <TableHead className="text-right">Recall</TableHead>
                    <TableHead className="text-right">F1</TableHead>
                    <TableHead className="text-right">Examples</TableHead>
                    <TableHead className="hidden w-32 sm:table-cell" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(winner?.per_class || {}).map(([label, m]) => (
                    <TableRow key={label}>
                      <TableCell className="font-medium">{label}</TableCell>
                      <TableCell className="tnum text-right">{percent(m.precision, 0)}</TableCell>
                      <TableCell className="tnum text-right">{percent(m.recall, 0)}</TableCell>
                      <TableCell className="tnum text-right font-semibold">{percent(m.f1, 0)}</TableCell>
                      <TableCell className="tnum text-right text-muted-foreground">{m.support}</TableCell>
                      <TableCell className="hidden sm:table-cell">
                        <Progress
                          value={m.f1 * 100}
                          tone={m.f1 >= 0.9 ? "success" : m.f1 >= 0.75 ? "primary" : "warning"}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>

          {winner?.top_confusions?.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Where it goes wrong</CardTitle>
                <CardDescription>
                  The actionable part of an evaluation: these tell you which examples to add
                  next, in a way a single accuracy figure never can.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-1.5">
                {winner.top_confusions.map((c, i) => (
                  <div key={i} className="flex items-center gap-2 rounded-lg border p-2.5 text-sm">
                    <Badge variant="muted">{c.actual}</Badge>
                    <span className="text-muted-foreground">called</span>
                    <Badge variant="warning">{c.predicted}</Badge>
                    <span className="tnum ml-auto text-muted-foreground">
                      {c.count}×
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="confusion">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Confusion matrix</CardTitle>
              <CardDescription>
                Rows are what it actually was; columns are what the model said. The diagonal
                is correct.
              </CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="text-sm">
                <thead>
                  <tr>
                    <th className="p-2 text-left text-xs text-muted-foreground">actual \ predicted</th>
                    {labels.map((l) => (
                      <th key={l} className="p-2 text-xs font-medium text-muted-foreground">
                        {l.length > 10 ? `${l.slice(0, 9)}…` : l}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {labels.map((actual) => {
                    const row = matrix[actual] || {};
                    const total = Object.values(row).reduce((a, b) => a + b, 0) || 1;
                    return (
                      <tr key={actual}>
                        <td className="whitespace-nowrap p-2 text-xs font-medium">{actual}</td>
                        {labels.map((pred) => {
                          const n = row[pred] || 0;
                          const share = n / total;
                          const correct = actual === pred;
                          return (
                            <td key={pred} className="p-1">
                              <div
                                className={cn(
                                  "tnum flex h-10 w-14 items-center justify-center rounded-md text-sm font-medium",
                                  n === 0 && "text-muted-foreground/40"
                                )}
                                style={
                                  n > 0
                                    ? {
                                        background: correct
                                          ? `hsl(var(--success) / ${0.12 + share * 0.5})`
                                          : `hsl(var(--destructive) / ${0.12 + share * 0.6})`,
                                      }
                                    : undefined
                                }
                                title={`${actual} predicted as ${pred}: ${n}`}
                              >
                                {n || "·"}
                              </div>
                            </td>
                          );
                        })}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="try">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                <Sparkles className="mr-2 inline h-4 w-4" />
                Try a product name
              </CardTitle>
              <CardDescription>
                Ask the live model what it would suggest, and why. Nothing is changed.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <form
                onSubmit={async (e) => {
                  e.preventDefault();
                  if (!testName.trim()) return;
                  try {
                    setTestResult(await api.predict(testName.trim()));
                  } catch (err) {
                    toast.error(err.message);
                  }
                }}
                className="flex gap-2"
              >
                <Input
                  value={testName}
                  onChange={(e) => setTestName(e.target.value)}
                  placeholder="e.g. stainless steel travel mug 500ml"
                />
                <Button type="submit">Classify</Button>
              </form>

              {testResult && (
                <div className="space-y-3 rounded-lg border p-4">
                  <div className="flex items-baseline justify-between">
                    <span className="text-sm text-muted-foreground">Prediction</span>
                    <span className="text-lg font-semibold">{testResult.prediction}</span>
                  </div>
                  <div>
                    <div className="mb-1 flex justify-between text-xs text-muted-foreground">
                      <span>Confidence</span>
                      <span className="tnum">{percent(testResult.confidence)}</span>
                    </div>
                    <Progress
                      value={testResult.confidence * 100}
                      tone={testResult.confidence > 0.7 ? "success" : "warning"}
                    />
                  </div>
                  <Separator />
                  <div className="space-y-1.5">
                    {Object.entries(testResult.probabilities)
                      .sort((a, b) => b[1] - a[1])
                      .map(([label, p]) => (
                        <div key={label} className="flex items-center gap-2">
                          <span className="w-28 shrink-0 truncate text-xs">{label}</span>
                          <Progress value={p * 100} className="h-1.5 flex-1" />
                          <span className="tnum w-12 shrink-0 text-right text-xs text-muted-foreground">
                            {percent(p, 0)}
                          </span>
                        </div>
                      ))}
                  </div>
                  {testResult.explanation?.notes?.length > 0 && (
                    <>
                      <Separator />
                      {testResult.explanation.notes.map((n, i) => (
                        <p key={i} className="text-xs text-muted-foreground">{n}</p>
                      ))}
                    </>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
