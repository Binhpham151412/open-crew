# 🎨 OpenCrew — UI SPEC (cho OpenDesign)
 
> **File này đưa cho OpenDesign** → nó tự generate code HTML/NextJS cho config panel.
> Style: giống trang quản trị router (OpenWRT / 9Router) — sidebar + content panels.
 
-----
 
## Design System
 
```
Colors:
  primary: #2563EB (blue-600)
  success: #16A34A (green-600)
  warning: #D97706 (amber-600)
  danger:  #DC2626 (red-600)
  bg:      #0F172A (slate-900)  ← dark mode default
  surface: #1E293B (slate-800)
  text:    #F8FAFC (slate-50)
  muted:   #94A3B8 (slate-400)
 
Typography:
  font: Inter / system-ui
  heading: 600 weight
  body: 400 weight
  mono: JetBrains Mono (cho code/logs)
 
Spacing: 4px grid (4, 8, 12, 16, 24, 32, 48)
Border-radius: 8px (cards), 4px (buttons, inputs)
```
 
-----
 
## Layout — Router Admin Style
 
```
┌──────────────────────────────────────────────────────┐
│  🤖 OpenCrew          [status: ● running]    [user]  │  ← Top bar
├──────────┬───────────────────────────────────────────┤
│          │                                           │
│ Dashboard│   [Main Content Area]                     │
│ Tasks    │                                           │
│ Agents   │                                           │
│ Config   │                                           │
│ Logs     │                                           │
│          │                                           │
│──────────│                                           │
│ System   │                                           │
│ About    │                                           │
│          │                                           │
├──────────┴───────────────────────────────────────────┤
│  OpenCrew v1.0 | Uptime: 3d 12h | Tokens: 1.2M used │  ← Footer
└──────────────────────────────────────────────────────┘
```
 
-----
 
## Pages
 
### 1. Dashboard (/)
 
```
┌─ Agent Status ───────────────────────────────────────┐
│ ● Coding Agent    online  | 12,340 tokens today      │
│ ● BA Agent        online  |  3,210 tokens today      │
│ ● UIUX Agent      online  |  1,050 tokens today      │
│ ○ Tester Agent    offline |  0 tokens today           │
│ ● DevOps Agent    online  |  890 tokens today         │
│ ● TechLead Agent  online  |  5,600 tokens today       │
└──────────────────────────────────────────────────────┘
 
┌─ Recent Tasks ───────────────────────────────────────┐
│ #001  "Build login feature"   done      3h ago       │
│ #002  "Review PR #42"         working   5m ago       │
│ #003  "Fix auth bug"          pending   just now     │
└──────────────────────────────────────────────────────┘
 
┌─ Token Usage (7-day chart) ──────────────────────────┐
│ ▁▂▃▅▇█▆  bar chart per day, stacked by agent         │
│ Total: 45,200 tokens | Est. cost: $0.02              │
└──────────────────────────────────────────────────────┘
```
 
### 2. Tasks (/tasks)
 
```
┌─ New Task ───────────────────────────────────────────┐
│ [Enter task... e.g. "Build user registration"]       │
│ [Submit Task]                                         │
└──────────────────────────────────────────────────────┘
 
┌─ Task #002: "Review PR #42" ─────────────────────────┐
│ Status: ● working                                     │
│ Phase: 2/4 (Code Review)                              │
│                                                       │
│ Timeline:                                             │
│ 14:01  TechLead assigned → Coding, Tester             │
│ 14:02  Coding: reviewing diff (142 lines)             │
│ 14:05  Coding: found 3 issues                         │
│ 14:06  Tester: coverage check — 78% (need 80%)       │
│ 14:07  Tester → Coding: CHALLENGE "missing test X"    │
│ 14:08  Coding: accepted, adding test                  │
│ ...                                                   │
└──────────────────────────────────────────────────────┘
```
 
### 3. Agents (/agents)
 
```
Per-agent card (expandable):
 
┌─ Coding Agent ───────────────────────────────────────┐
│ Status: ● online                                      │
│ Model:  mimo-v2.5-pro                                 │
│ Tools:  review_code, explain_error, suggest_fix       │
│                                                       │
│ Settings:                                             │
│   Model:       [dropdown: mimo-v2.5-pro ▾]           │
│   Temperature: [slider: 0.2]                          │
│   Max tokens:  [input: 8192]                          │
│   Enabled:     [toggle: ON]                           │
│                                                       │
│ [Test Agent] [View Logs] [Restart]                    │
└──────────────────────────────────────────────────────┘
```
 
### 4. Config (/config)
 
```
┌─ API Keys ───────────────────────────────────────────┐
│ MiMo API Key:    [••••••••••••xxxx]  [Test] [Save]   │
│ MiMo Base URL:   [https://api.xiaomi.com/v1]         │
│ MiMo Model:      [mimo-v2.5-pro]                     │
│ GitHub Token:    [••••••••xxxx]       [Test] [Save]   │
│ OpenDesign URL:  [https://...]        [Test] [Save]   │
└──────────────────────────────────────────────────────┘
 
┌─ MCP Servers ────────────────────────────────────────┐
│ GitHub MCP     https://api.github...  ● connected     │
│ Context7       https://mcp.context7.. ● connected     │
│ Open-Design    (not configured)       ○ disconnected  │
│ Linear         (not configured)       ○ disconnected  │
│                                                       │
│ [+ Add MCP Server]                                    │
└──────────────────────────────────────────────────────┘
 
┌─ A2A Connections ────────────────────────────────────┐
│ Coding ←→ Tester     ● active                        │
│ BA ←→ UIUX           ● active                        │
│ Coding ←→ TechLead   ● active                        │
│ ...                                                   │
│ All agents auto-discovered via /.well-known/agent.json│
└──────────────────────────────────────────────────────┘
```
 
### 5. Logs (/logs)
 
```
┌─ Filters ────────────────────────────────────────────┐
│ Agent: [All ▾]  Level: [All ▾]  Search: [          ] │
└──────────────────────────────────────────────────────┘
 
┌─ Log Stream (real-time) ─────────────────────────────┐
│ 14:08:23 [coding]   INFO  Reviewing file src/auth.ts │
│ 14:08:24 [coding]   WARN  Found: SQL injection L:42  │
│ 14:08:25 [tester]   INFO  Running coverage analysis  │
│ 14:08:26 [techlead] INFO  Arbitrating: coding vs ba  │
│ 14:08:27 [coding]   INFO  Fix applied: sanitize()    │
│ ...                                                   │
└──────────────────────────────────────────────────────┘
```
 
-----
 
## Components cần generate
 
1. **Sidebar** — collapsible, highlight active page
2. **AgentStatusCard** — dot indicator + name + tokens
3. **TaskCard** — task info + expandable timeline
4. **ConfigForm** — label + input + test button + save
5. **LogViewer** — monospace, auto-scroll, color-coded by level
6. **TokenChart** — simple bar chart (dùng recharts hoặc chart.js)
7. **StatusDot** — ● green (online) / ○ gray (offline) / ● yellow (working)
 
-----
 
## Tech Stack
 
- NextJS 14+ (App Router)
- TypeScript
- Tailwind CSS
- shadcn/ui components
- recharts (charts)
- Dark mode default, light mode toggle
 
-----
 
## API Endpoints (NextJS API Routes)
 
```
GET  /api/agents           → list agents + status
GET  /api/agents/:id       → agent detail
POST /api/agents/:id/test  → health check
POST /api/tasks            → submit new task
GET  /api/tasks            → list tasks
GET  /api/tasks/:id        → task detail + timeline
GET  /api/config           → current config
POST /api/config           → update config
GET  /api/logs             → log stream (SSE)
GET  /api/stats            → token usage, uptime
```