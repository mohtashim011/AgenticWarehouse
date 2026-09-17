import * as React from "react";
import {
  Users, UserPlus, Shield, KeyRound, Unlock, Trash2, Loader2, Circle,
  MoreHorizontal, AlertTriangle,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Stat, Switch, Separator } from "@/components/ui/misc";
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
import { cn, formatTime, timeAgo } from "@/lib/utils";

export default function Staff() {
  const toast = useToast();
  const { can, user: me } = useAuth();
  const [data, setData] = React.useState(null);
  const [events, setEvents] = React.useState([]);
  const [createOpen, setCreateOpen] = React.useState(false);
  const [editing, setEditing] = React.useState(null);
  const [resetting, setResetting] = React.useState(null);

  const load = React.useCallback(async () => {
    const [s, e] = await Promise.all([
      api.staff(),
      api.staffEvents(60).catch(() => ({ events: [] })),
    ]);
    setData(s);
    setEvents(e.events || []);
  }, []);

  React.useEffect(() => {
    load().catch((err) => toast.error(err.message));
  }, [load, toast]);

  const act = async (fn) => {
    try {
      const res = await fn();
      toast.success(res.message);
      // The Staff Agent may accept an action while still flagging it as worth
      // knowing about. Those warnings are the interesting half.
      (res.decision?.warnings || []).forEach((w) => toast.warning(w));
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

  const { staff, summary, roles, sessions } = data;

  return (
    <div className="space-y-6">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat icon={Users} label="Staff" value={summary.total} hint={`${summary.active} active`} />
        <Stat icon={Circle} label="Online now" value={summary.online} tone="success" />
        <Stat icon={Shield} label="Administrators" value={summary.by_role.admin} />
        <Stat
          icon={AlertTriangle}
          label="Locked out"
          value={summary.locked}
          tone={summary.locked ? "warning" : "default"}
        />
      </div>

      <Tabs defaultValue="people">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <TabsList>
            <TabsTrigger value="people">People</TabsTrigger>
            <TabsTrigger value="sessions">Sessions</TabsTrigger>
            <TabsTrigger value="roles">Roles</TabsTrigger>
            <TabsTrigger value="events">Security log</TabsTrigger>
          </TabsList>
          {can("staff.create") && (
            <Button onClick={() => setCreateOpen(true)}>
              <UserPlus className="h-4 w-4" />
              Add staff member
            </Button>
          )}
        </div>

        <TabsContent value="people">
          <Card>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Name</TableHead>
                    <TableHead>Role</TableHead>
                    <TableHead className="hidden md:table-cell">Shift</TableHead>
                    <TableHead className="hidden lg:table-cell">Last seen</TableHead>
                    <TableHead>Status</TableHead>
                    {can("staff.update") && <TableHead className="w-32" />}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {staff.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>
                        <div className="font-medium">{s.full_name || s.username}</div>
                        <div className="text-xs text-muted-foreground">
                          @{s.username}
                          {s.id === me?.id && " (you)"}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant={s.role === "admin" ? "default" : "muted"}>
                          {s.role_label}
                        </Badge>
                      </TableCell>
                      <TableCell className="hidden text-muted-foreground md:table-cell">
                        {s.shift || "-"}
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground lg:table-cell">
                        {s.last_login_at ? timeAgo(s.last_login_at) : "never"}
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap gap-1">
                          {!s.active && <Badge variant="muted">disabled</Badge>}
                          {s.active && s.live_sessions > 0 && (
                            <Badge variant="success">online</Badge>
                          )}
                          {s.locked_until && new Date(s.locked_until) > new Date() && (
                            <Badge variant="destructive">locked</Badge>
                          )}
                          {s.must_change_pw && <Badge variant="warning">temp password</Badge>}
                        </div>
                      </TableCell>
                      {can("staff.update") && (
                        <TableCell>
                          <div className="flex gap-1">
                            <Button variant="ghost" size="icon" title="Edit" onClick={() => setEditing(s)}>
                              <MoreHorizontal className="h-4 w-4" />
                            </Button>
                            <Button variant="ghost" size="icon" title="Reset password" onClick={() => setResetting(s)}>
                              <KeyRound className="h-4 w-4" />
                            </Button>
                            {s.locked_until && new Date(s.locked_until) > new Date() && (
                              <Button
                                variant="ghost"
                                size="icon"
                                title="Unlock"
                                onClick={() => act(() => api.unlockStaff(s.id))}
                              >
                                <Unlock className="h-4 w-4" />
                              </Button>
                            )}
                          </div>
                        </TableCell>
                      )}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sessions">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Active sessions</CardTitle>
              <CardDescription>
                Signed in right now. Disabling an account ends its sessions immediately.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Who</TableHead>
                    <TableHead className="hidden sm:table-cell">Address</TableHead>
                    <TableHead>Last seen</TableHead>
                    <TableHead className="hidden md:table-cell">Expires</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sessions.map((s) => (
                    <TableRow key={s.id}>
                      <TableCell>
                        <div className="font-medium">{s.full_name || s.username}</div>
                        <div className="text-xs text-muted-foreground">@{s.username}</div>
                      </TableCell>
                      <TableCell className="tnum hidden text-muted-foreground sm:table-cell">
                        {s.ip || "-"}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {timeAgo(s.last_seen_at)}
                      </TableCell>
                      <TableCell className="hidden text-xs text-muted-foreground md:table-cell">
                        {formatTime(s.expires_at)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!sessions.length && <TableEmpty colSpan={4}>Nobody is signed in.</TableEmpty>}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="roles" className="space-y-3">
          {roles.map((r) => (
            <Card key={r.key}>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  {r.label}
                  <Badge variant="muted">{summary.by_role[r.key]} active</Badge>
                </CardTitle>
                <CardDescription>{r.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1">
                  {r.capabilities.map((c) => (
                    <Badge key={c} variant="outline" className="font-mono text-[11px]">
                      {c}
                    </Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
        </TabsContent>

        <TabsContent value="events">
          <Card>
            <CardHeader>
              <CardTitle className="text-base">Security log</CardTitle>
              <CardDescription>
                Sign-ins, failures, lockouts and account changes — kept apart from the stock
                trail so a security question can be answered without wading through scans.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Event</TableHead>
                    <TableHead>Account</TableHead>
                    <TableHead className="hidden md:table-cell">Detail</TableHead>
                    <TableHead className="text-right">When</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {events.map((e) => (
                    <TableRow key={e.id}>
                      <TableCell>
                        <Badge
                          variant={
                            e.event === "login_failed"
                              ? "destructive"
                              : e.event === "login"
                              ? "success"
                              : "muted"
                          }
                        >
                          {e.event.replace("_", " ")}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-medium">{e.username || "-"}</TableCell>
                      <TableCell className="hidden text-sm text-muted-foreground md:table-cell">
                        {e.detail}
                      </TableCell>
                      <TableCell className="text-right text-xs text-muted-foreground">
                        {formatTime(e.ts)}
                      </TableCell>
                    </TableRow>
                  ))}
                  {!events.length && <TableEmpty colSpan={4}>Nothing recorded yet.</TableEmpty>}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <StaffFormDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        roles={roles}
        onSubmit={async (payload) => {
          const ok = await act(() => api.createStaff(payload));
          if (ok) setCreateOpen(false);
        }}
      />

      <EditStaffDialog
        member={editing}
        roles={roles}
        isSelf={editing?.id === me?.id}
        onOpenChange={() => setEditing(null)}
        onSubmit={async (payload) => {
          const ok = await act(() => api.updateStaff(editing.id, payload));
          if (ok) setEditing(null);
        }}
        onDelete={async () => {
          if (!window.confirm(`Remove ${editing.username}? Their audit entries are kept.`)) return;
          const ok = await act(() => api.deleteStaff(editing.id));
          if (ok) setEditing(null);
        }}
        canDelete={can("staff.delete")}
      />

      <ResetPasswordDialog
        member={resetting}
        onOpenChange={() => setResetting(null)}
        onSubmit={async (password) => {
          const ok = await act(() => api.resetStaffPassword(resetting.id, password));
          if (ok) setResetting(null);
        }}
      />
    </div>
  );
}

function StaffFormDialog({ open, onOpenChange, roles, onSubmit }) {
  const [form, setForm] = React.useState({
    username: "", full_name: "", email: "", phone: "", shift: "",
    role: "staff", password: "", must_change_pw: true,
  });
  const [busy, setBusy] = React.useState(false);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  React.useEffect(() => {
    if (open) {
      setForm({
        username: "", full_name: "", email: "", phone: "", shift: "",
        role: "staff", password: "", must_change_pw: true,
      });
    }
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add a staff member</DialogTitle>
          <DialogDescription>
            They will sign in with this username and password. Every action they take is
            recorded against the account.
          </DialogDescription>
        </DialogHeader>
        <form
          onSubmit={async (e) => {
            e.preventDefault();
            setBusy(true);
            try {
              await onSubmit(form);
            } finally {
              setBusy(false);
            }
          }}
          className="space-y-3"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label htmlFor="s-username">Username</Label>
              <Input id="s-username" value={form.username} onChange={set("username")} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-name">Full name</Label>
              <Input id="s-name" value={form.full_name} onChange={set("full_name")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-email">Email</Label>
              <Input id="s-email" type="email" value={form.email} onChange={set("email")} />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="s-shift">Shift</Label>
              <Input id="s-shift" placeholder="Day / Night" value={form.shift} onChange={set("shift")} />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select value={form.role} onValueChange={(v) => setForm((f) => ({ ...f, role: v }))}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {roles.map((r) => (
                  <SelectItem key={r.key} value={r.key}>{r.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              {roles.find((r) => r.key === form.role)?.description}
            </p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="s-password">Temporary password</Label>
            <Input
              id="s-password"
              type="text"
              value={form.password}
              onChange={set("password")}
              placeholder="At least 8 characters with a digit or symbol"
              required
            />
          </div>
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Must change at first sign-in</p>
              <p className="text-xs text-muted-foreground">
                Leave this on. A password you chose for them cannot attribute their actions.
              </p>
            </div>
            <Switch
              checked={form.must_change_pw}
              onCheckedChange={(v) => setForm((f) => ({ ...f, must_change_pw: v }))}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy}>{busy ? "Creating..." : "Create account"}</Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function EditStaffDialog({ member, roles, onOpenChange, onSubmit, onDelete, canDelete, isSelf }) {
  const [form, setForm] = React.useState({});
  React.useEffect(() => {
    if (member) {
      setForm({
        full_name: member.full_name, email: member.email, phone: member.phone,
        shift: member.shift, role: member.role, active: member.active,
      });
    }
  }, [member]);
  if (!member) return null;

  return (
    <Dialog open={Boolean(member)} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{member.full_name || member.username}</DialogTitle>
          <DialogDescription>@{member.username}</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="space-y-1.5">
              <Label>Full name</Label>
              <Input
                value={form.full_name || ""}
                onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))}
              />
            </div>
            <div className="space-y-1.5">
              <Label>Shift</Label>
              <Input
                value={form.shift || ""}
                onChange={(e) => setForm((f) => ({ ...f, shift: e.target.value }))}
              />
            </div>
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select
              value={form.role}
              onValueChange={(v) => setForm((f) => ({ ...f, role: v }))}
              disabled={isSelf}
            >
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                {roles.map((r) => (
                  <SelectItem key={r.key} value={r.key}>{r.label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
            {isSelf && (
              <p className="text-xs text-muted-foreground">
                You cannot change your own role. Ask another administrator.
              </p>
            )}
          </div>
          <div className="flex items-center justify-between rounded-lg border p-3">
            <div>
              <p className="text-sm font-medium">Account active</p>
              <p className="text-xs text-muted-foreground">
                Turning this off ends their sessions immediately.
              </p>
            </div>
            <Switch
              checked={Boolean(form.active)}
              disabled={isSelf}
              onCheckedChange={(v) => setForm((f) => ({ ...f, active: v }))}
            />
          </div>
        </div>
        <DialogFooter className="sm:justify-between">
          {canDelete && !isSelf ? (
            <Button variant="destructive" onClick={onDelete}>
              <Trash2 className="h-4 w-4" />
              Remove
            </Button>
          ) : <span />}
          <div className="flex gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button onClick={() => onSubmit(form)}>Save</Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function ResetPasswordDialog({ member, onOpenChange, onSubmit }) {
  const [password, setPassword] = React.useState("");
  React.useEffect(() => setPassword(""), [member]);
  if (!member) return null;
  return (
    <Dialog open={Boolean(member)} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Reset password for {member.username}</DialogTitle>
          <DialogDescription>
            They must change it at their next sign-in, and all of their current sessions end
            straight away.
          </DialogDescription>
        </DialogHeader>
        <Input
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="New temporary password"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={() => onSubmit(password)} disabled={!password}>Reset</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
