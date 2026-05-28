"use client";

import React, { useState, useEffect, useCallback } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface A2AMessage {
  protocol: string;
  type: "task" | "challenge" | "response" | "final_position" | "escalate" | "decision" | "result";
  from: string;
  to: string;
  task_id: string;
  round: number;
  payload: {
    claim: string;
    evidence?: string;
    suggestion?: string;
    artifacts?: { name: string; content: string; mime_type?: string }[];
    metadata?: Record<string, string>;
  };
  timestamp: string;
}

interface Task {
  id: string;
  title: string;
  description?: string;
  status: "pending" | "in_progress" | "review" | "done" | "failed";
  created_at: string;
  updated_at?: string;
  assigned_agents?: string[];
  current_phase?: string;
  phase_number?: number;
  total_phases?: number;
  messages?: A2AMessage[];
}

type TaskStatus = Task["status"];
type MessageType = A2AMessage["type"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const STATUS_CONFIG: Record<
  TaskStatus,
  { label: string; dotClass: string; badgeClass: string }
> = {
  pending: {
    label: "Pending",
    dotClass: "bg-slate-400",
    badgeClass: "bg-slate-700 text-slate-300",
  },
  in_progress: {
    label: "Working",
    dotClass: "bg-amber-500 animate-pulse",
    badgeClass: "bg-amber-900/50 text-amber-300",
  },
  review: {
    label: "Review",
    dotClass: "bg-blue-500 animate-pulse",
    badgeClass: "bg-blue-900/50 text-blue-300",
  },
  done: {
    label: "Done",
    dotClass: "bg-green-500",
    badgeClass: "bg-green-900/50 text-green-300",
  },
  failed: {
    label: "Failed",
    dotClass: "bg-red-500",
    badgeClass: "bg-red-900/50 text-red-300",
  },
};

const MESSAGE_TYPE_CONFIG: Record<
  MessageType,
  { color: string; icon: string; bgClass: string }
> = {
  task: {
    color: "text-blue-400",
    icon: "📋",
    bgClass: "border-blue-800/40",
  },
  challenge: {
    color: "text-amber-400",
    icon: "⚔️",
    bgClass: "border-amber-800/40",
  },
  response: {
    color: "text-green-400",
    icon: "💬",
    bgClass: "border-green-800/40",
  },
  final_position: {
    color: "text-purple-400",
    icon: "📌",
    bgClass: "border-purple-800/40",
  },
  escalate: {
    color: "text-red-400",
    icon: "🔺",
    bgClass: "border-red-800/40",
  },
  decision: {
    color: "text-cyan-400",
    icon: "⚖️",
    bgClass: "border-cyan-800/40",
  },
  result: {
    color: "text-green-400",
    icon: "✅",
    bgClass: "border-green-800/40",
  },
};

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  } catch {
    return iso;
  }
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

function relativeTime(iso: string): string {
  try {
    const now = Date.now();
    const then = new Date(iso).getTime();
    const diffSec = Math.floor((now - then) / 1000);
    if (diffSec < 60) return "just now";
    const diffMin = Math.floor(diffSec / 60);
    if (diffMin < 60) return `${diffMin}m ago`;
    const diffHr = Math.floor(diffMin / 60);
    if (diffHr < 24) return `${diffHr}h ago`;
    const diffDay = Math.floor(diffHr / 24);
    return `${diffDay}d ago`;
  } catch {
    return iso;
  }
}

function agentDisplayName(name: string): string {
  return name
    .replace(/[-_]/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: TaskStatus }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      {(status === "in_progress" || status === "review") && (
        <span className="absolute inset-0 rounded-full opacity-75 animate-ping bg-amber-400" />
      )}
      <span className={`relative inline-flex rounded-full h-2.5 w-2.5 ${cfg.dotClass}`} />
    </span>
  );
}

function MessageBubble({ msg }: { msg: A2AMessage }) {
  const cfg = MESSAGE_TYPE_CONFIG[msg.type] ?? MESSAGE_TYPE_CONFIG.task;

  return (
    <div className={`flex gap-3 items-start border-l-2 pl-4 py-2 ${cfg.bgClass}`}>
      {/* Icon */}
      <span className="text-base mt-0.5 select-none" aria-hidden="true">
        {cfg.icon}
      </span>

      <div className="flex-1 min-w-0">
        {/* Header row */}
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="text-xs font-mono text-slate-500">
            {formatTime(msg.timestamp)}
          </span>
          <span className={`text-xs font-semibold ${cfg.color} uppercase tracking-wider`}>
            {msg.type.replace("_", " ")}
          </span>
          {msg.round > 0 && (
            <span className="text-[10px] font-mono bg-slate-700 text-slate-300 rounded px-1.5 py-0.5">
              R{msg.round}
            </span>
          )}
          <span className="text-xs text-slate-400">
            {agentDisplayName(msg.from)} → {agentDisplayName(msg.to)}
          </span>
        </div>

        {/* Claim */}
        <p className="mt-1 text-sm text-slate-200 leading-relaxed break-words">
          {msg.payload.claim}
        </p>

        {/* Evidence */}
        {msg.payload.evidence && (
          <p className="mt-1 text-xs text-slate-400 leading-relaxed">
            <span className="font-semibold text-slate-300">Evidence:</span>{" "}
            {msg.payload.evidence}
          </p>
        )}

        {/* Suggestion */}
        {msg.payload.suggestion && (
          <p className="mt-1 text-xs text-slate-400 leading-relaxed">
            <span className="font-semibold text-slate-300">Suggestion:</span>{" "}
            {msg.payload.suggestion}
          </p>
        )}

        {/* Artifacts */}
        {msg.payload.artifacts && msg.payload.artifacts.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {msg.payload.artifacts.map((a, i) => (
              <span
                key={i}
                className="inline-flex items-center gap-1 text-[11px] font-mono bg-slate-700/80 text-slate-300 rounded px-2 py-0.5"
                title={`${a.name}${a.mime_type ? ` (${a.mime_type})` : ""}`}
              >
                📎 {a.name}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TaskTimeline({ messages }: { messages: A2AMessage[] }) {
  if (!messages || messages.length === 0) {
    return (
      <div className="py-6 text-center text-sm text-slate-500">
        No timeline events yet. Messages will appear here as agents process this task.
      </div>
    );
  }

  // Sort chronologically
  const sorted = [...messages].sort(
    (a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
  );

  return (
    <div className="space-y-1">
      {sorted.map((msg, idx) => (
        <MessageBubble key={`${msg.task_id}-${idx}`} msg={msg} />
      ))}
    </div>
  );
}

function TaskCard({ task }: { task: Task }) {
  const [expanded, setExpanded] = useState(false);
  const cfg = STATUS_CONFIG[task.status];
  const msgCount = task.messages?.length ?? 0;

  return (
    <div className="bg-slate-800 border border-slate-700/60 rounded-lg overflow-hidden transition-shadow hover:shadow-lg hover:shadow-slate-950/40">
      {/* Header — always visible */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-slate-800/80 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-inset rounded-lg"
        aria-expanded={expanded}
      >
        <StatusDot status={task.status} />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-slate-100 truncate">
              {task.title}
            </span>
            <span
              className={`text-[10px] font-semibold uppercase tracking-wider rounded px-1.5 py-0.5 ${cfg.badgeClass}`}
            >
              {cfg.label}
            </span>
          </div>
          <div className="flex items-center gap-3 mt-0.5">
            {task.current_phase && task.phase_number != null && task.total_phases != null && (
              <span className="text-xs text-slate-400">
                Phase {task.phase_number}/{task.total_phases} ({task.current_phase})
              </span>
            )}
            {task.assigned_agents && task.assigned_agents.length > 0 && (
              <span className="text-xs text-slate-500 hidden sm:inline">
                {task.assigned_agents.map(agentDisplayName).join(", ")}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 shrink-0">
          {msgCount > 0 && (
            <span className="text-[10px] font-mono bg-slate-700 text-slate-300 rounded-full px-2 py-0.5">
              {msgCount} msg{msgCount !== 1 ? "s" : ""}
            </span>
          )}
          <span className="text-xs text-slate-500 hidden sm:inline">
            {relativeTime(task.created_at)}
          </span>
          {/* Chevron */}
          <svg
            className={`h-4 w-4 text-slate-400 transition-transform duration-200 ${
              expanded ? "rotate-180" : ""
            }`}
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {/* Expanded timeline */}
      {expanded && (
        <div className="border-t border-slate-700/60 bg-slate-900/50 px-4 py-3">
          <h4 className="text-xs font-semibold uppercase tracking-wider text-slate-400 mb-3">
            A2A Timeline
          </h4>
          <TaskTimeline messages={task.messages ?? []} />
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Page
// ---------------------------------------------------------------------------

export default function TasksPage() {
  const [tasks, setTasks] = useState<Task[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [newTaskText, setNewTaskText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitSuccess, setSubmitSuccess] = useState(false);
  const [filterStatus, setFilterStatus] = useState<TaskStatus | "all">("all");

  // ---- Fetch tasks ----

  const fetchTasks = useCallback(async () => {
    try {
      setError(null);
      const res = await fetch("/api/tasks", { cache: "no-store" });
      if (!res.ok) {
        throw new Error(`Failed to fetch tasks: ${res.status} ${res.statusText}`);
      }
      const data: Task[] = await res.json();
      setTasks(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error fetching tasks");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchTasks();
    // Poll every 8 seconds for live updates
    const interval = setInterval(fetchTasks, 8000);
    return () => clearInterval(interval);
  }, [fetchTasks]);

  // ---- Submit new task ----

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newTaskText.trim();
    if (!trimmed) return;

    setSubmitting(true);
    setSubmitError(null);
    setSubmitSuccess(false);

    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed, description: trimmed }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => null);
        throw new Error(body?.error ?? `Server returned ${res.status}`);
      }

      setNewTaskText("");
      setSubmitSuccess(true);
      setTimeout(() => setSubmitSuccess(false), 3000);
      // Immediately refresh task list
      await fetchTasks();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to submit task");
    } finally {
      setSubmitting(false);
    }
  };

  // ---- Filtering ----

  const filteredTasks =
    filterStatus === "all"
      ? tasks
      : tasks.filter((t) => t.status === filterStatus);

  const statusCounts = tasks.reduce(
    (acc, t) => {
      acc[t.status] = (acc[t.status] || 0) + 1;
      return acc;
    },
    {} as Record<TaskStatus, number>
  );

  // ---- Render ----

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Page title */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-slate-50">
          Tasks
        </h1>
        <p className="mt-1 text-sm text-slate-400">
          Submit new tasks and monitor agent progress through the pipeline.
        </p>
      </div>

      {/* New Task Form */}
      <form onSubmit={handleSubmit} className="space-y-3">
        <label htmlFor="new-task" className="block text-sm font-medium text-slate-300">
          New Task
        </label>
        <textarea
          id="new-task"
          rows={3}
          value={newTaskText}
          onChange={(e) => {
            setNewTaskText(e.target.value);
            setSubmitError(null);
          }}
          placeholder='Describe the task... e.g. "Build user registration with email verification"'
          className="w-full rounded-lg border border-slate-600 bg-slate-800 px-4 py-3 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 resize-y transition-colors"
          disabled={submitting}
        />
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={submitting || !newTaskText.trim()}
            className="inline-flex items-center gap-2 rounded-lg bg-blue-600 px-5 py-2 text-sm font-medium text-white hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {submitting ? (
              <>
                <svg
                  className="animate-spin h-4 w-4"
                  viewBox="0 0 24 24"
                  fill="none"
                >
                  <circle
                    className="opacity-25"
                    cx="12"
                    cy="12"
                    r="10"
                    stroke="currentColor"
                    strokeWidth="4"
                  />
                  <path
                    className="opacity-75"
                    fill="currentColor"
                    d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                  />
                </svg>
                Submitting…
              </>
            ) : (
              <>
                <svg
                  className="h-4 w-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                  strokeWidth={2}
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    d="M12 4v16m8-8H4"
                  />
                </svg>
                Submit Task
              </>
            )}
          </button>

          {submitSuccess && (
            <span className="text-sm text-green-400 animate-fade-in">
              ✓ Task submitted successfully
            </span>
          )}
          {submitError && (
            <span className="text-sm text-red-400">
              ✕ {submitError}
            </span>
          )}
        </div>
      </form>

      {/* Divider */}
      <hr className="border-slate-700/60" />

      {/* Filters + Refresh */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            type="button"
            onClick={() => setFilterStatus("all")}
            className={`text-xs font-medium rounded-full px-3 py-1 transition-colors ${
              filterStatus === "all"
                ? "bg-slate-600 text-slate-100"
                : "bg-slate-800 text-slate-400 hover:text-slate-200"
            }`}
          >
            All ({tasks.length})
          </button>
          {(["in_progress", "pending", "review", "done", "failed"] as TaskStatus[]).map(
            (s) => {
              const count = statusCounts[s] || 0;
              if (count === 0 && filterStatus !== s) return null;
              const cfg = STATUS_CONFIG[s];
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => setFilterStatus(filterStatus === s ? "all" : s)}
                  className={`text-xs font-medium rounded-full px-3 py-1 transition-colors ${
                    filterStatus === s
                      ? "bg-blue-600/30 text-blue-300 ring-1 ring-blue-500/40"
                      : "bg-slate-800 text-slate-400 hover:text-slate-200"
                  }`}
                >
                  <span className="inline-flex items-center gap-1.5">
                    <StatusDot status={s} />
                    {cfg.label} ({count})
                  </span>
                </button>
              );
            }
          )}
        </div>

        <button
          type="button"
          onClick={fetchTasks}
          className="inline-flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 transition-colors"
        >
          <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
            />
          </svg>
          Refresh
        </button>
      </div>

      {/* Task List */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div
              key={i}
              className="bg-slate-800 border border-slate-700/60 rounded-lg h-16 animate-pulse"
            />
          ))}
        </div>
      ) : error ? (
        <div className="bg-red-900/20 border border-red-800/40 rounded-lg p-4 text-sm text-red-300">
          <p className="font-medium">Failed to load tasks</p>
          <p className="mt-1 text-red-400">{error}</p>
          <button
            type="button"
            onClick={fetchTasks}
            className="mt-3 text-xs text-red-300 underline hover:text-red-200"
          >
            Retry
          </button>
        </div>
      ) : filteredTasks.length === 0 ? (
        <div className="bg-slate-800 border border-slate-700/60 rounded-lg p-12 text-center">
          <svg
            className="mx-auto h-12 w-12 text-slate-600"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1}
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"
            />
          </svg>
          <p className="mt-3 text-sm text-slate-400">
            {filterStatus === "all"
              ? "No tasks yet. Submit your first task above to get started."
              : `No ${STATUS_CONFIG[filterStatus].label.toLowerCase()} tasks found.`}
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {filteredTasks.map((task) => (
            <TaskCard key={task.id} task={task} />
          ))}
        </div>
      )}
    </div>
  );
}