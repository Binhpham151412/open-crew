"use client";

import React, { useState, useCallback } from "react";
import { useFetch } from "@/hooks/useFetch";
import { StatusDot, Badge, Button, Card, CardHeader, CardTitle, EmptyState } from "@/components/ui";
import { timeAgo, formatTimestamp, agentDisplayName } from "@/lib/format";
import type { Task, TaskStatus, TimelineEvent } from "@/lib/types";

const STATUS_FILTERS: { value: TaskStatus | "all"; label: string }[] = [
  { value: "all", label: "All" },
  { value: "in_progress", label: "Working" },
  { value: "pending", label: "Pending" },
  { value: "review", label: "Review" },
  { value: "done", label: "Done" },
  { value: "failed", label: "Failed" },
];

export default function TasksPage() {
  const { data, loading, refetch } = useFetch<{ tasks: Task[] }>("/api/tasks", 8000);
  const tasks = data?.tasks ?? [];
  const [filter, setFilter] = useState<TaskStatus | "all">("all");
  const [newTaskText, setNewTaskText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitMsg, setSubmitMsg] = useState<{ type: "ok" | "err"; text: string } | null>(null);

  const filtered = filter === "all" ? tasks : tasks.filter((t) => t.status === filter);
  const statusCounts = tasks.reduce((acc, t) => { acc[t.status] = (acc[t.status] || 0) + 1; return acc; }, {} as Record<TaskStatus, number>);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = newTaskText.trim();
    if (!trimmed) {
      setSubmitMsg({ type: "err", text: "Task description is required" });
      return;
    }
    setSubmitting(true);
    setSubmitMsg(null);
    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title: trimmed, description: trimmed }),
      });
      if (!res.ok) throw new Error((await res.json().catch(() => null))?.error ?? `HTTP ${res.status}`);
      setNewTaskText("");
      setSubmitMsg({ type: "ok", text: "Task submitted" });
      setTimeout(() => setSubmitMsg(null), 3000);
      await refetch();
    } catch (err) {
      setSubmitMsg({ type: "err", text: err instanceof Error ? err.message : "Failed" });
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100 tracking-tight">Tasks</h1>
        <p className="text-sm text-slate-400 mt-1">Submit and track multi-agent tasks</p>
      </div>

      {/* New Task Form */}
      <Card>
        <CardHeader>
          <CardTitle>New Task</CardTitle>
        </CardHeader>
        <form onSubmit={handleSubmit} className="p-5 space-y-3">
          <textarea
            rows={3}
            value={newTaskText}
            onChange={(e) => { setNewTaskText(e.target.value); setSubmitMsg(null); }}
            placeholder='Describe the task... e.g. "Build user registration with email verification"'
            className="w-full rounded border border-slate-600 bg-slate-900 px-3 py-2.5 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 focus:outline-none resize-y transition-colors"
            disabled={submitting}
          />
          <div className="flex items-center gap-3">
            <Button type="submit" disabled={submitting}>
              {submitting ? "Submitting…" : "Submit Task"}
            </Button>
            <span className="text-xs text-slate-500">TechLead will auto-decompose and assign agents</span>
            {submitMsg && (
              <span className={`text-xs ${submitMsg.type === "ok" ? "text-green-400" : "text-red-400"}`}>
                {submitMsg.type === "ok" ? "✓" : "✕"} {submitMsg.text}
              </span>
            )}
          </div>
        </form>
      </Card>

      {/* Filters */}
      <div className="flex items-center gap-2 flex-wrap">
        {STATUS_FILTERS.map((f) => {
          const count = f.value === "all" ? tasks.length : (statusCounts[f.value] ?? 0);
          if (f.value !== "all" && count === 0 && filter !== f.value) return null;
          return (
            <button
              key={f.value}
              onClick={() => setFilter(filter === f.value ? "all" : f.value)}
              className={`text-xs font-medium rounded-full px-3 py-1 transition-colors ${
                filter === f.value
                  ? "bg-blue-600/30 text-blue-300 ring-1 ring-blue-500/40"
                  : "bg-slate-800 text-slate-400 hover:text-slate-200"
              }`}
            >
              {f.value !== "all" && <StatusDot status={f.value === "in_progress" ? "working" : f.value === "failed" ? "error" : f.value === "done" ? "online" : "offline"} className="mr-1.5 inline-flex" />}
              {f.label} ({count})
            </button>
          );
        })}
      </div>

      {/* Task List */}
      {loading ? (
        <div className="space-y-3">
          {[1, 2, 3].map((i) => (
            <div key={i} className="bg-slate-800 border border-slate-700 rounded-lg h-16 animate-pulse" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState
            title={filter === "all" ? "No tasks yet" : `No ${filter} tasks`}
            description={filter === "all" ? "Submit your first task above to get started." : "Try a different filter."}
          />
        </Card>
      ) : (
        <div className="space-y-2">
          {filtered.map((task) => <TaskCard key={task.id} task={task} />)}
        </div>
      )}
    </div>
  );
}

/* ─── Task Card ──────────────────────────────────────────────── */

function TaskCard({ task }: { task: Task }) {
  const [expanded, setExpanded] = useState(false);
  const timeline = task.timeline ?? [];

  return (
    <Card className="hover:border-slate-600 transition-colors">
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-slate-700/20 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
      >
        <StatusDot status={task.status === "in_progress" ? "working" : task.status === "failed" ? "error" : task.status === "done" ? "online" : "offline"} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm font-medium text-slate-100 truncate">{task.title}</span>
            <Badge variant={task.status}>{task.status.replace("_", " ")}</Badge>
          </div>
          {task.currentPhase && task.phaseNumber != null && task.totalPhases != null && (
            <p className="text-xs text-slate-400 mt-0.5">
              Phase {task.phaseNumber}/{task.totalPhases} ({task.currentPhase})
            </p>
          )}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {timeline.length > 0 && (
            <span className="text-[10px] font-mono bg-slate-700 text-slate-300 rounded-full px-2 py-0.5">
              {timeline.length} events
            </span>
          )}
          <span className="text-xs text-slate-500">{timeAgo(task.updatedAt ?? task.createdAt)}</span>
          <svg className={`h-4 w-4 text-slate-400 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>
      {expanded && (
        <div className="border-t border-slate-700 px-4 py-4 bg-slate-900/30">
          {task.assignedAgents && task.assignedAgents.length > 0 && (
            <p className="text-xs text-slate-400 mb-3">
              Agents: {task.assignedAgents.map(agentDisplayName).join(", ")}
            </p>
          )}
          {timeline.length === 0 ? (
            <p className="text-xs text-slate-500">No timeline events yet.</p>
          ) : (
            <Timeline events={timeline} />
          )}
        </div>
      )}
    </Card>
  );
}

function Timeline({ events }: { events: TimelineEvent[] }) {
  const sorted = [...events].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
  return (
    <div className="relative pl-5 border-l-2 border-slate-700 space-y-3">
      {sorted.map((ev) => (
        <div key={ev.id} className="relative">
          <div className={`absolute -left-[23px] top-1.5 w-2.5 h-2.5 rounded-full border-2 border-slate-900 ${
            ev.type === "success" ? "bg-green-500" : ev.type === "warning" ? "bg-amber-500" : ev.type === "error" ? "bg-red-500" : ev.type === "a2a_message" ? "bg-violet-500" : "bg-blue-500"
          }`} />
          <div className="text-[11px] font-mono text-slate-500 mb-0.5">{formatTimestamp(ev.timestamp)}</div>
          <div className="text-xs text-slate-200">
            <span className="font-medium text-blue-400">{agentDisplayName(ev.agent)}</span>: {ev.action}
          </div>
          <div className="text-xs text-slate-400 mt-0.5">{ev.detail}</div>
        </div>
      ))}
    </div>
  );
}
