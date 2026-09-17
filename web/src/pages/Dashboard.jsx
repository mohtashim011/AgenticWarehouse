import * as React from "react";
import { Link } from "react-router-dom";
import {
  Boxes, ScanLine, Tags, AlertTriangle, TrendingUp, Cpu, Brain,
  ArrowDownToLine, ArrowUpFromLine, ShoppingCart, ShieldAlert, Loader2,
} from "lucide-react";
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Stat, Separator } from "@/components/ui/misc";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow, TableEmpty,
} from "@/components/ui/table";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { actionTone, percent, seriesColor, timeAgo, cn } from "@/lib/utils";

const chartTheme = {
  grid: "hsl(var(--border))",
  text: "hsl(var(--muted-foreground))",
};

function ChartTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-sm shadow-md">
      <p className="font-medium">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="tnum text-muted-foreground">
          <span style={{ color: p.color }}>&#9632;</span> {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
}

export default function Dashboard() {
  const { user, can, signInInfo, dismissSignInInfo } = useAuth();
  const [state, setState] = React.useState(null);
  const [procurement, setProcurement] = React.useState([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const data = await api.state();
        if (alive) setState(data);
        if (can("reports.read")) {
          const p = await api.procurement().catch(() => null);
          if (alive && p) setProcurement(p.proposals || []);
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [can]);

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!state) return <p className="text-sm text-muted-foreground">Could not load the dashboard.</p>;

  const { stats, charts, low_stock: lowStock, logs, model, agents } = state;
  const activity = (charts?.activity || []).map((d) => ({
    day: d.day.slice(5),
    IN: d.in,
    OUT: d.out,
  }));
  const byCategory = (charts?.categories || []).map((c) => ({
    category: c.category,
    units: c.qty,
  }));
  const urgent = procurement.filter((p) => p.priority === "urgent");

  return (
    <div className="space-y-6">
      <div>
        {/* The whole name, not the first word: "System Administrator" split on
            a space greets the reader as "System". */}
        <h2 className="text-xl font-semibold">
          Welcome back, {user?.full_name || user?.username}
        </h2>
        <p className="text-sm text-muted-foreground">
          {stats.in_stock} units on hand across {stats.categories} categories.
        </p>
      </div>

      {/* The Authentication Agent's risk signals, shown once. */}
      {signInInfo?.signals?.length > 0 && (
        <Card className="border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/5">
          <CardContent className="flex items-start gap-3 p-4">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--warning))]" />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">
                The Authentication Agent noted this sign-in
              </p>
              <ul className="mt-1 space-y-0.5">
                {signInInfo.signals.map((s, i) => (
                  <li key={i} className="text-sm text-muted-foreground">
                    {s}
                  </li>
                ))}
              </ul>
            </div>
            <Button variant="ghost" size="sm" onClick={dismissSignInInfo}>
              Dismiss
            </Button>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={Boxes} label="In stock" value={stats.in_stock} hint="units on hand" />
        <Stat icon={ScanLine} label="Scans" value={stats.total_scans}
              hint={`${stats.scans_in} in / ${stats.scans_out} out`} />
        <Stat icon={Tags} label="Categories" value={stats.categories} />
        <Stat
          icon={AlertTriangle}
          label="Anomalies"
          value={stats.anomalies}
          tone={stats.anomalies > 0 ? "warning" : "default"}
          hint={stats.total_scans ? percent(stats.anomalies / stats.total_scans, 1) + " of scans" : "none yet"}
        />
      </div>

      {/* System health: the agents and the model that are actually running. */}
      <div className="grid gap-3 sm:grid-cols-2">
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/12 text-primary">
              <Cpu className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{agents?.agents || 0} agents running</p>
              <p className="text-xs text-muted-foreground">
                {percent(agents?.reliability ?? 1, 1)} reliability across{" "}
                {agents?.total_calls || 0} decisions
              </p>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/agents">View</Link>
            </Button>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-4 p-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-primary/12 text-primary">
              <Brain className="h-5 w-5" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium">
                {model?.trained ? model.model : "Training..."}
              </p>
              <p className="text-xs text-muted-foreground">
                {model?.trained
                  ? `${percent(model.accuracy)} accuracy on ${model.samples} examples`
                  : "The first model is being trained"}
              </p>
            </div>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/models">View</Link>
            </Button>
          </CardContent>
        </Card>
      </div>

      {(lowStock?.length > 0 || urgent.length > 0) && (
        <Card className="border-[hsl(var(--warning))]/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <ShoppingCart className="h-4 w-4 text-[hsl(var(--warning))]" />
              Needs attention
            </CardTitle>
            <CardDescription>
              Products at or below their reorder point, most urgent first.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Product</TableHead>
                  <TableHead className="text-right">On hand</TableHead>
                  <TableHead className="text-right">Reorder at</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {(lowStock || []).map((a) => (
                  <TableRow key={a.name}>
                    <TableCell className="font-medium">{a.name}</TableCell>
                    <TableCell className="tnum text-right">{a.qty}</TableCell>
                    <TableCell className="tnum text-right">{a.min_qty}</TableCell>
                    <TableCell>
                      <Badge variant={a.status === "OUT" ? "destructive" : "warning"}>
                        {a.status === "OUT" ? "out of stock" : "reorder"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
                {!lowStock?.length && <TableEmpty colSpan={4}>Nothing below its reorder level.</TableEmpty>}
              </TableBody>
            </Table>

            {urgent.length > 0 && (
              <>
                <Separator className="my-4" />
                <p className="mb-2 text-sm font-medium">
                  The Procurement Agent proposes ordering:
                </p>
                <ul className="space-y-1.5">
                  {urgent.slice(0, 4).map((p) => (
                    <li key={p.name} className="text-sm">
                      <span className="font-medium">{p.name}</span>
                      <span className="tnum text-muted-foreground"> &mdash; order {p.order_qty}. </span>
                      <span className="text-muted-foreground">{p.reason}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Stock by category</CardTitle>
            <CardDescription>
              Units on hand. One hue on purpose &mdash; the axis already names each bar.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {byCategory.length ? (
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={byCategory} layout="vertical" margin={{ left: 8, right: 24 }}>
                  <CartesianGrid horizontal={false} stroke={chartTheme.grid} />
                  <XAxis type="number" stroke={chartTheme.text} fontSize={11} allowDecimals={false} />
                  <YAxis
                    type="category"
                    dataKey="category"
                    stroke={chartTheme.text}
                    fontSize={11}
                    width={100}
                  />
                  <Tooltip content={<ChartTooltip />} cursor={{ fill: "hsl(var(--muted))" }} />
                  <Bar dataKey="units" fill={seriesColor(0)} radius={[0, 4, 4, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <p className="py-12 text-center text-sm text-muted-foreground">
                No stock yet &mdash; scan an item in.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">Activity &mdash; last 7 days</CardTitle>
            <CardDescription>Scans per day. Reversed scans are excluded.</CardDescription>
          </CardHeader>
          <CardContent>
            <ResponsiveContainer width="100%" height={260}>
              <LineChart data={activity} margin={{ left: -12, right: 12 }}>
                <CartesianGrid stroke={chartTheme.grid} vertical={false} />
                <XAxis dataKey="day" stroke={chartTheme.text} fontSize={11} />
                <YAxis stroke={chartTheme.text} fontSize={11} allowDecimals={false} />
                <Tooltip content={<ChartTooltip />} />
                <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                <Line type="monotone" dataKey="IN" stroke={seriesColor(1)} strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey="OUT" stroke={seriesColor(0)} strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0">
          <div>
            <CardTitle className="text-base">Recent activity</CardTitle>
            <CardDescription>Every movement, and who made it.</CardDescription>
          </div>
          <Button variant="outline" size="sm" asChild>
            <Link to="/activity">See all</Link>
          </Button>
        </CardHeader>
        <CardContent>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Action</TableHead>
                <TableHead>Product</TableHead>
                <TableHead className="hidden sm:table-cell">Staff</TableHead>
                <TableHead className="text-right">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(logs || []).slice(0, 8).map((l, i) => (
                <TableRow key={i} className={cn(l.undone && "opacity-50")}>
                  <TableCell>
                    <span
                      className={cn(
                        "inline-flex rounded-md border px-1.5 py-0.5 text-xs font-medium",
                        actionTone(l.action)
                      )}
                    >
                      {l.action}
                    </span>
                  </TableCell>
                  <TableCell className={cn("font-medium", l.undone && "line-through")}>
                    {l.name || "-"}
                    {l.anomaly ? (
                      <AlertTriangle className="ml-1.5 inline h-3.5 w-3.5 text-[hsl(var(--warning))]" />
                    ) : null}
                  </TableCell>
                  <TableCell className="hidden text-muted-foreground sm:table-cell">
                    {l.username || "-"}
                  </TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">
                    {timeAgo(l.ts)}
                  </TableCell>
                </TableRow>
              ))}
              {!logs?.length && <TableEmpty colSpan={4}>No activity yet.</TableEmpty>}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}
