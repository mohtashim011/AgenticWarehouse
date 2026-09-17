import * as React from "react";
import { cva } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary/12 text-primary",
        secondary: "border-transparent bg-secondary text-secondary-foreground",
        destructive: "border-destructive/25 bg-destructive/12 text-destructive",
        outline: "text-foreground",
        success:
          "border-[hsl(var(--success))]/25 bg-[hsl(var(--success))]/12 text-[hsl(var(--success))]",
        warning:
          "border-[hsl(var(--warning))]/25 bg-[hsl(var(--warning))]/12 text-[hsl(var(--warning))]",
        info: "border-[hsl(var(--info))]/25 bg-[hsl(var(--info))]/12 text-[hsl(var(--info))]",
        muted: "border-border bg-muted text-muted-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

function Badge({ className, variant, ...props }) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
