"use client";

import * as React from "react";
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

interface AgentTokenEntry {
  date: string;
  [agentName: string]: number | string;
}

interface TokenChartProps {
  /** Optional override data. If not provided, uses built-in mock. */
  data?: AgentTokenEntry[];
  /** Price per token in USD (default: $0.000002 = $2 per 1M tokens) */
  pricePerToken?: number;
  /** Chart height in px (default: 260) */
  height?: number;
  /** Additional CSS classes */
  className?: string;
}

// ---------------------------------------------------------------------------
// Agent color palette — aligns with the design system
// ---------------------------------------------------------------------------

const AGENT_COLORS: Record<string, string> = {
  PO: "#3B82F6",       // blue-500
  PM: "#8B5CF6",       // violet-500
  BA: "#06B6D4",       // cyan-500
  "Solution Architect": "#14B8A6", // teal-500
  "Frontend Dev": "#F59E0B",       // amber-500
  "Backend Dev": "#EF4444",        // red-500
  "UIUX Reviewer": "#EC4899",      // pink-500
  "Security Reviewer": "#F97316",  // orange-500
  QA: "#22C55E",       // green-500
  DevOps: "#6366F1",   // indigo-500
  TechLead: "#A855F7", // purple-500
};

const FALLBACK_COLORS = [
  "#3B82F6", "#8B5CF6", "#06B6D4", "#14B8A6", "#F59E0B",
  "#EF4444", "#EC4899", "#F97316", "#22C55E", "#6366F1", "#A855F7",
];

// ---------------------------------------------------------------------------
// Default mock data (7 days)
// ---------------------------------------------------------------------------

function generateDefaultData(): AgentTokenEntry[] {
  const agents = [
    "PO", "PM", "BA", "Solution Architect", "Frontend Dev",
    "Backend Dev", "UIUX Reviewer", "Security Reviewer", "QA", "DevOps", "TechLead",
  ];

  const now = new Date();
  return Array.from({ length: 7 }, (_, i) => {
    const d = new Date(now);
    d.setDate(d.getDate() - (6 - i));
    const dayLabel = d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });

    const entry: AgentTokenEntry = { date: dayLabel };
    agents.forEach((agent) => {
      // Simulate realistic token usage — some agents idle some days
      const active = Math.random() > 0.25;
      entry[agent] = active ? Math.floor(Math.random() * 8000) + 200 : 0;
    });
    return entry;
  });
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Derive the list of agent names present in the data */
function getAgentNames(data: AgentTokenEntry[]): string[] {
  const names = new Set<string>();
  data.forEach((entry) => {
    Object.keys(entry).forEach((key) => {
      if (key !== "date") names.add(key);
    });
  });
  return Array.from(names);
}

/** Compute total tokens across all agents and days */
function computeTotal(data: AgentTokenEntry[]): number {
  return data.reduce((sum, entry) => {
    return (
      sum +
      Object.entries(entry)
        .filter(([k]) => k !== "date")
        .reduce((s, [, v]) => s + (typeof v === "number" ? v : 0), 0)
    );
  }, 0);
}

/** Format large numbers with commas */
function formatNumber(n: number): string {
  return n.toLocaleString("en-US");
}

/** Format USD cost */
function formatCost(n: number): string {
  if (n < 0.01) return `$${n.toFixed(4)}`;
  if (n < 1) return `$${n.toFixed(2)}`;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

// ---------------------------------------------------------------------------
// Custom Tooltip
// ---------------------------------------------------------------------------

interface TooltipPayloadItem {
  name: string;
  value: number;
  color: string;
  dataKey: string;
}

function CustomTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const nonZero = payload.filter((p) => p.value > 0);
  const dayTotal = nonZero.reduce((s, p) => s + p.value, 0);

  return (
    <div className="rounded-lg border border-slate-600 bg-slate-800 p-3 shadow-xl text-xs min-w-[180px]">
      <p className="font-semibold text-slate-200 mb-1.5">{label}</p>
      <div className="space-y-1">
        {nonZero.map((item) => (
          <div key={item.dataKey} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5">
              <span
                className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-slate-300 truncate max-w-[120px]">{item.name}</span>
            </span>
            <span className="font-mono text-slate-100 tabular-nums">
              {formatNumber(item.value)}
            </span>
          </div>
        )}
      </div>
      <div className="mt-2 pt-1.5 border-t border-slate-600 flex justify-between">
        <span className="text-slate-400">Day total</span>
        <span className="font-mono font-medium text-slate-100 tabular-nums">
          {formatNumber(dayTotal)}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function TokenChart({
  data: dataProp,
  pricePerToken = 0.000002,
  height = 260,
  className,
}: TokenChartProps) {
  const data = React.useMemo(() => dataProp ?? generateDefaultData(), [dataProp]);
  const agentNames = React.useMemo(() => getAgentNames(data), [data]);
  const totalTokens = React.useMemo(() => computeTotal(data), [data]);
  const estimatedCost = totalTokens * pricePerToken;

  return (
    <section
      className={`rounded-xl border border-slate-700/60 bg-slate-800/50 backdrop-blur p-4 lg:p-5 ${className ?? ""}`}
    >
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-end justify-between gap-2 mb-4">
        <div>
          <h3 className="text-sm font-semibold text-slate-200">Token Usage</h3>
          <p className="text-xs text-slate-400 mt-0.5">Last 7 days &middot; stacked by agent</p>
        </div>

        {/* Totals */}
        <div className="flex items-center gap-4 text-xs">
          <div className="text-right">
            <span className="block text-slate-400 leading-none">Total</span>
            <span className="font-mono font-semibold text-slate-100 text-sm tabular-nums">
              {formatNumber(totalTokens)}
            </span>
            <span className="text-slate-400 ml-1">tokens</span>
          </div>
          <div className="h-8 w-px bg-slate-700" aria-hidden />
          <div className="text-right">
            <span className="block text-slate-400 leading-none">Est. cost</span>
            <span className="font-mono font-semibold text-green-400 text-sm tabular-nums">
              {formatCost(estimatedCost)}
            </span>
          </div>
        </div>
      </div>

      {/* Chart */}
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={data} margin={{ top: 4, right: 4, left: -12, bottom: 0 }}>
          <CartesianGrid
            strokeDasharray="3 3"
            stroke="#334155" /* slate-700 */
            vertical={false}
          />
          <XAxis
            dataKey="date"
            tick={{ fill: "#94A3B8", fontSize: 11 }}
            tickLine={false}
            axisLine={{ stroke: "#334155" }}
            interval={0}
          />
          <YAxis
            tick={{ fill: "#94A3B8", fontSize: 11 }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) =>
              v >= 1000 ? `${(v / 1000).toFixed(0)}k` : `${v}`
            }
          />
          <Tooltip
            content={<CustomTooltip />}
            cursor={{ fill: "rgba(148,163,184,0.06)" }}
          />
          <Legend
            verticalAlign="bottom"
            iconType="square"
            iconSize={10}
            wrapperStyle={{
              paddingTop: 12,
              fontSize: 11,
              color: "#94A3B8",
            }}
            formatter={(value: string) => (
              <span className="text-slate-400 ml-1">{value}</span>
            )}
          />
          {agentNames.map((name, idx) => (
            <Bar
              key={name}
              dataKey={name}
              stackId="tokens"
              fill={AGENT_COLORS[name] ?? FALLBACK_COLORS[idx % FALLBACK_COLORS.length]}
              radius={
                idx === agentNames.length - 1 ? [3, 3, 0, 0] : [0, 0, 0, 0]
              }
            />
          ))}
        </BarChart>
      </ResponsiveContainer>
    </section>
  );
}

export default TokenChart;