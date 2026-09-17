import { clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Merge class names, letting a later Tailwind class win over an earlier one. */
export function cn(...inputs) {
  return twMerge(clsx(inputs));
}

/** A timestamp as a short local date and time. */
export function formatTime(iso) {
  if (!iso) return "-";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** "3 minutes ago" -- easier to judge at a glance than a wall-clock time. */
export function timeAgo(iso) {
  if (!iso) return "-";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const seconds = Math.round((Date.now() - then) / 1000);
  if (seconds < 45) return "just now";
  const units = [
    ["minute", 60],
    ["hour", 3600],
    ["day", 86400],
    ["week", 604800],
  ];
  let label = "minute";
  let size = 60;
  for (const [name, secs] of units) {
    if (seconds >= secs) {
      label = name;
      size = secs;
    }
  }
  const n = Math.round(seconds / size);
  return `${n} ${label}${n === 1 ? "" : "s"} ago`;
}

export function percent(value, digits = 1) {
  if (value === null || value === undefined) return "-";
  return `${(value * 100).toFixed(digits)}%`;
}

/** Group an array by a key function. */
export function groupBy(items, keyFn) {
  return items.reduce((acc, item) => {
    const key = keyFn(item);
    (acc[key] = acc[key] || []).push(item);
    return acc;
  }, {});
}

/**
 * Categorical colours for charts.
 *
 * Ordered so that adjacent series stay distinguishable, and chosen to keep
 * enough contrast against both the light and dark card surfaces. Anything past
 * the sixth category wraps -- by then a chart is better off aggregating.
 */
export const SERIES_COLORS = [
  "hsl(209 96% 62%)",
  "hsl(152 58% 48%)",
  "hsl(36 94% 58%)",
  "hsl(280 70% 66%)",
  "hsl(190 82% 52%)",
  "hsl(348 78% 62%)",
];

export function seriesColor(index) {
  return SERIES_COLORS[index % SERIES_COLORS.length];
}

/** Tailwind classes for an action pill in the activity log. */
export function actionTone(action) {
  switch (action) {
    case "IN":
      return "bg-[hsl(var(--success))]/12 text-[hsl(var(--success))] border-[hsl(var(--success))]/25";
    case "OUT":
      return "bg-[hsl(var(--info))]/12 text-[hsl(var(--info))] border-[hsl(var(--info))]/25";
    case "REJECT":
      return "bg-destructive/12 text-destructive border-destructive/25";
    case "ADJUST":
      return "bg-[hsl(var(--warning))]/12 text-[hsl(var(--warning))] border-[hsl(var(--warning))]/25";
    default:
      return "bg-muted text-muted-foreground border-border";
  }
}
