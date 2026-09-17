import * as React from "react";
import { useNavigate, useParams, Link } from "react-router-dom";
import {
  ArrowLeft, Boxes, Loader2, Pencil, Trash2, Plus, TrendingUp, ShoppingCart,
  QrCode, Users, AlertTriangle, History, Save, X, Link2,
} from "lucide-react";
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Stat, Progress, Separator } from "@/components/ui/misc";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow, TableEmpty,
} from "@/components/ui/table";
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter,
} from "@/components/ui/dialog";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";
import { actionTone, cn, formatTime, percent, seriesColor, timeAgo } from "@/lib/utils";

export default function ProductDetail() {
  const { productno } = useParams();
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useAuth();

  const [data, setData] = React.useState(null);
  const [categories, setCategories] = React.useState([]);
  const [editing, setEditing] = React.useState(false);
  const [addBatch, setAddBatch] = React.useState(false);
  const [linking, setLinking] = React.useState(false);
  const [confirmDelete, setConfirmDelete] = React.useState(false);

  const load = React.useCallback(async () => {
    const res = await api.product(productno);
    setData(res.product);
    setCategories(res.categories || []);
  }, [productno]);

  React.useEffect(() => {
    load().catch((e) => {
      toast.error(e.message);
      if (e.status === 404) navigate("/inventory");
    });
  }, [load, toast, navigate]);

  const act = async (fn) => {
    try {
      const res = await fn();
      toast.success(res.message);
      await load();
      return true;
    } catch (err) {
      toast.error(err.message);
      return false;
    }
  };

  if (!data) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const movement = data.movement.map((m) => ({
    day: m.day.slice(5),
    IN: m.ins,
    OUT: m.outs,
  }));
  const forecastData = data.forecast || {};

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <Button variant="ghost" size="sm" className="-ml-2 mb-1" asChild>
            <Link to="/inventory">
              <ArrowLeft className="h-4 w-4" />
              Inventory
            </Link>
          </Button>
          <h2 className="truncate text-xl font-semibold">{data.name}</h2>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            <Badge variant="muted" className="tnum">{data.productno}</Badge>
            <Badge variant={data.category === "Uncategorised" ? "warning" : "outline"}>
              {data.category}
            </Badge>
            {data.low && (
              <Badge variant="warning">
                <AlertTriangle className="h-3 w-3" />
                below reorder level
              </Badge>
            )}
          </div>
        </div>
        <div className="flex gap-2">
          {can("catalog.manage") && (
            <>
              <Button variant="outline" size="sm" onClick={() => setEditing(true)}>
                <Pencil className="h-4 w-4" />
                Edit
              </Button>
              <Button variant="outline" size="sm" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="h-4 w-4 text-destructive" />
                Delete
              </Button>
            </>
          )}
        </div>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={Boxes} label="On hand" value={data.qty}
              tone={data.low ? "warning" : "default"}
              hint={`${data.batches.length} batch${data.batches.length === 1 ? "" : "es"}`} />
        <Stat icon={History} label="Movements" value={data.totals.in + data.totals.out}
              hint={`${data.totals.in} in / ${data.totals.out} out`} />
        <Stat
          icon={TrendingUp}
          label="Days of cover"
          value={forecastData.days_to_stockout ?? "—"}
          tone={forecastData.days_to_stockout != null && forecastData.days_to_stockout < 3
                ? "warning" : "default"}
          hint={forecastData.avg_daily_out
                ? `${forecastData.avg_daily_out}/day` : "no demand history"}
        />
        <Stat icon={AlertTriangle} label="Anomalies" value={data.totals.anomalies}
              tone={data.totals.anomalies ? "warning" : "default"} />
      </div>

      {/* What the planning agents make of it */}
      {/* A Decision carries its reasoning as `rationale`, not `notes` -- reading
          the wrong key here silently hid this whole card. */}
      {(data.procurement || forecastData.rationale?.length > 0) && (
        <Card className={cn(data.procurement?.priority === "urgent" &&
                            "border-[hsl(var(--warning))]/30")}>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-base">
              <ShoppingCart className="h-4 w-4" />
              What the agents say
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {data.procurement && (
              <div className="rounded-lg border p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge variant={data.procurement.priority === "urgent" ? "destructive"
                                  : data.procurement.priority === "soon" ? "warning" : "muted"}>
                    {data.procurement.priority}
                  </Badge>
                  <span className="text-sm font-medium">
                    Order {data.procurement.order_qty} units
                  </span>
                  <span className="tnum text-xs text-muted-foreground">
                    reorder point {data.procurement.reorder_point} · safety stock{" "}
                    {data.procurement.safety_stock}
                  </span>
                </div>
                <p className="mt-1.5 text-sm text-muted-foreground">
                  {data.procurement.reason}
                </p>
              </div>
            )}
            {forecastData.rationale?.length > 0 && (
              <ul className="space-y-1">
                {forecastData.rationale.map((n, i) => (
                  <li key={i} className="text-sm text-muted-foreground">{n}</li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      )}

      <Tabs defaultValue="batches">
        <TabsList>
          <TabsTrigger value="batches">Batches</TabsTrigger>
          <TabsTrigger value="movement">Movement</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
          <TabsTrigger value="codes">Codes</TabsTrigger>
        </TabsList>

        {/* ---- Batches (CRUD) ---- */}
        <TabsContent value="batches" className="space-y-3">
          <div className="flex justify-end">
            {can("inventory.adjust") && (
              <Button size="sm" onClick={() => setAddBatch(true)}>
                <Plus className="h-4 w-4" />
                New batch
              </Button>
            )}
          </div>
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Batch</TableHead>
                    <TableHead className="text-right">Quantity</TableHead>
                    <TableHead className="hidden sm:table-cell">First in</TableHead>
                    <TableHead className="hidden md:table-cell">Last out</TableHead>
                    {can("inventory.adjust") && <TableHead className="w-28" />}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.batches.map((b) => (
                    <BatchRow
                      key={b.batchno || "-none-"}
                      batch={b}
                      productno={data.productno}
                      editable={can("inventory.adjust")}
                      onSave={(qty) => act(() => api.adjust(data.productno, b.batchno, qty))}
                      onDelete={() =>
                        act(() => api.deleteBatch(data.productno, b.batchno || "-"))
                      }
                    />
                  ))}
                  {!data.batches.length && <TableEmpty colSpan={5}>No batches.</TableEmpty>}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---- Movement chart ---- */}
        <TabsContent value="movement">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Movement over time</CardTitle>
              <CardDescription>
                Scans in and out per day for this product. Reversed scans excluded.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {movement.length ? (
                <ResponsiveContainer width="100%" height={280}>
                  <LineChart data={movement} margin={{ left: -12, right: 12 }}>
                    <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
                    <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" fontSize={11} />
                    <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        background: "hsl(var(--popover))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 8, fontSize: 12,
                      }}
                    />
                    <Legend iconType="plainline" wrapperStyle={{ fontSize: 12 }} />
                    <Line type="monotone" dataKey="IN" stroke={seriesColor(1)} strokeWidth={2} />
                    <Line type="monotone" dataKey="OUT" stroke={seriesColor(0)} strokeWidth={2} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <p className="py-12 text-center text-sm text-muted-foreground">
                  No movement recorded yet.
                </p>
              )}
            </CardContent>
          </Card>

          {data.handlers.length > 0 && (
            <Card className="mt-4">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Users className="h-4 w-4" />
                  Who handles this product
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {data.handlers.map((h) => (
                  <div key={h.username} className="flex items-center gap-3">
                    <span className="w-32 shrink-0 truncate text-sm">{h.username}</span>
                    <Progress
                      value={(h.moves / data.handlers[0].moves) * 100}
                      className="flex-1"
                    />
                    <span className="tnum w-12 shrink-0 text-right text-xs text-muted-foreground">
                      {h.moves}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        {/* ---- Full history ---- */}
        <TabsContent value="history">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Action</TableHead>
                    <TableHead className="hidden sm:table-cell">Batch</TableHead>
                    <TableHead>Staff</TableHead>
                    <TableHead className="text-right">When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.history.map((h, i) => (
                    <TableRow key={i} className={cn(h.undone && "opacity-50")}>
                      <TableCell>
                        <span className={cn(
                          "inline-flex rounded-md border px-1.5 py-0.5 text-xs font-medium",
                          actionTone(h.action))}
                        >
                          {h.action}
                        </span>
                        {h.anomaly ? (
                          <AlertTriangle className="ml-1.5 inline h-3.5 w-3.5 text-[hsl(var(--warning))]" />
                        ) : null}
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground sm:table-cell">
                        {h.batchno || "—"}
                      </TableCell>
                      <TableCell>{h.username || <span className="text-xs text-muted-foreground">not recorded</span>}</TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {formatTime(h.ts)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!data.history.length && <TableEmpty colSpan={4}>No history.</TableEmpty>}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
          <p className="mt-2 text-xs text-muted-foreground">
            First seen {data.first_seen ? formatTime(data.first_seen) : "—"} ·
            last activity {data.last_seen ? timeAgo(data.last_seen) : "—"}
          </p>
        </TabsContent>

        {/* ---- Codes ---- */}
        <TabsContent value="codes">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2 text-base">
                <QrCode className="h-4 w-4" />
                Codes that reach this product
              </CardTitle>
              <CardDescription>
                Scanning any of these lands on this record. A QR payload and a printed
                barcode usually differ by a check digit; both resolve here, in either
                direction.
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {/* Both symbologies for the same product, side by side. Scanning
                  either lands on this record — that is the claim, made visible. */}
              <div className="flex flex-wrap items-center gap-4 rounded-lg border bg-muted/30 p-4">
                <img
                  src={`/api/products/${encodeURIComponent(data.productno)}/qr.svg?module=3`}
                  alt={`QR code for ${data.name}`}
                  className="h-28 w-28 rounded bg-white p-1"
                />
                <img
                  src={`/api/products/${encodeURIComponent(data.productno)}/barcode.svg`}
                  alt={`Barcode for ${data.productno}`}
                  className="h-20 rounded bg-white p-1"
                  onError={(e) => { e.currentTarget.style.display = "none"; }}
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium">Printable label</p>
                  <p className="mb-2 text-xs text-muted-foreground">
                    The QR carries <code>name,batch,productno</code>; the barcode carries the
                    product number. Either one resolves here.
                  </p>
                  <Button variant="outline" size="sm" asChild>
                    <a
                      href={`/api/products/${encodeURIComponent(data.productno)}/label`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <QrCode className="h-4 w-4" />
                      Open printable label
                    </a>
                  </Button>
                </div>
              </div>

              <div>
                <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                  Automatic variants
                </Label>
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {data.codes.map((c) => (
                    <Badge key={c} variant={c === data.productno ? "default" : "muted"} className="tnum">
                      {c}
                      {c === data.productno && " (primary)"}
                    </Badge>
                  ))}
                </div>
              </div>
              <div>
                <div className="flex items-center justify-between">
                  <Label className="text-xs uppercase tracking-wide text-muted-foreground">
                    Linked by hand
                  </Label>
                  {can("catalog.manage") && (
                    <Button variant="outline" size="sm" onClick={() => setLinking(true)}>
                      <Link2 className="h-4 w-4" />
                      Link a code
                    </Button>
                  )}
                </div>
                {data.linked_codes.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {data.linked_codes.map((c) => (
                      <span key={c} className="inline-flex items-center gap-1">
                        <Badge variant="info" className="tnum">{c}</Badge>
                        {can("catalog.manage") && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-6 w-6"
                            title="Remove this link"
                            onClick={() => act(() => api.unlink(c))}
                          >
                            <X className="h-3 w-3" />
                          </Button>
                        )}
                      </span>
                    ))}
                  </div>
                ) : (
                  <p className="mt-1.5 text-xs text-muted-foreground">
                    None yet. Link a supplier's own label here when its number is
                    genuinely different, rather than a check-digit variant of this one.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      {/* ---- Edit ---- */}
      <EditProductDialog
        open={editing}
        onOpenChange={setEditing}
        product={data}
        categories={categories}
        onSave={async (payload) => {
          const ok = await act(() => api.updateProduct(data.productno, payload));
          if (ok) setEditing(false);
        }}
      />

      {/* ---- Link a code ---- */}
      <LinkCodeDialog
        open={linking}
        onOpenChange={setLinking}
        product={data}
        onSave={async (code) => {
          const ok = await act(() => api.link(code, data.productno));
          if (ok) setLinking(false);
        }}
      />

      {/* ---- New batch ---- */}
      <NewBatchDialog
        open={addBatch}
        onOpenChange={setAddBatch}
        onSave={async (batchno, qty) => {
          const ok = await act(() => api.createBatch(data.productno, batchno, qty));
          if (ok) setAddBatch(false);
        }}
      />

      {/* ---- Delete ---- */}
      <Dialog open={confirmDelete} onOpenChange={setConfirmDelete}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {data.name}?</DialogTitle>
            <DialogDescription>
              This removes the stock record and its code links. The audit trail keeps every
              movement — a log that forgets what happened is not an audit trail.
            </DialogDescription>
          </DialogHeader>
          {data.qty > 0 && (
            <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/10 p-3 text-sm">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--warning))]" />
              <span className="text-muted-foreground">
                This product still has <b>{data.qty}</b> unit(s) on hand. Set the batches to
                zero first unless you really mean to discard the count.
              </span>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button
              variant="destructive"
              onClick={async () => {
                try {
                  const res = await api.deleteProduct(data.productno, data.qty > 0);
                  toast.success(res.message);
                  navigate("/inventory");
                } catch (err) {
                  toast.error(err.message);
                }
              }}
            >
              <Trash2 className="h-4 w-4" />
              {data.qty > 0 ? "Delete anyway" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function BatchRow({ batch, editable, onSave, onDelete }) {
  const [qty, setQty] = React.useState(batch.qty);
  const [editing, setEditing] = React.useState(false);
  React.useEffect(() => setQty(batch.qty), [batch.qty]);

  return (
    <TableRow>
      <TableCell className="font-medium">{batch.batchno || "no batch"}</TableCell>
      <TableCell className="text-right">
        {editing ? (
          <Input
            type="number"
            min={0}
            className="ml-auto w-24"
            value={qty}
            autoFocus
            onChange={(e) => setQty(Number(e.target.value))}
          />
        ) : (
          <span className="tnum font-semibold">{batch.qty}</span>
        )}
      </TableCell>
      <TableCell className="hidden text-xs text-muted-foreground sm:table-cell">
        {batch.scanned_in_at ? formatTime(batch.scanned_in_at) : "—"}
      </TableCell>
      <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
        {batch.scanned_out_at ? formatTime(batch.scanned_out_at) : "—"}
      </TableCell>
      {editable && (
        <TableCell>
          <div className="flex gap-1">
            {editing ? (
              <>
                <Button size="icon" variant="ghost" onClick={() => { onSave(qty); setEditing(false); }}>
                  <Save className="h-4 w-4" />
                </Button>
                <Button size="icon" variant="ghost" onClick={() => { setQty(batch.qty); setEditing(false); }}>
                  <X className="h-4 w-4" />
                </Button>
              </>
            ) : (
              <>
                <Button size="icon" variant="ghost" onClick={() => setEditing(true)} title="Correct the count">
                  <Pencil className="h-4 w-4" />
                </Button>
                <Button size="icon" variant="ghost" onClick={onDelete} title="Remove batch">
                  <Trash2 className="h-4 w-4 text-destructive" />
                </Button>
              </>
            )}
          </div>
        </TableCell>
      )}
    </TableRow>
  );
}

function EditProductDialog({ open, onOpenChange, product, categories, onSave }) {
  const [form, setForm] = React.useState({});
  React.useEffect(() => {
    if (open && product) {
      setForm({ name: product.name, category: product.category, min_qty: product.min_qty });
    }
  }, [open, product]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit product</DialogTitle>
          <DialogDescription>
            Renaming updates every batch. Filing it under a category also teaches the
            classifier.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="p-name">Name</Label>
            <Input id="p-name" value={form.name || ""}
                   onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))} />
          </div>
          <div className="space-y-1.5">
            <Label>Category</Label>
            <Select value={form.category}
                    onValueChange={(v) => setForm((f) => ({ ...f, category: v }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {categories.map((c) => (
                  <SelectItem key={c.name} value={c.name}>{c.name}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="p-min">Reorder level</Label>
            <Input id="p-min" type="number" min={0} value={form.min_qty ?? 0}
                   onChange={(e) => setForm((f) => ({ ...f, min_qty: Number(e.target.value) }))} />
            <p className="text-xs text-muted-foreground">
              0 turns the alert off. The Procurement Agent treats this as a floor.
            </p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => onSave(form)}>Save</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function LinkCodeDialog({ open, onOpenChange, product, onSave }) {
  const [code, setCode] = React.useState("");
  React.useEffect(() => {
    if (open) setCode("");
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Link a code to {product?.name}</DialogTitle>
          <DialogDescription>
            For a code that means this product but is not a variant of its number — a
            supplier's own label, for instance. Check-digit and UPC/EAN variants are
            already matched automatically and do not need linking.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="link-code">Scanned code</Label>
          <Input
            id="link-code"
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="The code the scanner reads"
          />
          <p className="text-xs text-muted-foreground">
            Any stock this code accumulated while it was unrecognised is folded into this
            product, so nothing is stranded under "Unknown Item".
          </p>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            disabled={!code.trim() || code.trim() === product?.productno}
            onClick={() => onSave(code.trim())}
          >
            Link it
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function NewBatchDialog({ open, onOpenChange, onSave }) {
  const [batchno, setBatchno] = React.useState("");
  const [qty, setQty] = React.useState(0);
  React.useEffect(() => {
    if (open) { setBatchno(""); setQty(0); }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New batch</DialogTitle>
          <DialogDescription>
            The opening quantity is recorded as an ADJUST, never as a scan.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="b-no">Batch number</Label>
            <Input id="b-no" value={batchno} autoFocus
                   onChange={(e) => setBatchno(e.target.value)} placeholder="e.g. BATCH-07" />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="b-qty">Opening quantity</Label>
            <Input id="b-qty" type="number" min={0} value={qty}
                   onChange={(e) => setQty(Number(e.target.value))} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => onSave(batchno, qty)}>Create batch</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
