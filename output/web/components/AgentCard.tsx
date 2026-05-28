"use client";

import { useState } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AgentStatusType = "online" | "offline" | "working" | "error";

export interface AgentCardProps {
  /** Unique agent identifier, e.g. "backend-dev" */
  id: string;
  /** Human-readable display name */
  name: string;
  /** Current runtime status */
  status: AgentStatusType;
  /** LLM model used by this agent */
  model: string;
  /** List of tool / capability names */
  tools: string[];
  /** Tokens consumed today */
  tokensToday?: number;
  /** Agent port number */
  port?: number;
  /** Whether the agent is enabled in the system */
  enabled?: boolean;
  /** Callback when user clicks "Test Agent" */
  onTest?: (agentId: string) => void;
  /** Callback when user clicks "View Logs" */
  onViewLogs?: (agentId: string) => void;
  /** Callback when user clicks "Restart" */
  onRestart?: (agentId: string) => void;
  /** Callback when the enabled toggle changes */
  onToggleEnabled?: (agentId: string, enabled: boolean) => void;
  /** Callback when settings are saved */
  onSaveSettings?: (agentId: string, settings: AgentSettings) => void;
  /** Optional additional CSS classes */
  className?: string;
}

export interface AgentSettings {
  model: string;
  temperature: number;
  maxTokens: number;
  enabled: boolean;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<
  AgentStatusType,
  { dot: string; label: string; bg: string }
> = {
  online: {
    dot: "bg-green-500 shadow-[0_0_6px_2px_rgba(22,163,74,0.5)]",
    label: "Online",
    bg: "bg-green-500/10 text-green-400 border-green-500/20",
  },
  offline: {
    dot: "bg-slate-500",
    label: "Offline",
    bg: "bg-slate-500/10 text-slate-400 border-slate-500/20",
  },
  working: {
    dot: "bg-amber-500 shadow-[0_0_6px_2px_rgba(217,119,6,0.5)] animate-pulse",
    label: "Working",
    bg: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  },
  error: {
    dot: "bg-red-500 shadow-[0_0_6px_2px_rgba(220,38,38,0.5)]",
    label: "Error",
    bg: "bg-red-500/10 text-red-400 border-red-500/20",
  },
};

const MODEL_OPTIONS = [
  "mimo-v2.5-pro",
  "mimo-v2.5-lite",
  "mimo-v2-flash",
  "gpt-4o",
  "claude-3.5-sonnet",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTokens(count: number): string {
  if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`;
  if (count >= 1_000) return `${(count / 1_000).toFixed(1)}k`;
  return count.toString();
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusDot({ status }: { status: AgentStatusType }) {
  return (
    <span
      className={`inline-block h-2.5 w-2.5 rounded-full shrink-0 ${STATUS_STYLES[status].dot}`}
      aria-label={`Status: ${STATUS_STYLES[status].label}`}
    />
  );
}

function SettingsPanel({
  agentId,
  initialModel,
  initialEnabled,
  onSave,
  onClose,
}: {
  agentId: string;
  initialModel: string;
  initialEnabled: boolean;
  onSave: (agentId: string, settings: AgentSettings) => void;
  onClose: () => void;
}) {
  const [model, setModel] = useState(initialModel);
  const [temperature, setTemperature] = useState(0.2);
  const [maxTokens, setMaxTokens] = useState(8192);
  const [enabled, setEnabled] = useState(initialEnabled);

  const handleSave = () => {
    onSave(agentId, { model, temperature, maxTokens, enabled });
    onClose();
  };

  return (
    <div className="mt-4 border-t border-slate-700 pt-4 space-y-4 animate-in slide-in-from-top-2 duration-200">
      {/* Model */}
      <div className="space-y-1.5">
        <label
          htmlFor={`model-${agentId}`}
          className="text-xs font-medium text-slate-400 uppercase tracking-wider"
        >
          Model
        </label>
        <select
          id={`model-${agentId}`}
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="w-full rounded border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
        >
          {MODEL_OPTIONS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      {/* Temperature */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between">
          <label
            htmlFor={`temp-${agentId}`}
            className="text-xs font-medium text-slate-400 uppercase tracking-wider"
          >
            Temperature
          </label>
          <span className="text-xs font-mono text-blue-400">{temperature.toFixed(2)}</span>
        </div>
        <input
          id={`temp-${agentId}`}
          type="range"
          min={0}
          max={1}
          step={0.01}
          value={temperature}
          onChange={(e) => setTemperature(parseFloat(e.target.value))}
          className="w-full h-1.5 rounded-full appearance-none bg-slate-700 accent-blue-500 cursor-pointer"
        />
        <div className="flex justify-between text-[10px] text-slate-500">
          <span>Precise</span>
          <span>Creative</span>
        </div>
      </div>

      {/* Max Tokens */}
      <div className="space-y-1.5">
        <label
          htmlFor={`max-tokens-${agentId}`}
          className="text-xs font-medium text-slate-400 uppercase tracking-wider"
        >
          Max Tokens
        </label>
        <input
          id={`max-tokens-${agentId}`}
          type="number"
          min={256}
          max={131072}
          step={256}
          value={maxTokens}
          onChange={(e) => setMaxTokens(parseInt(e.target.value, 10) || 256)}
          className="w-full rounded border border-slate-600 bg-slate-800 px-3 py-2 text-sm text-slate-100 font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-colors"
        />
      </div>

      {/* Enabled toggle */}
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-400 uppercase tracking-wider">
          Enabled
        </span>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => setEnabled(!enabled)}
          className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 ${
            enabled ? "bg-blue-600" : "bg-slate-600"
          }`}
        >
          <span
            className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ${
              enabled ? "translate-x-5" : "translate-x-0"
            }`}
          />
        </button>
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 pt-2">
        <button
          onClick={handleSave}
          className="flex-1 rounded bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition-colors"
        >
          Save Settings
        </button>
        <button
          onClick={onClose}
          className="rounded border border-slate-600 px-3 py-2 text-sm font-medium text-slate-300 hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition-colors"
        >
          Cancel
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function AgentCard({
  id,
  name,
  status,
  model,
  tools,
  tokensToday = 0,
  port,
  enabled = true,
  onTest,
  onViewLogs,
  onRestart,
  onToggleEnabled,
  onSaveSettings,
  className,
}: AgentCardProps) {
  const [showSettings, setShowSettings] = useState(false);

  const statusStyle = STATUS_STYLES[status];
  const isActionable = status !== "offline";

  return (
    <div
      className={`rounded-lg border border-slate-700 bg-slate-800 p-4 transition-all hover:border-slate-600 ${
        !enabled ? "opacity-60" : ""
      } ${className ?? ""}`}
    >
      {/* Header: status dot + name + status badge + port */}
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-3 min-w-0">
          <StatusDot status={status} />
          <div className="min-w-0">
            <h3 className="text-sm font-semibold text-slate-100 truncate">
              {name}
            </h3>
            {port != null && (
              <span className="text-[11px] font-mono text-slate-500">
                :{port}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Status badge */}
          <span
            className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${statusStyle.bg}`}
          >
            {statusStyle.label}
          </span>

          {/* Settings toggle */}
          <button
            onClick={() => setShowSettings((v) => !v)}
            className="rounded p-1 text-slate-400 hover:text-slate-200 hover:bg-slate-700 transition-colors focus:outline-none focus:ring-2 focus:ring-slate-500"
            aria-label="Toggle settings"
            title="Settings"
          >
            <svg
              className={`h-4 w-4 transition-transform duration-200 ${showSettings ? "rotate-90" : ""}`}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
              strokeWidth={2}
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"
              />
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"
              />
            </svg>
          </button>
        </div>
      </div>

      {/* Info rows */}
      <div className="mt-3 space-y-2">
        {/* Model */}
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider w-12 shrink-0">
            Model
          </span>
          <span className="text-xs font-mono text-slate-300 truncate">
            {model}
          </span>
        </div>

        {/* Tools */}
        <div className="flex items-start gap-2">
          <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider w-12 shrink-0 pt-0.5">
            Tools
          </span>
          <div className="flex flex-wrap gap-1.5">
            {tools.length > 0 ? (
              tools.map((tool) => (
                <span
                  key={tool}
                  className="inline-flex items-center rounded bg-slate-700/60 border border-slate-600/40 px-2 py-0.5 text-[11px] font-mono text-slate-300"
                >
                  {tool}
                </span>
              ))
            ) : (
              <span className="text-xs text-slate-500 italic">No tools</span>
            )}
          </div>
        </div>

        {/* Tokens today */}
        {tokensToday > 0 && (
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-medium text-slate-500 uppercase tracking-wider w-12 shrink-0">
              Tokens
            </span>
            <span className="text-xs font-mono text-blue-400">
              {formatTokens(tokensToday)} today
            </span>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="mt-4 flex items-center gap-2">
        <button
          onClick={() => onTest?.(id)}
          disabled={!isActionable}
          className="flex-1 rounded bg-blue-600/90 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-500 disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition-colors"
        >
          Test
        </button>
        <button
          onClick={() => onViewLogs?.(id)}
          className="flex-1 rounded border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700 hover:text-slate-100 focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition-colors"
        >
          View Logs
        </button>
        <button
          onClick={() => onRestart?.(id)}
          disabled={!isActionable}
          className="flex-1 rounded border border-slate-600 px-3 py-1.5 text-xs font-medium text-slate-300 hover:bg-slate-700 hover:text-slate-100 disabled:opacity-40 disabled:cursor-not-allowed focus:outline-none focus:ring-2 focus:ring-slate-500 focus:ring-offset-2 focus:ring-offset-slate-900 transition-colors"
        >
          Restart
        </button>
      </div>

      {/* Settings panel (expandable) */}
      {showSettings && (
        <SettingsPanel
          agentId={id}
          initialModel={model}
          initialEnabled={enabled}
          onSave={(agentId, settings) => {
            onSaveSettings?.(agentId, settings);
            if (onToggleEnabled && settings.enabled !== enabled) {
              onToggleEnabled(agentId, settings.enabled);
            }
          }}
          onClose={() => setShowSettings(false)}
        />
      )}
    </div>
  );
}

export default AgentCard;