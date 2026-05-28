"use client";

import React, { useCallback, useEffect, useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApiKeyField {
  id: string;
  label: string;
  description?: string;
  value: string;
  masked: boolean;
  placeholder: string;
  /** Whether the key has been tested and is valid */
  testStatus: "untested" | "testing" | "success" | "error";
  testMessage?: string;
  /** Whether the value has been modified since last save */
  dirty: boolean;
  saveStatus: "idle" | "saving" | "saved" | "error";
}

interface McpServer {
  id: string;
  name: string;
  url: string;
  status: "connected" | "disconnected" | "error";
  toolsCount: number;
  lastPing?: string;
}

interface A2AConnection {
  id: string;
  fromAgent: string;
  fromDisplayName: string;
  toAgent: string;
  toDisplayName: string;
  status: "active" | "inactive" | "error";
  messagesExchanged: number;
  lastMessage?: string;
}

interface ConfigData {
  apiKeys: {
    mimoApiKey: string;
    mimoBaseUrl: string;
    mimoModel: string;
    githubToken: string;
    opensignUrl: string;
  };
  mcpServers: McpServer[];
  a2aConnections: A2AConnection[];
}

// ---------------------------------------------------------------------------
// Status badge component
// ---------------------------------------------------------------------------

function StatusDot({
  status,
  size = "sm",
}: {
  status: "connected" | "disconnected" | "active" | "inactive" | "error";
  size?: "sm" | "md";
}) {
  const sizeClass = size === "sm" ? "h-2 w-2" : "h-2.5 w-2.5";

  const colorClass =
    status === "connected" || status === "active"
      ? "bg-green-500 shadow-green-500/40"
      : status === "error"
        ? "bg-red-500 shadow-red-500/40"
        : "bg-slate-500";

  return (
    <span
      className={`${sizeClass} ${colorClass} rounded-full inline-block shadow-sm`}
      aria-label={status}
    />
  );
}

// ---------------------------------------------------------------------------
// Loading spinner
// ---------------------------------------------------------------------------

function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin h-4 w-4 ${className}`}
      xmlns="http://www.w3.org/2000/svg"
      fill="none"
      viewBox="0 0 24 24"
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
  );
}

// ---------------------------------------------------------------------------
// API Key Input Row
// ---------------------------------------------------------------------------

function ApiKeyRow({
  field,
  onChange,
  onTest,
  onSave,
}: {
  field: ApiKeyField;
  onChange: (value: string) => void;
  onTest: () => void;
  onSave: () => void;
}) {
  const [showPassword, setShowPassword] = useState(false);

  const testButtonLabel =
    field.testStatus === "testing"
      ? "Testing…"
      : field.testStatus === "success"
        ? "✓ Pass"
        : field.testStatus === "error"
          ? "✗ Fail"
          : "Test";

  const testButtonClass =
    field.testStatus === "success"
      ? "border-green-600 text-green-400 hover:bg-green-600/10"
      : field.testStatus === "error"
        ? "border-red-600 text-red-400 hover:bg-red-600/10"
        : "border-slate-600 text-slate-300 hover:bg-slate-700";

  const saveButtonLabel =
    field.saveStatus === "saving"
      ? "Saving…"
      : field.saveStatus === "saved"
        ? "✓ Saved"
        : "Save";

  const saveButtonClass =
    field.saveStatus === "saved"
      ? "bg-green-600 hover:bg-green-700 text-white"
      : "bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 disabled:cursor-not-allowed";

  const isPasswordField =
    field.id.includes("key") ||
    field.id.includes("token") ||
    field.id.includes("secret");

  return (
    <div className="grid grid-cols-12 gap-3 items-start py-3 border-b border-slate-700/40 last:border-b-0">
      {/* Label */}
      <div className="col-span-12 sm:col-span-3 flex flex-col justify-center min-h-[2.5rem]">
        <label
          htmlFor={field.id}
          className="text-sm font-medium text-slate-200"
        >
          {field.label}
        </label>
        {field.description && (
          <span className="text-xs text-slate-500 mt-0.5">
            {field.description}
          </span>
        )}
      </div>

      {/* Input */}
      <div className="col-span-12 sm:col-span-6 relative">
        <input
          id={field.id}
          type={isPasswordField && !showPassword ? "password" : "text"}
          value={field.value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.placeholder}
          spellCheck={false}
          autoComplete="off"
          className="w-full rounded-md border border-slate-600 bg-slate-800/80 px-3 py-2 pr-10 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40 transition-colors font-mono"
        />
        {isPasswordField && (
          <button
            type="button"
            onClick={() => setShowPassword((v) => !v)}
            className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-200 transition-colors p-1"
            aria-label={showPassword ? "Hide value" : "Show value"}
          >
            {showPassword ? (
              /* Eye off icon */
              <svg
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.542-7a9.956 9.956 0 012.026-3.286m1.638-1.664A9.963 9.963 0 0112 5c4.478 0 8.268 2.943 9.542 7a9.97 9.97 0 01-1.158 2.128M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M3 3l18 18"
                />
              </svg>
            ) : (
              /* Eye icon */
              <svg
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z"
                />
              </svg>
            )}
          </button>
        )}

        {/* Test feedback message */}
        {field.testMessage && field.testStatus !== "testing" && (
          <p
            className={`text-xs mt-1 ${
              field.testStatus === "success"
                ? "text-green-400"
                : field.testStatus === "error"
                  ? "text-red-400"
                  : "text-slate-400"
            }`}
          >
            {field.testMessage}
          </p>
        )}
      </div>

      {/* Buttons */}
      <div className="col-span-12 sm:col-span-3 flex items-center gap-2 justify-end min-h-[2.5rem]">
        <button
          type="button"
          onClick={onTest}
          disabled={
            field.testStatus === "testing" ||
            !field.value.trim()
          }
          className={`inline-flex items-center gap-1.5 rounded border px-3 py-1.5 text-xs font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${testButtonClass}`}
        >
          {field.testStatus === "testing" && (
            <Spinner className="text-current" />
          )}
          {testButtonLabel}
        </button>
        <button
          type="button"
          onClick={onSave}
          disabled={
            field.saveStatus === "saving" || !field.dirty
          }
          className={`inline-flex items-center gap-1.5 rounded px-3 py-1.5 text-xs font-medium transition-colors ${saveButtonClass}`}
        >
          {field.saveStatus === "saving" && (
            <Spinner className="text-current" />
          )}
          {saveButtonLabel}
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// MCP Server Row
// ---------------------------------------------------------------------------

function McpServerRow({ server }: { server: McpServer }) {
  return (
    <div className="flex items-center justify-between py-2.5 border-b border-slate-700/40 last:border-b-0">
      <div className="flex items-center gap-3 min-w-0">
        <StatusDot status={server.status} size="md" />
        <div className="min-w-0">
          <span className="text-sm font-medium text-slate-200 block truncate">
            {server.name}
          </span>
          <span className="text-xs text-slate-500 font-mono block truncate">
            {server.url || "(not configured)"}
          </span>
        </div>
      </div>
      <div className="flex items-center gap-4 shrink-0 ml-4">
        {server.toolsCount > 0 && (
          <span className="text-xs text-slate-400 bg-slate-800 rounded px-2 py-0.5">
            {server.toolsCount} tools
          </span>
        )}
        <span
          className={`text-xs font-medium ${
            server.status === "connected"
              ? "text-green-400"
              : server.status === "error"
                ? "text-red-400"
                : "text-slate-500"
          }`}
        >
          {server.status}
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// A2A Connection Card
// ---------------------------------------------------------------------------

function A2AConnectionCard({ conn }: { conn: A2AConnection }) {
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-800/50 p-3 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-medium text-slate-200">
            {conn.fromDisplayName}
          </span>
          <span className="text-slate-500">⇄</span>
          <span className="font-medium text-slate-200">
            {conn.toDisplayName}
          </span>
        </div>
        <StatusDot status={conn.status} />
      </div>
      <div className="flex items-center justify-between text-xs text-slate-400">
        <span>{conn.messagesExchanged.toLocaleString()} messages</span>
        {conn.lastMessage && (
          <span className="truncate ml-2">Last: {conn.lastMessage}</span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add MCP Server Modal
// ---------------------------------------------------------------------------

function AddMcpServerModal({
  open,
  onClose,
  onAdd,
}: {
  open: boolean;
  onClose: () => void;
  onAdd: (name: string, url: string) => void;
}) {
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md rounded-lg border border-slate-700 bg-slate-900 p-6 shadow-2xl">
        <h3 className="text-lg font-semibold text-slate-100 mb-4">
          Add MCP Server
        </h3>
        <div className="space-y-4">
          <div>
            <label
              htmlFor="mcp-name"
              className="block text-sm font-medium text-slate-300 mb-1"
            >
              Server Name
            </label>
            <input
              id="mcp-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g. My Custom MCP"
              className="w-full rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40 transition-colors"
            />
          </div>
          <div>
            <label
              htmlFor="mcp-url"
              className="block text-sm font-medium text-slate-300 mb-1"
            >
              Server URL
            </label>
            <input
              id="mcp-url"
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://mcp.example.com/mcp"
              spellCheck={false}
              className="w-full rounded-md border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 placeholder-slate-500 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500/40 transition-colors font-mono"
            />
          </div>
        </div>
        <div className="flex justify-end gap-3 mt-6">
          <button
            type="button"
            onClick={onClose}
            className="rounded px-4 py-2 text-sm font-medium text-slate-300 hover:bg-slate-800 transition-colors"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              if (name.trim() && url.trim()) {
                onAdd(name.trim(), url.trim());
                setName("");
                setUrl("");
                onClose();
              }
            }}
            disabled={!name.trim() || !url.trim()}
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            Add Server
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Config Page
// ---------------------------------------------------------------------------

export default function ConfigPage() {
  // --- API Key fields state ---
  const [apiKeys, setApiKeys] = useState<Record<string, ApiKeyField>>({
    mimoApiKey: {
      id: "mimoApiKey",
      label: "MiMo API Key",
      description: "Xiaomi MiMo LLM service key",
      value: "",
      masked: true,
      placeholder: "sk-mimo-xxxxxxxxxxxxxxxx",
      testStatus: "untested",
      dirty: false,
      saveStatus: "idle",
    },
    mimoBaseUrl: {
      id: "mimoBaseUrl",
      label: "MiMo Base URL",
      description: "Endpoint for MiMo API requests",
      value: "https://api.xiaomi.com/v1",
      masked: false,
      placeholder: "https://api.xiaomi.com/v1",
      testStatus: "untested",
      dirty: false,
      saveStatus: "idle",
    },
    mimoModel: {
      id: "mimoModel",
      label: "MiMo Model",
      description: "Model identifier",
      value: "mimo-v2.5-pro",
      masked: false,
      placeholder: "mimo-v2.5-pro",
      testStatus: "untested",
      dirty: false,
      saveStatus: "idle",
    },
    githubToken: {
      id: "githubToken",
      label: "GitHub Token",
      description: "Personal access token for GitHub MCP",
      value: "",
      masked: true,
      placeholder: "ghp_xxxxxxxxxxxxxxxxxxxx",
      testStatus: "untested",
      dirty: false,
      saveStatus: "idle",
    },
    opensignUrl: {
      id: "opensignUrl",
      label: "OpenDesign URL",
      description: "Design spec comparison endpoint",
      value: "",
      masked: false,
      placeholder: "https://opendesign.example.com/mcp",
      testStatus: "untested",
      dirty: false,
      saveStatus: "idle",
    },
  });

  // --- MCP Servers ---
  const [mcpServers, setMcpServers] = useState<McpServer[]>([
    {
      id: "github",
      name: "GitHub MCP",
      url: "https://api.github.com/mcp",
      status: "connected",
      toolsCount: 7,
      lastPing: "2s ago",
    },
    {
      id: "context7",
      name: "Context7",
      url: "https://mcp.context7.com/mcp",
      status: "connected",
      toolsCount: 2,
      lastPing: "5s ago",
    },
    {
      id: "opendesign",
      name: "OpenDesign MCP",
      url: "",
      status: "disconnected",
      toolsCount: 0,
    },
    {
      id: "linear",
      name: "Linear MCP",
      url: "",
      status: "disconnected",
      toolsCount: 0,
    },
  ]);

  // --- A2A Connections ---
  const [a2aConnections, setA2aConnections] = useState<A2AConnection[]>([
    {
      id: "po-pm",
      fromAgent: "po",
      fromDisplayName: "PO",
      toAgent: "pm",
      toDisplayName: "PM",
      status: "active",
      messagesExchanged: 12,
      lastMessage: "2m ago",
    },
    {
      id: "pm-ba",
      fromAgent: "pm",
      fromDisplayName: "PM",
      toAgent: "ba",
      toDisplayName: "BA",
      status: "active",
      messagesExchanged: 28,
      lastMessage: "30s ago",
    },
    {
      id: "pm-sa",
      fromAgent: "pm",
      fromDisplayName: "PM",
      toAgent: "sa",
      toDisplayName: "Solution Architect",
      status: "active",
      messagesExchanged: 15,
      lastMessage: "1m ago",
    },
    {
      id: "ba-fe",
      fromAgent: "ba",
      fromDisplayName: "BA",
      toAgent: "frontend",
      toDisplayName: "Frontend Dev",
      status: "active",
      messagesExchanged: 42,
      lastMessage: "45s ago",
    },
    {
      id: "ba-be",
      fromAgent: "ba",
      fromDisplayName: "BA",
      toAgent: "backend",
      toDisplayName: "Backend Dev",
      status: "active",
      messagesExchanged: 38,
      lastMessage: "1m ago",
    },
    {
      id: "fe-uiux",
      fromAgent: "frontend",
      fromDisplayName: "Frontend Dev",
      toAgent: "uiux",
      toDisplayName: "UIUX Reviewer",
      status: "active",
      messagesExchanged: 8,
      lastMessage: "5m ago",
    },
    {
      id: "be-security",
      fromAgent: "backend",
      fromDisplayName: "Backend Dev",
      toAgent: "security",
      toDisplayName: "Security Reviewer",
      status: "active",
      messagesExchanged: 6,
      lastMessage: "3m ago",
    },
    {
      id: "uiux-qa",
      fromAgent: "uiux",
      fromDisplayName: "UIUX Reviewer",
      toAgent: "qa",
      toDisplayName: "QA",
      status: "active",
      messagesExchanged: 14,
      lastMessage: "2m ago",
    },
    {
      id: "security-qa",
      fromAgent: "security",
      fromDisplayName: "Security Reviewer",
      toAgent: "qa",
      toDisplayName: "QA",
      status: "active",
      messagesExchanged: 10,
      lastMessage: "2m ago",
    },
    {
      id: "qa-devops",
      fromAgent: "qa",
      fromDisplayName: "QA",
      toAgent: "devops",
      toDisplayName: "DevOps",
      status: "active",
      messagesExchanged: 4,
      lastMessage: "8m ago",
    },
    {
      id: "devops-techlead",
      fromAgent: "devops",
      fromDisplayName: "DevOps",
      toAgent: "techlead",
      toDisplayName: "TechLead",
      status: "active",
      messagesExchanged: 2,
      lastMessage: "15m ago",
    },
    {
      id: "techlead-po",
      fromAgent: "techlead",
      fromDisplayName: "TechLead",
      toAgent: "po",
      toDisplayName: "PO",
      status: "active",
      messagesExchanged: 1,
      lastMessage: "20m ago",
    },
  ]);

  const [showAddMcpModal, setShowAddMcpModal] = useState(false);

  // --- Load saved config on mount ---
  useEffect(() => {
    async function loadConfig() {
      try {
        const res = await fetch("/api/config");
        if (!res.ok) return;
        const data: ConfigData = await res.json();

        if (data.apiKeys) {
          setApiKeys((prev) => {
            const next = { ...prev };
            for (const [key, value] of Object.entries(data.apiKeys)) {
              if (next[key]) {
                next[key] = {
                  ...next[key],
                  value: value as string,
                  dirty: false,
                  testStatus: "untested",
                  saveStatus: "idle",
                };
              }
            }
            return next;
          });
        }

        if (data.mcpServers && data.mcpServers.length > 0) {
          setMcpServers(data.mcpServers);
        }

        if (data.a2aConnections && data.a2aConnections.length > 0) {
          setA2aConnections(data.a2aConnections);
        }
      } catch {
        // Use defaults — no config saved yet
      }
    }
    loadConfig();
  }, []);

  // --- Handlers ---

  const handleApiKeyChange = useCallback(
    (fieldId: string, value: string) => {
      setApiKeys((prev) => ({
        ...prev,
        [fieldId]: {
          ...prev[fieldId],
          value,
          dirty: true,
          saveStatus: "idle",
          testStatus: "untested",
          testMessage: undefined,
        },
      }));
    },
    [],
  );

  const handleTest = useCallback(
    async (fieldId: string) => {
      setApiKeys((prev) => ({
        ...prev,
        [fieldId]: {
          ...prev[fieldId],
          testStatus: "testing",
          testMessage: undefined,
        },
      }));

      try {
        const res = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "test",
            field: fieldId,
            value: apiKeys[fieldId].value,
          }),
        });
        const data = await res.json();

        setApiKeys((prev) => ({
          ...prev,
          [fieldId]: {
            ...prev[fieldId],
            testStatus: data.success ? "success" : "error",
            testMessage:
              data.message ||
              (data.success ? "Connection successful" : "Connection failed"),
          },
        }));
      } catch {
        setApiKeys((prev) => ({
          ...prev,
          [fieldId]: {
            ...prev[fieldId],
            testStatus: "error",
            testMessage: "Network error — could not reach server",
          },
        }));
      }
    },
    [apiKeys],
  );

  const handleSave = useCallback(
    async (fieldId: string) => {
      setApiKeys((prev) => ({
        ...prev,
        [fieldId]: {
          ...prev[fieldId],
          saveStatus: "saving",
        },
      }));

      try {
        const res = await fetch("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "save",
            field: fieldId,
            value: apiKeys[fieldId].value,
          }),
        });

        if (res.ok) {
          setApiKeys((prev) => ({
            ...prev,
            [fieldId]: {
              ...prev[fieldId],
              dirty: false,
              saveStatus: "saved",
            },
          }));
          // Reset save status after 2s
          setTimeout(() => {
            setApiKeys((prev) => ({
              ...prev,
              [fieldId]: {
                ...prev[fieldId],
                saveStatus: "idle",
              },
            }));
          }, 2000);
        } else {
          setApiKeys((prev) => ({
            ...prev,
            [fieldId]: {
              ...prev[fieldId],
              saveStatus: "error",
            },
          }));
        }
      } catch {
        setApiKeys((prev) => ({
          ...prev,
          [fieldId]: {
            ...prev[fieldId],
            saveStatus: "error",
          },
        }));
      }
    },
    [apiKeys],
  );

  const handleAddMcpServer = useCallback(
    (name: string, url: string) => {
      const id = name.toLowerCase().replace(/\s+/g, "-");
      setMcpServers((prev) => [
        ...prev,
        {
          id,
          name,
          url,
          status: "disconnected",
          toolsCount: 0,
        },
      ]);
    },
    [],
  );

  const activeConnections = a2aConnections.filter(
    (c) => c.status === "active",
  ).length;
  const connectedServers = mcpServers.filter(
    (s) => s.status === "connected",
  ).length;

  return (
    <div className="max-w-5xl mx-auto space-y-6">
      {/* Page Header */}
      <div>
        <h1 className="text-2xl font-semibold text-slate-100 tracking-tight">
          Configuration
        </h1>
        <p className="text-sm text-slate-400 mt-1">
          Manage API keys, MCP servers, and agent-to-agent connections.
        </p>
      </div>

      {/* ----------------------------------------------------------------- */}
      {/* API Keys Section                                                    */}
      {/* ----------------------------------------------------------------- */}
      <section className="rounded-lg border border-slate-700/60 bg-slate-800/40 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-700/60 flex items-center gap-3">
          <div className="p-1.5 rounded bg-blue-600/20 text-blue-400">
            <svg
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"
              />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold text-slate-100">
              API Keys & Endpoints
            </h2>
            <p className="text-xs text-slate-400">
              Credentials for LLM service, code hosting, and design tools.
            </p>
          </div>
        </div>
        <div className="px-5 py-2">
          {Object.values(apiKeys).map((field) => (
            <ApiKeyRow
              key={field.id}
              field={field}
              onChange={(val) => handleApiKeyChange(field.id, val)}
              onTest={() => handleTest(field.id)}
              onSave={() => handleSave(field.id)}
            />
          ))}
        </div>
      </section>

      {/* ----------------------------------------------------------------- */}
      {/* MCP Servers Section                                                 */}
      {/* ----------------------------------------------------------------- */}
      <section className="rounded-lg border border-slate-700/60 bg-slate-800/40 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-700/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded bg-purple-600/20 text-purple-400">
              <svg
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 12h14M5 12a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v4a2 2 0 01-2 2M5 12a2 2 0 00-2 2v4a2 2 0 002 2h14a2 2 0 002-2v-4a2 2 0 00-2-2m-2-4h.01M17 16h.01"
                />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100">
                MCP Servers
              </h2>
              <p className="text-xs text-slate-400">
                {connectedServers} of {mcpServers.length} connected &bull;
                Model Context Protocol tool endpoints
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => setShowAddMcpModal(true)}
            className="inline-flex items-center gap-1.5 rounded bg-slate-700 hover:bg-slate-600 px-3 py-1.5 text-xs font-medium text-slate-200 transition-colors"
          >
            <svg
              className="h-3.5 w-3.5"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 4v16m8-8H4"
              />
            </svg>
            Add Server
          </button>
        </div>
        <div className="px-5 py-1">
          {mcpServers.map((server) => (
            <McpServerRow key={server.id} server={server} />
          ))}
        </div>
      </section>

      {/* ----------------------------------------------------------------- */}
      {/* A2A Connections Section                                             */}
      {/* ----------------------------------------------------------------- */}
      <section className="rounded-lg border border-slate-700/60 bg-slate-800/40 overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-700/60 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-1.5 rounded bg-green-600/20 text-green-400">
              <svg
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4"
                />
              </svg>
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100">
                A2A Connections
              </h2>
              <p className="text-xs text-slate-400">
                {activeConnections} active connections &bull; Agents
                auto-discovered via{" "}
                <code className="font-mono text-xs bg-slate-700/60 px-1 rounded">
                  /.well-known/agent.json
                </code>
              </p>
            </div>
          </div>
        </div>
        <div className="px-5 py-4">
          {a2aConnections.length === 0 ? (
            <div className="text-center py-8 text-sm text-slate-500">
              No A2A connections discovered yet. Start agents to auto-register.
            </div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {a2aConnections.map((conn) => (
                <A2AConnectionCard key={conn.id} conn={conn} />
              ))}
            </div>
          )}
        </div>
      </section>

      {/* ----------------------------------------------------------------- */}
      {/* Danger Zone                                                         */}
      {/* ----------------------------------------------------------------- */}
      <section className="rounded-lg border border-red-900/40 bg-red-950/20 overflow-hidden">
        <div className="px-5 py-4 border-b border-red-900/40 flex items-center gap-3">
          <div className="p-1.5 rounded bg-red-600/20 text-red-400">
            <svg
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z"
              />
            </svg>
          </div>
          <div>
            <h2 className="text-base font-semibold text-red-300">
              Danger Zone
            </h2>
            <p className="text-xs text-red-400/60">
              These actions are irreversible. Proceed with caution.
            </p>
          </div>
        </div>
        <div className="px-5 py-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <p className="text-sm text-slate-200">
                Reset all configuration
              </p>
              <p className="text-xs text-slate-500">
                Clears all API keys, MCP servers, and connection data.
              </p>
            </div>
            <button
              type="button"
              onClick={async () => {
                if (
                  window.confirm(
                    "Are you sure? This will reset ALL configuration to defaults.",
                  )
                ) {
                  await fetch("/api/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: "reset" }),
                  });
                  window.location.reload();
                }
              }}
              className="rounded border border-red-700 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-900/30 transition-colors"
            >
              Reset Config
            </button>
          </div>
          <div className="flex items-center justify-between border-t border-red-900/30 pt-3">
            <div>
              <p className="text-sm text-slate-200">Disconnect all agents</p>
              <p className="text-xs text-slate-500">
                Stops all A2A connections and agent processes.
              </p>
            </div>
            <button
              type="button"
              onClick={async () => {
                if (
                  window.confirm(
                    "This will stop all running agents. Continue?",
                  )
                ) {
                  await fetch("/api/config", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ action: "disconnect_all" }),
                  });
                  setA2aConnections((prev) =>
                    prev.map((c) => ({ ...c, status: "inactive" as const })),
                  );
                  setMcpServers((prev) =>
                    prev.map((s) => ({
                      ...s,
                      status: "disconnected" as const,
                    })),
                  );
                }
              }}
              className="rounded border border-red-700 px-3 py-1.5 text-xs font-medium text-red-400 hover:bg-red-900/30 transition-colors"
            >
              Disconnect All
            </button>
          </div>
        </div>
      </section>

      {/* Add MCP Server Modal */}
      <AddMcpServerModal
        open={showAddMcpModal}
        onClose={() => setShowAddMcpModal(false)}
        onAdd={handleAddMcpServer}
      />
    </div>
  );
}