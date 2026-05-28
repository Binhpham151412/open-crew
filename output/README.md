<p align="center">
  <img src="https://img.shields.io/badge/OpenCrew-v1.0-2563EB?style=for-the-badge&logo=robot&logoColor=white" alt="OpenCrew v1.0" />
  <img src="https://img.shields.io/badge/Agents-11-16A34A?style=for-the-badge" alt="11 Agents" />
  <img src="https://img.shields.io/badge/Protocol-A2A%20+%20MCP-D97706?style=for-the-badge" alt="A2A + MCP" />
  <img src="https://img.shields.io/badge/License-MIT-DC2626?style=for-the-badge" alt="License" />
</p>

<h1 align="center">🤖 OpenCrew</h1>

<p align="center">
  <strong>A fully autonomous multi-agent AI software team.</strong><br/>
  You describe what you want — agents plan, design, build, review, test, and ship it.
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#architecture">Architecture</a> •
  <a href="#agents">Agents</a> •
  <a href="#tech-stack">Tech Stack</a> •
  <a href="#development-guide">Development Guide</a> •
  <a href="#api-reference">API Reference</a>
</p>

---

## Overview

OpenCrew is an autonomous software delivery pipeline powered by 11 specialized AI agents that collaborate to take a feature request from idea to production deployment — with zero human intervention in between.

**You describe what you want. OpenCrew delivers working software.**

```
You: "Build a user registration system with email verification"

OpenCrew:
  ├── PO       → Writes PRD, defines requirements
  ├── PM       → Breaks into stories, creates sprint plan
  ├── BA       → Writes acceptance criteria, API spec, data model
  ├── SA       → Designs architecture, DB schema
  ├── FE Dev   → Implements NextJS UI
  ├── BE Dev   → Implements FastAPI endpoints
  ├── UIUX     → Reviews accessibility & UX
  ├── Security → OWASP Top 10 audit
  ├── QA       → Writes & runs test suites
  ├── DevOps   → Docker, CI/CD, deployment
  └── TechLead → Final review & sign-off

  → docker-compose up → Working system at localhost:3000
```

---

## Quick Start

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) ≥ 24.0
- [Docker Compose](https://docs.docker.com/compose/) ≥ 2.20
- A MiMo API key (or compatible LLM provider)

### 1. Clone & Configure

```bash
git clone https://github.com/your-org/opencrypt.git
cd opencrypt

# Copy environment template and fill in your keys
cp .env.example .env
```

### 2. Edit `.env`

```bash
# Required
MIMO_API_KEY=your-mimo-api-key-here
MIMO_BASE_URL=https://api.xiaomi.com/v1
MIMO_MODEL=mimo-v2.5-pro

# Optional — for full GitHub integration
GITHUB_TOKEN=ghp_xxxxxxxxxxxx

# Optional — for Linear project management
LINEAR_API_KEY=lin_xxxxxxxxxxxx

# Optional — for design comparison
OPENDESIGN_MCP_URL=https://opendesign.example.com/mcp
```

### 3. Launch

```bash
docker-compose up --build
```

### 4. Verify

```bash
# Web UI
curl -s http://localhost:3000 | head -5

# Agent health checks
for port in 8000 8001 8002 8003 8004 8005 8006 8007 8008 8009 8010; do
  echo "Port $port: $(curl -s http://localhost:$port/health)"
done
```

All services should return `{"status": "ok"}`.

### 5. Submit Your First Task

Open the web UI at **http://localhost:3000/tasks** and enter a feature description, or use the API:

```bash
curl -X POST http://localhost:3000/api/tasks \
  -H "Content-Type: application/json" \
  -d '{"description": "Build a todo app with user auth, CRUD operations, and a dark mode toggle"}'
```

---

## Architecture

### Pipeline Flow

```
User Input
    │
    ▼
  [PO] ────── Product Owner (port 8000)
    │ PRD
    ▼
  [PM] ────── Project Manager (port 8001)
    │ Stories
    ├──────────────────────────┐
    ▼                          ▼
  [BA] ──────── Business      [SA] ──── Solution Architect
    │            Analyst         │        (port 8003)
    │ AC + API spec              │ ADR + DB schema
    ├──────────┐                 │
    ▼          ▼                 ▼
 [FE Dev]  [BE Dev] ◄───────────┘ receives schema
    │         │
    ▼         ▼
[UIUX]   [Security]
    │         │
    └────┬────┘
         ▼
       [QA] ─────── QA / Tester (port 8008)
         │ all tests pass
         ▼
      [DevOps] ──── DevOps / SRE (port 8009)
         │ deployment ready
         ▼
     [TechLead] ─── Tech Lead (port 8010)
         │ final sign-off
         ▼
       [PO] ──────► User receives result
```

### Design Principles

| Principle | Description |
|---|---|
| **Single touchpoint** | User submits a request and receives a result — nothing else in between |
| **Async & non-blocking** | Every agent pushes output downstream then immediately picks the next task from its queue |
| **Agent-to-Agent (A2A)** | Agents communicate through a standardized JSON protocol with structured debate flows |
| **Model Context Protocol (MCP)** | Agents interact with external tools (GitHub, Linear, Context7) via MCP |
| **Auto-approve everything** | No human approval needed mid-pipeline; TechLead is the final gate |
| **Self-healing** | Failed tests trigger automatic fix-and-retry (up to 3 rounds) before escalation |

### Communication Protocols

**A2A Protocol** — Agent-to-Agent messaging:

```json
{
  "protocol": "a2a/1.0",
  "type": "task",
  "from": "ba",
  "to": "backend-dev",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "round": 1,
  "payload": {
    "claim": "Implement POST /api/users endpoint",
    "evidence": "api_spec.yaml:line 42",
    "suggestion": "Use Pydantic v2 for request validation",
    "artifacts": [{"name": "api_spec.yaml", "content": "..."}]
  },
  "timestamp": "2026-05-27T10:00:00Z"
}
```

**MCP Protocol** — Tool invocation via JSON-RPC 2.0:

```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "github_create_pr",
    "arguments": {
      "title": "feat: add user registration endpoint",
      "head": "feature/user-registration",
      "base": "main"
    }
  },
  "id": "req-001"
}
```

**Debate Flow** — When agents disagree:

```
Round 1: Agent A → CHALLENGE → Agent B
Round 2: Agent B → RESPONSE  → Agent A   (accept | counter)
Round 3: Agent A → FINAL_POS → Agent B
         ↓ (if still conflicting)
Both    → ESCALATE → TechLead
TechLead → DECISION → both agents         (final, no appeal)
```

---

## Agents

### Organization

| Layer | Agent | Port | Role |
|---|---|---|---|
| **Strategy** | [Product Owner](#product-owner) | 8000 | Receives user requests, writes PRD, accepts/rejects deliverables |
| **Strategy** | [Project Manager](#project-manager) | 8001 | Sprint planning, story breakdown, effort estimation |
| **Analysis** | [Business Analyst](#business-analyst) | 8002 | User stories, acceptance criteria, API contracts, data models |
| **Analysis** | [Solution Architect](#solution-architect) | 8003 | System architecture, ADRs, DB schemas, interface contracts |
| **Build** | [Frontend Developer](#frontend-developer) | 8004 | NextJS 14 implementation with TypeScript and Tailwind |
| **Build** | [Backend Developer](#backend-developer) | 8005 | FastAPI endpoints with SQLAlchemy and Pydantic |
| **Quality** | [UIUX Reviewer](#uiux-reviewer) | 8006 | WCAG 2.1 AA compliance, responsive design, UX validation |
| **Quality** | [Security Reviewer](#security-reviewer) | 8007 | OWASP Top 10 audit, CVE scanning, secret detection |
| **Quality** | [QA / Tester](#qa--tester) | 8008 | Automated testing with pytest + Playwright |
| **Delivery** | [DevOps / SRE](#devops--sre) | 8009 | Docker, CI/CD pipelines, deployment infrastructure |
| **Gate** | [TechLead](#techlead) | 8010 | Final review, conflict arbitration, delivery sign-off |

### Agent Details

#### Product Owner

> **Port 8000** · Single point of contact with the user

The only agent that interacts with the user. Receives free-text requests, writes a Product Requirements Document (PRD), classifies features (Must/Should/Nice to Have), and defines the Definition of Done. Accepts or rejects the final deliverable on the user's behalf.

- **MCP Tools:** Context7 (domain knowledge), Linear (create Epic)
- **Pushes to:** PM

#### Project Manager

> **Port 8001** · Sprint planning & coordination

Reads the PRD, breaks it into estimable Stories and Tasks, sizes effort (S/M/L/XL), creates sprint plans, assigns work, and tracks real-time progress on a dashboard.

- **MCP Tools:** Linear (Sprints, Stories), GitHub (milestones, labels)
- **Pushes to:** BA + SA (parallel, non-blocking)

#### Business Analyst

> **Port 8002** · Requirements & API contracts

Converts stories into precise User Stories with Gherkin acceptance criteria (Given/When/Then), writes OpenAPI specs, defines data models with entity relationships, and validates final output against acceptance criteria.

- **MCP Tools:** Context7 (business patterns), Linear (update Stories)
- **Pushes to:** Frontend Dev + Backend Dev (parallel)

#### Solution Architect

> **Port 8003** · System design & technical direction

Designs the overall system architecture with Mermaid diagrams, selects and justifies the tech stack, defines inter-service interfaces, writes SQL DDL schemas, handles cross-cutting concerns (auth, logging, caching, rate limiting), and maintains Architecture Decision Records.

- **MCP Tools:** Context7 (architecture patterns), GitHub (read existing code)
- **Pushes to:** Backend Dev + DevOps
- **Rule:** Every architecture decision must have an ADR (Context → Decision → Consequences)

#### Frontend Developer

> **Port 8004** · NextJS implementation

Implements NextJS 14 components and pages following user stories and API contracts. Builds responsive layouts (mobile/tablet/desktop), dark mode by default, and handles all loading/empty/error states. Self-reviews code before pushing (lint + type check must pass).

- **MCP Tools:** GitHub (branches, commits, PRs), Context7 (NextJS/React/Tailwind docs)
- **Pushes to:** UIUX Reviewer
- **Gate:** `npx tsc --noEmit && npm run lint` must pass before push

#### Backend Developer

> **Port 8005** · FastAPI implementation

Implements FastAPI endpoints following API contracts and DB schemas. Builds business logic with SQLAlchemy ORM, validates all input with Pydantic, handles errors with proper HTTP status codes, and writes inline docstrings for every function.

- **MCP Tools:** GitHub (branches, commits, PRs), Context7 (FastAPI/SQLAlchemy docs)
- **Pushes to:** Security Reviewer
- **Rule:** No hardcoded secrets. Validate all input. Handle all exceptions. Log all errors.

#### UIUX Reviewer

> **Port 8006** · Accessibility & UX validation

Reviews frontend code against WCAG 2.1 AA standards. Checks spacing, typography, color contrast (≥ 4.5:1 ratio), touch targets (≥ 44px), focus states, keyboard navigation, responsive breakpoints, and all state handling (loading/empty/error).

- **MCP Tools:** GitHub (code review, PR comments), OpenDesign (design spec comparison)
- **Pushes to:** QA (if pass) / Frontend Dev (if violations found)
- **Classifications:** VIOLATION (must fix, blocks merge) · SUGGESTION (should fix) · OPINION (backlog)

#### Security Reviewer

> **Port 8007** · OWASP audit & vulnerability scanning

Reviews all backend and frontend code against the OWASP Top 10. Scans for committed secrets, hardcoded credentials, SQL/NoSQL/command injection, XSS, IDOR, SSRF, and checks dependencies for known CVEs.

- **MCP Tools:** GitHub (code review, block merge on critical), Context7 (CVE database)
- **Pushes to:** QA (if pass) / Backend/Frontend Dev (if issues found)
- **Severity:** CRITICAL (blocks merge immediately) · HIGH (fix before merge) · MEDIUM (fix this sprint) · LOW (backlog)

#### QA / Tester

> **Port 8008** · Automated testing

Reads acceptance criteria, writes test cases (40% happy path, 35% edge cases, 25% error cases), implements automated tests (pytest + httpx for backend, Playwright for E2E), runs suites, and produces detailed bug reports for failures.

- **MCP Tools:** GitHub (commit tests, read source), Context7 (testing patterns)
- **Pushes to:** DevOps (if all pass) / Dev agents (if tests fail)
- **Target:** ≥ 80% code coverage
- **Bug report format:** Steps to Reproduce · Expected · Actual · Severity (P0–P3) · Evidence
- **Auto-retry:** Up to 3 rounds, then escalate to TechLead

#### DevOps / SRE

> **Port 8009** · Infrastructure & deployment

Writes Dockerfiles (non-root, multi-stage, pinned versions), docker-compose configuration with health checks, GitHub Actions CI/CD workflows, and handles structured JSON logging and metrics endpoints.

- **MCP Tools:** GitHub (push configs, trigger workflows), Context7 (Docker/Actions best practices)
- **Pushes to:** TechLead
- **Rules:** No `:latest` tags · Health checks required · Resource limits enforced (512m RAM, 0.5 CPU) · Secrets via .env only

#### TechLead

> **Port 8010** · Final gate & conflict resolution

Does exactly four things: (1) arbitrates agent conflicts after 3 debate rounds, (2) performs final overall architecture review, (3) merges the final PR and signs off delivery, and (4) monitors the pipeline and unblocks stuck agents.

- **MCP Tools:** GitHub (final PR review, merge), Linear (mark Epics/Stories Done)
- **Pushes to:** PO (delivery report)
- **Conflict priority:** Security > Accessibility > Business Logic > Architecture > Readability

### MCP Tool Matrix

| Agent | GitHub | Context7 | Linear | OpenDesign |
|---|:---:|:---:|:---:|:---:|
| PO | | R | W | |
| PM | W | | W | |
| BA | | R | W | |
| Solution Architect | R | R | | |
| Frontend Dev | W | R | | |
| Backend Dev | W | R | | |
| UIUX Reviewer | W | | | R |
| Security Reviewer | W | R | | |
| QA / Tester | W | R | | |
| DevOps / SRE | W | R | | |
| TechLead | W | | W | |

> R = read-only · W = read + write

---

## Tech Stack

### Backend Agents

| Technology | Version | Purpose |
|---|---|---|
| Python | 3.11+ | Agent runtime |
| FastAPI | 0.110+ | HTTP server for each agent |
| Uvicorn | latest | ASGI runner |
| Pydantic | v2 | Data validation & schemas |
| SQLAlchemy | 2.0 | ORM (when DB needed) |
| httpx | latest | Async HTTP client (A2A + MCP calls) |
| redis-py | latest | Task queue & agent registry |
| python-dotenv | latest | Environment variable loading |
| structlog | latest | Structured JSON logging |

### Frontend Web UI

| Technology | Version | Purpose |
|---|---|---|
| NextJS | 14+ | App Router framework |
| TypeScript | 5+ | Type-safe frontend |
| Tailwind CSS | 3+ | Utility-first styling |
| shadcn/ui | latest | Accessible component library |
| Recharts | latest | Token usage charts |
| Zustand | latest | Lightweight state management |
| EventSource (SSE) | — | Real-time log streaming |

### Infrastructure

| Technology | Purpose |
|---|---|
| Docker + Docker Compose | Containerization & orchestration |
| Redis | Task queue + agent discovery registry |
| PostgreSQL | Persistent storage (SQLite for dev) |
| GitHub Actions | CI/CD pipelines |
| Nginx | Reverse proxy for web UI |

---

## Development Guide

### Project Structure

```
.
├── docker-compose.yml          # Multi-service orchestration
├── .env.example                # Environment variable template
├── README.md                   # This file
│
├── shared/                     # Shared libraries (imported by all agents)
│   ├── a2a_client.py           # Send A2A messages to other agents
│   ├── a2a_server.py           # Base class for A2A HTTP servers
│   ├── mcp_client.py           # Invoke MCP tools via JSON-RPC
│   ├── task_queue.py           # Redis-backed async task queue
│   ├── models.py               # Pydantic models shared across agents
│   └── registry.py             # Agent auto-discovery via /well-known
│
├── agents/                     # One directory per agent
│   ├── po/
│   │   ├── main.py             # FastAPI app: /a2a + /.well-known/agent.json + /health
│   │   ├── tools.py            # MCP tool wrappers
│   │   ├── prompts.py          # Agent system prompt
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── pm/
│   ├── ba/
│   ├── solution_architect/
│   ├── frontend_dev/
│   ├── backend_dev/
│   ├── uiux_reviewer/
│   ├── security_reviewer/
│   ├── qa/
│   ├── devops/
│   └── techlead/
│
└── web/                        # NextJS 14 admin panel
    ├── package.json
    ├── next.config.js
    ├── tailwind.config.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx            # Dashboard
    │   ├── tasks/page.tsx      # Task submission + progress timeline
    │   ├── agents/page.tsx     # Agent status + per-agent configuration
    │   ├── config/page.tsx     # API keys, MCP servers, A2A settings
    │   ├── logs/page.tsx       # Real-time log stream
    │   └── api/
    │       ├── tasks/route.ts
    │       ├── agents/route.ts
    │       ├── config/route.ts
    │       └── logs/route.ts   # SSE endpoint
    └── components/
        ├── Sidebar.tsx
        ├── AgentCard.tsx
        ├── TaskTimeline.tsx    # A2A message flow visualization
        ├── DebateViewer.tsx    # Agent debate transcripts
        ├── LogViewer.tsx
        └── TokenChart.tsx
```

### Agent Implementation Pattern

Every agent follows this standard pattern:

```python
from fastapi import FastAPI
from shared.a2a_server import A2AServer
from shared.mcp_client import MCPClient
from shared.task_queue import TaskQueue
from .tools import get_tools
from .prompts import SYSTEM_PROMPT

app = FastAPI()
a2a = A2AServer(agent_name="backend-dev", port=8005)
queue = TaskQueue(agent_name="backend-dev")

@app.get("/.well-known/agent.json")
def agent_card():
    """Return the A2A agent card for auto-discovery."""
    return a2a.get_card()

@app.post("/a2a")
async def receive_task(message: dict):
    """Accept an incoming A2A task and enqueue it (non-blocking)."""
    await queue.push(message)
    return {"status": "accepted", "task_id": message["task_id"]}

@app.get("/health")
def health():
    """Health check endpoint for Docker and monitoring."""
    return {"status": "ok", "agent": "backend-dev", "queue_size": queue.size()}

async def worker():
    """Background worker: process tasks and push results downstream."""
    while True:
        task = await queue.pop()
        if task:
            result = await process(task)
            await a2a.push(to=next_agent(task), message=result)
        # Pick next task immediately — no idle waiting
```

### Running Locally (Without Docker)

```bash
# 1. Install shared dependencies
pip install -r shared/requirements.txt

# 2. Start Redis (required for task queue)
docker run -d -p 6379:6379 redis:7-alpine

# 3. Start a single agent (e.g., backend-dev)
cd agents/backend_dev
pip install -r requirements.txt
uvicorn main:app --port 8005 --reload

# 4. Start the web UI
cd web
npm install
npm run dev    # → http://localhost:3000
```

### Running Tests

```bash
# Backend agent tests
cd agents/backend_dev
pytest tests/ -v --cov=. --cov-report=term-missing

# Frontend agent tests
cd agents/frontend_dev
npx tsc --noEmit && npm run lint

# Integration tests
pytest tests/integration/ -v

# E2E tests (requires running services)
cd web
npx playwright test
```

### Environment Variables

| Variable | Required | Description |
|---|---|---|
| `MIMO_API_KEY` | ✅ | API key for the LLM backend |
| `MIMO_BASE_URL` | ✅ | Base URL for the LLM API |
| `MIMO_MODEL` | ✅ | Model identifier (e.g., `mimo-v2.5-pro`) |
| `GITHUB_TOKEN` | | Personal access token for GitHub MCP |
| `GITHUB_MCP_URL` | | GitHub MCP server URL |
| `LINEAR_API_KEY` | | API key for Linear MCP |
| `LINEAR_MCP_URL` | | Linear MCP server URL |
| `OPENDESIGN_MCP_URL` | | OpenDesign MCP server URL |
| `REDIS_URL` | | Redis connection string (default: `redis://localhost:6379`) |
| `DATABASE_URL` | | PostgreSQL connection string (default: SQLite) |
| `LOG_LEVEL` | | Logging level (default: `INFO`) |

---

## API Reference

### Web UI Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/agents` | List all agents with status |
| `GET` | `/api/agents/:id` | Get agent detail |
| `POST` | `/api/agents/:id/test` | Trigger agent health check |
| `POST` | `/api/tasks` | Submit a new task |
| `GET` | `/api/tasks` | List all tasks |
| `GET` | `/api/tasks/:id` | Get task detail with timeline |
| `GET` | `/api/config` | Get current configuration |
| `POST` | `/api/config` | Update configuration |
| `GET` | `/api/logs` | Real-time log stream (SSE) |
| `GET` | `/api/stats` | Token usage and uptime stats |

### Agent Endpoints (each agent)

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/.well-known/agent.json` | A2A agent card for auto-discovery |
| `POST` | `/a2a` | Receive an A2A message (returns 202) |
| `GET` | `/health` | Health check (`{"status": "ok"}`) |

---

## Pipeline Rules

| Rule | Description |
|---|---|
| **Non-blocking push** | After pushing output downstream, every agent immediately picks the next task from its queue. No idle waiting. |
| **Auto-approve all** | No user approval needed mid-pipeline. TechLead approves all internal decisions. |
| **Retry loop** | Test/build failures trigger automatic fix-and-retry (max 3 rounds), then escalate to TechLead. |
| **Debate limit** | Max 3 rounds per conflict, then auto-escalate. TechLead's decision is final. |
| **Stuck detection** | Agent with no activity for 30+ minutes triggers an alert to TechLead for unblocking. |
| **Stop condition** | Pipeline halts only when: `docker-compose up` succeeds, web UI returns 200, and all `/health` endpoints return OK. |

---

## UI Overview

The admin panel follows a router-admin style interface (dark mode default) with five main sections:

| Page | Description |
|---|---|
| **Dashboard** | Agent status grid, recent tasks, 7-day token usage chart |
| **Tasks** | Submit new tasks, view progress timeline, inspect A2A message flow |
| **Agents** | Per-agent status cards, model configuration, tool settings, restart controls |
| **Config** | API key management, MCP server connections, A2A connection map |
| **Logs** | Real-time log stream with agent/level filters and search |

---

## FAQ

**Q: What happens if an agent gets stuck?**
A: TechLead monitors all agents. If any agent shows no activity for 30+ minutes, TechLead receives an alert and can unblock or reassign the task.

**Q: Can I use a different LLM instead of MiMo?**
A: Yes. Set `MIMO_BASE_URL` and `MIMO_MODEL` to any OpenAI-compatible API endpoint and model identifier.

**Q: How do agent conflicts get resolved?**
A: Agents follow a structured 3-round debate (Challenge → Response → Final Position). If they still disagree, both escalate to TechLead, whose decision is final. Security issues always take absolute priority.

**Q: Do I need all MCP tools configured?**
A: No. GitHub MCP and Context7 are recommended for full functionality. Linear and OpenDesign are optional — agents gracefully degrade without them.

**Q: How is code quality enforced?**
A: Multiple layers — developers self-review (lint + type check), UIUX checks accessibility, Security checks OWASP compliance, QA verifies with automated tests, and TechLead performs the final review before merge.

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

<p align="center">
  Built with 🤖 by the <strong>OpenCrew</strong> community<br/>
  <em>11 agents. 1 mission. Zero human intervention.</em>
</p>