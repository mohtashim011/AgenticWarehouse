import * as React from "react";
import { KeyRound, ShieldAlert } from "lucide-react";
import {
  Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/useAuth";
import { api } from "@/lib/api";

export function ChangePasswordDialog({ open, onOpenChange, forced = false }) {
  const toast = useToast();
  const { refresh } = useAuth();
  const [current, setCurrent] = React.useState("");
  const [next, setNext] = React.useState("");
  const [confirm, setConfirm] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    if (next !== confirm) {
      setError("The two new passwords do not match.");
      return;
    }
    setBusy(true);
    try {
      const res = await api.changePassword(current, next);
      toast.success(res.message || "Password updated.");
      setCurrent("");
      setNext("");
      setConfirm("");
      await refresh();
      onOpenChange(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={forced ? () => {} : onOpenChange}>
      <DialogContent hideClose={forced} className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="h-4 w-4" />
            {forced ? "Choose a new password" : "Change your password"}
          </DialogTitle>
          <DialogDescription>
            {forced
              ? "This account is still using the password it was issued. Choose your own before continuing."
              : "At least 8 characters, with at least one digit or symbol."}
          </DialogDescription>
        </DialogHeader>

        {forced && (
          <div className="flex items-start gap-2 rounded-lg border border-[hsl(var(--warning))]/30 bg-[hsl(var(--warning))]/10 p-3 text-sm">
            <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[hsl(var(--warning))]" />
            <p className="text-muted-foreground">
              An issued password is known to whoever issued it. Until it is changed, any
              action taken by this account cannot be attributed with confidence.
            </p>
          </div>
        )}

        <form onSubmit={submit} className="space-y-3">
          <div className="space-y-1.5">
            <Label htmlFor="current-pw">Current password</Label>
            <Input
              id="current-pw"
              type="password"
              autoComplete="current-password"
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="new-pw">New password</Label>
            <Input
              id="new-pw"
              type="password"
              autoComplete="new-password"
              value={next}
              onChange={(e) => setNext(e.target.value)}
              required
            />
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="confirm-pw">Confirm new password</Label>
            <Input
              id="confirm-pw"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              required
            />
          </div>

          {error && <p className="text-sm text-destructive">{error}</p>}

          <DialogFooter>
            {!forced && (
              <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
            )}
            <Button type="submit" disabled={busy}>
              {busy ? "Saving..." : "Update password"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
