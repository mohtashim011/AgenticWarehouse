/**
 * Toasts
 * ======
 * Confirmation that something happened, without stealing focus.
 *
 * Written rather than pulled in because the requirements are narrow and
 * specific: a scan result must be readable from arm's length, an error must
 * stay long enough to act on, and nothing may ever cover the scanner viewport.
 */
import * as React from "react";
import { CheckCircle2, AlertTriangle, XCircle, Info, X } from "lucide-react";
import { cn } from "@/lib/utils";

const ToastContext = React.createContext(null);

const ICONS = {
  success: CheckCircle2,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

const TONES = {
  success: "border-[hsl(var(--success))]/30 bg-card text-foreground",
  error: "border-destructive/40 bg-card text-foreground",
  warning: "border-[hsl(var(--warning))]/35 bg-card text-foreground",
  info: "border-border bg-card text-foreground",
};

const ICON_TONES = {
  success: "text-[hsl(var(--success))]",
  error: "text-destructive",
  warning: "text-[hsl(var(--warning))]",
  info: "text-[hsl(var(--info))]",
};

export function ToastProvider({ children }) {
  const [toasts, setToasts] = React.useState([]);

  const dismiss = React.useCallback((id) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const push = React.useCallback(
    (message, { variant = "info", title, duration, node, onClick } = {}) => {
      const id = Math.random().toString(36).slice(2);
      // Errors linger: they usually require the person to do something, and a
      // message that vanishes before it is read is worse than none.
      const ms = duration ?? (variant === "error" ? 8000 : 4000);
      setToasts((prev) => [...prev.slice(-3), { id, message, variant, title, node, onClick }]);
      if (ms > 0) setTimeout(() => dismiss(id), ms);
      return id;
    },
    [dismiss]
  );

  const value = React.useMemo(
    () => ({
      toast: push,
      success: (m, o) => push(m, { ...o, variant: "success" }),
      error: (m, o) => push(m, { ...o, variant: "error" }),
      warning: (m, o) => push(m, { ...o, variant: "warning" }),
      info: (m, o) => push(m, { ...o, variant: "info" }),
      // A fully custom body, for the scan acknowledgement. It has to be read at
      // arm's length in under two seconds, which the title/message pair cannot do.
      custom: (node, o = {}) => push(null, { ...o, node }),
      dismiss,
    }),
    [push, dismiss]
  );

  return (
    <ToastContext.Provider value={value}>
      {children}
      <div
        className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
        role="region"
        aria-live="polite"
      >
        {toasts.map((t) => {
          const Icon = ICONS[t.variant] || Info;
          if (t.node) {
            return (
              <div
                key={t.id}
                role={t.onClick ? "button" : undefined}
                onClick={t.onClick ? () => { t.onClick(); dismiss(t.id); } : undefined}
                className={cn(
                  "pointer-events-auto overflow-hidden rounded-lg border shadow-lg animate-slide-up",
                  TONES[t.variant],
                  t.onClick && "cursor-pointer hover:brightness-110"
                )}
              >
                {t.node}
              </div>
            );
          }
          return (
            <div
              key={t.id}
              className={cn(
                "pointer-events-auto flex items-start gap-3 rounded-lg border p-3 shadow-lg animate-slide-up",
                TONES[t.variant]
              )}
            >
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", ICON_TONES[t.variant])} />
              <div className="min-w-0 flex-1">
                {t.title && <p className="text-sm font-semibold">{t.title}</p>}
                <p className="break-words text-sm text-muted-foreground">{t.message}</p>
              </div>
              <button
                type="button"
                onClick={() => dismiss(t.id)}
                className="shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground"
                aria-label="Dismiss"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          );
        })}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  const ctx = React.useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used inside a ToastProvider.");
  return ctx;
}
