import { NextRequest, NextResponse } from "next/server";

// ---------------------------------------------------------------------------
// Agent Registry — maps agent id to metadata + health endpoint
// ---------------------------------------------------------------------------

interface AgentMeta {
  id: string;
  name: string;
  displayName: string;
  port: number;
  role: string;
  layer: string;
  tools: string[];
  pushTo: string[];
}

const AGENTS: AgentMeta[] = [
  {
    id: "po",
    name: "po",
    displayName: "Product Owner",
    port: 8000,
    role: "Continues nhận yêu cầu từ user, viết PRD, định nghĩa DoD",
    layer: "Strategy",
    tools: ["linear_mcp", "context7"],
    pushTo: ["pm"],
  },
  {
    id: "pm",
    name: "pm",
    displayName: "Project Manager",
    port: 8001,
    role: "Phân rã PRD thành Stories + Tasks, sprint plan, assign",
    layer: "Strategy",
    tools: ["linear_mcp", "github_mcp"],
    pushTo: ["ba", "solution_architect"],
  },
  {
    id: "ba",
    name: "ba",
    displayName: "Business Analyst",
    port: 8002,
    role: "User Stories, Acceptance Criteria, API contract, data model",
    layer: "Analysis",
    tools: ["context7", "linear_mcp"],
    pushTo: ["frontend_dev", "backend_dev"],
  },
  {
    id: "solution_architect",
    name: "solution-architect",
    displayName: "Solution Architect",
    port: 8003,
    role: "System architecture, ADR, DB schema, interface contracts",
    layer: "Design",
    tools: ["context7", "github_mcp"],
    pushTo: ["backend_dev", "devops"],
  },
  {
    id: "frontend_dev",
    name: "frontend-dev",
    displayName: "Frontend Developer",
    port: 8004,
    role: "NextJS 14 implementation, responsive, dark mode",
    layer: "Build",
    tools: ["github_mcp", "context7"],
    pushTo: ["uiux_reviewer"],
  },
  {
    id: "backend_dev",
    name: "backend-dev",
    displayName: "Backend Developer",
    port: 8005,
    role: "FastAPI endpoints, business logic, data access layer",
    layer: "Build",
    tools: ["github_mcp", "context7"],
    pushTo: ["security_reviewer"],
  },
  {
    id: "uiux_reviewer",
    name: "uiux-reviewer",
    displayName: "UIUX Reviewer",
    port: 8006,
    role: "WCAG 2.1 AA accessibility, spacing, responsive review",
    layer: "Quality",
    tools: ["github_mcp", "opendesign_mcp"],
    pushTo: ["qa"],
  },
  {
    id: "security_reviewer",
    name: "security-reviewer",
    displayName: "Security Reviewer",
    port: 8007,
    role: "OWASP Top 10, CVE check, secret scan",
    layer: "Quality",
    tools: ["github_mcp", "context7"],
    pushTo: ["qa"],
  },
  {
    id: "qa",
    name: "qa",
    displayName: "QA / Tester",
    port: 8008,
    role: "pytest + Playwright, bug reports, coverage analysis",
    layer: "Quality",
    tools: ["github_mcp", "context7"],
    pushTo: ["devops"],
  },
  {
    id: "devops",
    name: "devops",
    displayName: "DevOps / SRE",
    port: 8009,
    role: "Docker, CI/CD, deployment, monitoring",
    layer: "Delivery",
    tools: ["github_mcp", "context7"],
    pushTo: ["techlead"],
  },
  {
    id: "techlead",
    name: "techlead",
    displayName: "TechLead",
    port: 8010,
    role: "Final review, arbitrate conflicts, sign-off delivery",
    layer: "Final Gate",
    tools: ["github_mcp", "linear_mcp"],
    pushTo: ["po"],
  },
];

// ---------------------------------------------------------------------------
// Health-check helpers
// ---------------------------------------------------------------------------

interface HealthResult {
  status: "online" | "offline" | "error";
  queueSize: number | null;
  latencyMs: number | null;
  lastChecked: string;
  error: string | null;
}

/**
 * Ping a single agent's `/health` endpoint with a short timeout.
 * Returns a normalised HealthResult regardless of outcome.
 */
async function checkAgentHealth(port: number): Promise<HealthResult> {
  const url = `http://localhost:${port}/health`;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 3000); // 3 s timeout

  const startTime = Date.now();

  try {
    const res = await fetch(url, {
      method: "GET",
      signal: controller.signal,
      headers: { Accept: "application/json" },
      // Disable Next.js fetch caching — always hit the real agent
      cache: "no-store",
    });

    const latencyMs = Date.now() - startTime;

    if (!res.ok) {
      return {
        status: "error",
        queueSize: null,
        latencyMs,
        lastChecked: new Date().toISOString(),
        error: `HTTP ${res.status}`,
      };
    }

    const body = await res.json();

    return {
      status: body.status === "ok" ? "online" : "error",
      queueSize: typeof body.queue_size === "number" ? body.queue_size : null,
      latencyMs,
      lastChecked: new Date().toISOString(),
      error: body.status !== "ok" ? `Unexpected status: ${body.status}` : null,
    };
  } catch (err: unknown) {
    const latencyMs = Date.now() - startTime;
    const message =
      err instanceof DOMException && err.name === "AbortError"
        ? "Health check timed out (3 s)"
        : err instanceof Error
          ? err.message
          : "Unknown error";

    return {
      status: "offline",
      queueSize: null,
      latencyMs,
      lastChecked: new Date().toISOString(),
      error: message,
    };
  } finally {
    clearTimeout(timeout);
  }
}

// ---------------------------------------------------------------------------
// Response types
// ---------------------------------------------------------------------------

interface AgentResponse {
  id: string;
  name: string;
  displayName: string;
  port: number;
  role: string;
  layer: string;
  tools: string[];
  pushTo: string[];
  health: HealthResult;
}

interface AgentsListResponse {
  agents: AgentResponse[];
  total: number;
  online: number;
  offline: number;
  timestamp: string;
}

// ---------------------------------------------------------------------------
// GET /api/agents
// ---------------------------------------------------------------------------

/**
 * Poll every agent's `/health` endpoint in parallel and return the full
 * registry with live status information.
 *
 * Response shape:
 * ```json
 * {
 *   "agents": [ { id, name, displayName, port, role, layer, tools, pushTo, health } ],
 *   "total": 11,
 *   "online": 9,
 *   "offline": 2,
 *   "timestamp": "2026-05-27T10:00:00.000Z"
 * }
 * ```
 */
export async function GET(_request: NextRequest): Promise<NextResponse> {
  // Fire all health checks concurrently
  const healthChecks = await Promise.allSettled(
    AGENTS.map((agent) => checkAgentHealth(agent.port)),
  );

  const agents: AgentResponse[] = AGENTS.map((agent, index) => {
    const result = healthChecks[index];

    // Promise.allSettled always fulfils; this is defensive
    const health: HealthResult =
      result.status === "fulfilled"
        ? result.value
        : {
            status: "error",
            queueSize: null,
            latencyMs: null,
            lastChecked: new Date().toISOString(),
            error: "Health check promise rejected",
          };

    return {
      id: agent.id,
      name: agent.name,
      displayName: agent.displayName,
      port: agent.port,
      role: agent.role,
      layer: agent.layer,
      tools: agent.tools,
      pushTo: agent.pushTo,
      health,
    };
  });

  const online = agents.filter((a) => a.health.status === "online").length;
  const offline = agents.length - online;

  const body: AgentsListResponse = {
    agents,
    total: agents.length,
    online,
    offline,
    timestamp: new Date().toISOString(),
  };

  return NextResponse.json(body, {
    status: 200,
    headers: {
      // Always fresh — agents may come and go at any time
      "Cache-Control": "no-store, no-cache, must-revalidate",
    },
  });
}