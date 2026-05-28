"use client";

import { useEffect, useState, useCallback } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Agent {
  id: string;
  name: string;
  display_name: string;
  status: "online" | "offline" | "working" | "error";
  port: number;
  tokens_today: number;
  queue_size: number;
  last_heartbeat: string | null;
}

interface Task {
  id: string;
  title: string;
  status: "pending" | "in_progress" | "review" | "done" | "failed";
  created_at: string;
  updated_at: string;
  assigned_agents: string[];
  progress: number;
}

interface DailyTokenStat {
  date: string;
  [agentName: string]: number | string;
}

interface StatsResponse {
  total_tokens: number;
  estimated_cost: number;
  daily_breakdown: DailyTokenStat[];
  agent_colors: Record<string, string>;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<string, { dot: string; badge: string }> = {
  online: {
    dot: "bg-green-500 shadow-[0_0_6px_rgba(22,163,74,0.6)]",
    badge: "bg-green-500/15 text-green-400 border border-green-500/30",
  },
  working: {
    dot: "bg-amber-500 shadow-[0_0_6px_rgba(217,119,6,0.6)] animate-pulse",
    badge: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  },
  offline: {
    dot: "bg-slate-500",
    badge: "bg-slate-500/15 text-slate-400 border border-slate-500/30",
  },
  error: {
    dot: "bg-red-500 shadow-[0_0_6px_rgba(220,38,38,0.6)]",
    badge: "bg-red-500/15 text-red-400 border border-red-500/30",
  },
};

const TASK_STATUS_STYLES: Record<string, string> = {
  pending: "bg-slate-500/15 text-slate-300 border border-slate-500/30",
  in_progress: "bg-blue-500/15 text-blue-400 border border-blue-500/30",
  review: "bg-amber-500/15 text-amber-400 border border-amber-500/30",
  done: "bg-green-500/15 text-green-400 border border-green-500/30",
  failed: "bg-red-500/15 text-red-400 border border-red-500/30",
};

const DEFAULT_AGENT_COLORS: Record<string, string> = {
  po: "#818CF8",
  pm: "#38BDF8",
  ba: "#34D399",
  "solution-architect": "#A78BFA",
  "frontend-dev": "#22D3EE",
  "backend-dev": "#F472B6",
  "uiux-reviewer": "#FBBF24",
  "security-reviewer": "#F87171",
  qa: "#4ADE80",
  devops: "#FB923C",
  techlead: "#C084FC",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return String(n);
}

function timeAgo(iso: string): string {
  const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: string }) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.offline;
  return <span className={`inline-block w-2.5 h-2.5 rounded-full ${style.dot}`} />;
}

function AgentStatusCard({ agent }: { agent: Agent }) {
  const style = STATUS_STYLES[agent.status] ?? STATUS_STYLES.offline;

  return (
    <div className="bg-slate-800 border border-slate-700/60 rounded-lg p-4 flex flex-col gap-3 hover:border-slate-600/80 transition-colors">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5 min-w-0">
          <StatusDot status={agent.status} />
          <span className="font-medium text-slate-100 truncate">
            {agent.display_name}
          </span>
        </div>
        <span
          className={`text-[11px] font-medium px-2 py-0.5 rounded-full capitalize ${style.badge}`}
        >
          {agent.status}
        </span>
      </div>

      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>
          Tokens today:{" "}
          <span className="text-slate-200 font-medium tabular-nums">
            {formatTokens(agent.tokens_today)}
          </span>
        </span>
        {agent.queue_size > 0 && (
          <span className="flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-blue-400" />
            Queue: {agent.queue_size}
          </span>
        )}
      </div>
    </div>
  );
}

function TaskStatusBadge({ status }: { status: string }) {
  return (
    <span
      className={`text-[11px] font-medium px-2 py-0.5 rounded-full capitalize whitespace-nowrap ${
        TASK_STATUS_STYLES[status] ?? TASK_STATUS_STYLES.pending
      }`}
    >
      {status.replace("_", " ")}
    </span>
  );
}

function RecentTaskRow({ task }: { task: Task }) {
  return (
    <div className="flex items-center justify-between gap-3 py-3 border-b border-slate-700/40 last:border-0 group">
      <div className="min-w-0 flex-1">
        <p className="text-sm text-slate-100 font-medium truncate group-hover:text-white transition-colors">
          {task.title}
        </p>
        <p className="text-xs text-slate-400 mt-0.5">
          {task.assigned_agents.length > 0 && (
            <span className="mr-2">
              {task.assigned_agents.slice(0, 3).join(", ")}
              {task.assigned_agents.length > 3 &&
                ` +${task.assigned_agents.length - 3}`}
            </span>
          )}
        </p>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <TaskStatusBadge status={task.status} />
        <span className="text-xs text-slate-500 tabular-nums w-14 text-right">
          {timeAgo(task.updated_at)}
        </span>
      </div>
    </div>
  );
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl">
      <p className="text-xs text-slate-400 mb-1.5">{label}</p>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center gap-2 text-xs">
          <span
            className="w-2 h-2 rounded-full shrink-0"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-slate-300 capitalize">{entry.name}</span>
          <span className="text-slate-100 font-medium tabular-nums ml-auto">
            {formatTokens(entry.value)}
          </span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Skeleton loaders
// ---------------------------------------------------------------------------

function CardSkeleton() {
  return (
    <div className="bg-slate-800 border border-slate-700/60 rounded-lg p-4 animate-pulse">
      <div className="flex items-center gap-2.5">
        <div className="w-2.5 h-2.5 rounded-full bg-slate-700" />
        <div className="h-4 w-24 bg-slate-700 rounded" />
      </div>
      <div className="h-3 w-20 bg-slate-700/60 rounded mt-3" />
    </div>
  );
}

function TaskSkeleton() {
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-700/40 animate-pulse">
      <div>
        <div className="h-4 w-40 bg-slate-700 rounded" />
        <div className="h-3 w-24 bg-slate-700/60 rounded mt-1.5" />
      </div>
      <div className="h-5 w-16 bg-slate-700 rounded-full" />
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="h-64 flex items-end gap-3 px-4 animate-pulse">
      {Array.from({ length: 7 }).map((_, i) => (
        <div
          key={i}
          className="flex-1 bg-slate-700/60 rounded-t"
          style={{ height: `${30 + Math.random() * 60}%` }}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Custom Legend
// ---------------------------------------------------------------------------

function ChartLegend({
  payload,
}: {
  payload?: Array<{ value: string; color: string }>;
}) {
  if (!payload) return null;
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 justify-center mt-2">
      {payload.map((entry) => (
        <div key={entry.value} className="flex items-center gap-1.5 text-xs">
          <span
            className="w-2.5 h-2.5 rounded-sm shrink-0"
            style={{ backgroundColor: entry.color }}
          />
          <span className="text-slate-400 capitalize">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [stats, setStats] = useState<StatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    try {
      const [agentsRes, tasksRes, statsRes] = await Promise.all([
        fetch("/api/agents", { cache: "no-store" }),
        fetch("/api/tasks", { cache: "no-store" }),
        fetch("/api/stats", { cache: "no-store" }),
      ]);

      if (!agentsRes.ok || !tasksRes.ok || !statsRes.ok) {
        throw new Error("Failed to fetch dashboard data");
      }

      const [agentsData, tasksData, statsData] = await Promise.all([
        agentsRes.json(),
        tasksRes.json(),
        statsRes.json(),
      ]);

      setAgents(agentsData);
      setTasks(tasksData);
      setStats(statsData);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();

    // Auto-refresh every 15 seconds
    const interval = setInterval(fetchData, 15_000);
    return () => clearInterval(interval);
  }, [fetchData]);

  // Derive chart data & agent keys
  const agentKeys = agents.map((a) => a.name);
  const agentColors = stats?.agent_colors ?? DEFAULT_AGENT_COLORS;
  const dailyData = stats?.daily_breakdown ?? [];
  const totalTokens = stats?.total_tokens ?? 0;
  const estimatedCost = stats?.estimated_cost ?? 0;

  // Recent tasks — sorted by updated_at descending, take top 8
  const recentTasks = [...tasks]
    .sort(
      (a, b) =>
        new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
    )
    .slice(0, 8);

  // Agent summary
  const onlineCount = agents.filter(
    (a) => a.status === "online" || a.status === "working"
  ).length;

  return (
    <div className="space-y-6 max-w-7xl mx-auto">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-50 tracking-tight">
            Dashboard
          </h1>
          <p className="text-sm text-slate-400 mt-0.5">
            {loading ? (
              "Loading agents…"
            ) : error ? (
              <span className="text-red-400">Error loading data</span>
            ) : (
              <>
                {onlineCount} of {agents.length} agents online
              </>
            )}
          </p>
        </div>
        <button
          onClick={fetchData}
          disabled={loading}
          className="text-xs text-slate-400 hover:text-slate-200 border border-slate-700 hover:border-slate-600 rounded-md px-3 py-1.5 transition-colors disabled:opacity-50"
        >
          ↻ Refresh
        </button>
      </div>

      {/* ── Agent Status Grid ─────────────────────────────────────── */}
      <section>
        <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
          Agent Status
        </h2>
        {loading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {Array.from({ length: 8 }).map((_, i) => (
              <CardSkeleton key={i} />
            ))}
          </div>
        ) : error ? (
          <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-4 text-sm text-red-400">
            Failed to load agents: {error}
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
            {agents.map((agent) => (
              <AgentStatusCard key={agent.id} agent={agent} />
            ))}
          </div>
        )}
      </section>

      {/* ── Recent Tasks + Token Chart ────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Recent Tasks — 2 columns */}
        <section className="lg:col-span-2">
          <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider mb-3">
            Recent Tasks
          </h2>
          <div className="bg-slate-800 border border-slate-700/60 rounded-lg p-4">
            {loading ? (
              <div>
                {Array.from({ length: 5 }).map((_, i) => (
                  <TaskSkeleton key={i} />
                ))}
              </div>
            ) : error ? (
              <div className="text-sm text-red-400">Failed to load tasks.</div>
            ) : recentTasks.length === 0 ? (
              <div className="text-center py-8">
                <p className="text-slate-500 text-sm">No tasks yet</p>
                <p className="text-slate-600 text-xs mt-1">
                  Submit a task from the Tasks page
                </p>
              </div>
            ) : (
              <div>
                {recentTasks.map((task) => (
                  <RecentTaskRow key={task.id} task={task} />
                ))}
              </div>
            )}
          </div>
        </section>

        {/* Token Chart — 3 columns */}
        <section className="lg:col-span-3">
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-medium text-slate-400 uppercase tracking-wider">
              Token Usage (7 days)
            </h2>
            {stats && (
              <div className="text-xs text-slate-400 flex items-center gap-4">
                <span>
                  Total:{" "}
                  <span className="text-slate-200 font-medium">
                    {formatTokens(totalTokens)}
                  </span>
                </span>
                <span>
                  Est. cost:{" "}
                  <span className="text-slate-200 font-medium">
                    ${estimatedCost.toFixed(2)}
                  </span>
                </span>
              </div>
            )}
          </div>
          <div className="bg-slate-800 border border-slate-700/60 rounded-lg p-4">
            {loading ? (
              <ChartSkeleton />
            ) : error ? (
              <div className="text-sm text-red-400">
                Failed to load token stats.
              </div>
            ) : dailyData.length === 0 ? (
              <div className="h-64 flex items-center justify-center">
                <p className="text-slate-500 text-sm">No token data available</p>
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={dailyData}
                  margin={{ top: 4, right: 4, left: -12, bottom: 0 }}
                  barCategoryGap="20%"
                >
                  <CartesianGrid
                    strokeDasharray="3 3"
                    stroke="#334155"
                    vertical={false}
                  />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 11, fill: "#94A3B8" }}
                    tickLine={false}
                    axisLine={{ stroke: "#334155" }}
                  />
                  <YAxis
                    tick={{ fontSize: 11, fill: "#94A3B8" }}
                    tickLine={false}
                    axisLine={false}
                    tickFormatter={(v) => formatTokens(v)}
                  />
                  <Tooltip
                    content={<CustomTooltip />}
                    cursor={{ fill: "rgba(148,163,184,0.08)" }}
                  />
                  <Legend content={<ChartLegend />} />
                  {agentKeys.map((name) => (
                    <Bar
                      key={name}
                      dataKey={name}
                      stackId="tokens"
                      fill={agentColors[name] ?? DEFAULT_AGENT_COLORS[name] ?? "#64748B"}
                      radius={
                        agentKeys.indexOf(name) === agentKeys.length - 1
                          ? [2, 2, 0, 0]
                          : [0, 0, 0, 0]
                      }
                    />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </section>
      </div>
    </div>
  );
}