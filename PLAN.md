# OpenCrew — MASTER BUILD PLAN
 
> `build.py` đọc file này → dùng CrewAI + MiMo để sinh toàn bộ hệ thống vào `output/`.
> Không hỏi user giữa chừng. Tất cả agent tự chạy, tự quyết định, tự deliver.
 
---
 
## Triết lý thiết kế
 
```
User (end-user)
  │
  │  "Tôi muốn feature X"
  ▼
┌──────────────────────────────────────────────┐
│               OpenCrew System                │
│                                              │
│  PO ──► PM ──► BA                            │
│               │   └──► Solution Architect    │
│               │                │             │
│         Frontend Dev      Backend Dev        │
│               │                │             │
│         UIUX Reviewer   Security Reviewer    │
│               └────────┬───────┘             │
│                    QA / Tester               │
│                        │                    │
│                  DevOps / SRE               │
│                        │                    │
│               TechLead (final gate)         │
└──────────────────────────────────────────────┘
  │
  │  PR merged, deployed, health check pass
  ▼
User nhận kết quả
```
 
**Nguyên tắc cốt lõi:**
 
- User chỉ đưa yêu cầu và nhận kết quả — không làm gì khác ở giữa
- Mỗi agent = 1 vai trò thực sự trong công ty phần mềm
- Agent tự pick task tiếp theo sau khi push output (pipeline async)
- TechLead là checkpoint cuối duy nhất, KHÔNG phải dispatcher
- Agent ↔ Agent giao tiếp qua **A2A protocol**
- Agent ↔ Tool giao tiếp qua **MCP protocol**
 
---
 
## Cơ cấu tổ chức — 11 Agents
 
### Tầng 1 — Strategy (What & Why)
 
#### PO — Product Owner (port 8000)
 
```yaml
responsibility:
  - Tiếp nhận yêu cầu từ user (điểm tiếp xúc DUY NHẤT với user)
  - Viết Product Requirements Document (PRD)
  - Phân loại Must Have / Should Have / Nice to Have
  - Định nghĩa Definition of Done (DoD)
  - Accept hoặc reject kết quả cuối thay mặt user
mcp_tools:
  - linear_mcp  : Tạo Epic
  - context7    : Tra cứu domain knowledge, industry standards
input  : Yêu cầu text tự do từ user
output : PRD.md + Epic trên Linear
push_to: [PM]
rule   : "Yêu cầu mơ hồ → tự suy luận theo ngữ cảnh, KHÔNG hỏi lại user"
```
 
#### PM — Project Manager (port 8001)
 
```yaml
responsibility:
  - Đọc PRD từ PO
  - Phân rã thành Stories + Tasks có thể estimate
  - Ước lượng effort: S (< 2h) / M (2–8h) / L (1–3 ngày) / XL (cần phân rã thêm)
  - Tạo sprint plan, assign Stories
  - Theo dõi tiến độ, unblock dependencies
  - Report tiến độ lên dashboard theo thời gian thực
mcp_tools:
  - linear_mcp : Tạo Sprint, Stories, assign
  - github_mcp : Tạo milestones, labels
input  : PRD từ PO
output : Sprint plan + Stories đã assign trên Linear
push_to: [BA, Solution_Architect]  # song song, không đợi nhau
rule   : "Push BA và SA cùng lúc — không để 2 agents idle chờ nhau"
```
 
### Tầng 2 — Analysis & Design (How)
 
#### BA — Business Analyst (port 8002)
 
```yaml
responsibility:
  - Đọc Story từ PM
  - Viết User Stories: "As a [role], I want [goal], so that [benefit]"
  - Viết Acceptance Criteria theo chuẩn Gherkin (Given / When / Then)
  - Viết API contract: endpoint, request schema, response schema, error codes
  - Viết data model (entities, relations, constraints)
  - Validate output cuối: có đúng acceptance criteria không?
mcp_tools:
  - context7   : Tra cứu business patterns, domain vocabulary
  - linear_mcp : Update Story description, add subtasks
input  : Stories từ PM
output : User Stories + Acceptance Criteria + OpenAPI YAML spec + Data model ERD
push_to: [Frontend_Dev, Backend_Dev]  # async, cả 2 cùng lúc
rule   : "Sau khi push → ngay lập tức pick Story tiếp theo từ queue, không đứng chờ"
```
 
#### Solution Architect (port 8003)
 
```yaml
responsibility:
  - Đọc PRD + Stories
  - Thiết kế system architecture (Mermaid diagram)
  - Chọn và lý giải tech stack
  - Định nghĩa interfaces giữa services
  - Thiết kế database schema (SQL DDL)
  - Xử lý cross-cutting concerns: auth, logging, caching, rate limiting
  - Viết Architecture Decision Records (ADR)
  - Review code architecture (không review business logic)
mcp_tools:
  - context7   : Architecture patterns, best practices
  - github_mcp : Đọc existing codebase structure
input  : PRD + Stories từ PM
output : ADR docs + system diagram + DB schema (SQL) + interface contracts
push_to: [Backend_Dev, DevOps]
rule   : "Mọi architecture decision phải có ADR: Context → Decision → Consequences"
```
 
### Tầng 3 — Build (Do the work)
 
#### Frontend Developer (port 8004)
 
```yaml
responsibility:
  - Đọc User Stories + API contract từ BA
  - Đọc UI spec từ UI_SPEC.md
  - Implement NextJS 14 components và pages
  - Gọi API backend đúng contract đã định
  - Implement responsive (mobile / tablet / desktop)
  - Dark mode mặc định
  - Loading states, empty states, error states đầy đủ
  - Tự review code trước khi push (lint + type check phải pass)
mcp_tools:
  - github_mcp : Tạo branch, commit, push code, open PR
  - context7   : NextJS / React / Tailwind / shadcn docs
input  : User Stories + API contract + UI_SPEC.md
output : NextJS TypeScript code trên feature branch
push_to: [UIUX_Reviewer]
rule   : "npx tsc --noEmit && npm run lint phải pass trước khi push"
```
 
#### Backend Developer (port 8005)
 
```yaml
responsibility:
  - Đọc API contract + DB schema từ BA/SA
  - Implement FastAPI endpoints
  - Implement business logic và data access layer (SQLAlchemy)
  - Input validation (Pydantic)
  - Error handling chuẩn (HTTP status codes + error response schema)
  - Inline docstrings cho mọi function
  - Tự review code trước khi push
mcp_tools:
  - github_mcp : Tạo branch, commit, push code, open PR
  - context7   : FastAPI / SQLAlchemy / Pydantic docs
input  : API spec + DB schema + User Stories
output : Python FastAPI code trên feature branch
push_to: [Security_Reviewer]
rule   : "Không hardcode secret. Validate mọi input. Handle mọi exception. Log mọi error."
```
 
#### UIUX Reviewer (port 8006)
 
```yaml
responsibility:
  - Review UI code từ Frontend Dev
  - Kiểm tra WCAG 2.1 AA accessibility
  - Kiểm tra spacing, typography, color contrast (≥ 4.5:1)
  - Kiểm tra touch targets (≥ 44px)
  - Kiểm tra focus states, keyboard navigation
  - Kiểm tra responsive breakpoints
  - Kiểm tra loading / empty / error states tồn tại
  - So sánh với UI_SPEC.md
mcp_tools:
  - github_mcp    : Xem code, comment PR
  - opendesign_mcp: Compare với design spec (nếu có)
input  : Frontend code + UI_SPEC.md
output : Review report + PR comments
push_to: [Frontend_Dev] nếu có VIOLATION | [QA] nếu pass
rule   : |
  Phân loại bắt buộc:
    VIOLATION  (must fix, blocks merge) : Sai accessibility, broken layout
    SUGGESTION (should fix this sprint) : UX improvement
    OPINION    (nice to have, backlog)  : Aesthetic preference
```
 
### Tầng 4 — Quality & Safety
 
#### Security Reviewer (port 8007)
 
```yaml
responsibility:
  - Review toàn bộ code backend (và frontend khi liên quan auth/data)
  - Kiểm tra OWASP Top 10:
      A01 Broken Access Control
      A02 Cryptographic Failures
      A03 Injection (SQL, NoSQL, Command)
      A04 Insecure Design
      A05 Security Misconfiguration
      A06 Vulnerable Components
      A07 Auth/Session Failures
      A08 Integrity Failures
      A09 Logging/Monitoring Failures
      A10 SSRF
  - Kiểm tra secrets không bị commit (scan .env, hardcode strings)
  - Kiểm tra dependencies có CVE đã biết
mcp_tools:
  - github_mcp : Xem code, comment PR, block merge nếu CRITICAL
  - context7   : CVE database, security advisories
input  : Backend code + Frontend code
output : Security report phân loại rõ severity
push_to: [Backend_Dev / Frontend_Dev] nếu có issue | [QA] nếu pass
rule   : |
  CRITICAL (block ngay, không merge) : Secret exposed, SQL injection, auth bypass
  HIGH     (fix trước khi merge)     : XSS, IDOR, missing auth
  MEDIUM   (fix trong sprint này)    : Missing rate limit, weak validation
  LOW      (backlog)                 : Defense-in-depth
```
 
#### QA / Tester (port 8008)
 
```yaml
responsibility:
  - Đọc Acceptance Criteria từ BA
  - Viết test cases theo phân bổ: 40% happy path + 35% edge cases + 25% error cases
  - Implement automated tests:
      Backend  : pytest + httpx (API tests)
      Frontend : Playwright (E2E tests)
  - Chạy tests, phân tích kết quả
  - Viết bug reports đầy đủ cho failures
  - Regression testing sau khi dev fix
mcp_tools:
  - github_mcp : Commit test code, đọc source code để hiểu implementation
  - context7   : pytest / Playwright / testing patterns
input  : Acceptance Criteria + code từ dev agents
output : Test suite + test results + bug reports (nếu có)
push_to: [Backend/Frontend Dev] nếu test fail | [DevOps] nếu tất cả pass
rule   : |
  Target: ≥ 80% coverage
  Bug report bắt buộc có:
    - Steps to Reproduce
    - Expected Result
    - Actual Result
    - Severity (P0/P1/P2/P3)
    - Screen capture (text representation)
  Auto-rerun sau khi dev fix, tối đa 3 lần, sau đó escalate TechLead
```
 
### Tầng 5 — Delivery
 
#### DevOps / SRE (port 8009)
 
```yaml
responsibility:
  - Viết Dockerfile cho từng service (non-root, multi-stage, pinned versions)
  - Viết docker-compose.yml (services, networks, volumes, health checks)
  - Viết GitHub Actions CI/CD:
      - On PR: lint, type check, unit tests
      - On merge to main: build, integration tests, deploy
  - Resource limits (CPU/memory) cho mọi container
  - Structured logging (JSON format)
  - Metrics endpoint (/metrics) cho monitoring
  - Secrets management (chỉ qua env vars, không commit)
mcp_tools:
  - github_mcp : Push Dockerfiles, CI/CD configs, trigger workflows
  - context7   : Docker / GitHub Actions / nginx best practices
input  : Merged code từ feature branches + Architecture từ SA
output : docker-compose.yml + CI/CD workflows + deployment documentation
push_to: [TechLead]
rule   : |
  Không dùng :latest tag
  Mọi service phải có health check
  Resource limits bắt buộc (mặc định: 512m RAM, 0.5 CPU)
  Secrets chỉ từ .env file (không commit .env)
```
 
### Tầng 6 — Final Gate
 
#### TechLead (port 8010)
 
```yaml
responsibility:
  - KHÔNG assign tasks (PM làm)
  - KHÔNG viết code (Dev agents làm)
  - Làm DUY NHẤT 4 việc:
      1. Arbitrate conflict giữa agents (sau round 3 debate)
      2. Final architecture review tổng thể
      3. Merge PR cuối và sign-off delivery
      4. Monitor pipeline, unblock agent stuck > 30 phút
  - Maintain agent registry
mcp_tools:
  - github_mcp : Final review PR, approve merge
  - linear_mcp : Update Epic/Story sang Done
input  : Reports từ tất cả agents + delivery package từ DevOps
output : Final approval + delivery report → PO
rule   : |
  Conflict priority (ai thắng khi conflict):
    Security issue       → Security Reviewer (luôn luôn)
    Accessibility issue  → UIUX Reviewer
    Business logic       → BA
    Technical approach   → Solution Architect
    Performance vs Clean → Clean code thắng (mặc định)
    Deadlock > 3 rounds  → TechLead quyết định unilaterally
```
 
---
 
## Pipeline Flow — Async Non-blocking
 
```
User Input
    │
    ▼
  [PO]
    │ PRD ready
    ▼ A2A push
  [PM]
    │ Stories ready
    ├─────────────────────────────┐
    ▼                             ▼
  [BA]                   [Solution Architect]
    │ AC + API spec           │ ADR + DB schema
    │                         │
    ├─────────┐               │ pushes schema to Backend Dev
    │         │               │
    ▼         ▼               ▼
[Frontend] [Backend] ◄── receives schema
    │           │
    ▼           ▼
[UIUX]    [Security]
    │           │
    │ pass      │ pass
    └─────┬─────┘
          ▼
        [QA]
          │ all tests pass
          ▼
       [DevOps]
          │ deployment ready
          ▼
      [TechLead]
          │ final sign-off
          ▼
        [PO] ──────────► User nhận kết quả
```
 
**Async rule**: Sau khi agent push output xuống agent tiếp theo → **ngay lập tức** pick task mới từ queue. Không agent nào idle chờ agent khác.
 
---
 
## A2A Message Format
 
```json
{
  "protocol": "a2a/1.0",
  "type": "task | challenge | response | final_position | escalate | decision | result",
  "from": "<agent_name>",
  "to": "<agent_name>",
  "task_id": "<uuid>",
  "round": 1,
  "payload": {
    "claim": "Mô tả vấn đề hoặc kết quả",
    "evidence": "Lý do, file:line, data",
    "suggestion": "Đề xuất hành động",
    "artifacts": ["path/to/file.py", "path/to/spec.yaml"]
  },
  "timestamp": "2026-05-27T10:00:00Z"
}
```
 
**Debate flow:**
 
```
Round 1: Agent A gửi CHALLENGE → Agent B
Round 2: Agent B gửi RESPONSE (accept | counter)
Round 3: Agent A gửi FINAL_POSITION
         ↓ nếu vẫn conflict
         Cả 2 gửi ESCALATE → TechLead
         TechLead gửi DECISION (final, không appeal)
```
 
---
 
## MCP Tool Registry
 
| Agent | github_mcp | context7 | linear_mcp | opendesign_mcp |
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
 
*(R = read only, W = read + write)*
 
---
 
## Output Folder Structure
 
```text
output/
├── docker-compose.yml
├── .env.example
├── README.md
│
├── shared/
│   ├── a2a_client.py        ← Gửi A2A message tới agent khác
│   ├── a2a_server.py        ← Base class cho A2A server
│   ├── mcp_client.py        ← Gọi MCP tool
│   ├── task_queue.py        ← Async task queue (Redis)
│   ├── models.py            ← Pydantic shared models
│   └── registry.py          ← Agent auto-discovery registry
│
├── agents/
│   ├── po/
│   │   ├── main.py          ← FastAPI: /a2a + /.well-known/agent.json + /health
│   │   ├── tools.py         ← MCP tool implementations
│   │   ├── prompts.py       ← System prompt của agent này
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
└── web/
    ├── package.json
    ├── next.config.js
    ├── tailwind.config.ts
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx              ← Dashboard
    │   ├── tasks/page.tsx        ← Submit task + progress timeline
    │   ├── agents/page.tsx       ← Agent status + per-agent config
    │   ├── config/page.tsx       ← API keys, MCP, A2A settings
    │   ├── logs/page.tsx         ← Real-time log stream
    │   └── api/
    │       ├── tasks/route.ts
    │       ├── agents/route.ts
    │       ├── config/route.ts
    │       └── logs/route.ts     ← SSE endpoint
    └── components/
        ├── Sidebar.tsx
        ├── AgentCard.tsx
        ├── TaskTimeline.tsx      ← Hiển thị A2A message flow
        ├── DebateViewer.tsx      ← Hiển thị agent debates
        ├── LogViewer.tsx
        └── TokenChart.tsx
```
 
---
 
## Build Phases
 
### Phase 1 — Shared Infrastructure
Generate: toàn bộ `shared/` — a2a_client, a2a_server, mcp_client, task_queue, models, registry
 
### Phase 2 — All Agents
Generate: 11 agents trong `agents/`
Mỗi agent: main.py + tools.py + prompts.py + Dockerfile + requirements.txt
 
### Phase 3 — Web UI
Generate: `web/` NextJS 14 app với tất cả pages + components theo UI_SPEC.md
 
### Phase 4 — Integration & Deployment
Generate: docker-compose.yml + .env.example + GitHub Actions + integration tests
 
---
 
## Auto-Approve Rules
 
```
✅ Tất cả đều auto-approve:
   Code changes, test additions, refactoring, bug fixes,
   config changes, architecture decisions, PR merges (nếu tests pass)
 
🔁 Auto-retry:
   Test fail → dev agent tự fix → retest (tối đa 3 lần)
   Build fail → devops tự fix → rebuild (tối đa 3 lần)
 
⏫ Auto-escalate:
   Agent stuck > 30 phút → TechLead nhận alert
   Debate > 3 rounds → TechLead arbitrate
   Retry > 3 lần vẫn fail → TechLead quyết định skip hoặc redesign
 
🛑 Dừng khi (và chỉ khi):
   Tất cả phases complete
   docker-compose up thành công
   Web UI trả về 200 tại localhost:3000
   Tất cả agent /health trả về {"status": "ok"}
```