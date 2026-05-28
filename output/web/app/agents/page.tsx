"use client";

import { useState, useCallback } from "react";
import Link from "next/link";
import { useFetch } from "@/hooks/useFetch";
import { StatusDot, Badge, Button, Card, Toggle, EmptyState, Spinner } from "@/components/ui";
import type { Agent } from "@/lib/types";

const MODELS = ["mimo-v2.5-pro", "mimo-v2.5-lite", "mimo-v2-flash", "gpt-4o", "claude-3.5-sonnet"];

export default function AgentsPage() {
  const { data, loading, refetch } = useFetch<{ agents: Agent[] }>("/api/agents", 10000);
  const agents = data?.agents ?? [];
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("all");

  const filtered = agents.filter((a) => {
    const matchSearch = !search || a.displayName.toLowerCase().includes(search.toLowerCase()) || a.name.toLowerCase().includes(search.toLowerCase());
    const matchStatus = statusFilter === "all" || a.status === statusFilter;
    return matchSearch && matchStatus;
  });

  const onlineCount = agents.filter((a) => a.status === "online" || a.status === "working").length;

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-100 tracking-tight">Agents</h1>
          <p className="text-sm text-slate-400 mt-1">{agents.length} agents &middot; {onlineCount} online</p>
        </div>
        <Button variant="secondary" size="sm" onClick={refetch}>↻ Refresh</Button>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
          <input
            type="text"
            placeholder="Search agents..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-slate-800 border border-slate-600/60 text-sm text-slate-200 placeholder-slate-500 rounded pl-10 pr-3 py-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 focus:outline-none transition-colors"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="bg-slate-800 border border-slate-600/60 text-sm text-slate-200 rounded px-3 py-2 focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 focus:outline-none"
        >
          <option value="all">All Status</option>
          <option value="online">Online</option>
          <option value="working">Working</option>
          <option value="offline">Offline</option>
          <option value="error">Error</option>
        </select>
      </div>

      {/* Agent Grid */}
      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="bg-slate-800 border border-slate-700 rounded-lg p-4 animate-pulse h-32" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <Card>
          <EmptyState title="No agents found" description={agents.length === 0 ? "Agents will appear once the system is running." : "Try adjusting your search or filter."} />
        </Card>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {filtered.map((agent) => <AgentCard key={agent.id} agent={agent} />)}
        </div>
      )}
    </div>
  );
}

/* ─── Agent Card (expandable) ────────────────────────────────── */

function AgentCard({ agent }: { agent: Agent }) {
  const [expanded, setExpanded] = useState(false);
  const [testing, setTesting] = useState(false);

  const handleTest = async () => {
    setTesting(true);
    try { await fetch(`/api/agents/${agent.id}/test`, { method: "POST" }); } catch { /* */ }
    setTesting(false);
  };

  const handleRestart = async () => {
    try { await fetch(`/api/agents/${agent.id}/restart`, { method: "POST" }); } catch { /* */ }
  };

  return (
    <div className={`bg-slate-800 border border-slate-700 rounded-lg overflow-hidden hover:border-slate-600 transition-colors`}>
      {/* Header */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="w-full text-left px-4 py-3 flex items-center gap-3 hover:bg-slate-700/20 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-blue-500"
      >
        <StatusDot status={agent.status} />
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-slate-100 truncate">{agent.displayName}</h3>
          <p className="text-xs text-slate-400 mt-0.5">Port {agent.port} &middot; {agent.role}</p>
        </div>
        <Badge variant={agent.status}>{agent.status}</Badge>
        <svg className={`h-4 w-4 text-slate-400 transition-transform shrink-0 ${expanded ? "rotate-180" : ""}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </button>

      {/* Body */}
      {expanded && (
        <div className="border-t border-slate-700 px-4 py-4 space-y-4 bg-slate-900/20" onClick={(e) => e.stopPropagation()}>
          {/* Tools */}
          {agent.tools && agent.tools.length > 0 && (
            <div>
              <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">Tools</span>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {agent.tools.map((tool) => (
                  <span key={tool} className="font-mono text-[11px] px-2 py-0.5 bg-slate-900 border border-slate-700 rounded text-slate-400">
                    {tool}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Settings Grid */}
          <div className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-3 items-center">
            <span className="text-xs font-medium text-slate-400">Model</span>
            <select className="bg-slate-900 border border-slate-600 rounded px-2 py-1.5 text-xs text-slate-200 focus:border-blue-500 focus:outline-none">
              {MODELS.map((m) => <option key={m}>{m}</option>)}
            </select>

            <span className="text-xs font-medium text-slate-400">Temperature</span>
            <div className="flex items-center gap-3">
              <input type="range" min={0} max={1} step={0.01} defaultValue={0.2} className="flex-1 h-1 bg-slate-700 rounded-full appearance-none accent-blue-500" />
              <span className="text-xs font-mono text-blue-400 w-8 text-right">0.2</span>
            </div>

            <span className="text-xs font-medium text-slate-400">Max tokens</span>
            <input type="number" defaultValue={8192} min={256} max={131072} step={256} className="bg-slate-900 border border-slate-600 rounded px-2 py-1.5 text-xs text-slate-200 font-mono w-28 focus:border-blue-500 focus:outline-none" />

            <span className="text-xs font-medium text-slate-400">Enabled</span>
            <Toggle checked={true} onChange={() => {}} />
          </div>

          {/* Actions */}
          <div className="flex gap-2 pt-2 border-t border-slate-700">
            <Button variant="secondary" size="sm" onClick={handleTest} disabled={testing || agent.status === "offline"}>
              {testing ? <Spinner className="mr-1" /> : null} Test
            </Button>
            <Link href={`/logs?agent=${agent.name}`} className="flex-1">
              <Button variant="ghost" size="sm" className="w-full">View Logs</Button>
            </Link>
            <Button variant="danger" size="sm" onClick={handleRestart} disabled={agent.status === "offline"}>
              Restart
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
