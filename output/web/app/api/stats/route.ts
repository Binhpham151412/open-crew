import { NextResponse } from "next/server";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface AgentHealth {
  name: string;
  status: "online" | "offline" | "working" | "error";
  queue_size: number;
  uptime_seconds: number;
  port: number;
}

interface TokenRecord {
  agent: string;
  tokens: number;
  timestamp: string;
}

interface DailyTokenUsage {
  date: string;
  total: number;
  byAgent: Record<string, number>;
}

interface AgentStats {
  name: string;
  displayName: string;
  status: "online" | "offline" | "working" | "error";
  port: number;
  tokensToday: number;
  tokensTotal: number;
  uptimeSeconds: number;
  queueSize: number;
}

interface StatsResponse {
  uptime: number;
  uptimeFormatted: string;
  totalTokens: number;
  tokensToday: number;
  estimatedCostUsd: number;
  activeAgents: number;
  totalAgents: number;
  agents: AgentStats[];
  dailyUsage: DailyTokenUsage[];
  startedAt: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const AGENTS: { name: string; displayName: string; port: number }[] = [
  { name: "po", displayName: "Product Owner", port: 8000 },
  { name: "pm", displayName: "Project Manager", port: 8001 },
  { name: "ba", displayName: "Business Analyst", port: 8002 },
  { name: "solution-architect", displayName: "Solution Architect", port: 8003 },
  { name: "frontend-dev", displayName: "Frontend Developer", port: 8004 },
  { name: "backend-dev", displayName: "Backend Developer", port: 8005 },
  { name: "uiux-reviewer", displayName: "UIUX Reviewer", port: 8006 },
  { name: "security-reviewer", displayName: "Security Reviewer", port: 8007 },
  { name: "qa", displayName: "QA / Tester", port: 8008 },
  { name: "devops", displayName: "DevOps / SRE", port: 8009 },
  { name: "techlead", displayName: "TechLead", port: 8010 },
];

const REDIS_URL = process.env.REDIS_URL ?? "redis://localhost:6379";
const COST_PER_TOKEN = 0.000002; // ~$0.002 per 1k tokens (MiMo estimate)

// In-memory fallback for system start time when Redis is unavailable
const SYSTEM_STARTED_AT = new Date().toISOString();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Format seconds into a human-readable string like "3d 12h 05m".
 */
function formatUptime(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);

  const parts: string[] = [];
  if (days > 0) parts.push(`${days}d`);
  if (hours > 0) parts.push(`${hours}h`);
  parts.push(`${String(minutes).padStart(2, "0")}m`);

  return parts.join(" ");
}

/**
 * Attempt to fetch JSON from a URL with a short timeout.
 * Returns null on any failure so callers can fall back gracefully.
 */
async function fetchJson<T>(url: string, timeoutMs = 2000): Promise<T | null> {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);

    const res = await fetch(url, { signal: controller.signal, cache: "no-store" });
    clearTimeout(timer);

    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

/**
 * Resolve the base URL for an agent given its port.
 * Inside Docker Compose the hostname matches the service name;
 * from the host machine we hit localhost.
 */
function agentBaseUrl(port: number): string {
  // Prefer Docker-internal hostnames when running inside the compose network.
  // The AGENT_HOST env var can override to "localhost" for local dev.
  const host = process.env.AGENT_HOST ?? "localhost";
  return `http://${host}:${port}`;
}

/**
 * Build the last 7 days of token usage from a flat list of TokenRecords.
 * In production this would come from Redis or a time-series store;
 * here we synthesise an empty skeleton when no data exists yet.
 */
function buildDailyUsage(records: TokenRecord[]): DailyTokenUsage[] {
  const now = new Date();
  const days: DailyTokenUsage[] = [];

  for (let i = 6; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(d.getDate() - i);
    const dateKey = d.toISOString().slice(0, 10);
    days.push({ date: dateKey, total: 0, byAgent: {} });
  }

  for (const rec of records) {
    const recDate = rec.timestamp.slice(0, 10);
    const bucket = days.find((d) => d.date === recDate);
    if (bucket) {
      bucket.total += rec.tokens;
      bucket.byAgent[rec.agent] = (bucket.byAgent[rec.agent] ?? 0) + rec.tokens;
    }
  }

  return days;
}

/**
 * Try to read token usage from Redis. Returns an empty array on failure.
 */
async function getTokenRecords(): Promise<TokenRecord[]> {
  try {
    // Dynamic import so the route doesn't blow up if `ioredis` isn't installed
    const Redis = (await import("ioredis")).default;
    const redis = new Redis(REDIS_URL, { maxRetriesPerRequest: 1, connectTimeout: 2000 });

    const keys = await redis.keys("opencrew:tokens:*");
    const records: TokenRecord[] = [];

    for (const key of keys) {
      const raw = await redis.get(key);
      if (raw) {
        try {
          records.push(JSON.parse(raw) as TokenRecord);
        } catch {
          // skip malformed entries
        }
      }
    }

    await redis.quit();
    return records;
  } catch {
    return [];
  }
}

/**
 * Try to read the system start timestamp from Redis.
 */
async function getSystemStartTime(): Promise<Date> {
  try {
    const Redis = (await import("ioredis")).default;
    const redis = new Redis(REDIS_URL, { maxRetriesPerRequest: 1, connectTimeout: 2000 });

    const val = await redis.get("opencrew:system:started_at");
    await redis.quit();

    if (val) return new Date(val);
  } catch {
    // fall through
  }

  return new Date(SYSTEM_STARTED_AT);
}

// ---------------------------------------------------------------------------
// Route handler
// ---------------------------------------------------------------------------

export async function GET(): Promise<NextResponse<StatsResponse | { error: string }>> {
  try {
    // Parallel fetches: agent health checks + token records + system start time
    const healthChecks = await Promise.allSettled(
      AGENTS.map((a) => fetchJson<AgentHealth>(`${agentBaseUrl(a.port)}/health`)),
    );

    const [tokenRecords, systemStart] = await Promise.all([
      getTokenRecords(),
      getSystemStartTime(),
    ]);

    // Aggregate agent stats
    let activeAgents = 0;
    const agents: AgentStats[] = AGENTS.map((agent, idx) => {
      const result = healthChecks[idx];
      const health: AgentHealth | null =
        result.status === "fulfilled" ? result.value : null;

      const status = health?.status ?? "offline";
      if (status === "online" || status === "working") activeAgents++;

      // Sum today's tokens for this agent
      const todayKey = new Date().toISOString().slice(0, 10);
      const tokensToday = tokenRecords
        .filter((r) => r.agent === agent.name && r.timestamp.slice(0, 10) === todayKey)
        .reduce((sum, r) => sum + r.tokens, 0);

      const tokensTotal = tokenRecords
        .filter((r) => r.agent === agent.name)
        .reduce((sum, r) => sum + r.tokens, 0);

      return {
        name: agent.name,
        displayName: agent.displayName,
        status,
        port: agent.port,
        tokensToday,
        tokensTotal,
        uptimeSeconds: health?.uptime_seconds ?? 0,
        queueSize: health?.queue_size ?? 0,
      };
    });

    // Totals
    const totalTokens = tokenRecords.reduce((sum, r) => sum + r.tokens, 0);
    const todayKey = new Date().toISOString().slice(0, 10);
    const tokensToday = tokenRecords
      .filter((r) => r.timestamp.slice(0, 10) === todayKey)
      .reduce((sum, r) => sum + r.tokens, 0);

    const uptimeSeconds = Math.floor((Date.now() - systemStart.getTime()) / 1000);

    const dailyUsage = buildDailyUsage(tokenRecords);

    const body: StatsResponse = {
      uptime: uptimeSeconds,
      uptimeFormatted: formatUptime(uptimeSeconds),
      totalTokens,
      tokensToday,
      estimatedCostUsd: parseFloat((totalTokens * COST_PER_TOKEN).toFixed(4)),
      activeAgents,
      totalAgents: AGENTS.length,
      agents,
      dailyUsage,
      startedAt: systemStart.toISOString(),
    };

    return NextResponse.json(body, {
      status: 200,
      headers: {
        // Cache for 10 seconds to avoid hammering agent health endpoints
        "Cache-Control": "public, s-maxage=10, stale-while-revalidate=30",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("[/api/stats] Failed to compute stats:", message);

    return NextResponse.json({ error: message }, { status: 500 });
  }
}