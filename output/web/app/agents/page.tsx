"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  RefreshCw,
  Play,
  FileText,
  RotateCw,
  ChevronDown,
  ChevronUp,
  Search,
  Filter,
  Zap,
  Cpu,
  Wrench,
  Settings2,
} from "lucide-react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type AgentStatus = "online" | "offline" | "working" | "error";

interface AgentTool {
  name: string;
  description?: string;
}

interface Agent {
  id: string;
  name: string;
  display_name: string;
  status: AgentStatus;
  model: string;
  port: number;
  tools: AgentTool[];
  temperature: number;
  max_tokens: number;
  enabled: boolean;
  tokens_today: number;
  queue_size: number;
  uptime_seconds?: number;
}

interface AgentSettings {
  model: string;
  temperature: number;
  max_tokens: number;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AVAILABLE_MODELS = [
  "mimo-v2.5-pro",
  "mimo-v2.5-mini",
  "mimo-v2.5-flash",
  "gpt-4o",
  "gpt-4o-mini",
  "claude-3.5-sonnet",
  "claude-3-haiku",
];

const STATUS_CONFIG: Record<
  AgentStatus,
  { color: string; bg: string; ring: string; label: string }
> = {
  online: {
    color: "bg-green-500",
    bg: "bg-green-500/10",
    ring: "ring-green-500/30",
    label: "Online",
  },
  offline: {
    color: "bg-slate-500",
    bg: "bg-slate-500/10",
    ring: "ring-slate-500/30",
    label: "Offline",
  },
  working: {
    color: "bg-amber-500",
    bg: "bg-amber-500/10",
    ring: "ring-amber-500/30",
    label: "Working",
  },
  error: {
    color: "bg-red-500",
    bg: "bg-red-500/10",
    ring: "ring-red-500/30",
    label: "Error",
  },
};

// ---------------------------------------------------------------------------
// Helper: format uptime
// ---------------------------------------------------------------------------

function formatUptime(seconds?: number): string {
  if (!seconds) return "—";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 24) {
    const d = Math.floor(h / 24);
    return `${d}d ${h % 24}h`;
  }
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return n.toString();
}

// ---------------------------------------------------------------------------
// StatusDot component
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: AgentStatus }) {
  const cfg = STATUS_CONFIG[status];
  return (
    <span className="relative inline-flex items-center justify-center">
      <span
        className={`absolute inline-flex h-2.5 w-2.5 rounded-full ${cfg.color} opacity-75 ${
          status === "working" ? "animate-ping" : ""
        }`}
      />
      <span
        className={`relative inline-flex h-2.5 w-2.5 rounded-full ${cfg.color}`}
      />
    </span>
  );
}

// ---------------------------------------------------------------------------
// Toggle component
// ---------------------------------------------------------------------------

function Toggle({
  checked,
  onChange,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900 ${
        checked ? "bg-blue-600" : "bg-slate-600"
      }`}
    >
      <span
        className={`pointer-events-none inline-block h-5 w-5 rounded-full bg-white shadow-lg ring-0 transition-transform duration-200 ease-in-out ${
          checked ? "translate-x-5" : "translate-x-0"
        }`}
      />
    </button>
  );
}

// ---------------------------------------------------------------------------
// AgentCard component
// ---------------------------------------------------------------------------

function AgentCard({
  agent,
  onTest,
  onRestart,
  onSettingsChange,
}: {
  agent: Agent;
  onTest: (id: string) => void;
  onRestart: (id: string) => void;
  onSettingsChange: (id: string, settings: AgentSettings) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [testing, setTesting] = useState(false);
  const [restarting, setRestarting] = useState(false);

  // Local editable settings
  const [model, setModel] = useState(agent.model);
  const [temperature, setTemperature] = useState(agent.temperature);
  const [maxTokens, setMaxTokens] = useState(agent.max_tokens);
  const [enabled, setEnabled] = useState(agent.enabled);
  const [dirty, setDirty] = useState(false);

  const cfg = STATUS_CONFIG[agent.status];

  const markDirty = () => {
    if (!dirty) setDirty(true);
  };

  const handleTest = async () => {
    setTesting(true);
    await onTest(agent.id);
    setTesting(false);
  };

  const handleRestart = async () => {
    setRestarting(true);
    await onRestart(agent.id);
    setRestarting(false);
  };

  const handleSave = () => {
    onSettingsChange(agent.id, {
      model,
      temperature,
      max_tokens: maxTokens,
      enabled,
    });
    setDirty(false);
  };

  return (
    <div
      className={`group relative rounded-lg border transition-all duration-200 ${
        agent.enabled
          ? "border-slate-700/80 hover:border-slate-600 bg-slate-800/60 hover:bg-slate-800/80"
          : "border-slate-800/60 bg-slate-900/40 opacity-70 hover:opacity-90"
      }`}
    >
      {/* Card Header */}
      <div className="p-4 pb-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2.5 min-w-0">
            <StatusDot status={agent.status} />
            <div className="min-w-0">
              <h3 className="text-sm font-semibold text-slate-100 truncate">
                {agent.display_name}
              </h3>
              <p className="text-xs text-slate-400 mt-0.5">
                Port {agent.port} &middot; {cfg.label}
              </p>
            </div>
          </div>

          {/* Tokens badge */}
          <div className="flex items-center gap-1 text-xs text-slate-400 shrink-0 bg-slate-800 rounded px-2 py-1">
            <Zap className="h-3 w-3 text-amber-400" />
            <span>{formatTokens(agent.tokens_today)}</span>
          </div>
        </div>

        {/* Model & Queue */}
        <div className="mt-3 flex flex-wrap gap-2">
          <span className="inline-flex items-center gap-1.5 text-xs bg-blue-500/10 text-blue-300 border border-blue-500/20 rounded px-2 py-0.5">
            <Cpu className="h-3 w-3" />
            {agent.model}
          </span>
          {agent.queue_size > 0 && (
            <span className="inline-flex items-center gap-1 text-xs bg-amber-500/10 text-amber-300 border border-amber-500/20 rounded px-2 py-0.5">
              Queue: {agent.queue_size}
            </span>
          )}
          <span className="inline-flex items-center gap-1 text-xs text-slate-400">
            Uptime: {formatUptime(agent.uptime_seconds)}
          </span>
        </div>

        {/* Tools */}
        {agent.tools.length > 0 && (
          <div className="mt-3">
            <div className="flex items-center gap-1.5 text-xs text-slate-400 mb-1.5">
              <Wrench className="h-3 w-3" />
              <span>Tools</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {agent.tools.map((tool) => (
                <span
                  key={tool.name}
                  title={tool.description || tool.name}
                  className="inline-block text-[11px] font-mono bg-slate-700/60 text-slate-300 border border-slate-600/40 rounded px-1.5 py-0.5 cursor-default hover:bg-slate-700 transition-colors"
                >
                  {tool.name}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Expand / Collapse Toggle */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-center gap-1.5 text-xs text-slate-400 hover:text-slate-200 py-2 border-t border-slate-700/40 hover:bg-slate-700/20 transition-colors rounded-b-lg"
      >
        <Settings2 className="h-3.5 w-3.5" />
        {expanded ? (
          <>
            Hide Settings <ChevronUp className="h-3 w-3" />
          </>
        ) : (
          <>
            Show Settings <ChevronDown className="h-3 w-3" />
          </>
        )}
      </button>

      {/* Settings Panel */}
      {expanded && (
        <div className="border-t border-slate-700/40 p-4 space-y-4 bg-slate-900/40 rounded-b-lg">
          {/* Model Dropdown */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Model
            </label>
            <select
              value={model}
              onChange={(e) => {
                setModel(e.target.value);
                markDirty();
              }}
              className="w-full bg-slate-800 border border-slate-600/60 text-sm text-slate-200 rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-colors"
            >
              {AVAILABLE_MODELS.map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          {/* Temperature Slider */}
          <div>
            <label className="flex items-center justify-between text-xs font-medium text-slate-300 mb-1.5">
              <span>Temperature</span>
              <span className="font-mono text-blue-400">{temperature.toFixed(2)}</span>
            </label>
            <input
              type="range"
              min={0}
              max={2}
              step={0.01}
              value={temperature}
              onChange={(e) => {
                setTemperature(parseFloat(e.target.value));
                markDirty();
              }}
              className="w-full h-1.5 bg-slate-700 rounded-full appearance-none cursor-pointer accent-blue-600 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:bg-blue-500 [&::-webkit-slider-thumb]:shadow-md [&::-webkit-slider-thumb]:border-2 [&::-webkit-slider-thumb]:border-blue-400"
            />
            <div className="flex justify-between text-[10px] text-slate-500 mt-1">
              <span>0 (precise)</span>
              <span>1 (balanced)</span>
              <span>2 (creative)</span>
            </div>
          </div>

          {/* Max Tokens Input */}
          <div>
            <label className="block text-xs font-medium text-slate-300 mb-1.5">
              Max Tokens
            </label>
            <input
              type="number"
              min={256}
              max={131072}
              step={256}
              value={maxTokens}
              onChange={(e) => {
                setMaxTokens(parseInt(e.target.value, 10) || 4096);
                markDirty();
              }}
              className="w-full bg-slate-800 border border-slate-600/60 text-sm text-slate-200 font-mono rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-colors"
            />
          </div>

          {/* Enabled Toggle */}
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-slate-300">
              Enabled
            </label>
            <Toggle
              checked={enabled}
              onChange={(v) => {
                setEnabled(v);
                markDirty();
              }}
            />
          </div>

          {/* Save button (only if dirty) */}
          {dirty && (
            <button
              onClick={handleSave}
              className="w-full bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium rounded px-3 py-2 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:ring-offset-2 focus:ring-offset-slate-900"
            >
              Save Changes
            </button>
          )}
        </div>
      )}

      {/* Action Buttons */}
      <div className="px-4 pb-4 pt-2 flex gap-2">
        <button
          onClick={handleTest}
          disabled={testing || agent.status === "offline"}
          className="flex-1 inline-flex items-center justify-center gap-1.5 text-xs font-medium bg-green-600/10 text-green-400 border border-green-600/30 hover:bg-green-600/20 rounded px-3 py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-green-500/40"
        >
          {testing ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <Play className="h-3.5 w-3.5" />
          )}
          Test
        </button>

        <Link
          href={`/logs?agent=${agent.id}`}
          className="flex-1 inline-flex items-center justify-center gap-1.5 text-xs font-medium bg-slate-700/40 text-slate-300 border border-slate-600/40 hover:bg-slate-700/60 rounded px-3 py-2 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-500/40"
        >
          <FileText className="h-3.5 w-3.5" />
          Logs
        </Link>

        <button
          onClick={handleRestart}
          disabled={restarting || agent.status === "offline"}
          className="flex-1 inline-flex items-center justify-center gap-1.5 text-xs font-medium bg-amber-600/10 text-amber-400 border border-amber-600/30 hover:bg-amber-600/20 rounded px-3 py-2 transition-colors disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-amber-500/40"
        >
          {restarting ? (
            <RefreshCw className="h-3.5 w-3.5 animate-spin" />
          ) : (
            <RotateCw className="h-3.5 w-3.5" />
          )}
          Restart
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Agents Page
// ---------------------------------------------------------------------------

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<AgentStatus | "all">("all");
  const [refreshing, setRefreshing] = useState(false);

  // ----- Fetch agents -----
  const fetchAgents = useCallback(async () => {
    try {
      setRefreshing(true);
      const res = await fetch("/api/agents", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data: Agent[] = await res.json();
      setAgents(data);
      setError(null);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Failed to fetch agents");
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    fetchAgents();
    // Auto-refresh every 10s
    const interval = setInterval(fetchAgents, 10_000);
    return () => clearInterval(interval);
  }, [fetchAgents]);

  // ----- Handlers -----
  const handleTest = async (id: string) => {
    try {
      await fetch(`/api/agents/${id}/test`, { method: "POST" });
      await fetchAgents();
    } catch {
      // silently fail — user can retry
    }
  };

  const handleRestart = async (id: string) => {
    try {
      await fetch(`/api/agents/${id}/restart`, { method: "POST" });
      await fetchAgents();
    } catch {
      // silently fail
    }
  };

  const handleSettingsChange = async (id: string, settings: AgentSettings) => {
    try {
      await fetch(`/api/agents/${id}/settings`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(settings),
      });
      await fetchAgents();
    } catch {
      // silently fail
    }
  };

  // ----- Filtering -----
  const filtered = agents.filter((a) => {
    const matchesSearch =
      !search ||
      a.display_name.toLowerCase().includes(search.toLowerCase()) ||
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.model.toLowerCase().includes(search.toLowerCase());
    const matchesStatus =
      statusFilter === "all" || a.status === statusFilter;
    return matchesSearch && matchesStatus;
  });

  // ----- Stats -----
  const onlineCount = agents.filter((a) => a.status === "online").length;
  const workingCount = agents.filter((a) => a.status === "working").length;
  const offlineCount = agents.filter((a) => a.status === "offline").length;
  const errorCount = agents.filter((a) => a.status === "error").length;
  const totalTokens = agents.reduce((sum, a) => sum + a.tokens_today, 0);

  // ----- Loading skeleton -----
  if (loading) {
    return (
      <div className="space-y-6">
        <div className="flex items-center justify-between">
          <div>
            <div className="h-7 w-32 bg-slate-800 rounded animate-pulse" />
            <div className="h-4 w-48 bg-slate-800 rounded animate-pulse mt-2" />
          </div>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div
              key={i}
              className="rounded-lg border border-slate-700/40 bg-slate-800/40 p-4 space-y-3 animate-pulse"
            >
              <div className="flex items-center gap-2">
                <div className="h-2.5 w-2.5 rounded-full bg-slate-700" />
                <div className="h-4 w-36 bg-slate-700 rounded" />
              </div>
              <div className="h-3 w-24 bg-slate-700 rounded" />
              <div className="flex gap-1.5">
                <div className="h-5 w-20 bg-slate-700 rounded" />
                <div className="h-5 w-16 bg-slate-700 rounded" />
              </div>
              <div className="flex gap-2 pt-2">
                <div className="h-8 flex-1 bg-slate-700 rounded" />
                <div className="h-8 flex-1 bg-slate-700 rounded" />
                <div className="h-8 flex-1 bg-slate-700 rounded" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-slate-100 tracking-tight">
            Agents
          </h1>
          <p className="text-sm text-slate-400 mt-1">
            {agents.length} agents &middot; {onlineCount} online &middot;{" "}
            {formatTokens(totalTokens)} tokens today
          </p>
        </div>
        <button
          onClick={fetchAgents}
          disabled={refreshing}
          className="inline-flex items-center gap-2 text-sm text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-600/40 rounded px-3 py-2 transition-colors disabled:opacity-50 focus:outline-none focus:ring-2 focus:ring-blue-500/40"
        >
          <RefreshCw
            className={`h-4 w-4 ${refreshing ? "animate-spin" : ""}`}
          />
          Refresh
        </button>
      </div>

      {/* Summary Bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryCard
          label="Online"
          value={onlineCount}
          color="text-green-400"
          dotColor="bg-green-500"
        />
        <SummaryCard
          label="Working"
          value={workingCount}
          color="text-amber-400"
          dotColor="bg-amber-500"
        />
        <SummaryCard
          label="Offline"
          value={offlineCount}
          color="text-slate-400"
          dotColor="bg-slate-500"
        />
        <SummaryCard
          label="Error"
          value={errorCount}
          color="text-red-400"
          dotColor="bg-red-500"
        />
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search agents by name or model..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600/60 text-sm text-slate-200 placeholder-slate-500 rounded pl-10 pr-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-colors"
          />
        </div>

        {/* Status Filter */}
        <div className="relative">
          <Filter className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <select
            value={statusFilter}
            onChange={(e) =>
              setStatusFilter(e.target.value as AgentStatus | "all")
            }
            className="bg-slate-800 border border-slate-600/60 text-sm text-slate-200 rounded pl-10 pr-8 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 transition-colors appearance-none cursor-pointer"
          >
            <option value="all">All Status</option>
            <option value="online">Online</option>
            <option value="working">Working</option>
            <option value="offline">Offline</option>
            <option value="error">Error</option>
          </select>
          <ChevronDown className="absolute right-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-slate-400 pointer-events-none" />
        </div>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-300">
          <strong className="font-medium">Error:</strong> {error}
          <button
            onClick={() => setError(null)}
            className="ml-3 text-red-400 hover:text-red-300 underline"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Agent Grid */}
      {filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-center">
          <div className="h-12 w-12 rounded-full bg-slate-800 flex items-center justify-center mb-4">
            <Cpu className="h-6 w-6 text-slate-500" />
          </div>
          <p className="text-sm font-medium text-slate-300">
            No agents found
          </p>
          <p className="text-xs text-slate-500 mt-1">
            {agents.length === 0
              ? "Agents will appear here once the system is running."
              : "Try adjusting your search or filter."}
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              onTest={handleTest}
              onRestart={handleRestart}
              onSettingsChange={handleSettingsChange}
            />
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// SummaryCard
// ---------------------------------------------------------------------------

function SummaryCard({
  label,
  value,
  color,
  dotColor,
}: {
  label: string;
  value: number;
  color: string;
  dotColor: string;
}) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/40 px-4 py-3 flex items-center gap-3">
      <span className={`inline-block h-2.5 w-2.5 rounded-full ${dotColor}`} />
      <div>
        <p className={`text-lg font-semibold ${color}`}>{value}</p>
        <p className="text-xs text-slate-400">{label}</p>
      </div>
    </div>
  );
}