import { type AgentStatus, type TaskStatus } from "@/lib/types";

const STATUS_BADGES: Record<AgentStatus, string> = {
  online: "bg-green-500/15 text-green-400 border border-green-500/30",
  offline: "bg-slate-500/15 text-slate-400 border border-slate-500/30",
  working: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  error: "bg-red-500/15 text-red-400 border border-red-500/30",
};

const TASK_BADGES: Record<TaskStatus, string> = {
  pending: "bg-blue-500/15 text-blue-400 border border-blue-500/30",
  in_progress: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  review: "bg-violet-500/15 text-violet-400 border border-violet-500/30",
  done: "bg-green-500/15 text-green-400 border border-green-500/30",
  failed: "bg-red-500/15 text-red-400 border border-red-500/30",
};

const TASK_LABELS: Record<TaskStatus, string> = {
  pending: "pending",
  in_progress: "working",
  review: "review",
  done: "done",
  failed: "failed",
};

export function Badge({
  variant,
  className = "",
  children,
}: {
  variant: AgentStatus | TaskStatus | "success" | "warning" | "danger" | "info" | "muted";
  className?: string;
  children: React.ReactNode;
}) {
  const base = "inline-flex items-center text-[11px] font-semibold font-mono uppercase tracking-wider px-2 py-0.5 rounded-full whitespace-nowrap";

  let colorClass = "";
  if (variant in STATUS_BADGES) {
    colorClass = STATUS_BADGES[variant as AgentStatus];
  } else if (variant in TASK_BADGES) {
    colorClass = TASK_BADGES[variant as TaskStatus];
  } else {
    const extras: Record<string, string> = {
      success: "bg-green-500/15 text-green-400 border border-green-500/30",
      warning: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
      danger: "bg-red-500/15 text-red-400 border border-red-500/30",
      info: "bg-blue-500/15 text-blue-400 border border-blue-500/30",
      muted: "bg-slate-500/15 text-slate-400 border border-slate-500/30",
    };
    colorClass = extras[variant] ?? extras.muted;
  }

  return (
    <span className={`${base} ${colorClass} ${className}`}>
      {children}
    </span>
  );
}

export function TaskStatusBadge({ status }: { status: TaskStatus }) {
  return <Badge variant={status}>{TASK_LABELS[status]}</Badge>;
}

export function AgentStatusBadge({ status }: { status: AgentStatus }) {
  return <Badge variant={status}>{status}</Badge>;
}
