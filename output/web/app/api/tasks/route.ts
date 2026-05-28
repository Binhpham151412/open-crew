import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "crypto";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type TaskStatus = "pending" | "in_progress" | "review" | "done" | "failed";

interface TimelineEvent {
  id: string;
  timestamp: string;
  agent: string;
  action: string;
  detail: string;
  type: "info" | "warning" | "error" | "success" | "a2a_message";
}

interface Task {
  id: string;
  title: string;
  description: string;
  status: TaskStatus;
  createdAt: string;
  updatedAt: string;
  assignedAgents: string[];
  currentPhase: string;
  timeline: TimelineEvent[];
}

// ---------------------------------------------------------------------------
// In-memory store
// ---------------------------------------------------------------------------

const taskStore = new Map<string, Task>();

// Seed a few demo tasks so the UI isn't empty on first load
function seedDemoTasks(): void {
  if (taskStore.size > 0) return;

  const now = new Date();
  const ago = (minutes: number) =>
    new Date(now.getTime() - minutes * 60_000).toISOString();

  const demos: Task[] = [
    {
      id: "task-001",
      title: "Build login feature",
      description:
        "Implement user authentication with email/password, including registration, login, and JWT token management.",
      status: "done",
      createdAt: ago(180),
      updatedAt: ago(20),
      assignedAgents: ["po", "pm", "ba", "backend-dev", "frontend-dev", "security-reviewer", "qa", "devops", "techlead"],
      currentPhase: "Delivery",
      timeline: [
        {
          id: randomUUID(),
          timestamp: ago(180),
          agent: "po",
          action: "Created PRD",
          detail: "Product Requirements Document generated from user request",
          type: "info",
        },
        {
          id: randomUUID(),
          timestamp: ago(170),
          agent: "pm",
          action: "Sprint planned",
          detail: "3 stories created and assigned: registration, login, JWT management",
          type: "info",
        },
        {
          id: randomUUID(),
          timestamp: ago(150),
          agent: "ba",
          action: "API spec delivered",
          detail: "OpenAPI spec with 3 endpoints, acceptance criteria in Gherkin",
          type: "info",
        },
        {
          id: randomUUID(),
          timestamp: ago(120),
          agent: "backend-dev",
          action: "Implementation complete",
          detail: "FastAPI endpoints: POST /auth/register, POST /auth/login, GET /auth/me",
          type: "success",
        },
        {
          id: randomUUID(),
          timestamp: ago(60),
          agent: "security-reviewer",
          action: "Security review passed",
          detail: "No critical issues. OWASP Top 10 checks clear.",
          type: "success",
        },
        {
          id: randomUUID(),
          timestamp: ago(40),
          agent: "qa",
          action: "All tests passed",
          detail: "24 test cases, 86% coverage, 0 failures",
          type: "success",
        },
        {
          id: randomUUID(),
          timestamp: ago(20),
          agent: "techlead",
          action: "Delivery approved",
          detail: "PR merged, deployed to staging, health checks passing",
          type: "success",
        },
      ],
    },
    {
      id: "task-002",
      title: "Review PR #42",
      description: "Review the pull request for the dashboard component refactor.",
      status: "in_progress",
      createdAt: ago(10),
      updatedAt: ago(2),
      assignedAgents: ["backend-dev", "qa", "techlead"],
      currentPhase: "Code Review",
      timeline: [
        {
          id: randomUUID(),
          timestamp: ago(10),
          agent: "techlead",
          action: "Review assigned",
          detail: "PR #42 assigned to backend-dev and qa for review",
          type: "info",
        },
        {
          id: randomUUID(),
          timestamp: ago(7),
          agent: "backend-dev",
          action: "Reviewing diff",
          detail: "142 lines changed across 5 files",
          type: "info",
        },
        {
          id: randomUUID(),
          timestamp: ago(4),
          agent: "backend-dev",
          action: "Found issues",
          detail: "3 issues identified: missing error handling, unused import, inconsistent naming",
          type: "warning",
        },
        {
          id: randomUUID(),
          timestamp: ago(3),
          agent: "qa",
          action: "Coverage check",
          detail: "Current coverage: 78% — target is 80%",
          type: "warning",
        },
        {
          id: randomUUID(),
          timestamp: ago(2),
          agent: "qa",
          action: "A2A: CHALLENGE",
          detail: "Suggested: add test for edge case in parseConfig utility",
          type: "a2a_message",
        },
      ],
    },
    {
      id: "task-003",
      title: "Fix auth bug",
      description: "Users report 401 errors when token expires during active session.",
      status: "pending",
      createdAt: ago(1),
      updatedAt: ago(1),
      assignedAgents: [],
      currentPhase: "Intake",
      timeline: [
        {
          id: randomUUID(),
          timestamp: ago(1),
          agent: "user",
          action: "Task submitted",
          detail: "Bug report: 401 on token expiry during active session",
          type: "info",
        },
      ],
    },
  ];

  for (const task of demos) {
    taskStore.set(task.id, task);
  }
}

// Ensure demos are seeded once when this module is first loaded
seedDemoTasks();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sortTasks(tasks: Task[], sortBy: string, order: string): Task[] {
  const sorted = [...tasks];
  const dir = order === "asc" ? 1 : -1;

  sorted.sort((a, b) => {
    switch (sortBy) {
      case "createdAt":
        return dir * (new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());
      case "updatedAt":
        return dir * (new Date(a.updatedAt).getTime() - new Date(b.updatedAt).getTime());
      case "title":
        return dir * a.title.localeCompare(b.title);
      case "status":
        return dir * a.status.localeCompare(b.status);
      default:
        return 0;
    }
  });

  return sorted;
}

// ---------------------------------------------------------------------------
// GET /api/tasks  —  List all tasks with optional filters
// ---------------------------------------------------------------------------

export async function GET(request: NextRequest): Promise<NextResponse> {
  const { searchParams } = request.nextUrl;

  const statusFilter = searchParams.get("status") as TaskStatus | null;
  const agentFilter = searchParams.get("agent");
  const search = searchParams.get("search")?.toLowerCase() ?? "";
  const sortBy = searchParams.get("sort") ?? "updatedAt";
  const order = searchParams.get("order") ?? "desc";
  const page = Math.max(1, parseInt(searchParams.get("page") ?? "1", 10) || 1);
  const pageSize = Math.min(
    100,
    Math.max(1, parseInt(searchParams.get("pageSize") ?? "50", 10) || 50)
  );

  let tasks = Array.from(taskStore.values());

  // Filter by status
  if (statusFilter) {
    tasks = tasks.filter((t) => t.status === statusFilter);
  }

  // Filter by assigned agent
  if (agentFilter) {
    tasks = tasks.filter((t) => t.assignedAgents.includes(agentFilter));
  }

  // Text search on title and description
  if (search) {
    tasks = tasks.filter(
      (t) =>
        t.title.toLowerCase().includes(search) ||
        t.description.toLowerCase().includes(search)
    );
  }

  // Sort
  tasks = sortTasks(tasks, sortBy, order);

  // Pagination
  const totalCount = tasks.length;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const start = (page - 1) * pageSize;
  const paginatedTasks = tasks.slice(start, start + pageSize);

  return NextResponse.json({
    tasks: paginatedTasks,
    pagination: {
      page,
      pageSize,
      totalCount,
      totalPages,
    },
  });
}

// ---------------------------------------------------------------------------
// POST /api/tasks  —  Create a new task
// ---------------------------------------------------------------------------

interface CreateTaskBody {
  title?: string;
  description?: string;
  priority?: "low" | "medium" | "high" | "critical";
}

export async function POST(request: NextRequest): Promise<NextResponse> {
  let body: CreateTaskBody;

  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { error: "Invalid JSON body" },
      { status: 400 }
    );
  }

  const { title, description, priority } = body;

  if (!title || typeof title !== "string" || title.trim().length === 0) {
    return NextResponse.json(
      { error: "Field 'title' is required and must be a non-empty string" },
      { status: 400 }
    );
  }

  const trimmedTitle = title.trim().slice(0, 500);
  const trimmedDescription =
    typeof description === "string" ? description.trim().slice(0, 5000) : "";
  const now = new Date().toISOString();

  const task: Task = {
    id: `task-${randomUUID().slice(0, 8)}`,
    title: trimmedTitle,
    description: trimmedDescription,
    status: "pending",
    createdAt: now,
    updatedAt: now,
    assignedAgents: [],
    currentPhase: "Intake",
    timeline: [
      {
        id: randomUUID(),
        timestamp: now,
        agent: "user",
        action: "Task submitted",
        detail: trimmedTitle,
        type: "info",
      },
    ],
  };

  taskStore.set(task.id, task);

  // In a production system this would also:
  //   1. Push task to the PO agent via A2A protocol
  //   2. Persist to Redis / database
  //   3. Emit SSE event for real-time UI updates
  //
  // For now we store in-memory and return the created task.

  return NextResponse.json({ task }, { status: 201 });
}