import * as React from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { Loader2, Lock } from "lucide-react";
import { AppShell } from "@/components/layout/AppShell";
import { useAuth } from "@/hooks/useAuth";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { Button } from "@/components/ui/button";

import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Scanner from "@/pages/Scanner";
import Cameras from "@/pages/Cameras";
import Inventory from "@/pages/Inventory";
import ProductDetail from "@/pages/ProductDetail";
import Reports from "@/pages/Reports";
import Activity from "@/pages/Activity";
import Staff from "@/pages/Staff";
import Agents from "@/pages/Agents";
import Models from "@/pages/Models";
import Report from "@/pages/Report";
import Comparison from "@/pages/Comparison";
import Settings from "@/pages/Settings";

function FullPageSpinner() {
  return (
    <div className="flex min-h-screen items-center justify-center">
      <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
    </div>
  );
}

/** Requires a signed-in user, and optionally a capability. */
function Protected({ needs, children }) {
  const { user, loading, can } = useAuth();
  const location = useLocation();

  if (loading) return <FullPageSpinner />;
  if (!user) return <Navigate to="/login" state={{ from: location }} replace />;

  if (needs && !can(needs)) {
    // Say plainly what is missing rather than bouncing them somewhere else
    // with no explanation -- a silent redirect reads as a broken link.
    return (
      <div className="mx-auto max-w-md py-16 text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-muted">
          <Lock className="h-5 w-5 text-muted-foreground" />
        </div>
        <h2 className="mt-4 text-lg font-semibold">Not available to your role</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          This screen needs the <code className="rounded bg-muted px-1">{needs}</code>{" "}
          permission, which {user.role_label} does not hold. An administrator can change
          your role.
        </p>
        <Button className="mt-6" onClick={() => window.history.back()}>
          Go back
        </Button>
      </div>
    );
  }
  // A render failure on one screen must not unmount the whole application.
  // The boundary is keyed on the path so navigating away clears a failure.
  return <ErrorBoundary key={location.pathname} name={location.pathname}>{children}</ErrorBoundary>;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Protected>
            <AppShell />
          </Protected>
        }
      >
        <Route index element={<Protected needs="inventory.read"><Dashboard /></Protected>} />
        <Route path="scan" element={<Protected needs="scan"><Scanner /></Protected>} />
        <Route path="cameras" element={<Protected needs="scan"><Cameras /></Protected>} />
        <Route path="inventory" element={<Protected needs="inventory.read"><Inventory /></Protected>} />
        <Route path="inventory/:productno" element={<Protected needs="inventory.read"><ProductDetail /></Protected>} />
        <Route path="reports" element={<Protected needs="reports.read"><Reports /></Protected>} />
        <Route path="activity" element={<Protected needs="inventory.read"><Activity /></Protected>} />
        <Route path="staff" element={<Protected needs="staff.read"><Staff /></Protected>} />
        <Route path="agents" element={<Protected needs="agents.read"><Agents /></Protected>} />
        <Route path="models" element={<Protected needs="models.read"><Models /></Protected>} />
        <Route path="report" element={<Protected needs="reports.read"><Report /></Protected>} />
        <Route path="comparison" element={<Protected needs="reports.read"><Comparison /></Protected>} />
        <Route path="settings" element={<Protected needs="inventory.read"><Settings /></Protected>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
