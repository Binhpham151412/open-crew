"use client";

import React, {
  useCallback,
  useEffect,
  useRef,
  useState,
  useMemo,
} from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type LogLevel = "debug" | "info" | "warn" | "error" | "fatal";

export interface LogEntry {
  id: string;
  timestamp: string; // ISO-8601
  agent: string;
  level: LogLevel;
  message: string;
  metadata?: Record<string, unknown>;
}

interface LogViewerProps {
  /** Maximum number of log lines to keep in memory (older ones are pruned). */
  maxLines?: number;
  /** URL for the SSE log stream. Defaults to `/api/logs`. */
  streamUrl?: string;
  /** Optional initial filter state. */
  defaultAgent?: string;
  defaultLevel?: LogLevel | "all";
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LEVEL_COLORS: Record<LogLevel, { bg: string; text: string; badge: string }> = {
  debug: {
    bg: "bg-slate-800/40",
    text: "text-slate-400",
    badge: "bg-slate-700 text-slate-300",
  },
  info: {
    bg: "bg-blue-900/10",
    text: "text-blue-400",
    badge: "bg-blue-900/50 text-blue-300",
  },
  warn: {
    bg: "bg-amber-900/10",
    text: "text-amber-400",
    badge: "bg-amber-900/50 text-amber-300",
  },
  error: {
    bg: "bg-red-900/10",
    text: "text-red-400",
    badge: "bg-red-900/50 text-red-300",
  },
  fatal: {
    bg: "bg-red-900/20",
    text: "text-red-300",
    badge: "bg-red-800/60 text-red-200",
  },
};

const ALL_LEVELS: (LogLevel | "all")[] = ["all", "debug", "info", "warn", "error", "fatal"];

// Known agents from the OpenCrew system (pre-populated; also built dynamically)
const KNOWN_AGENTS = [
  "po",
  "pm",
  "ba",
  "solution-architect",
  "frontend-dev",
  "backend-dev",
  "uiux-reviewer",
  "security-reviewer",
  "qa",
  "devops",
  "techlead",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return d.toLocaleTimeString("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function escapeRegExp(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function highlightMatch(text: string, query: string): React.ReactNode {
  if (!query) return text;
  const escaped = escapeRegExp(query);
  const regex = new RegExp(`(${escaped})`, "gi");
  const parts = text.split(regex);
  return parts.map((part, i) =>
    regex.test(part) ? (
      <mark key={i} className="bg-yellow-500/30 text-yellow-200 rounded-sm px-0.5">
        {part}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

interface StatusDotProps {
  active: boolean;
}

function StatusDot({ active }: StatusDotProps) {
  return (
    <span className="relative flex h-2.5 w-2.5 shrink-0">
      {active && (
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75" />
      )}
      <span
        className={`relative inline-flex rounded-full h-2.5 w-2.5 ${
          active ? "bg-green-500" : "bg-slate-500"
        }`}
      />
    </span>
  );
}

// ---------------------------------------------------------------------------
// Main Component
// ---------------------------------------------------------------------------

export function LogViewer({
  maxLines = 2000,
  streamUrl = "/api/logs",
  defaultAgent = "all",
  defaultLevel = "all",
}: LogViewerProps) {
  // ----- State -----
  const [logs, setLogs] = useState<LogEntry[]>([]);
  const [isPaused, setIsPaused] = useState(false);
  const [isConnected, setIsConnected] = useState(false);
  const [filterAgent, setFilterAgent] = useState(defaultAgent);
  const [filterLevel, setFilterLevel] = useState<LogLevel | "all">(defaultLevel);
  const [searchQuery, setSearchQuery] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const [totalReceived, setTotalReceived] = useState(0);

  // Refs
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const logsRef = useRef<LogEntry[]>([]);
  const isPausedRef = useRef(isPaused);

  // Keep refs in sync
  useEffect(() => {
    isPausedRef.current = isPaused;
  }, [isPaused]);

  // ----- Dynamic agent list (merge known + discovered from logs) -----
  const agents = useMemo(() => {
    const discovered = new Set<string>();
    logs.forEach((l) => discovered.add(l.agent));
    KNOWN_AGENTS.forEach((a) => discovered.add(a));
    return ["all", ...Array.from(discovered).sort()];
  }, [logs]);

  // ----- SSE Connection -----
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    const es = new EventSource(streamUrl);
    eventSourceRef.current = es;

    es.onopen = () => {
      setIsConnected(true);
    };

    es.addEventListener("log", (event: MessageEvent) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        setTotalReceived((c) => c + 1);

        if (isPausedRef.current) {
          // Buffer even when paused so we don't miss anything
          logsRef.current = [...logsRef.current.slice(-(maxLines - 1)), entry];
        } else {
          setLogs((prev) => {
            const next = [...prev.slice(-(maxLines - 1)), entry];
            logsRef.current = next;
            return next;
          });
        }
      } catch {
        // Malformed log line — ignore
      }
    });

    // Fallback: handle generic SSE "message" events
    es.onmessage = (event: MessageEvent) => {
      try {
        const entry: LogEntry = JSON.parse(event.data);
        setTotalReceived((c) => c + 1);

        if (isPausedRef.current) {
          logsRef.current = [...logsRef.current.slice(-(maxLines - 1)), entry];
        } else {
          setLogs((prev) => {
            const next = [...prev.slice(-(maxLines - 1)), entry];
            logsRef.current = next;
            return next;
          });
        }
      } catch {
        // Not JSON or malformed
      }
    };

    es.onerror = () => {
      setIsConnected(false);
      es.close();
      // Attempt reconnect after 3 seconds
      setTimeout(() => connect(), 3000);
    };
  }, [streamUrl, maxLines]);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  // ----- Flush buffered logs when resuming -----
  useEffect(() => {
    if (!isPaused && logsRef.current.length > 0) {
      setLogs([...logsRef.current]);
    }
  }, [isPaused]);

  // ----- Auto-scroll -----
  useEffect(() => {
    if (autoScroll && !isPaused) {
      const el = scrollContainerRef.current;
      if (el) {
        el.scrollTop = el.scrollHeight;
      }
    }
  }, [logs, autoScroll, isPaused]);

  // Detect manual scroll to disable auto-scroll
  const handleScroll = useCallback(() => {
    const el = scrollContainerRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60;
    setAutoScroll(atBottom);
  }, []);

  // ----- Filtering -----
  const filteredLogs = useMemo(() => {
    const query = searchQuery.toLowerCase();
    return logs.filter((log) => {
      if (filterAgent !== "all" && log.agent !== filterAgent) return false;
      if (filterLevel !== "all" && log.level !== filterLevel) return false;
      if (query && !log.message.toLowerCase().includes(query) &&
          !log.agent.toLowerCase().includes(query)) {
        return false;
      }
      return true;
    });
  }, [logs, filterAgent, filterLevel, searchQuery]);

  // ----- Actions -----
  const togglePause = useCallback(() => {
    setIsPaused((p) => !p);
  }, []);

  const clearLogs = useCallback(() => {
    setLogs([]);
    logsRef.current = [];
    setTotalReceived(0);
  }, []);

  const scrollToBottom = useCallback(() => {
    const el = scrollContainerRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
      setAutoScroll(true);
    }
  }, []);

  // ----- Render -----
  return (
    <div className="flex flex-col h-full rounded-lg border border-slate-700/60 bg-slate-900 overflow-hidden">
      {/* ── Header / Toolbar ── */}
      <div className="shrink-0 border-b border-slate-700/60 bg-slate-900/95 backdrop-blur">
        {/* Row 1: Title + stats + actions */}
        <div className="flex items-center justify-between px-4 py-2.5 gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <h2 className="text-sm font-semibold text-slate-100 shrink-0">Log Stream</h2>
            <StatusDot active={isConnected} />
            <span className="text-xs text-slate-400 shrink-0">
              {isConnected ? "Connected" : "Reconnecting…"}
            </span>
            <span className="text-xs text-slate-500 shrink-0 hidden sm:inline">
              {filteredLogs.length} / {totalReceived} entries
            </span>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            {/* Scroll to bottom */}
            {!autoScroll && (
              <button
                onClick={scrollToBottom}
                className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-slate-300 bg-slate-800 hover:bg-slate-700 rounded transition-colors"
                title="Scroll to latest"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 14l-7 7m0 0l-7-7m7 7V3" />
                </svg>
                Latest
              </button>
            )}

            {/* Pause / Resume */}
            <button
              onClick={togglePause}
              className={`inline-flex items-center gap-1.5 px-3 py-1 text-xs font-medium rounded transition-colors ${
                isPaused
                  ? "bg-green-600/20 text-green-400 hover:bg-green-600/30 border border-green-600/30"
                  : "bg-amber-600/20 text-amber-400 hover:bg-amber-600/30 border border-amber-600/30"
              }`}
            >
              {isPaused ? (
                <>
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M8 5v14l11-7z" />
                  </svg>
                  Resume
                </>
              ) : (
                <>
                  <svg className="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M6 4h4v16H6V4zm8 0h4v16h-4V4z" />
                  </svg>
                  Pause
                </>
              )}
            </button>

            {/* Clear */}
            <button
              onClick={clearLogs}
              className="inline-flex items-center gap-1 px-2.5 py-1 text-xs font-medium text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded transition-colors"
              title="Clear all logs"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
              </svg>
              Clear
            </button>
          </div>
        </div>

        {/* Row 2: Filters */}
        <div className="flex flex-wrap items-center gap-2 px-4 pb-2.5">
          {/* Agent filter */}
          <div className="flex items-center gap-1.5">
            <label htmlFor="log-filter-agent" className="text-xs text-slate-400 shrink-0">
              Agent:
            </label>
            <select
              id="log-filter-agent"
              value={filterAgent}
              onChange={(e) => setFilterAgent(e.target.value)}
              className="h-7 px-2 text-xs bg-slate-800 border border-slate-700 rounded text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 appearance-none pr-6 cursor-pointer"
              style={{
                backgroundImage:
                  'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' fill=\'none\' viewBox=\'0 0 20 20\'%3E%3Cpath stroke=\'%2394a3b8\' stroke-linecap=\'round\' stroke-linejoin=\'round\' stroke-width=\'1.5\' d=\'M6 8l4 4 4-4\'/%3E%3C/svg%3E")',
                backgroundPosition: "right 4px center",
                backgroundRepeat: "no-repeat",
                backgroundSize: "16px",
              }}
            >
              {agents.map((a) => (
                <option key={a} value={a}>
                  {a === "all" ? "All Agents" : a}
                </option>
              ))}
            </select>
          </div>

          {/* Level filter */}
          <div className="flex items-center gap-1.5">
            <label htmlFor="log-filter-level" className="text-xs text-slate-400 shrink-0">
              Level:
            </label>
            <select
              id="log-filter-level"
              value={filterLevel}
              onChange={(e) => setFilterLevel(e.target.value as LogLevel | "all")}
              className="h-7 px-2 text-xs bg-slate-800 border border-slate-700 rounded text-slate-200 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500 appearance-none pr-6 cursor-pointer"
              style={{
                backgroundImage:
                  'url("data:image/svg+xml,%3Csvg xmlns=\'http://www.w3.org/2000/svg\' fill=\'none\' viewBox=\'0 0 20 20\'%3E%3Cpath stroke=\'%2394a3b8\' stroke-linecap=\'round\' stroke-linejoin=\'round\' stroke-width=\'1.5\' d=\'M6 8l4 4 4-4\'/%3E%3C/svg%3E")',
                backgroundPosition: "right 4px center",
                backgroundRepeat: "no-repeat",
                backgroundSize: "16px",
              }}
            >
              {ALL_LEVELS.map((l) => (
                <option key={l} value={l}>
                  {l === "all" ? "All Levels" : l.toUpperCase()}
                </option>
              ))}
            </select>
          </div>

          {/* Search */}
          <div className="flex items-center gap-1.5 flex-1 min-w-[180px] max-w-sm">
            <label htmlFor="log-search" className="text-xs text-slate-400 shrink-0">
              Search:
            </label>
            <div className="relative flex-1">
              <svg
                className="absolute left-2 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-slate-500 pointer-events-none"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"
                />
              </svg>
              <input
                id="log-search"
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Filter logs…"
                className="w-full h-7 pl-7 pr-2 text-xs bg-slate-800 border border-slate-700 rounded text-slate-200 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
              />
              {searchQuery && (
                <button
                  onClick={() => setSearchQuery("")}
                  className="absolute right-1.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300 transition-colors"
                >
                  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* ── Log Body ── */}
      <div
        ref={scrollContainerRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto overflow-x-auto font-mono text-[13px] leading-relaxed"
      >
        {filteredLogs.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2 py-12">
            <svg className="w-10 h-10 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
              />
            </svg>
            <span className="text-sm">
              {isPaused
                ? "Stream paused — click Resume to continue"
                : "Waiting for logs…"}
            </span>
            {isConnected && !isPaused && (
              <span className="text-xs text-slate-600">Connected to {streamUrl}</span>
            )}
          </div>
        ) : (
          <table className="w-full border-collapse">
            <tbody>
              {filteredLogs.map((log) => {
                const colors = LEVEL_COLORS[log.level] ?? LEVEL_COLORS.info;
                return (
                  <tr
                    key={log.id}
                    className={`group border-b border-slate-800/60 hover:bg-slate-800/40 transition-colors ${colors.bg}`}
                  >
                    {/* Timestamp */}
                    <td className="px-3 py-1 whitespace-nowrap text-slate-500 select-all align-top w-[1%]">
                      {formatTimestamp(log.timestamp)}
                    </td>

                    {/* Agent */}
                    <td className="px-2 py-1 whitespace-nowrap align-top w-[1%]">
                      <span className="inline-block text-xs font-medium px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700/50">
                        {log.agent}
                      </span>
                    </td>

                    {/* Level badge */}
                    <td className="px-2 py-1 whitespace-nowrap align-top w-[1%]">
                      <span
                        className={`inline-block text-[11px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded ${colors.badge}`}
                      >
                        {log.level}
                      </span>
                    </td>

                    {/* Message */}
                    <td className={`px-3 py-1 break-all ${colors.text}`}>
                      {searchQuery ? highlightMatch(log.message, searchQuery) : log.message}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      {/* ── Footer ── */}
      <div className="shrink-0 border-t border-slate-700/60 bg-slate-900/95 px-4 py-1.5 flex items-center justify-between text-[11px] text-slate-500">
        <span>
          {filteredLogs.length} displayed
          {filterAgent !== "all" || filterLevel !== "all" || searchQuery
            ? ` (filtered from ${logs.length})`
            : ""}
        </span>
        <div className="flex items-center gap-3">
          {isPaused && (
            <span className="flex items-center gap-1 text-amber-400">
              <span className="inline-block w-1.5 h-1.5 rounded-full bg-amber-400 animate-pulse" />
              Paused
            </span>
          )}
          {autoScroll && !isPaused && (
            <span className="text-green-500/70">auto-scrolling</span>
          )}
        </div>
      </div>
    </div>
  );
}

export default LogViewer;