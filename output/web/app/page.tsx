"use client";

import Link from "next/link";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from "recharts";
import { useFetch } from "@/hooks/useFetch";
import { StatusDot, Badge, Card, CardHeader, CardTitle, Button, EmptyState } from "@/components/ui";
import { formatTokens, formatCost, timeAgo, agentDisplayName } from "@/lib/format";
import type { Agent, Task, StatsResponse } from "@/lib/types";

export default function DashboardPage() {
  const { data: agentsData, loading: agentsLoading } = useFetch<{ agents: Agent[] }>("/api/agents", 15000);
  const { data: tasksData, loading: tasksLoading } = useFetch<{ tasks: Task[] }>("/api/tasks", 15000);
  const { data: stats, loading: statsLoading } = useFetch<StatsResponse>("/api/stats", 15000);

  const agents = agentsData?.agents ?? [];
  const tasks = tasksData?.tasks ?? [];
  const loading = agentsLoading || tasksLoading || statsLoading;

  const onlineCount = agents.filter((a) => a.status === "online" || a.status === "working").length;
  const recentTasks = [...tasks]
    .sort((a, b) => new Date(b.updatedAt ?? b.createdAt).getTime() - new Date(a.updatedAt ?? a.createdAt).getTime())
    .slice(0, 5);

  return (
    <div className="space-y-6">
      <div className="page-header">
        <h1 className="text-2xl font-semibold text-slate-100 tracking-tight">Dashboard</h1>
        <p className="text-sm text-slate-400 mt-1">System overview and agent activity</p>
      </div>

      {/* Agent Status + Token Chart */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        {/* Agent Status — 3 cols */}
        <Card className="lg:col-span-3">
          <CardHeader>
            <CardTitle>Agent Status</CardTitle>
            <Badge variant="success">{onlineCount} online</Badge>
          </CardHeader>
          <div className="divide-y divide-slate-700/40">
            {loading ? (
              Array.from({ length: 6 }).map((_, i) => (
                <div key={i} className="flex items-center gap-3 px-4 py-3 animate-pulse">
                  <div className="h-2.5 w-2.5 rounded-full bg-slate-700" />
                  <div className="h-4 w-32 bg-slate-700 rounded" />
                  <div className="ml-auto h-4 w-20 bg-slate-700 rounded" />
                </div>
              ))
            ) : agents.length === 0 ? (
              <EmptyState title="No agents running" />
            ) : (
              agents.map((agent) => (
                <div
                  key={agent.id}
                  className="flex items-center gap-3 px-4 py-3 hover:bg-slate-700/30 transition-colors"
                >
                  <StatusDot status={agent.status} />
                  <span className="font-medium text-sm text-slate-100 flex-1">
                    {agent.displayName}
                  </span>
                  <Badge variant={agent.status}>{agent.status}</Badge>
                  <span className="text-xs font-mono text-slate-400 w-24 text-right">
                    {agent.health?.queueSize != null && agent.health.queueSize > 0
                      ? `Queue: ${agent.health.queueSize}`
                      : agent.health?.latencyMs != null
                        ? `${agent.health.latencyMs}ms`
                        : "—"}
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>

        {/* Token Chart — 2 cols */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Token Usage</CardTitle>
            <span className="text-xs text-slate-400 font-mono">7 days</span>
          </CardHeader>
          <div className="p-4">
            {statsLoading ? (
              <div className="h-48 flex items-end gap-2 px-2 animate-pulse">
                {Array.from({ length: 7 }).map((_, i) => (
                  <div key={i} className="flex-1 bg-slate-700 rounded-t" style={{ height: `${30 + Math.random() * 60}%` }} />
                ))}
              </div>
            ) : (stats?.dailyUsage?.length ?? 0) === 0 ? (
              <div className="h-48 flex items-center justify-center text-slate-500 text-sm">
                No token data
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={200}>
                <BarChart data={stats!.dailyUsage} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#94A3B8" }} tickLine={false} axisLine={{ stroke: "#334155" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#94A3B8" }} tickLine={false} axisLine={false} tickFormatter={(v: number) => formatTokens(v)} />
                  <Tooltip
                    content={<ChartTooltip />}
                    cursor={{ fill: "rgba(148,163,184,0.08)" }}
                  />
                  <Legend content={<ChartLegend />} />
                  {stats!.agents.map((a, idx) => (
                    <Bar key={a.name} dataKey={a.name} stackId="tokens" fill={AGENT_COLORS[idx % AGENT_COLORS.length]} radius={idx === stats!.agents.length - 1 ? [2, 2, 0, 0] : [0, 0, 0, 0]} />
                  ))}
                </BarChart>
              </ResponsiveContainer>
            )}
            <div className="flex items-baseline gap-3 mt-4 pt-4 border-t border-slate-700">
              <span className="text-xl font-semibold font-mono text-slate-100">
                {formatTokens(stats?.totalTokens ?? 0)}
              </span>
              <span className="text-xs text-slate-400">
                total tokens &middot; est. {formatCost(stats?.estimatedCostUsd ?? 0)}
              </span>
            </div>
          </div>
        </Card>
      </div>

      {/* Recent Tasks */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Tasks</CardTitle>
          <Link href="/tasks">
            <Button variant="ghost" size="sm">View all &rarr;</Button>
          </Link>
        </CardHeader>
        <div className="divide-y divide-slate-700/40">
          {loading ? (
            Array.from({ length: 3 }).map((_, i) => (
              <div key={i} className="px-4 py-3 animate-pulse">
                <div className="h-4 w-48 bg-slate-700 rounded" />
                <div className="h-3 w-24 bg-slate-700/60 rounded mt-1.5" />
              </div>
            ))
          ) : recentTasks.length === 0 ? (
            <EmptyState title="No tasks yet" description="Submit a task from the Tasks page" />
          ) : (
            recentTasks.map((task) => <TaskRow key={task.id} task={task} />)
          )}
        </div>
      </Card>
    </div>
  );
}

/* ─── Sub-components ─────────────────────────────────────────── */

function TaskRow({ task }: { task: Task }) {
  return (
    <div className="flex items-center gap-3 px-4 py-3 hover:bg-slate-700/30 transition-colors group">
      <span className="text-xs font-mono text-slate-500 w-10 shrink-0">
        {task.id.slice(-5)}
      </span>
      <span className="text-sm font-medium text-slate-100 flex-1 truncate group-hover:text-white transition-colors">
        {task.title}
      </span>
      <Badge variant={task.status}>{task.status.replace("_", " ")}</Badge>
      <span className="text-xs text-slate-500 font-mono w-16 text-right">
        {timeAgo(task.updatedAt ?? task.createdAt)}
      </span>
    </div>
  );
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name: string; value: number; color: string }>; label?: string }) {
  if (!active || !payload || payload.length === 0) return null;
  return (
    <div className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 shadow-xl text-xs">
      <p className="text-slate-400 mb-1.5">{label}</p>
      {payload.map((entry) => (
        <div key={entry.name} className="flex items-center gap-2">
          <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-300 capitalize">{entry.name}</span>
          <span className="text-slate-100 font-medium font-mono ml-auto">{formatTokens(entry.value)}</span>
        </div>
      ))}
    </div>
  );
}

function ChartLegend({ payload }: { payload?: Array<{ value: string; color: string }> }) {
  if (!payload) return null;
  return (
    <div className="flex flex-wrap gap-x-3 gap-y-1 justify-center mt-2">
      {payload.map((entry) => (
        <div key={entry.value} className="flex items-center gap-1 text-[11px]">
          <span className="w-2 h-2 rounded-sm shrink-0" style={{ backgroundColor: entry.color }} />
          <span className="text-slate-400 capitalize">{entry.value}</span>
        </div>
      ))}
    </div>
  );
}

const AGENT_COLORS = ["#3B82F6", "#8B5CF6", "#06B6D4", "#14B8A6", "#F59E0B", "#EF4444", "#EC4899", "#F97316", "#22C55E", "#6366F1", "#A855F7"];
