/**
 * Application shell
 * =================
 * The sidebar, the top bar, and the frame every screen sits inside.
 *
 * Navigation is filtered by capability, so a picker never sees a Staff link
 * that would only refuse them. The sidebar collapses to icons on a laptop and
 * becomes a slide-over sheet on a phone, because this is used on both.
 */
import * as React from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import {
  Boxes, ScanLine, LayoutDashboard, Users, Brain, Cpu, BarChart3,
  Settings as SettingsIcon, History, LogOut, Menu, X, Warehouse,
  ChevronLeft, ShieldCheck, Sun, Moon, KeyRound, CalendarDays,
  Video, Scale,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/misc";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import { ChangePasswordDialog } from "@/components/dialogs/ChangePasswordDialog";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, needs: "inventory.read", end: true },
  { to: "/scan", label: "Scanner", icon: ScanLine, needs: "scan" },
  { to: "/cameras", label: "Cameras", icon: Video, needs: "scan" },
  { to: "/inventory", label: "Inventory", icon: Boxes, needs: "inventory.read" },
  { to: "/reports", label: "Daily report", icon: CalendarDays, needs: "reports.read" },
  { to: "/activity", label: "Activity", icon: History, needs: "inventory.read" },
  { to: "/staff", label: "Staff", icon: Users, needs: "staff.read" },
  { to: "/agents", label: "Agents", icon: Cpu, needs: "agents.read" },
  { to: "/models", label: "AI Models", icon: Brain, needs: "models.read" },
  { to: "/report", label: "Report", icon: BarChart3, needs: "reports.read" },
  { to: "/comparison", label: "Comparison", icon: Scale, needs: "reports.read" },
  { to: "/settings", label: "Settings", icon: SettingsIcon, needs: "inventory.read" },
];

function useTheme() {
  const [dark, setDark] = React.useState(
    () => localStorage.getItem("aw-theme") !== "light"
  );
  React.useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    localStorage.setItem("aw-theme", dark ? "dark" : "light");
  }, [dark]);
  return [dark, setDark];
}

export function AppShell() {
  const { user, logout, can } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = React.useState(false);
  const [collapsed, setCollapsed] = React.useState(
    () => localStorage.getItem("aw-sidebar") === "collapsed"
  );
  const [dark, setDark] = useTheme();
  const [passwordOpen, setPasswordOpen] = React.useState(false);

  React.useEffect(() => setMobileOpen(false), [location.pathname]);
  React.useEffect(() => {
    localStorage.setItem("aw-sidebar", collapsed ? "collapsed" : "expanded");
  }, [collapsed]);

  // An account still on its issued password is nudged immediately: leaving it
  // is how a well-known default becomes the permanent one.
  React.useEffect(() => {
    if (user?.must_change_pw) setPasswordOpen(true);
  }, [user?.must_change_pw]);

  const items = NAV.filter((item) => can(item.needs));

  // Match nested routes to their section, so a detail page like
  // /inventory/900001 still says "Inventory" instead of leaving the bar blank.
  const current = items.find((item) =>
    item.end ? location.pathname === item.to
             : location.pathname === item.to ||
               location.pathname.startsWith(item.to + "/")
  );
  const currentLabel = current?.label || "";

  const handleLogout = async () => {
    await logout();
    navigate("/login", { replace: true });
  };

  const SidebarBody = ({ showLabels }) => (
    <>
      <div className={cn("flex items-center gap-2.5 px-3 py-4", !showLabels && "justify-center")}>
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <Warehouse className="h-5 w-5" />
        </div>
        {showLabels && (
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold leading-tight">Agentic Warehouse</p>
            <p className="truncate text-xs text-muted-foreground">Multi-agent AI</p>
          </div>
        )}
      </div>

      <Separator />

      <nav className="flex-1 space-y-1 overflow-y-auto p-2">
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            title={showLabels ? undefined : label}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                !showLabels && "justify-center px-2",
                isActive
                  ? "bg-primary/12 text-primary"
                  : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {showLabels && <span className="truncate">{label}</span>}
          </NavLink>
        ))}
      </nav>

      <Separator />

      <div className="p-2">
        <div
          className={cn(
            "flex items-center gap-2.5 rounded-lg px-2 py-2",
            !showLabels && "justify-center"
          )}
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-secondary text-xs font-semibold uppercase">
            {(user?.full_name || user?.username || "?").slice(0, 2)}
          </div>
          {showLabels && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium leading-tight">
                {user?.full_name || user?.username}
              </p>
              <p className="truncate text-xs text-muted-foreground">{user?.role_label}</p>
            </div>
          )}
        </div>
        {showLabels && (
          <div className="mt-1 flex gap-1">
            <Button
              variant="ghost"
              size="sm"
              className="flex-1 justify-start"
              onClick={() => setPasswordOpen(true)}
            >
              <KeyRound className="h-4 w-4" />
              Password
            </Button>
            <Button variant="ghost" size="icon" onClick={() => setDark(!dark)} title="Theme">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={handleLogout} title="Sign out">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        )}
        {!showLabels && (
          <div className="mt-1 flex flex-col gap-1">
            <Button variant="ghost" size="icon" onClick={() => setDark(!dark)} className="mx-auto">
              {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
            <Button variant="ghost" size="icon" onClick={handleLogout} className="mx-auto">
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
    </>
  );

  return (
    // h-screen + overflow-hidden pins the whole frame to the viewport, so the
    // sidebar and top bar cannot scroll away. Only <main> scrolls, which is
    // what keeps navigation reachable from anywhere on a long page.
    <div className="app-frame flex overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <aside
        className={cn(
          "relative hidden h-full shrink-0 flex-col border-r bg-card transition-all duration-200 lg:flex",
          collapsed ? "w-[68px]" : "w-60"
        )}
      >
        <SidebarBody showLabels={!collapsed} />
        <button
          type="button"
          onClick={() => setCollapsed((c) => !c)}
          className="absolute -right-3 top-16 z-10 flex h-6 w-6 items-center justify-center rounded-full border bg-card text-muted-foreground shadow-sm hover:text-foreground"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <ChevronLeft className={cn("h-3.5 w-3.5 transition-transform", collapsed && "rotate-180")} />
        </button>
      </aside>

      {/* Mobile sheet */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 lg:hidden">
          <div
            className="absolute inset-0 bg-black/70 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />
          <aside className="absolute left-0 top-0 flex h-full w-64 flex-col border-r bg-card animate-slide-up">
            <SidebarBody showLabels />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <header className="z-30 flex h-14 shrink-0 items-center gap-3 border-b bg-background/85 px-4 backdrop-blur">
          <Button
            variant="ghost"
            size="icon"
            className="lg:hidden"
            onClick={() => setMobileOpen((o) => !o)}
            aria-label="Menu"
          >
            {mobileOpen ? <Menu className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </Button>
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-sm font-semibold">{currentLabel}</h1>
          </div>
          <Badge variant="muted" className="hidden sm:inline-flex">
            <ShieldCheck className="h-3 w-3" />
            {user?.role_label}
          </Badge>
        </header>

        {/* The only scrolling region. overscroll-contain stops a scroll that
            reaches the bottom here from bouncing the page behind it. */}
        <main className="min-w-0 flex-1 overflow-y-auto overscroll-contain p-4 sm:p-6">
          <Outlet />
        </main>
      </div>

      <ChangePasswordDialog
        open={passwordOpen}
        onOpenChange={setPasswordOpen}
        forced={Boolean(user?.must_change_pw)}
      />
    </div>
  );
}
