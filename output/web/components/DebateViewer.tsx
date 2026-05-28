import { useMemo } from "react";

// ─── Types ────────────────────────────────────────────────────────────────────

export type MessageType =
  | "task"
  | "challenge"
  | "response"
  | "final_position"
  | "escalate"
  | "decision"
  | "result";

export type ResponseDisposition = "accept" | "counter";

export interface DebateArtifact {
  name: string;
  content?: string;
}

export interface DebatePayload {
  claim: string;
  evidence?: string;
  suggestion?: string;
  artifacts?: DebateArtifact[];
}

export interface DebateMessage {
  id?: string;
  protocol?: string;
  type: MessageType;
  from: string;
  to: string;
  task_id?: string;
  round: number;
  payload: DebatePayload;
  timestamp: string;
  /** Optional disposition embedded in payload metadata for response messages */
  disposition?: ResponseDisposition;
}

export interface DebateViewerProps {
  /** Task or conflict ID tying the debate together */
  taskId: string;
  /** Ordered list of A2A messages that form this debate */
  messages: DebateMessage[];
  /** Optional human-readable title */
  title?: string;
  /** Optional callback when a message is clicked */
  onMessageClick?: (message: DebateMessage) => void;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const TYPE_META: Record<
  MessageType,
  {
    label: string;
    color: string;
    bg: string;
    border: string;
    icon: string;
    ring: string;
  }
> = {
  challenge: {
    label: "Challenge",
    color: "text-amber-400",
    bg: "bg-amber-500/10",
    border: "border-amber-500/40",
    icon: "⚡",
    ring: "ring-amber-500/30",
  },
  response: {
    label: "Response",
    color: "text-sky-400",
    bg: "bg-sky-500/10",
    border: "border-sky-500/40",
    icon: "💬",
    ring: "ring-sky-500/30",
  },
  final_position: {
    label: "Final Position",
    color: "text-violet-400",
    bg: "bg-violet-500/10",
    border: "border-violet-500/40",
    icon: "🎯",
    ring: "ring-violet-500/30",
  },
  escalate: {
    label: "Escalate",
    color: "text-red-400",
    bg: "bg-red-500/10",
    border: "border-red-500/40",
    icon: "⏫",
    ring: "ring-red-500/30",
  },
  decision: {
    label: "Decision",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/40",
    icon: "⚖️",
    ring: "ring-emerald-500/30",
  },
  task: {
    label: "Task",
    color: "text-slate-400",
    bg: "bg-slate-500/10",
    border: "border-slate-500/40",
    icon: "📋",
    ring: "ring-slate-500/30",
  },
  result: {
    label: "Result",
    color: "text-emerald-400",
    bg: "bg-emerald-500/10",
    border: "border-emerald-500/40",
    icon: "✅",
    ring: "ring-emerald-500/30",
  },
};

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    });
  } catch {
    return iso;
  }
}

function formatAgentName(raw: string): string {
  return raw
    .split(/[-_]/)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function getDispositionBadge(disposition?: ResponseDisposition) {
  if (!disposition) return null;
  if (disposition === "accept") {
    return (
      <span className="ml-2 inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
        ✓ Accepted
      </span>
    );
  }
  return (
    <span className="ml-2 inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide bg-amber-500/15 text-amber-400 border border-amber-500/30">
      ↩ Counter
    </span>
  );
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function PhaseConnector({ variant = "default" }: { variant?: "default" | "escalation" | "final" }) {
  const color =
    variant === "escalation"
      ? "border-red-500/40"
      : variant === "final"
        ? "border-emerald-500/40"
        : "border-slate-700/60";

  return (
    <div className="flex justify-center py-1">
      <div className={`w-px h-6 border-l-2 border-dashed ${color}`} />
    </div>
  );
}

function ArtifactsList({ artifacts }: { artifacts: DebateArtifact[] }) {
  if (!artifacts.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {artifacts.map((a, i) => (
        <span
          key={`${a.name}-${i}`}
          className="inline-flex items-center gap-1 rounded bg-slate-700/50 px-2 py-0.5 text-[11px] font-mono text-slate-300 border border-slate-600/50"
          title={a.content ? a.content.slice(0, 200) : undefined}
        >
          <span className="text-slate-500">📎</span>
          {a.name}
        </span>
      ))}
    </div>
  );
}

function DebateMessageCard({
  message,
  isLast,
  onClick,
}: {
  message: DebateMessage;
  isLast: boolean;
  onClick?: (msg: DebateMessage) => void;
}) {
  const meta = TYPE_META[message.type] ?? TYPE_META.task;
  const isDecision = message.type === "decision";
  const isEscalate = message.type === "escalate";

  return (
    <button
      type="button"
      onClick={() => onClick?.(message)}
      className={`
        w-full text-left rounded-lg border p-4 transition-all duration-200
        ${meta.bg} ${meta.border}
        hover:ring-2 ${meta.ring} hover:shadow-lg hover:shadow-slate-950/40
        focus:outline-none focus:ring-2 ${meta.ring}
        ${isDecision ? "ring-2 ring-emerald-500/20" : ""}
        ${isEscalate ? "ring-2 ring-red-500/20" : ""}
      `}
    >
      {/* Header row */}
      <div className="flex items-center justify-between gap-2 mb-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-base shrink-0" aria-hidden="true">
            {meta.icon}
          </span>
          <span className={`text-xs font-semibold uppercase tracking-wide ${meta.color}`}>
            {meta.label}
          </span>
          {getDispositionBadge(message.disposition)}
          {(isDecision || isEscalate) && (
            <span className="ml-1 inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-bold uppercase tracking-wider bg-slate-700/60 text-slate-300 border border-slate-600/40">
              Final
            </span>
          )}
        </div>
        <span className="text-[11px] text-slate-500 font-mono shrink-0 tabular-nums">
          {formatTimestamp(message.timestamp)}
        </span>
      </div>

      {/* Agents involved */}
      <div className="flex items-center gap-1.5 mb-3 text-xs">
        <span className="inline-flex items-center gap-1 rounded bg-slate-800/80 px-2 py-0.5 font-medium text-slate-200 border border-slate-700/60">
          {formatAgentName(message.from)}
        </span>
        <span className={`text-sm ${meta.color}`} aria-hidden="true">
          →
        </span>
        <span className="inline-flex items-center gap-1 rounded bg-slate-800/80 px-2 py-0.5 font-medium text-slate-200 border border-slate-700/60">
          {formatAgentName(message.to)}
        </span>
        <span className="ml-auto text-[11px] text-slate-500 font-mono">
          Round {message.round}
        </span>
      </div>

      {/* Claim */}
      <p className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap">
        {message.payload.claim}
      </p>

      {/* Evidence */}
      {message.payload.evidence && (
        <div className="mt-2.5 rounded bg-slate-900/60 border border-slate-700/40 px-3 py-2">
          <span className="block text-[10px] font-semibold uppercase tracking-wide text-slate-500 mb-1">
            Evidence
          </span>
          <p className="text-xs text-slate-300 font-mono leading-relaxed whitespace-pre-wrap break-words">
            {message.payload.evidence}
          </p>
        </div>
      )}

      {/* Suggestion */}
      {message.payload.suggestion && (
        <div className="mt-2 rounded bg-blue-500/5 border border-blue-500/20 px-3 py-2">
          <span className="block text-[10px] font-semibold uppercase tracking-wide text-blue-400/70 mb-1">
            Suggestion
          </span>
          <p className="text-xs text-slate-300 leading-relaxed whitespace-pre-wrap">
            {message.payload.suggestion}
          </p>
        </div>
      )}

      {/* Artifacts */}
      <ArtifactsList artifacts={message.payload.artifacts ?? []} />
    </button>
  );
}

function DebateStatusBar({
  messages,
  taskId,
}: {
  messages: DebateMessage[];
  taskId: string;
}) {
  const roundCount = Math.max(...messages.map((m) => m.round), 0);
  const hasEscalation = messages.some((m) => m.type === "escalate" || m.type === "decision");
  const resolvedByAcceptance = messages.some(
    (m) => m.type === "response" && m.disposition === "accept",
  );

  const statusText = hasEscalation
    ? "Escalated to TechLead"
    : resolvedByAcceptance
      ? "Resolved — Accepted"
      : roundCount >= 3
        ? "Awaiting Resolution"
        : "In Progress";

  const statusColor = hasEscalation
    ? "text-red-400"
    : resolvedByAcceptance
      ? "text-emerald-400"
      : "text-amber-400";

  const dotColor = hasEscalation
    ? "bg-red-500"
    : resolvedByAcceptance
      ? "bg-emerald-500"
      : "bg-amber-500 animate-pulse";

  return (
    <div className="flex items-center justify-between gap-3 px-4 py-2.5 bg-slate-800/60 border border-slate-700/40 rounded-lg">
      <div className="flex items-center gap-3 min-w-0">
        <span className={`block w-2 h-2 rounded-full shrink-0 ${dotColor}`} />
        <span className="text-xs text-slate-400 truncate">
          Conflict <span className="font-mono text-slate-300">{taskId}</span>
        </span>
      </div>
      <div className="flex items-center gap-3 shrink-0">
        <span className="text-[11px] text-slate-500 font-mono tabular-nums">
          {roundCount} {roundCount === 1 ? "round" : "rounds"} · {messages.length}{" "}
          {messages.length === 1 ? "message" : "messages"}
        </span>
        <span className={`text-xs font-semibold ${statusColor}`}>{statusText}</span>
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

/**
 * DebateViewer — renders the full debate flow between two (or more) agents.
 *
 * Visualises the A2A protocol's conflict resolution pattern:
 *   CHALLENGE → RESPONSE → FINAL_POSITION → (optional) ESCALATE → DECISION
 *
 * Each message card is colour-coded by type and shows the agents involved,
 * the round number, claim, evidence, suggestion, and attached artifacts.
 */
export function DebateViewer({
  taskId,
  messages,
  title,
  onMessageClick,
}: DebateViewerProps) {
  const sorted = useMemo(
    () =>
      [...messages].sort((a, b) => {
        if (a.round !== b.round) return a.round - b.round;
        return new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime();
      }),
    [messages],
  );

  if (sorted.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700/40 bg-slate-800/40 p-8 text-center">
        <span className="text-2xl mb-2 block" aria-hidden="true">
          💬
        </span>
        <p className="text-sm text-slate-400">
          No debate messages yet for conflict{" "}
          <span className="font-mono text-slate-300">{taskId}</span>.
        </p>
      </div>
    );
  }

  return (
    <section className="flex flex-col gap-3" aria-label={`Debate ${taskId}`}>
      {/* Title */}
      {title && (
        <h3 className="text-sm font-semibold text-slate-200 flex items-center gap-2">
          <span aria-hidden="true">⚖️</span>
          {title}
        </h3>
      )}

      {/* Status bar */}
      <DebateStatusBar messages={sorted} taskId={taskId} />

      {/* Debate flow */}
      <div className="flex flex-col gap-0">
        {sorted.map((msg, i) => {
          const isLast = i === sorted.length - 1;
          const nextMsg = sorted[i + 1];

          const connectorVariant =
            msg.type === "escalate" || (nextMsg && nextMsg.type === "decision")
              ? "escalation"
              : isLast
                ? "final"
                : "default";

          return (
            <div key={msg.id ?? `${msg.type}-${msg.round}-${msg.from}-${i}`}>
              <DebateMessageCard
                message={msg}
                isLast={isLast}
                onClick={onMessageClick}
              />
              {!isLast && <PhaseConnector variant={connectorVariant} />}
            </div>
          );
        })}
      </div>

      {/* Conflict resolution summary */}
      <ConflictSummary messages={sorted} />
    </section>
  );
}

// ─── Conflict Resolution Summary ──────────────────────────────────────────────

function ConflictSummary({ messages }: { messages: DebateMessage[] }) {
  const hasEscalation = messages.some((m) => m.type === "escalate");
  const decision = messages.find((m) => m.type === "decision");
  const lastFinal = [...messages].reverse().find((m) => m.type === "final_position");
  const accepted = messages.some(
    (m) => m.type === "response" && m.disposition === "accept",
  );

  if (accepted) {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-4 py-3">
        <span className="text-lg shrink-0" aria-hidden="true">
          ✅
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">
            Conflict Resolved
          </p>
          <p className="text-sm text-slate-300 mt-0.5">
            The challenged agent accepted the challenge. No escalation needed.
          </p>
        </div>
      </div>
    );
  }

  if (decision) {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-emerald-500/10 border border-emerald-500/30 px-4 py-3">
        <span className="text-lg shrink-0" aria-hidden="true">
          ⚖️
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-emerald-400 uppercase tracking-wide">
            TechLead Decision — Final
          </p>
          <p className="text-sm text-slate-300 mt-0.5">
            {decision.payload.claim}
          </p>
          {decision.payload.suggestion && (
            <p className="text-xs text-slate-400 mt-1">
              Action: {decision.payload.suggestion}
            </p>
          )}
        </div>
      </div>
    );
  }

  if (hasEscalation) {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-red-500/10 border border-red-500/30 px-4 py-3">
        <span className="text-lg shrink-0" aria-hidden="true">
          ⏫
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-red-400 uppercase tracking-wide">
            Escalated to TechLead
          </p>
          <p className="text-sm text-slate-300 mt-0.5">
            Agents could not reach agreement after{" "}
            {Math.max(...messages.map((m) => m.round))} rounds. Awaiting
            TechLead arbitration.
          </p>
        </div>
      </div>
    );
  }

  if (lastFinal) {
    return (
      <div className="flex items-center gap-3 rounded-lg bg-violet-500/10 border border-violet-500/30 px-4 py-3">
        <span className="text-lg shrink-0" aria-hidden="true">
          🎯
        </span>
        <div className="min-w-0">
          <p className="text-xs font-semibold text-violet-400 uppercase tracking-wide">
            Final Position Stated
          </p>
          <p className="text-sm text-slate-300 mt-0.5">
            <span className="font-medium text-slate-200">
              {formatAgentName(lastFinal.from)}
            </span>{" "}
            has stated their final position. Conflict may escalate if unresolved.
          </p>
        </div>
      </div>
    );
  }

  return null;
}

export default DebateViewer;