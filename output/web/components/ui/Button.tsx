"use client";

import { cn } from "@/lib/utils";

const VARIANTS = {
  primary: "bg-blue-600 text-white hover:bg-blue-500 focus:ring-blue-500",
  secondary: "bg-slate-800 text-slate-200 border border-slate-700 hover:bg-slate-700 focus:ring-slate-500",
  ghost: "text-slate-400 hover:text-slate-200 hover:bg-slate-800/60 focus:ring-slate-500",
  danger: "bg-red-600/15 text-red-400 hover:bg-red-600/25 focus:ring-red-500",
  success: "bg-green-600/15 text-green-400 hover:bg-green-600/25 focus:ring-green-500",
} as const;

type Variant = keyof typeof VARIANTS;

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  disabled = false,
  children,
  ...props
}: {
  variant?: Variant;
  size?: "sm" | "md";
  className?: string;
  disabled?: boolean;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base =
    "inline-flex items-center justify-center gap-1.5 rounded-[4px] font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap";
  const sizeClass = size === "sm" ? "px-2.5 py-1 text-xs" : "px-4 py-2 text-[13px]";

  return (
    <button
      className={cn(base, sizeClass, VARIANTS[variant], className)}
      disabled={disabled}
      {...props}
    >
      {children}
    </button>
  );
}
