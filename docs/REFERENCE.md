# OpenCrew — Reference Knowledge
 
> Đây là tài liệu tham chiếu cho **build agents** đọc khi generate code.
> Chứa: định nghĩa agents, protocols, tech stack, patterns, rules.
 
---
 
## 1. Agent Registry
 
| Agent | Port | Vai trò | MCP Tools | Push đến |
| --- | --- | --- | --- | --- |
| PO | 8000 | Product Owner — tiếp nhận yêu cầu user, viết PRD | linear, context7 | PM |
| PM | 8001 | Project Manager — sprint plan, stories, assign | linear, github | BA + SA (song song) |
| BA | 8002 | Business Analyst — AC, API spec, data model | context7, linear | Frontend + Backend (song song) |
| Solution Architect | 8003 | System design, ADR, DB schema, interfaces | context7, github | Backend + DevOps |
| Frontend Dev | 8004 | NextJS implementation | github, context7 | UIUX Reviewer |
| Backend Dev | 8005 | FastAPI implementation | github, context7 | Security Reviewer |
| UIUX Reviewer | 8006 | Accessibility review, UX validation | github, opendesign | QA (nếu pass) / Frontend (nếu fail) |
| Security Reviewer | 8007 | OWASP Top 10, CVE check, secret scan | github, context7 | QA (nếu pass) / Backend (nếu fail) |
| QA / Tester | 8008 | pytest + Playwright, bug reports | github, context7 | DevOps (nếu pass) / Dev (nếu fail) |
| DevOps / SRE | 8009 | Docker, CI/CD, deployment | github, context7 | TechLead |
| TechLead | 8010 | Final review, arbitrate, sign-off | github, linear | PO |
 
---
 
## 2. A2A Protocol
 
### Agent Card (/.well-known/agent.json)
 
```json
{
  "name": "backend-dev",
  "display_name": "Backend Developer",
  "url": "http://backend-dev:8005",
  "version": "1.0.0",
  "capabilities": ["implement_api", "fix_bug", "code_review"],
  "input_types": ["api_spec", "db_schema", "user_story"],
  "output_types": ["source_code", "pr_url"],
  "protocol": "a2a/1.0"
}
```
 
### Message Schema
 
```json
{
  "protocol": "a2a/1.0",
  "type": "task | challenge | response | final_position | escalate | decision | result",
  "from": "ba",
  "to": "backend-dev",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "round": 1,
  "payload": {
    "claim": "Mô tả công việc hoặc lập luận",
    "evidence": "File, line number, data cụ thể",
    "suggestion": "Đề xuất hành động",
    "artifacts": [
      {"name": "api_spec.yaml", "content": "..."},
      {"name": "acceptance_criteria.md", "content": "..."}
    ]
  },
  "timestamp": "2026-05-27T10:00:00Z"
}
```
 
### Debate Flow
 
```
Agent A → CHALLENGE (round 1) → Agent B
Agent B → RESPONSE  (round 2) → Agent A    (accept | counter-argument)
Agent A → FINAL_POS (round 3) → Agent B
Nếu vẫn conflict:
Agent A + B → ESCALATE → TechLead
TechLead   → DECISION  → cả 2 agents    (final, không appeal)
```
 
### Conflict Resolution Priority
 
| Vấn đề | Agent thắng |
| --- | --- |
| Security vulnerability | Security Reviewer (tuyệt đối) |
| Accessibility violation | UIUX Reviewer |
| Business logic accuracy | BA |
| Technical architecture | Solution Architect |
| Performance vs Readability | Readability (mặc định) |
| Deadlock sau round 3 | TechLead quyết unilaterally |
 
---
 
## 3. MCP Protocol
 
### Request Format (JSON-RPC 2.0)
 
```json
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "github_create_pr",
    "arguments": {
      "title": "feat: add user registration endpoint",
      "body": "Closes #42",
      "head": "feature/user-registration",
      "base": "main"
    }
  },
  "id": "req-001"
}
```
 
### MCP Servers
 
| Server | URL (từ .env) | Tools |
| --- | --- | --- |
| GitHub MCP | `GITHUB_MCP_URL` | create_branch, commit_files, create_pr, merge_pr, get_file, search_code, create_issue |
| Context7 | `https://mcp.context7.com/mcp` | resolve_library_id, get_library_docs |
| Linear MCP | `LINEAR_MCP_URL` | create_epic, create_story, update_story, create_sprint, assign_story |
| OpenDesign MCP | `OPENDESIGN_MCP_URL` | get_design_spec, export_component, compare_design |
 
---
 
## 4. Tech Stack (Production Output)
 
### Backend Agents
 
```text
Python 3.11+
FastAPI 0.110+       ← HTTP server
Uvicorn              ← ASGI runner
Pydantic v2          ← Data validation
SQLAlchemy 2.0       ← ORM (nếu cần DB)
httpx                ← HTTP client (gọi A2A + MCP)
redis                ← Task queue
python-dotenv        ← Env vars
structlog            ← Structured JSON logging
```
 
### Frontend Web UI
 
```text
NextJS 14+           ← App Router
TypeScript 5+
Tailwind CSS 3+
shadcn/ui            ← Component library
Recharts             ← Charts (token usage)
Zustand              ← State management
SSE (EventSource)    ← Real-time log streaming
```
 
### Infrastructure
 
```text
Docker + docker-compose
Redis                ← Task queue + agent registry
PostgreSQL           ← Persistent storage (optional, SQLite for dev)
GitHub Actions       ← CI/CD
Nginx                ← Reverse proxy (web UI)
```
 
---
 
## 5. Agent Implementation Pattern
 
Mỗi agent trong `agents/<name>/main.py` implement pattern này:
 
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
    return a2a.get_card()
 
@app.post("/a2a")
async def receive_task(message: dict):
    # 1. Validate message
    # 2. Add to local queue
    # 3. Return 202 Accepted immediately (non-blocking)
    await queue.push(message)
    return {"status": "accepted", "task_id": message["task_id"]}
 
@app.get("/health")
def health():
    return {"status": "ok", "agent": "backend-dev", "queue_size": queue.size()}
 
# Background worker: process queue items
async def worker():
    while True:
        task = await queue.pop()
        if task:
            result = await process(task)
            await a2a.push(to=next_agent(task), message=result)
        # Pick next task immediately after push — no waiting
```
 
---
 
## 6. Folder Structure (output/)
 
```text
output/
├── docker-compose.yml
├── .env.example
├── README.md
│
├── shared/
│   ├── a2a_client.py        ← a2a.push(to, message)
│   ├── a2a_server.py        ← A2AServer base class
│   ├── mcp_client.py        ← mcp.call(tool, args)
│   ├── task_queue.py        ← Redis-backed async queue
│   ├── models.py            ← Shared Pydantic models
│   └── registry.py          ← Agent discovery (poll /.well-known/agent.json)
│
├── agents/
│   ├── po/                  ← Product Owner
│   ├── pm/                  ← Project Manager
│   ├── ba/                  ← Business Analyst
│   ├── solution_architect/  ← Solution Architect
│   ├── frontend_dev/        ← Frontend Developer
│   ├── backend_dev/         ← Backend Developer
│   ├── uiux_reviewer/       ← UIUX Reviewer
│   ├── security_reviewer/   ← Security Reviewer
│   ├── qa/                  ← QA / Tester
│   ├── devops/              ← DevOps / SRE
│   └── techlead/            ← TechLead
│
└── web/                     ← NextJS Admin Panel
    ├── app/
    │   ├── page.tsx         ← Dashboard
    │   ├── tasks/
    │   ├── agents/
    │   ├── config/
    │   └── logs/
    └── components/
        ├── Sidebar.tsx
        ├── AgentCard.tsx
        ├── TaskTimeline.tsx
        ├── DebateViewer.tsx
        ├── LogViewer.tsx
        └── TokenChart.tsx
```
 
---
 
## 7. Auto-Approve & Pipeline Rules
 
```text
RULE 1 — Non-blocking push:
  Agent hoàn thành task → push result xuống agent tiếp theo → ngay lập tức pick task mới
  Không agent nào đứng idle chờ agent khác
 
RULE 2 — Auto-approve all:
  Không cần user approve giữa chừng
  TechLead tự approve mọi quyết định nội bộ
 
RULE 3 — Retry loop:
  Test/build fail → agent tự fix → retry (max 3 lần)
  Sau 3 lần → escalate TechLead
 
RULE 4 — Debate limit:
  Max 3 rounds per conflict → auto-escalate TechLead
  TechLead decision = final, không appeal
 
RULE 5 — Stuck detection:
  Agent không activity > 30 phút → TechLead nhận alert
  TechLead unblock hoặc reassign
 
RULE 6 — Stop condition:
  Chỉ dừng khi: docker-compose up OK + localhost:3000 = 200 + all /health = OK
```