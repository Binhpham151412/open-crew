import { NextRequest, NextResponse } from "next/server";
import { readFile, writeFile, mkdir } from "fs/promises";
import { existsSync } from "fs";
import path from "path";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ApiKeysConfig {
  mimoApiKey: string;
  mimoBaseUrl: string;
  mimoModel: string;
  githubToken: string;
  openDesignUrl: string;
  linearApiKey: string;
}

interface McpServerConfig {
  id: string;
  name: string;
  url: string;
  enabled: boolean;
  status: "connected" | "disconnected" | "unknown";
  tools: string[];
}

interface AgentOverrideConfig {
  agentId: string;
  model: string;
  temperature: number;
  maxTokens: number;
  enabled: boolean;
}

interface SystemConfig {
  apiKeys: ApiKeysConfig;
  mcpServers: McpServerConfig[];
  agentOverrides: AgentOverrideConfig[];
  updatedAt: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CONFIG_FILE_PATH = process.env.OPENCREW_CONFIG_PATH
  ? path.resolve(process.env.OPENCREW_CONFIG_PATH)
  : path.resolve(process.cwd(), "data", "config.json");

const DEFAULT_CONFIG: SystemConfig = {
  apiKeys: {
    mimoApiKey: "",
    mimoBaseUrl: "https://api.xiaomi.com/v1",
    mimoModel: "mimo-v2.5-pro",
    githubToken: "",
    openDesignUrl: "",
    linearApiKey: "",
  },
  mcpServers: [
    {
      id: "github",
      name: "GitHub MCP",
      url: process.env.GITHUB_MCP_URL || "",
      enabled: !!process.env.GITHUB_MCP_URL,
      status: "unknown",
      tools: [
        "create_branch",
        "commit_files",
        "create_pr",
        "merge_pr",
        "get_file",
        "search_code",
        "create_issue",
      ],
    },
    {
      id: "context7",
      name: "Context7",
      url: "https://mcp.context7.com/mcp",
      enabled: true,
      status: "unknown",
      tools: ["resolve_library_id", "get_library_docs"],
    },
    {
      id: "opendesign",
      name: "OpenDesign MCP",
      url: process.env.OPENDESIGN_MCP_URL || "",
      enabled: !!process.env.OPENDESIGN_MCP_URL,
      status: "unknown",
      tools: ["get_design_spec", "export_component", "compare_design"],
    },
    {
      id: "linear",
      name: "Linear MCP",
      url: process.env.LINEAR_MCP_URL || "",
      enabled: !!process.env.LINEAR_MCP_URL,
      status: "unknown",
      tools: [
        "create_epic",
        "create_story",
        "update_story",
        "create_sprint",
        "assign_story",
      ],
    },
  ],
  agentOverrides: [],
  updatedAt: new Date().toISOString(),
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Mask a secret string, keeping only the last 4 characters visible.
 * Returns "not configured" for empty strings.
 */
function maskSecret(value: string): string {
  if (!value) return "";
  if (value.length <= 8) return "••••••••";
  return "•".repeat(value.length - 4) + value.slice(-4);
}

/**
 * Ensure the config directory exists, then return the resolved path.
 */
async function ensureConfigDir(): Promise<void> {
  const dir = path.dirname(CONFIG_FILE_PATH);
  if (!existsSync(dir)) {
    await mkdir(dir, { recursive: true });
  }
}

/**
 * Load config from disk. Falls back to DEFAULT_CONFIG populated from
 * environment variables if no config file exists yet.
 */
async function loadConfig(): Promise<SystemConfig> {
  try {
    await ensureConfigDir();
    const raw = await readFile(CONFIG_FILE_PATH, "utf-8");
    const parsed = JSON.parse(raw) as Partial<SystemConfig>;

    // Deep merge with defaults to guarantee all fields exist
    const config: SystemConfig = {
      ...DEFAULT_CONFIG,
      ...parsed,
      apiKeys: { ...DEFAULT_CONFIG.apiKeys, ...parsed.apiKeys },
      mcpServers: mergeMcpServers(DEFAULT_CONFIG.mcpServers, parsed.mcpServers),
      agentOverrides: parsed.agentOverrides ?? DEFAULT_CONFIG.agentOverrides,
    };

    return config;
  } catch {
    // File doesn't exist or is malformed — return defaults
    return { ...DEFAULT_CONFIG };
  }
}

/**
 * Merge persisted MCP server entries with defaults, preserving order
 * and filling in any newly-introduced defaults.
 */
function mergeMcpServers(
  defaults: McpServerConfig[],
  saved?: McpServerConfig[],
): McpServerConfig[] {
  if (!saved || saved.length === 0) return defaults;

  const savedMap = new Map(saved.map((s) => [s.id, s]));

  return defaults.map((d) => {
    const s = savedMap.get(d.id);
    if (!s) return d;
    return {
      ...d,
      ...s,
      // Keep the canonical tools list from defaults if the saved entry omitted them
      tools: s.tools && s.tools.length > 0 ? s.tools : d.tools,
    };
  });
}

/**
 * Persist config to disk as pretty-printed JSON.
 */
async function saveConfig(config: SystemConfig): Promise<void> {
  await ensureConfigDir();
  config.updatedAt = new Date().toISOString();
  await writeFile(CONFIG_FILE_PATH, JSON.stringify(config, null, 2), "utf-8");
}

/**
 * Mask all secrets inside an API keys config before sending to the client.
 */
function maskApiKeys(keys: ApiKeysConfig): ApiKeysConfig {
  return {
    ...keys,
    mimoApiKey: maskSecret(keys.mimoApiKey),
    githubToken: maskSecret(keys.githubToken),
    openDesignUrl: keys.openDesignUrl,
    linearApiKey: maskSecret(keys.linearApiKey),
  };
}

/**
 * Quick health-check ping to a given URL. Returns true if the endpoint
 * responds with a 2xx status within 5 seconds.
 */
async function pingEndpoint(url: string): Promise<boolean> {
  if (!url) return false;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(url, {
      method: "GET",
      signal: controller.signal,
    });
    clearTimeout(timeout);
    return res.ok;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// GET /api/config
// ---------------------------------------------------------------------------

/**
 * Returns the current system configuration.
 *
 * Query params:
 *   ?full=true  — include unmasked secrets (requires elevated context)
 *   ?ping=true  — also probe MCP server endpoints for live status
 */
export async function GET(request: NextRequest) {
  try {
    const { searchParams } = request.nextUrl;
    const full = searchParams.get("full") === "true";
    const ping = searchParams.get("ping") === "true";

    const config = await loadConfig();

    // Mask secrets unless the caller explicitly asks for full config
    const apiKeys = full ? config.apiKeys : maskApiKeys(config.apiKeys);

    // Optionally ping each MCP server for live connectivity status
    let mcpServers = config.mcpServers;
    if (ping) {
      mcpServers = await Promise.all(
        config.mcpServers.map(async (server) => {
          if (!server.enabled || !server.url) {
            return { ...server, status: "disconnected" as const };
          }
          const alive = await pingEndpoint(server.url);
          return {
            ...server,
            status: alive ? ("connected" as const) : ("disconnected" as const),
          };
        }),
      );
    }

    return NextResponse.json({
      apiKeys,
      mcpServers,
      agentOverrides: config.agentOverrides,
      updatedAt: config.updatedAt,
    });
  } catch (error) {
    console.error("[/api/config GET] Failed to load config:", error);
    return NextResponse.json(
      { error: "Failed to load configuration" },
      { status: 500 },
    );
  }
}

// ---------------------------------------------------------------------------
// POST /api/config
// ---------------------------------------------------------------------------

/**
 * Update the system configuration. Supports partial updates — only the
 * fields present in the request body will be overwritten.
 *
 * Body (JSON):
 *   {
 *     apiKeys?: { mimoApiKey?, mimoBaseUrl?, mimoModel?, githubToken?, openDesignUrl?, linearApiKey? },
 *     mcpServers?: McpServerConfig[],
 *     agentOverrides?: AgentOverrideConfig[],
 *     testConnection?: string   // MCP server id to test after saving
 *   }
 *
 * The `testConnection` field triggers an immediate connectivity check for
 * the specified MCP server and returns the result alongside the saved config.
 */
export async function POST(request: NextRequest) {
  try {
    const body = await request.json();

    // Load existing config as the base
    const config = await loadConfig();

    // ---------- Merge API keys ----------
    if (body.apiKeys && typeof body.apiKeys === "object") {
      const incoming = body.apiKeys as Partial<ApiKeysConfig>;

      // Only overwrite keys that are actually provided and not masked placeholders
      if (incoming.mimoApiKey !== undefined && !incoming.mimoApiKey.includes("•")) {
        config.apiKeys.mimoApiKey = incoming.mimoApiKey;
      }
      if (incoming.mimoBaseUrl !== undefined) {
        config.apiKeys.mimoBaseUrl = incoming.mimoBaseUrl;
      }
      if (incoming.mimoModel !== undefined) {
        config.apiKeys.mimoModel = incoming.mimoModel;
      }
      if (incoming.githubToken !== undefined && !incoming.githubToken.includes("•")) {
        config.apiKeys.githubToken = incoming.githubToken;
      }
      if (incoming.openDesignUrl !== undefined) {
        config.apiKeys.openDesignUrl = incoming.openDesignUrl;
      }
      if (incoming.linearApiKey !== undefined && !incoming.linearApiKey.includes("•")) {
        config.apiKeys.linearApiKey = incoming.linearApiKey;
      }
    }

    // ---------- Merge MCP servers ----------
    if (Array.isArray(body.mcpServers)) {
      const incomingServers = body.mcpServers as Partial<McpServerConfig>[];
      for (const incoming of incomingServers) {
        if (!incoming.id) continue;
        const idx = config.mcpServers.findIndex((s) => s.id === incoming.id);
        if (idx >= 0) {
          config.mcpServers[idx] = {
            ...config.mcpServers[idx],
            ...incoming,
            id: config.mcpServers[idx].id, // prevent id overwrite
          };
        } else {
          // New server entry
          config.mcpServers.push({
            id: incoming.id,
            name: incoming.name ?? incoming.id,
            url: incoming.url ?? "",
            enabled: incoming.enabled ?? false,
            status: "unknown",
            tools: incoming.tools ?? [],
          });
        }
      }
    }

    // ---------- Merge agent overrides ----------
    if (Array.isArray(body.agentOverrides)) {
      const incomingOverrides = body.agentOverrides as Partial<AgentOverrideConfig>[];
      for (const incoming of incomingOverrides) {
        if (!incoming.agentId) continue;
        const idx = config.agentOverrides.findIndex(
          (a) => a.agentId === incoming.agentId,
        );
        if (idx >= 0) {
          config.agentOverrides[idx] = {
            ...config.agentOverrides[idx],
            ...incoming,
            agentId: config.agentOverrides[idx].agentId,
          };
        } else {
          config.agentOverrides.push({
            agentId: incoming.agentId,
            model: incoming.model ?? "mimo-v2.5-pro",
            temperature: incoming.temperature ?? 0.2,
            maxTokens: incoming.maxTokens ?? 8192,
            enabled: incoming.enabled ?? true,
          });
        }
      }
    }

    // ---------- Persist ----------
    await saveConfig(config);

    // ---------- Optional connection test ----------
    let connectionTest: { serverId: string; reachable: boolean } | null = null;
    if (typeof body.testConnection === "string") {
      const target = config.mcpServers.find(
        (s) => s.id === body.testConnection,
      );
      if (target && target.url) {
        const reachable = await pingEndpoint(target.url);
        connectionTest = { serverId: target.id, reachable };

        // Update status in persisted config
        const idx = config.mcpServers.findIndex(
          (s) => s.id === target.id,
        );
        if (idx >= 0) {
          config.mcpServers[idx].status = reachable
            ? "connected"
            : "disconnected";
          await saveConfig(config);
        }
      }
    }

    return NextResponse.json({
      success: true,
      apiKeys: maskApiKeys(config.apiKeys),
      mcpServers: config.mcpServers,
      agentOverrides: config.agentOverrides,
      updatedAt: config.updatedAt,
      ...(connectionTest ? { connectionTest } : {}),
    });
  } catch (error) {
    console.error("[/api/config POST] Failed to update config:", error);

    if (error instanceof SyntaxError) {
      return NextResponse.json(
        { error: "Invalid JSON in request body" },
        { status: 400 },
      );
    }

    return NextResponse.json(
      { error: "Failed to update configuration" },
      { status: 500 },
    );
  }
}

// ---------------------------------------------------------------------------
// DELETE /api/config — Reset to defaults
// ---------------------------------------------------------------------------

/**
 * Resets the configuration file to defaults. Useful for recovery scenarios.
 */
export async function DELETE() {
  try {
    const fresh = { ...DEFAULT_CONFIG, updatedAt: new Date().toISOString() };
    await saveConfig(fresh);

    return NextResponse.json({
      success: true,
      message: "Configuration reset to defaults",
      apiKeys: maskApiKeys(fresh.apiKeys),
      mcpServers: fresh.mcpServers,
      agentOverrides: fresh.agentOverrides,
      updatedAt: fresh.updatedAt,
    });
  } catch (error) {
    console.error("[/api/config DELETE] Failed to reset config:", error);
    return NextResponse.json(
      { error: "Failed to reset configuration" },
      { status: 500 },
    );
  }
}