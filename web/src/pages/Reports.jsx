/**
 * Daily report
 * ============
 * How much went in and out, day by day, with the breakdowns a stock controller
 * actually asks for: by product, by category, by staff member, by hour.
 *
 * Net movement (in minus out) is given as much prominence as the totals,
 * because it is the number that says whether stock is growing or draining —
 * two busy days with equal in and out mean something quite different from two
 * busy days that are all outbound.
 */
import * as React from "react";
import { Link } from "react-router-dom";
import {
  CalendarDays, Download, Loader2, ArrowDownToLine, ArrowUpFromLine,
  TrendingUp, TrendingDown, Clock, AlertTriangle, Users, Tags, Package,
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend, ReferenceLine, Cell,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Stat, Separator } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow, TableEmpty,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { api } from "@/lib/api";
import { cn, seriesColor } from "@/lib/utils";

const RANGES = [
  { label: "7 days", days: 7 },
  { label: "30 days", days: 30 },
  { label: "90 days", days: 90 },
];

function Tip({ active, payload, label }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="mb-1 font-medium">{label}</p>
      {payload.map((p) => (
        <p key={p.dataKey} className="tnum text-muted-foreground">
          <span style={{ color: p.color }}>■</span> {p.name}: {p.value}
        </p>
      ))}
    </div>
  );
}

export default function Reports() {
  const toast = useToast();
  const [days, setDays] = React.useState(30);
  const [custom, setCustom] = React.useState({ from: "", to: "" });
  const [report, setReport] = React.useState(null);
  const [loading, setLoading] = React.useState(true);

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const res = await api.dailyReport({
        days,
        from: custom.from || undefined,
        to: custom.to || undefined,
      });
      setReport(res.report);
    } catch (err) {
      toast.error(err.message);
    } finally {
      setLoading(false);
    }
  }, [days, custom.from, custom.to, toast]);

  React.useEffect(() => {
    load();
  }, [load]);

  if (loading && !report) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (!report) return null;

  const { summary, series } = report;
  const chart = series.map((d) => ({ ...d, day: d.day.slice(5) }));
  const growing = summary.net > 0;
  const exportQuery = custom.from
    ? `from=${custom.from}&to=${custom.to || ""}`
    : `days=${days}`;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold">Daily report</h2>
          <p className="text-sm text-muted-foreground">
            {report.from} to {report.to} · {report.days} days ·{" "}
            {summary.active_days} with activity
          </p>
        </div>
        <Button variant="outline" size="sm" asChild>
          <a href={`/api/export/daily.csv?${exportQuery}`}>
            <Download className="h-4 w-4" />
            CSV
          </a>
        </Button>
      </div>

      {/* Range picker */}
      <Card>
        <CardContent className="flex flex-wrap items-end gap-3 p-4">
          <div className="flex gap-1.5">
            {RANGES.map((r) => (
              <Button
                key={r.days}
                variant={days === r.days && !custom.from ? "default" : "outline"}
                size="sm"
                onClick={() => {
                  setCustom({ from: "", to: "" });
                  setDays(r.days);
                }}
              >
                {r.label}
              </Button>
            ))}
          </div>
          <Separator orientation="vertical" className="hidden h-9 sm:block" />
          <div className="flex flex-wrap items-end gap-2">
            <div className="space-y-1">
              <Label htmlFor="from" className="text-xs">From</Label>
              <Input
                id="from"
                type="date"
                className="w-40"
                value={custom.from}
                onChange={(e) => setCustom((c) => ({ ...c, from: e.target.value }))}
              />
            </div>
            <div className="space-y-1">
              <Label htmlFor="to" className="text-xs">To</Label>
              <Input
                id="to"
                type="date"
                className="w-40"
                value={custom.to}
                onChange={(e) => setCustom((c) => ({ ...c, to: e.target.value }))}
              />
            </div>
            {custom.from && (
              <Button variant="ghost" size="sm" onClick={() => setCustom({ from: "", to: "" })}>
                Clear
              </Button>
            )}
          </div>
          {loading && <Loader2 className="mb-2 h-4 w-4 animate-spin text-muted-foreground" />}
        </CardContent>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          icon={ArrowDownToLine}
          label="Stock in"
          value={summary.in}
          tone="success"
          hint={`${summary.avg_in_per_active_day}/day when active`}
        />
        <Stat
          icon={ArrowUpFromLine}
          label="Stock out"
          value={summary.out}
          tone="info"
          hint={`${summary.avg_out_per_active_day}/day when active`}
        />
        <Stat
          icon={growing ? TrendingUp : TrendingDown}
          label="Net movement"
          value={`${summary.net > 0 ? "+" : ""}${summary.net}`}
          tone={growing ? "success" : summary.net < 0 ? "warning" : "default"}
          hint={growing ? "stock growing" : summary.net < 0 ? "stock draining" : "flat"}
        />
        <Stat
          icon={AlertTriangle}
          label="Anomalies"
          value={summary.anomalies}
          tone={summary.anomalies ? "warning" : "default"}
          hint={`${summary.rejects} rejected · ${summary.adjusts} corrected`}
        />
      </div>

      {(summary.busiest_day || summary.busiest_hour !== null) && (
        <Card className="border-dashed">
          <CardContent className="flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-sm">
            <span className="flex items-center gap-2 text-muted-foreground">
              <CalendarDays className="h-4 w-4" />
              Busiest day:{" "}
              <span className="font-medium text-foreground">
                {summary.busiest_day || "—"}
              </span>
            </span>
            <span className="flex items-center gap-2 text-muted-foreground">
              <Clock className="h-4 w-4" />
              Busiest hour:{" "}
              <span className="tnum font-medium text-foreground">
                {summary.busiest_hour !== null
                  ? `${String(summary.busiest_hour).padStart(2, "0")}:00 UTC`
                  : "—"}
              </span>
            </span>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Movement per day</CardTitle>
          <CardDescription>
            Reversed scans are excluded — this shows what actually happened to stock.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chart} margin={{ left: -12, right: 12 }}>
              <defs>
                <linearGradient id="gIn" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={seriesColor(1)} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={seriesColor(1)} stopOpacity={0.02} />
                </linearGradient>
                <linearGradient id="gOut" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={seriesColor(0)} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={seriesColor(0)} stopOpacity={0.02} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={11}
                     interval="preserveStartEnd" minTickGap={24} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} allowDecimals={false} />
              <Tooltip content={<Tip />} />
              <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
              <Area type="monotone" dataKey="in" name="IN" stroke={seriesColor(1)}
                    strokeWidth={2} fill="url(#gIn)" />
              <Area type="monotone" dataKey="out" name="OUT" stroke={seriesColor(0)}
                    strokeWidth={2} fill="url(#gOut)" />
            </AreaChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Net movement per day</CardTitle>
          <CardDescription>
            Above the line stock grew that day; below it, stock drained.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={chart} margin={{ left: -12, right: 12 }}>
              <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
              <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={11}
                     interval="preserveStartEnd" minTickGap={24} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} allowDecimals={false} />
              <Tooltip content={<Tip />} />
              <ReferenceLine y={0} stroke="hsl(var(--muted-foreground))" />
              <Bar dataKey="net" name="Net" radius={[3, 3, 0, 0]}>
                {chart.map((d, i) => (
                  <Cell key={i} fill={d.net >= 0 ? seriesColor(1) : seriesColor(5)} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </CardContent>
      </Card>

      <Tabs defaultValue="products">
        <TabsList>
          <TabsTrigger value="products">By product</TabsTrigger>
          <TabsTrigger value="categories">By category</TabsTrigger>
          <TabsTrigger value="staff">By staff</TabsTrigger>
          <TabsTrigger value="hours">By hour</TabsTrigger>
        </TabsList>

        <TabsContent value="products">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Product</TableHead>
                    <TableHead className="text-right">In</TableHead>
                    <TableHead className="text-right">Out</TableHead>
                    <TableHead className="text-right">Net</TableHead>
                    <TableHead className="hidden text-right sm:table-cell">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.by_product.map((p) => (
                    <TableRow key={p.productno}>
                      <TableCell>
                        <Link
                          to={`/inventory/${encodeURIComponent(p.productno)}`}
                          className="font-medium hover:underline"
                        >
                          {p.name}
                        </Link>
                        <span className="tnum ml-2 text-xs text-muted-foreground">
                          {p.productno}
                        </span>
                      </TableCell>
                      <TableCell className="tnum text-right text-[hsl(var(--success))]">{p.ins}</TableCell>
                      <TableCell className="tnum text-right text-[hsl(var(--info))]">{p.outs}</TableCell>
                      <TableCell className={cn("tnum text-right font-semibold",
                                               p.ins - p.outs < 0 && "text-[hsl(var(--warning))]")}>
                        {p.ins - p.outs > 0 ? "+" : ""}{p.ins - p.outs}
                      </TableCell>
                      <TableCell className="tnum hidden text-right text-muted-foreground sm:table-cell">
                        {p.ins + p.outs}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!report.by_product.length && (
                    <TableEmpty colSpan={5}>No movement in this period.</TableEmpty>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="categories">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">In</TableHead>
                    <TableHead className="text-right">Out</TableHead>
                    <TableHead className="text-right">Net</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.by_category.map((c) => (
                    <TableRow key={c.category}>
                      <TableCell>
                        <Badge variant={c.category === "Uncategorised" ? "warning" : "outline"}>
                          {c.category}
                        </Badge>
                      </TableCell>
                      <TableCell className="tnum text-right">{c.ins}</TableCell>
                      <TableCell className="tnum text-right">{c.outs}</TableCell>
                      <TableCell className="tnum text-right font-semibold">
                        {c.ins - c.outs > 0 ? "+" : ""}{c.ins - c.outs}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!report.by_category.length && (
                    <TableEmpty colSpan={4}>No movement in this period.</TableEmpty>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="staff">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <Users className="h-4 w-4" />
                Activity per staff member
              </CardTitle>
              <CardDescription>
                Movements logged before sign-in existed appear as "not recorded".
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Staff</TableHead>
                    <TableHead className="text-right">In</TableHead>
                    <TableHead className="text-right">Out</TableHead>
                    <TableHead className="text-right">Anomalies</TableHead>
                    <TableHead className="text-right">Total</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {report.by_staff.map((s) => (
                    <TableRow key={s.staff}>
                      <TableCell className="font-medium">
                        {s.staff === "not recorded" ? (
                          <span className="text-muted-foreground">not recorded</span>
                        ) : s.staff}
                      </TableCell>
                      <TableCell className="tnum text-right">{s.ins}</TableCell>
                      <TableCell className="tnum text-right">{s.outs}</TableCell>
                      <TableCell className={cn("tnum text-right",
                                               s.anomalies > 0 && "text-[hsl(var(--warning))]")}>
                        {s.anomalies}
                      </TableCell>
                      <TableCell className="tnum text-right font-semibold">{s.total}</TableCell>
                    </TableRow>
                  ))}
                  {!report.by_staff.length && (
                    <TableEmpty colSpan={5}>No activity in this period.</TableEmpty>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="hours">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">When scanning happens</CardTitle>
              <CardDescription>
                Movements by hour of day (UTC). Useful for staffing the busy stretches.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={report.by_hour} margin={{ left: -12, right: 12 }}>
                  <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                  <XAxis dataKey="hour" stroke="hsl(var(--muted-foreground))" fontSize={11}
                         tickFormatter={(h) => String(h).padStart(2, "0")} interval={1} />
                  <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} allowDecimals={false} />
                  <Tooltip content={<Tip />} />
                  <Bar dataKey="total" name="Movements" fill={seriesColor(0)} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
