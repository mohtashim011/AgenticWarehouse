import * as React from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { Warehouse, LogIn, ShieldCheck, Cpu, Brain, ScanLine } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent } from "@/components/ui/card";
import { useAuth } from "@/hooks/useAuth";

const HIGHLIGHTS = [
  { icon: Cpu, title: "13 cooperating agents", body: "Each decides independently and explains why." },
  { icon: ScanLine, title: "Scanner that survives failure", body: "Two cameras, photo capture, manual entry, and automatic repair of bad reads." },
  { icon: Brain, title: "93.7% categorisation", body: "Five models cross-validated; the best one runs." },
];

export default function Login() {
  const { user, loading, login } = useAuth();
  const navigate = useNavigate();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  if (!loading && user) return <Navigate to="/" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setError("");
    setBusy(true);
    try {
      await login(username.trim(), password);
      navigate("/", { replace: true });
    } catch (err) {
      // The server decides what to say here. It deliberately does not reveal
      // whether the username exists, and the interface must not undo that.
      setError(err.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen">
      {/* Context panel: hidden on phones, where the form is all that matters. */}
      <div className="hidden w-1/2 flex-col justify-between bg-card p-10 lg:flex">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
            <Warehouse className="h-5 w-5" />
          </div>
          <div>
            <p className="font-semibold leading-tight">Agentic Warehouse</p>
            <p className="text-xs text-muted-foreground">
              Multi-agent collaboration in warehouse management
            </p>
          </div>
        </div>

        <div className="space-y-6">
          <h2 className="max-w-md text-2xl font-semibold leading-snug">
            A warehouse run by cooperating agents, not one central rule engine.
          </h2>
          <div className="space-y-4">
            {HIGHLIGHTS.map(({ icon: Icon, title, body }) => (
              <div key={title} className="flex gap-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/12 text-primary">
                  <Icon className="h-4 w-4" />
                </div>
                <div>
                  <p className="text-sm font-medium">{title}</p>
                  <p className="max-w-sm text-sm text-muted-foreground">{body}</p>
                </div>
              </div>
            ))}
          </div>
        </div>

        <p className="text-xs text-muted-foreground">
          Mohtashim Hussain &middot; COS700 research project
        </p>
      </div>

      {/* Form */}
      <div className="flex w-full items-center justify-center p-6 lg:w-1/2">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <Warehouse className="h-5 w-5" />
            </div>
            <p className="font-semibold">Agentic Warehouse</p>
          </div>

          <h1 className="text-xl font-semibold">Sign in</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            Every action is recorded against your account.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="username">Username</Label>
              <Input
                id="username"
                autoComplete="username"
                autoFocus
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                required
              />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {error && (
              <div className="rounded-lg border border-destructive/30 bg-destructive/10 p-3">
                <p className="text-sm text-destructive">{error}</p>
              </div>
            )}

            <Button type="submit" className="w-full" size="lg" disabled={busy}>
              <LogIn className="h-4 w-4" />
              {busy ? "Signing in..." : "Sign in"}
            </Button>
          </form>

          <Card className="mt-6 border-dashed">
            <CardContent className="flex gap-3 p-4">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
              <div className="text-xs text-muted-foreground">
                <p className="font-medium text-foreground">First run?</p>
                <p className="mt-0.5">
                  Sign in as <code className="rounded bg-muted px-1">admin</code> with the
                  password printed in the server console. You will be asked to change it
                  straight away.
                </p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
