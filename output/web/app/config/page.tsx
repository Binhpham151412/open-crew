"use client";

import { useState, useEffect, useCallback } from "react";
import { StatusDot, Badge, Button, Card, CardHeader, CardTitle, Toggle, Spinner } from "@/components/ui";

interface McpServer { id: string; name: string; url: string; status: string; tools: string[]; enabled: boolean; }
interface A2AConn { id: string; from: string; to: string; status: string; messages: number; }
interface ConfigData { apiKeys: Record<string, string>; mcpServers: McpServer[]; updatedAt: string; }

const API_FIELDS = [
  { key: "mimoApiKey", label: "MiMo API Key", placeholder: "sk-mimo-xxxx", secret: true },
  { key: "mimoBaseUrl", label: "MiMo Base URL", placeholder: "https://api.xiaomi.com/v1", secret: false },
  { key: "mimoModel", label: "MiMo Model", placeholder: "mimo-v2.5-pro", secret: false },
  { key: "githubToken", label: "GitHub Token", placeholder: "ghp_xxxx", secret: true },
  { key: "openDesignUrl", label: "OpenDesign URL", placeholder: "https://...", secret: false },
  { key: "linearApiKey", label: "Linear API Key", placeholder: "lin_api_xxxx", secret: true },
] as const;

const A2A_PAIRS = [
  { id: "po-pm", from: "PO", to: "PM" },
  { id: "pm-ba", from: "PM", to: "BA" },
  { id: "pm-sa", from: "PM", to: "Solution Architect" },
  { id: "ba-fe", from: "BA", to: "Frontend Dev" },
  { id: "ba-be", from: "BA", to: "Backend Dev" },
  { id: "fe-uiux", from: "Frontend Dev", to: "UIUX Reviewer" },
  { id: "be-security", from: "Backend Dev", to: "Security Reviewer" },
  { id: "uiux-qa", from: "UIUX Reviewer", to: "QA" },
  { id: "security-qa", from: "Security Reviewer", to: "QA" },
  { id: "qa-devops", from: "QA", to: "DevOps" },
  { id: "devops-techlead", from: "DevOps", to: "TechLead" },
  { id: "techlead-po", from: "TechLead", to: "PO" },
];

export default function ConfigPage() {
  const [apiKeys, setApiKeys] = useState<Record<string, string>>({});
  const [mcpServers, setMcpServers] = useState<McpServer[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAddMcp, setShowAddMcp] = useState(false);

  useEffect(() => {
    fetch("/api/config")
      .then((r) => r.json())
      .then((data: ConfigData) => {
        setApiKeys(data.apiKeys ?? {});
        setMcpServers(data.mcpServers ?? []);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async (key: string, value: string) => {
    await fetch("/api/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apiKeys: { [key]: value } }),
    });
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-100 tracking-tight">Configuration</h1>
        <p className="text-sm text-slate-400 mt-1">API keys, MCP servers, and agent-to-agent connections</p>
      </div>

      {/* API Keys */}
      <Card>
        <CardHeader>
          <CardTitle>API Keys</CardTitle>
        </CardHeader>
        <div className="p-5 space-y-4">
          {API_FIELDS.map((field) => (
            <ApiKeyRow
              key={field.key}
              fieldKey={field.key}
              label={field.label}
              placeholder={field.placeholder}
              secret={field.secret}
              value={apiKeys[field.key] ?? ""}
              onChange={(v) => setApiKeys((prev) => ({ ...prev, [field.key]: v }))}
              onSave={(v) => handleSave(field.key, v)}
            />
          ))}
        </div>
      </Card>

      {/* MCP Servers */}
      <Card>
        <CardHeader>
          <CardTitle>MCP Servers</CardTitle>
          <Button variant="secondary" size="sm" onClick={() => setShowAddMcp(true)}>+ Add MCP Server</Button>
        </CardHeader>
        <div className="divide-y divide-slate-700/40">
          {mcpServers.map((server) => (
            <div key={server.id} className="flex items-center gap-3 px-4 py-3 hover:bg-slate-700/20 transition-colors">
              <StatusDot status={server.enabled ? (server.status === "connected" ? "online" : "offline") : "offline"} />
              <span className="text-sm font-medium text-slate-200 w-32 shrink-0">{server.name}</span>
              <span className="text-xs font-mono text-slate-500 flex-1 truncate">
                {server.url || "(not configured)"}
              </span>
              {server.tools.length > 0 && (
                <span className="text-xs text-slate-400 bg-slate-800 rounded px-2 py-0.5">{server.tools.length} tools</span>
              )}
              <Badge variant={server.status === "connected" ? "success" : "muted"}>{server.status}</Badge>
            </div>
          ))}
        </div>
      </Card>

      {/* A2A Connections */}
      <Card>
        <CardHeader>
          <CardTitle>A2A Connections</CardTitle>
          <span className="text-xs text-slate-500">Auto-discovered via /.well-known/agent.json</span>
        </CardHeader>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2 p-4">
          {A2A_PAIRS.map((conn) => (
            <div key={conn.id} className="flex items-center gap-2 px-3 py-2 bg-slate-900/50 rounded border border-slate-700/40">
              <span className="text-xs font-medium text-slate-300">{conn.from}</span>
              <span className="text-slate-500">⇄</span>
              <span className="text-xs font-medium text-slate-300">{conn.to}</span>
              <StatusDot status="online" className="ml-auto" />
            </div>
          ))}
        </div>
      </Card>

      {/* Add MCP Modal */}
      {showAddMcp && <AddMcpModal onClose={() => setShowAddMcp(false)} onAdd={(name, url) => {
        setMcpServers((prev) => [...prev, { id: name.toLowerCase().replace(/\s+/g, "-"), name, url, status: "disconnected", tools: [], enabled: true }]);
        setShowAddMcp(false);
      }} />}
    </div>
  );
}

/* ─── Sub-components ─────────────────────────────────────────── */

function ApiKeyRow({ fieldKey, label, placeholder, secret, value, onChange, onSave }: {
  fieldKey: string; label: string; placeholder: string; secret: boolean;
  value: string; onChange: (v: string) => void; onSave: (v: string) => void;
}) {
  const [show, setShow] = useState(false);
  const [saving, setSaving] = useState(false);
  const [dirty, setDirty] = useState(false);

  return (
    <div className="grid grid-cols-12 gap-3 items-center">
      <label className="col-span-12 sm:col-span-3 text-sm font-medium text-slate-300">{label}</label>
      <div className="col-span-12 sm:col-span-6 relative">
        <input
          type={secret && !show ? "password" : "text"}
          value={value}
          onChange={(e) => { onChange(e.target.value); setDirty(true); }}
          placeholder={placeholder}
          className="w-full bg-slate-900 border border-slate-600 rounded px-3 py-2 pr-10 text-sm text-slate-100 font-mono focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 focus:outline-none transition-colors"
        />
        {secret && (
          <button type="button" onClick={() => setShow((v) => !v)} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 p-1">
            <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              {show
                ? <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.542-7a9.956 9.956 0 012.026-3.286m1.638-1.664A9.963 9.963 0 0112 5c4.478 0 8.268 2.943 9.542 7a9.97 9.97 0 01-1.158 2.128M15 12a3 3 0 11-6 0 3 3 0 016 0zM3 3l18 18" />
                : <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0zM2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />}
            </svg>
          </button>
        )}
      </div>
      <div className="col-span-12 sm:col-span-3 flex gap-2 justify-end">
        <Button variant="secondary" size="sm" disabled={!value.trim()}>Test</Button>
        <Button size="sm" disabled={!dirty || saving} onClick={async () => { setSaving(true); await onSave(value); setSaving(false); setDirty(false); }}>
          {saving ? <Spinner /> : "Save"}
        </Button>
      </div>
    </div>
  );
}

function AddMcpModal({ onClose, onAdd }: { onClose: () => void; onAdd: (name: string, url: string) => void }) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="w-full max-w-md bg-slate-900 border border-slate-700 rounded-lg p-6 shadow-2xl">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">Add MCP Server</h3>
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Server Name</label>
            <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. My Custom MCP" className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-100 focus:border-blue-500 focus:outline-none" />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-1">Server URL</label>
            <input type="url" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://mcp.example.com/mcp" className="w-full bg-slate-800 border border-slate-600 rounded px-3 py-2 text-sm text-slate-100 font-mono focus:border-blue-500 focus:outline-none" />
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button disabled={!name.trim() || !url.trim()} onClick={() => onAdd(name.trim(), url.trim())}>Add Server</Button>
        </div>
      </div>
    </div>
  );
}
