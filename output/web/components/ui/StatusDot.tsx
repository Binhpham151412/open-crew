import { type AgentStatus } from "@/lib/types";

const STYLES: Record<AgentStatus, { dot: string; ring?: string }> = {
  online: { dot: "bg-green-500", ring: "shadow-[0_0_6px_rgba(22,163,74,0.5)]" },
  offline: { dot: "bg-slate-500" },
  working: { dot: "bg-amber-500", ring: "shadow-[0_0_6px_rgba(217,119,6,0.5)]" },
  error: { dot: "bg-red-500", ring: "shadow-[0_0_6px_rgba(220,38,38,0.5)]" },
};

export function StatusDot({
  status,
  size = "md",
  pulse = false,
  className = "",
}: {
  status: AgentStatus;
  size?: "sm" | "md" | "lg";
  pulse?: boolean;
  className?: string;
}) {
  const s = STYLES[status] ?? STYLES.offline;
  const sizeClass = size === "sm" ? "h-1.5 w-1.5" : size === "lg" ? "h-3 w-3" : "h-2 w-2";
  const shouldPulse = pulse || status === "working";

  return (
    <span className={`relative inline-flex shrink-0 ${className}`}>
      {shouldPulse && (
        <span
          className={`absolute inline-flex h-full w-full rounded-full ${s.dot} opacity-75 animate-ping`}
        />
      )}
      <span className={`relative inline-flex rounded-full ${sizeClass} ${s.dot} ${s.ring ?? ""}`} />
    </span>
  );
}
