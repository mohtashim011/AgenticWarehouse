import * as React from "react";
import { Link } from "react-router-dom";
import {
  Boxes, Download, Search, Pencil, Tag, Link2, Loader2, Plus, Trash2, AlertTriangle, Eye,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
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
import { cn } from "@/lib/utils";

export default function Inventory() {
  const toast = useToast();
  const { can } = useAuth();
  const [state, setState] = React.useState(null);
  const [categories, setCategories] = React.useState({ categories: [], uncategorised: [] });
  const [codes, setCodes] = React.useState(null);
  const [query, setQuery] = React.useState("");
  const [loading, setLoading] = React.useState(true);
  const [editing, setEditing] = React.useState(null);
  const [creating, setCreating] = React.useState(false);
  const [renaming, setRenaming] = React.useState(null);
  const [newCategory, setNewCategory] = React.useState("");

  const load = React.useCallback(async () => {
    const [s, c] = await Promise.all([api.state(), api.categories()]);
    setState(s);
    setCategories(c);
    setLoading(false);
  }, []);

  React.useEffect(() => {
    load().catch((e) => {
      toast.error(e.message);
      setLoading(false);
    });
  }, [load, toast]);

  const rows = (state?.inventory?.rows || []).filter((r) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      r.name.toLowerCase().includes(q) ||
      (r.category || "").toLowerCase().includes(q) ||
      (r.batches || []).some((b) => String(b.productno).includes(q))
    );
  });

  const act = async (fn, successMessage) => {
    try {
      const res = await fn();
      toast.success(successMessage || res.message);
      await load();
    } catch (err) {
      toast.error(err.message);
    }
  };

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Tabs defaultValue="stock">
        <TabsList>
          <TabsTrigger value="stock">Stock</TabsTrigger>
          <TabsTrigger value="categories">Categories</TabsTrigger>
          <TabsTrigger value="codes" onClick={() => !codes && api.codes().then(setCodes).catch(() => {})}>
            Code registry
          </TabsTrigger>
        </TabsList>

        {/* ---------------- Stock ---------------- */}
        <TabsContent value="stock" className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative min-w-[220px] flex-1">
              <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Search product, category or product number"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <Button variant="outline" asChild>
              <a href="/api/export/inventory.csv">
                <Download className="h-4 w-4" />
                CSV
              </a>
            </Button>
            {can("catalog.manage") && (
              <Button onClick={() => setCreating(true)}>
                <Plus className="h-4 w-4" />
                New product
              </Button>
            )}
          </div>

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Product</TableHead>
                    <TableHead>Category</TableHead>
                    <TableHead>Batches</TableHead>
                    <TableHead className="text-right">Qty</TableHead>
                    <TableHead className="text-right">Reorder at</TableHead>
                    <TableHead className="w-24" />
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {rows.map((r) => (
                    <TableRow key={`${r.name}-${r.category}`} className={cn(r.low && "bg-[hsl(var(--warning))]/5")}>
                      <TableCell className="font-medium">
                        {/* The product number is the identity, so the link uses it
                            rather than the name, which can change. */}
                        <Link
                          to={`/inventory/${encodeURIComponent((r.batches[0] || {}).productno || "")}`}
                          className="hover:underline"
                        >
                          {r.name}
                        </Link>
                        {r.name === "Unknown Item" && (
                          <Badge variant="warning" className="ml-2">unnamed</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {r.category === "Uncategorised" ? (
                          <Badge variant="muted">Uncategorised</Badge>
                        ) : (
                          <Badge variant="outline">{r.category}</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {(r.batches || []).map((b) => (
                            <Badge key={`${b.productno}-${b.batchno}`} variant="muted" className="tnum">
                              {b.batchno || "no batch"}: {b.qty}
                            </Badge>
                          ))}
                        </div>
                      </TableCell>
                      <TableCell className="tnum text-right font-semibold">
                        {r.qty}
                        {r.low && (
                          <AlertTriangle className="ml-1 inline h-3.5 w-3.5 text-[hsl(var(--warning))]" />
                        )}
                      </TableCell>
                      <TableCell className="tnum text-right text-muted-foreground">
                        {r.min_qty || "-"}
                      </TableCell>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="icon" asChild title="Open details">
                            <Link to={`/inventory/${encodeURIComponent((r.batches[0] || {}).productno || "")}`}>
                              <Eye className="h-4 w-4" />
                            </Link>
                          </Button>
                          {can("inventory.adjust") && (
                            <Button variant="ghost" size="icon" title="Quick edit"
                                    onClick={() => setEditing(r)}>
                              <Pencil className="h-4 w-4" />
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!rows.length && (
                    <TableEmpty colSpan={6}>
                      {query ? "Nothing matches that search." : "No stock yet — scan an item in."}
                    </TableEmpty>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------------- Categories ---------------- */}
        <TabsContent value="categories" className="space-y-4">
          {can("categories.manage") && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">Add a category</CardTitle>
                <CardDescription>
                  You own this list. Anything you assign always overrides the classifier.
                </CardDescription>
              </CardHeader>
              <CardContent className="flex gap-2">
                <Input
                  placeholder="New category name"
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && newCategory.trim()) {
                      act(() => api.addCategory(newCategory.trim()));
                      setNewCategory("");
                    }
                  }}
                />
                <Button
                  onClick={() => {
                    if (!newCategory.trim()) return;
                    act(() => api.addCategory(newCategory.trim()));
                    setNewCategory("");
                  }}
                >
                  <Plus className="h-4 w-4" />
                  Add
                </Button>
              </CardContent>
            </Card>
          )}

          {categories.uncategorised?.length > 0 && (
            <Card className="border-[hsl(var(--warning))]/30">
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Tag className="h-4 w-4" />
                  Waiting for a category
                </CardTitle>
                <CardDescription>
                  These are in stock but unfiled. Each one you assign becomes training data.
                </CardDescription>
              </CardHeader>
              <CardContent className="space-y-2">
                {categories.uncategorised.map((p) => (
                  <UncategorisedRow
                    key={p.name}
                    product={p}
                    categories={categories.categories}
                    onAssign={(cat) => act(() => api.assignCategory(p.name, cat))}
                  />
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Category</TableHead>
                    <TableHead className="text-right">Products</TableHead>
                    <TableHead className="text-right">Units</TableHead>
                    {can("categories.manage") && <TableHead className="w-24" />}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {categories.categories.map((c) => (
                    <TableRow key={c.name}>
                      <TableCell className="font-medium">{c.name}</TableCell>
                      <TableCell className="tnum text-right">{c.products}</TableCell>
                      <TableCell className="tnum text-right">{c.units}</TableCell>
                      {can("categories.manage") && (
                        <TableCell>
                          {c.name === "Uncategorised" ? (
                            <span className="text-xs text-muted-foreground">built-in</span>
                          ) : (
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                title="Rename"
                                onClick={() => setRenaming(c)}
                              >
                                <Pencil className="h-4 w-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                title="Delete"
                                onClick={() => {
                                  if (
                                    window.confirm(
                                      `Delete "${c.name}"? Its products move to Uncategorised.`
                                    )
                                  ) {
                                    act(() => api.deleteCategory(c.name));
                                  }
                                }}
                              >
                                <Trash2 className="h-4 w-4 text-destructive" />
                              </Button>
                            </div>
                          )}
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------------- Code registry ---------------- */}
        <TabsContent value="codes" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                <Link2 className="mr-2 inline h-4 w-4" />
                Every code that reaches each product
              </CardTitle>
              <CardDescription>
                A QR payload and a printed barcode usually differ by a check digit. Both
                resolve to the same stock record, in both directions — that is what stops one
                product becoming two.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Product</TableHead>
                    <TableHead>Product no.</TableHead>
                    <TableHead>Also recognised as</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {Object.entries(codes?.products || {}).map(([pn, info]) => (
                    <TableRow key={pn}>
                      <TableCell className="font-medium">{info.name}</TableCell>
                      <TableCell className="tnum">{pn}</TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {info.codes
                            .filter((c) => c !== pn)
                            .map((c) => (
                              <Badge key={c} variant="muted" className="tnum">{c}</Badge>
                            ))}
                          {info.linked.map((c) => (
                            <Badge key={c} variant="info" className="tnum">
                              {c} (linked)
                            </Badge>
                          ))}
                          {info.codes.length <= 1 && !info.linked.length && (
                            <span className="text-xs text-muted-foreground">—</span>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                  {!codes && <TableEmpty colSpan={3}>Loading…</TableEmpty>}
                  {codes && !Object.keys(codes.products || {}).length && (
                    <TableEmpty colSpan={3}>No products recorded yet.</TableEmpty>
                  )}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <NewProductDialog
        open={creating}
        onOpenChange={setCreating}
        categories={categories.categories}
        onSave={async (payload) => {
          try {
            const res = await api.createProduct(payload);
            toast.success(res.message);
            setCreating(false);
            await load();
          } catch (err) {
            toast.error(err.message);
          }
        }}
      />

      <RenameCategoryDialog
        category={renaming}
        onOpenChange={() => setRenaming(null)}
        onSave={async (next) => {
          const ok = await act(() => api.renameCategory(renaming.name, next));
          if (ok !== false) setRenaming(null);
        }}
      />

      <EditProductDialog
        product={editing}
        onOpenChange={() => setEditing(null)}
        onSave={async (payload) => {
          for (const b of payload.batches) {
            if (b.changed) await api.adjust(b.productno, b.batchno, b.qty);
          }
          if (payload.minChanged) await api.setReorder(payload.name, payload.min_qty);
          toast.success("Saved.");
          setEditing(null);
          await load();
        }}
      />
    </div>
  );
}

function NewProductDialog({ open, onOpenChange, categories, onSave }) {
  const blank = { name: "", productno: "", batchno: "", qty: 0,
                  category: "Uncategorised", min_qty: 0 };
  const [form, setForm] = React.useState(blank);
  const [busy, setBusy] = React.useState(false);
  React.useEffect(() => {
    if (open) setForm(blank);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const set = (k) => (e) =>
    setForm((f) => ({
      ...f,
      [k]: e.target.type === "number" ? Number(e.target.value) : e.target.value,
    }));

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>New product</DialogTitle>
          <DialogDescription>
            For stock that arrives before its labels do. The opening quantity is recorded as
            an ADJUST, so the trail never claims it was scanned.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await onSave(form);
            } finally {
              setBusy(false);
            }
          }}
          className="space-y-3"
        >
          <div className="space-y-1.5">
            <Label htmlFor="np-name">Product name</Label>
            <Input id="np-name" value={form.name} onChange={set("name")} required autoFocus />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="np-pn">Product number</Label>
              <Input id="np-pn" value={form.productno} onChange={set("productno")} required
                     placeholder="e.g. 900010 or an EAN" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="np-batch">Batch (optional)</Label>
              <Input id="np-batch" value={form.batchno} onChange={set("batchno")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="np-qty">Opening quantity</Label>
              <Input id="np-qty" type="number" min={0} value={form.qty} onChange={set("qty")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="np-min">Reorder level</Label>
              <Input id="np-min" type="number" min={0} value={form.min_qty} onChange={set("min_qty")} />
            </div>
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
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating..." : "Create product"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RenameCategoryDialog({ category, onOpenChange, onSave }) {
  const [name, setName] = React.useState("");
  React.useEffect(() => setName(category?.name || ""), [category]);
  if (!category) return null;
  return (
    <Dialog open={Boolean(category)} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Rename "{category.name}"</DialogTitle>
          <DialogDescription>
            The new name is applied everywhere it is referenced — the catalogue and every
            item already in stock — so nothing is orphaned.
          </DialogDescription>
        </DialogHeader>
        <Input autoFocus value={name} onChange={(e) => setName(e.target.value)} />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!name.trim() || name === category.name} onClick={() => onSave(name.trim())}>
            Rename
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function UncategorisedRow({ product, categories, onAssign }) {
  const [value, setValue] = React.useState("");
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border p-2.5">
      <span className="min-w-0 flex-1 truncate text-sm font-medium">{product.name}</span>
      <Badge variant="muted" className="tnum">{product.qty} units</Badge>
      <Select value={value} onValueChange={setValue}>
        <SelectTrigger className="w-44">
          <SelectValue placeholder="Choose category" />
        </SelectTrigger>
        <SelectContent>
          {categories
            .filter((c) => c.name !== "Uncategorised")
            .map((c) => (
              <SelectItem key={c.name} value={c.name}>{c.name}</SelectItem>
            ))}
        </SelectContent>
      </Select>
      <Button size="sm" disabled={!value} onClick={() => onAssign(value)}>
        Assign
      </Button>
    </div>
  );
}

function EditProductDialog({ product, onOpenChange, onSave }) {
  const [batches, setBatches] = React.useState([]);
  const [minQty, setMinQty] = React.useState(0);
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    if (!product) return;
    setBatches((product.batches || []).map((b) => ({ ...b, original: b.qty, changed: false })));
    setMinQty(product.min_qty || 0);
  }, [product]);

  if (!product) return null;

  return (
    <Dialog open={Boolean(product)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{product.name}</DialogTitle>
          <DialogDescription>
            Correct a miscount, or set the level at which this product raises an alert.
            Every correction is logged as an ADJUST, never as a scan.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          <div>
            <Label className="text-xs uppercase tracking-wide text-muted-foreground">
              Quantity per batch
            </Label>
            <div className="mt-1.5 space-y-2">
              {batches.map((b, i) => (
                <div key={`${b.productno}-${b.batchno}`} className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate text-sm">
                    {b.batchno || "no batch"}
                    <span className="tnum ml-2 text-xs text-muted-foreground">{b.productno}</span>
                  </span>
                  <Input
                    type="number"
                    min={0}
                    className="w-24"
                    value={b.qty}
                    onChange={(e) => {
                      const qty = Number(e.target.value);
                      setBatches((prev) =>
                        prev.map((x, j) =>
                          j === i ? { ...x, qty, changed: qty !== x.original } : x
                        )
                      );
                    }}
                  />
                </div>
              ))}
            </div>
          </div>

          <div>
            <Label htmlFor="min-qty" className="text-xs uppercase tracking-wide text-muted-foreground">
              Reorder level
            </Label>
            <Input
              id="min-qty"
              type="number"
              min={0}
              className="mt-1.5"
              value={minQty}
              onChange={(e) => setMinQty(Number(e.target.value))}
            />
            <p className="mt-1 text-xs text-muted-foreground">
              0 turns the alert off. The Procurement Agent treats this as a floor and may
              propose a higher point if demand warrants it.
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onSave({
                  name: product.name,
                  batches,
                  min_qty: minQty,
                  minChanged: minQty !== (product.min_qty || 0),
                });
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "Saving..." : "Save changes"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
