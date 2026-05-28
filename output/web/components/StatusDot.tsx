import { type FC } from "react";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type AgentStatus = "online" | "offline" | "working" | "error";

export interface StatusDotProps {
  /** Current status of the agent. */
  status: AgentStatus;
  /** Optional label rendered next to the dot. */
  label?: string;
  /** Size of the dot in pixels. @default 10 */
  size?: number;
  /** Additional className for the wrapper element. */
  className?: string;
}

// ---------------------------------------------------------------------------
// Style map
// ---------------------------------------------------------------------------

const STATUS_STYLES: Record<
  AgentStatus,
  { bg: string; ring: string; pulse: boolean; textColor: string }
> = {
  online: {
    bg: "bg-green-500",
    ring: "ring-green-500/30",
    pulse: false,
    textColor: "text-green-400",
  },
  offline: {
    bg: "bg-slate-500",
    ring: "ring-slate-500/20",
    pulse: false,
    textColor: "text-slate-400",
  },
  working: {
    bg: "bg-amber-400",
    ring: "ring-amber-400/30",
    pulse: true,
    textColor: "text-amber-400",
  },
  error: {
    bg: "bg-red-500",
    ring: "ring-red-500/30",
    pulse: true,
    textColor: "text-red-400",
  },
};

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * StatusDot — a small coloured circle that reflects an agent's runtime state.
 *
 * - **online** → solid green
 * - **offline** → solid gray (dimmer)
 * - **working** → amber with a pulsing glow animation
 * - **error** → red with a pulsing glow animation
 *
 * @example
 * ```tsx
 * <StatusDot status="online" />
 * <StatusDot status="working" label="coding" size={12} />
 * ```
 */
export const StatusDot: FC<StatusDotProps> = ({
  status,
  label,
  size = 10,
  className = "",
}) => {
  const styles = STATUS_STYLES[status] ?? STATUS_STYLES.offline;

  return (
    <span
      className={`inline-flex items-center gap-2 ${className}`}
      role="status"
      aria-label={`Status: ${status}`}
    >
      {/* Dot */}
      <span className="relative inline-flex shrink-0">
        {/* Pulse ring — only rendered for animated states */}
        {styles.pulse && (
          <span
            className={`absolute inset-0 rounded-full ${styles.bg} opacity-60 animate-ping`}
            style={{ width: size, height: size }}
          />
        )}

        {/* Core dot */}
        <span
          className={`relative block rounded-full ${styles.bg} ring-2 ${styles.ring}`}
          style={{ width: size, height: size }}
        />
      </span>

      {/* Optional label */}
      {label && (
        <span className={`text-sm font-medium capitalize ${styles.textColor}`}>
          {label}
        </span>
      )}
    </span>
  );
};

StatusDot.displayName = "StatusDot";