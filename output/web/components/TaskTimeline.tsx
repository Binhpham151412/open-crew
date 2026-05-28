"use client";

import React, { useState, useMemo } from "react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** A2A message types from the protocol */
type MessageType =
  | "task"
  | "challenge"
  | "response"
  | "final_position"
  | "escalate"
  | "decision"
  | "result";

/** Minimal A2A message for timeline display */
export interface A2AMessage {
  protocol: string;
  type: MessageType;
  from: string;
  to: string;
  task_id: string;
  round?: number;
  payload: {
    claim: string;
    evidence?: string;
    suggestion?: string;
    artifacts?: { name: string }[];
    metadata?: Record<string, unknown>;
  };
  timestamp: string;
}

interface TaskTimelineProps {
  /** Array of A2A messages ordered chronologically */
  messages: A2AMessage[];
  /** Optional className for the outer container */
  className?: string;
  /** Max messages shown initially (rest behind "Show more") */
  initialCount?: number;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Display-friendly agent names */
const AGENT_DISPLAY_NAMES: Record<string, string> = {
  po: "Product Owner",
  pm: "Project Manager",
  ba: "Business Analyst",
  "solution-architect": "Solution Architect",
  solution_architect: "Solution Architect",
  "frontend-dev": "Frontend Dev",
  frontend_dev: "Frontend Dev",
  "backend-dev": "Backend Dev",
  backend_dev: "Backend Dev",
  "uiux-reviewer": "UIUX Reviewer",
  uiux_reviewer: "UIUX Reviewer",
  "security-reviewer": "Security Reviewer",
  security_reviewer: "Security Reviewer",
  qa: "QA / Tester",
  devops: "DevOps / SRE",
  techlead: "TechLead",
};

/** Short colour palette for agent chips — cycles through on unknown agents */
const AGENT_COLORS = [
  { bg: "bg-blue-500/20", text: "text-blue-400", border: "border-blue-500/30" },
  { bg: "bg-emerald-500/20", text: "text-emerald-400", border: "border-emerald-500/30" },
  { bg: "bg-violet-500/20", text: "text-violet-400", border: "border-violet-500/30" },
  { bg: "bg-amber-500/20", text: "text-amber-400", border: "border-amber-500/30" },
  { bg: "bg-rose-500/20", text: "text-rose-400", border: "border-rose-500/30" },
  { bg: "bg-cyan-500/20", text: "text-cyan-400", border: "border-cyan-500/30" },
  { bg: "bg-fuchsia-500/20", text: "text-fuchsia-400", border: "border-fuchsia-500/30" },
  { bg: "bg-lime-500/20", text: "text-lime-400", border: "border-lime-500/30" },
  { bg: "bg-orange-500/20", text: "text-orange-400", border: "border-orange-500/30" },
  { bg: "bg-teal-500/20", text: "text-teal-400", border: "border-teal-500/30" },
  { bg: "bg-sky-500/20", text: "text-sky-400", border: "border-sky-500/30" },
];

function agentDisplayName(agent: string): string {
  return AGENT_DISPLAY_NAMES[agent] ?? agent;
}

/** Stable hash → index for agent colours */
function agentColorIndex(agent: string): number {
  let hash = 0;
  for (let i = 0; i < agent.length; i++) {
    hash = (hash * 31 + agent.charCodeAt(i)) | 0;
  }
  return Math.abs(hash) % AGENT_COLORS.length;
}

function agentColors(agent: string) {
  return AGENT_COLORS[agentColorIndex(agent)];
}

/** Badge styling per message type */
const MESSAGE_TYPE_META: Record<
  MessageType,
  { label: string; color: string; icon: string }
> = {
  task: {
    label: "Task",
    color: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    icon: "📋",
  },
  challenge: {
    label: "Challenge",
    color: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    icon: "⚔️",
  },
  response: {
    label: "Response",
    color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    icon: "💬",
  },
  final_position: {
    label: "Final Position",
    color: "bg-violet-500/20 text-violet-400 border-violet-500/30",
    icon: "📌",
  },
  escalate: {
    label: "Escalate",
    color: "bg-rose-500/20 text-rose-400 border-rose-500/30",
    icon: "⏫",
  },
  decision: {
    label: "Decision",
    color: "bg-rose-500/20 text-rose-400 border-rose-500/30",
    icon: "⚖️",
  },
  result: {
    label: "Result",
    color: "bg-emerald-500/20 text-emerald-400 border-emerald-500/30",
    icon: "✅",
  },
};

/** Format ISO timestamp → human-readable local time */
function formatTimestamp(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function formatDate(iso: string): string {
  try {
    const date = new Date(iso);
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "";
  }
}

/** Truncate text to a max length with ellipsis */
function truncate(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max).trimEnd() + "…";
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/** Small chip for an agent identity */
function AgentChip({ agent }: { agent: string }) {
  const c = agentColors(agent);
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
        c.bg,
        c.text,
        c.border
      )}
    >
      {agentDisplayName(agent)}
    </span>
  );
}

/** Badge for message type */
function MessageTypeBadge({ type }: { type: MessageType }) {
  const meta = MESSAGE_TYPE_META[type] ?? {
    label: type,
    color: "bg-slate-600/30 text-slate-300 border-slate-500/30",
    icon: "📩",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap",
        meta.color
      )}
    >
      <span aria-hidden>{meta.icon}</span>
      {meta.label}
    </span>
  );
}

/** Single timeline entry — the node + card */
function TimelineEntry({ message, isLast }: { message: A2AMessage; isLast: boolean }) {
  const [expanded, setExpanded] = useState(false);
  const hasEvidence = !!message.payload.evidence;
  const hasSuggestion = !!message.payload.suggestion;
  const artifactCount = message.payload.artifacts?.length ?? 0;
  const expandable = hasEvidence || hasSuggestion || artifactCount > 0;

  return (
    <div className="relative flex gap-4 group">
      {/* Vertical connector line */}
      <div className="flex flex-col items-center">
        {/* Node dot */}
        <div
          className={cn(
            "relative z-10 mt-1.5 h-3 w-3 shrink-0 rounded-full border-2",
            message.type === "task" || message.type === "result"
              ? "bg-blue-500 border-blue-400"
              : message.type === "challenge" || message.type === "escalate"
              ? "bg-amber-500 border-amber-400"
              : message.type === "decision"
              ? "bg-rose-500 border-rose-400"
              : "bg-slate-500 border-slate-400"
          )}
        />
        {/* Vertical line */}
        {!isLast && (
          <div className="w-px flex-1 bg-slate-700/60 group-last:hidden" />
        )}
      </div>

      {/* Card */}
      <div className="flex-1 pb-6">
        {/* Header row: timestamp + type badge + round */}
        <div className="flex flex-wrap items-center gap-2 mb-1.5">
          <span className="font-mono text-xs text-slate-400 tabular-nums">
            {formatTimestamp(message.timestamp)}
          </span>
          <MessageTypeBadge type={message.type} />
          {message.round !== undefined && message.round > 0 && (
            <span className="inline-flex items-center rounded-md bg-slate-700/50 border border-slate-600/40 px-1.5 py-0.5 text-[10px] font-medium text-slate-400 tabular-nums">
              Round {message.round}
            </span>
          )}
        </div>

        {/* From → To */}
        <div className="flex items-center gap-2 mb-2 text-sm">
          <AgentChip agent={message.from} />
          <span className="text-slate-500" aria-hidden>
            →
          </span>
          <AgentChip agent={message.to} />
        </div>

        {/* Claim / summary */}
        <p className="text-sm text-slate-200 leading-relaxed">
          {expanded ? message.payload.claim : truncate(message.payload.claim, 220)}
        </p>

        {/* Expandable details */}
        {expandable && (
          <>
            {expanded && (
              <div className="mt-3 space-y-2">
                {hasEvidence && (
                  <div className="rounded-md bg-slate-800/80 border border-slate-700/50 p-3">
                    <span className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                      Evidence
                    </span>
                    <p className="text-xs text-slate-300 font-mono whitespace-pre-wrap break-words">
                      {message.payload.evidence}
                    </p>
                  </div>
                )}
                {hasSuggestion && (
                  <div className="rounded-md bg-slate-800/80 border border-slate-700/50 p-3">
                    <span className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                      Suggestion
                    </span>
                    <p className="text-xs text-slate-300 whitespace-pre-wrap break-words">
                      {message.payload.suggestion}
                    </p>
                  </div>
                )}
                {artifactCount > 0 && (
                  <div className="rounded-md bg-slate-800/80 border border-slate-700/50 p-3">
                    <span className="block text-[10px] uppercase tracking-wider text-slate-500 font-semibold mb-1">
                      Artifacts ({artifactCount})
                    </span>
                    <ul className="space-y-1">
                      {message.payload.artifacts!.map((a, i) => (
                        <li
                          key={i}
                          className="flex items-center gap-1.5 text-xs text-slate-300"
                        >
                          <span className="text-slate-500" aria-hidden>
                            📄
                          </span>
                          <span className="font-mono">{a.name}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            <button
              type="button"
              onClick={() => setExpanded((v) => !v)}
              className="mt-2 text-xs text-blue-400 hover:text-blue-300 transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500 rounded"
            >
              {expanded ? "▲ Show less" : "▼ Show details"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export function TaskTimeline({
  messages,
  className,
  initialCount = 15,
}: TaskTimelineProps) {
  const [showAll, setShowAll] = useState(false);

  const sorted = useMemo(
    () =>
      [...messages].sort(
        (a, b) =>
          new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
      ),
    [messages]
  );

  const visible = showAll ? sorted : sorted.slice(0, initialCount);
  const hiddenCount = sorted.length - visible.length;

  if (sorted.length === 0) {
    return (
      <div
        className={cn(
          "flex flex-col items-center justify-center py-16 text-slate-400",
          className
        )}
      >
        <span className="text-4xl mb-3" aria-hidden>
          📭
        </span>
        <p className="text-sm">No messages yet for this task.</p>
        <p className="text-xs text-slate-500 mt-1">
          A2A messages will appear here as agents communicate.
        </p>
      </div>
    );
  }

  return (
    <div className={cn("relative", className)}>
      {/* Date header for the first message */}
      {sorted.length > 0 && (
        <div className="flex items-center gap-3 mb-4">
          <span className="text-xs font-medium text-slate-400">
            {formatDate(sorted[0].timestamp)}
          </span>
          <div className="flex-1 h-px bg-slate-700/40" />
        </div>
      )}

      {/* Timeline entries */}
      <div className="ml-1">
        {visible.map((msg, idx) => (
          <TimelineEntry
            key={`${msg.from}-${msg.to}-${msg.timestamp}-${idx}`}
            message={msg}
            isLast={idx === visible.length - 1 && hiddenCount <= 0}
          />
        ))}
      </div>

      {/* Show more button */}
      {hiddenCount > 0 && (
        <div className="flex justify-center pt-2 pb-4">
          <button
            type="button"
            onClick={() => setShowAll(true)}
            className="inline-flex items-center gap-1.5 rounded-md border border-slate-600/40 bg-slate-800/70 px-4 py-2 text-xs font-medium text-slate-300 hover:text-slate-100 hover:border-slate-500/50 transition-colors focus:outline-none focus-visible:ring-1 focus-visible:ring-blue-500"
          >
            Show {hiddenCount} more message{hiddenCount !== 1 ? "s" : ""}
          </button>
        </div>
      )}

      {/* Summary footer */}
      <div className="flex items-center justify-between pt-3 border-t border-slate-700/40 text-[11px] text-slate-500">
        <span>
          {sorted.length} message{sorted.length !== 1 ? "s" : ""}
        </span>
        <span className="tabular-nums">
          {formatTimestamp(sorted[0].timestamp)} –{" "}
          {formatTimestamp(sorted[sorted.length - 1].timestamp)}
        </span>
      </div>
    </div>
  );
}

export default TaskTimeline;