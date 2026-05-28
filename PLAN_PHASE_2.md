# OpenCrew — Phase 2 Plan

> Phase 1: Sinh code skeleton (116 files) → đang chạy
> Phase 2: Biến skeleton thành hệ thống thật, chạy tự động

---

## Timeline

```
Phase 1 (hiện tại)     ████████████████████░░░░  80%  → build.py đang generate
Phase 1.5: Test        ░░░░░░░░░░░░░░░░░░░░░░░  0%   → verify code chạy được
Phase 1.75: GitHub     ░░░░░░░░░░░░░░░░░░░░░░░  0%   → MIT, release, tag
Phase 2: LLM + Tools   ░░░░░░░░░░░░░░░░░░░░░░░  0%   → agents chạy thật
Phase 3: Production    ░░░░░░░░░░░░░░░░░░░░░░░  0%   → deploy 24/7
Phase 4: Community     ░░░░░░░░░░░░░░░░░░░░░░░  0%   → open source, paper
```

---

## Phase 1.5: Verify Phase 1 Output

Sau khi build.py chạy xong 116 files:

```bash
cd output

# 1. Check Python syntax
python -m py_compile shared/models.py
python -m py_compile shared/a2a_client.py
# ... check từng file

# 2. Check imports resolve
pip install -r agents/po/requirements.txt
python -c "from shared.models import A2AMessage"

# 3. Check FastAPI app khởi động được
cd agents/po
uvicorn main:app --port 8000
# → curl http://localhost:8000/health

# 4. Check NextJS build
cd web
npm install
npm run build
```

**Nếu fail → fix thủ công hoặc regenerate file đó:**
```bash
python build.py --file agents/po/main.py
```

---

## Phase 1.75: GitHub Release

### Repo structure

```
github.com/Binh151412/open-crew/
├── .gitignore
├── LICENSE                  ← MIT
├── README.md                ← Landing page (quan trọng nhất)
├── CHANGELOG.md
├── CONTRIBUTING.md
├── build.py                 ← Build engine
├── PLAN.md                  ← Architecture spec
├── PLAN_PHASE_2.md          ← This file
├── analyst.md
├── .env.example
├── requirements.txt         ← Build dependencies
├── docs/
│   ├── getting-started.md
│   ├── architecture.md
│   ├── api-reference.md
│   └── contributing.md
├── output/                  ← Generated system (hoặc gitignore, cho user tự build)
│   ├── shared/
│   ├── agents/
│   ├── web/
│   └── docker-compose.yml
└── .github/
    ├── ISSUE_TEMPLATE/
    │   ├── bug_report.md
    │   └── feature_request.md
    └── workflows/
        ├── ci.yml
        └── release.yml
```

### Git commands

```bash
# Init
git init
git add .
git commit -m "feat: initial OpenCrew - multi-agent AI software team"

# Remote
git remote add origin https://github.com/Binh151412/open-crew.git
git push -u origin main

# Tag v1.0.0
git tag -a v1.0.0 -m "v1.0.0: Phase 1 - Code generation engine"
git push origin v1.0.0

# GitHub Release
gh release create v1.0.0 \
  --title "OpenCrew v1.0.0" \
  --notes "Initial release: multi-agent AI software team with 11 specialized agents" \
  --verify-tag
```

### README.md nội dung chính

```markdown
# OpenCrew

> 11 AI agents form a software team. You write requirements. They build software.

## Quick Start

```bash
git clone https://github.com/Binh151412/open-crew.git
cd open-crew
pip install -r requirements.txt
cp .env.example .env   # Edit with your API key
python build.py        # Generate all code
cd output && docker-compose up
```

## What You Get

| Agent | Role | Port |
|---|---|---|
| PO | Product Owner | 8000 |
| PM | Project Manager | 8001 |
| ... | ... | ... |
| TechLead | Final gate | 8010 |
| Web UI | Dashboard | 3000 |

## How It Works

You: "Build user registration"
→ PO writes PRD → PM splits tasks → BA writes specs
→ Frontend + Backend code → QA tests → DevOps deploys
→ TechLead signs off → You get working code

## Supported Models

| Model | Cost | Quality |
|---|---|---|
| MiMo v2.5 Pro | ~$0.001/1K tokens | Good |
| GPT-4o | ~$0.005/1K tokens | Excellent |
| Claude 3.5 | ~$0.003/1K tokens | Excellent |
| Gemini 2.5 Flash | Free tier available | Good |
| Qwen 2.5 | Free (self-host) | Good |
| Ollama (local) | Free | Varies |

## License
MIT
```

---

## Phase 2: LLM Integration + Autonomous Agents

### Mục tiêu

Mỗi agent = 1 process chạy liên tục:
- Nhận task từ queue
- Gọi LLM suy nghĩ
- Dùng MCP tool thực thi
- Push result sang agent tiếp theo
- Lặp cho đến khi done

### Step 1: Multi-Model LLM Client

File: `shared/llm_client.py`

```python
# Hỗ trợ nhiều model provider
class LLMClient:
    def __init__(self, config: dict):
        self.provider = config["provider"]  # openai | ollama | gemini | qwen
        self.model = config["model"]
        self.api_key = config.get("api_key")
        self.base_url = config.get("base_url")
    
    async def chat(self, system: str, user: str, tools: list = None) -> Response:
        if self.provider == "openai":
            return await self._openai_chat(system, user, tools)
        elif self.provider == "ollama":
            return await self._ollama_chat(system, user, tools)
        elif self.provider == "gemini":
            return await self._gemini_chat(system, user, tools)
```

### Step 2: Agent Config System

File: `agents/*/config.yaml`

```yaml
# agents/frontend_dev/config.yaml
agent:
  name: frontend_dev
  display_name: Frontend Developer
  port: 8004

llm:
  provider: openai          # openai | ollama | gemini | qwen
  model: mimo-v2.5-pro
  base_url: ${MIMO_BASE_URL}
  api_key: ${MIMO_API_KEY}
  max_tokens: 16384
  temperature: 0.2

tools:
  - name: opencode
    type: mcp
    url: ${OPENCODE_MCP_URL}
    tools: [write_file, read_file, run_command, search_code]
  - name: context7
    type: mcp
    url: https://mcp.context7.com/mcp
    tools: [resolve_library_id, get_library_docs]
  - name: github
    type: mcp
    url: ${GITHUB_MCP_URL}
    tools: [create_branch, commit_files, create_pr]

queue:
  redis_url: ${REDIS_URL}
  input_queue: frontend_dev.tasks
  output_agents: [uiux_reviewer]

a2a:
  endpoint: http://frontend_dev:8004/a2a
```

### Step 3: Agent Loop

File: `shared/agent_loop.py`

```python
class AgentLoop:
    async def run(self):
        while True:
            task = await self.queue.pop()
            if not task:
                await asyncio.sleep(1)
                continue
            
            # Think
            response = await self.llm.chat(
                system=self.system_prompt,
                user=self.task_to_prompt(task),
                tools=self.tools.get_schemas()
            )
            
            # Act (nếu LLM muốn dùng tool)
            while response.tool_call:
                result = await self.tools.call(response.tool_call)
                response = await self.llm.chat(
                    system=self.system_prompt,
                    user=f"Tool result:\n{result}\n\nContinue the task."
                )
            
            # Push result
            for next_agent in self.next_agents:
                await self.a2a.push(to=next_agent, message=response.result)
```

### Step 4: MCP Tool Implementations

Mỗi tool = 1 MCP server thật:

| Tool | MCP Server | Agent dùng |
|---|---|---|
| **OpenCode** | `opencode-mcp` | FE Dev, BE Dev |
| **OpenDesign** | `opendesign-mcp` | UIUX Reviewer |
| **GitHub** | `github-mcp` | Tất cả |
| **Context7** | `context7-mcp` | PO, BA, SA, Devs |
| **Linear** | `linear-mcp` | PO, PM |
| **Snyk** | `snyk-mcp` | Security Reviewer |

### Step 5: One-Command Setup

```bash
# User chỉ cần chạy 1 lệnh
python setup.py

# Lệnh này sẽ:
# 1. Hỏi user dùng model nào (miễn phí hay trả phí)
# 2. Hỏi API key (nếu cần)
# 3. Tạo .env từ template
# 4. Build Docker images
# 5. Start all services
# 6. Mở browser → http://localhost:3000
```

Hoặc với Docker:
```bash
docker-compose up
# Tự động setup mọi thứ
```

---

## Free Model Support — Quan trọng

### Tại sao cần free model?

```
11 agents × mỗi agent gọi LLM mỗi task
= 11 API calls per task
= ~50K-200K tokens per task
= $0.05 - $0.20 per task (với MiMo)

100 tasks/ngày = $5 - $20/ngày
= $150 - $600/tháng

→ Nhiều user không afford được
```

### Model tiers

| Tier | Model | Chi phí | Chất lượng | Cho ai |
|---|---|---|---|---|
| **Free Local** | Ollama (Qwen2.5 7B) | $0 (cần GPU 8GB+) | Tốt | Dev có GPU |
| **Free Cloud** | Gemini 2.5 Flash | Free tier (15 RPM) | Khá | Người mới thử |
| **Free Cloud** | Qwen 2.5 (Alibaba) | Free tier | Khá | User châu Á |
| **Cheap** | MiMo v2.5 Pro | ~$0.001/1K | Tốt | Default |
| **Mid** | GPT-4o Mini | ~$0.00015/1K | Rất tốt | Production |
| **High** | Claude 3.5 Sonnet | ~$0.003/1K | Xuất sắc | Critical tasks |
| **High** | GPT-4o | ~$0.005/1K | Xuất sắc | Critical tasks |

### Config trong .env

```bash
# ===== MODEL CONFIG =====

# Default model (áp dụng cho tất cả agent)
DEFAULT_LLM_PROVIDER=openai
DEFAULT_LLM_MODEL=mimo-v2.5-pro
DEFAULT_LLM_BASE_URL=https://token-plan-sgp.xiaomimimo.com/v1
DEFAULT_LLM_API_KEY=your-key-here

# Per-agent override (optional)
PO_LLM_MODEL=mimo-v2.5-pro
FRONTEND_DEV_LLM_MODEL=gpt-4o        # Dev cần model mạnh
QA_LLM_MODEL=mimo-v2.5-pro           # QA model nhẹ hơn
SECURITY_LLM_MODEL=claude-3.5-sonnet  # Security cần model tốt nhất

# Free alternatives
# DEFAULT_LLM_PROVIDER=ollama
# DEFAULT_LLM_MODEL=qwen2.5:7b
# DEFAULT_LLM_BASE_URL=http://localhost:11434

# DEFAULT_LLM_PROVIDER=gemini
# DEFAULT_LLM_MODEL=gemini-2.5-flash
# DEFAULT_LLM_API_KEY=your-gemini-key
```

### Token budget calculator

```
User nhập: "Build a todo app"

ước tính tokens:
  PO:    ~5K tokens  (viết PRD)
  PM:    ~3K tokens  (chia tasks)
  BA:    ~8K tokens  (viết spec)
  SA:    ~5K tokens  (architecture)
  FE:    ~20K tokens (viết NextJS code)
  BE:    ~15K tokens (viết FastAPI code)
  UIUX:  ~3K tokens  (review)
  Sec:   ~5K tokens  (security check)
  QA:    ~10K tokens (viết tests)
  DevOps:~5K tokens  (docker + CI)
  TL:    ~2K tokens  (final review)
  ─────────────────
  Total: ~81K tokens/task
  
  Với MiMo: ~$0.08/task
  Với Ollama: $0/task
  Với Gemini Free: $0/task (giới hạn 15 RPM)
```

---

## Phase 3: Production Deploy

### Infrastructure

```yaml
# docker-compose.prod.yml
services:
  nginx:
    image: nginx:alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - /etc/letsencrypt:/etc/letsencrypt

  redis:
    image: redis:7-alpine
    volumes: [redis-data:/data]
    command: redis-server --appendonly yes

  # 11 agents
  po:
    build: ./agents/po
    env_file: .env
    depends_on: [redis]
    restart: always
  # ... 10 agents còn lại

  web:
    build: ./web
    ports: ["3000:3000"]
    depends_on: [po, pm, ba]
    restart: always
```

### Deploy script

```bash
# deploy.sh
#!/bin/bash
git pull
docker-compose -f docker-compose.prod.yml build
docker-compose -f docker-compose.prod.yml up -d
echo "Deployed! Check https://opencrew.yourdomain.com"
```

---

## Phase 4: Community & Paper

### GitHub Milestones

| Milestone | Target | Content |
|---|---|---|
| v1.0.0 | Week 1 | Phase 1: build.py + generated code |
| v1.1.0 | Week 3 | Phase 2: LLM integration, agents chạy thật |
| v1.2.0 | Week 5 | Free model support, one-command setup |
| v2.0.0 | Week 8 | Production deploy, monitoring, logs |

### Marketing plan

| Channel | Action | Khi nào |
|---|---|---|
| GitHub | README đẹp, examples, docs | v1.0.0 |
| Reddit r/LocalLLaMA | Post demo video | v1.1.0 |
| Reddit r/MachineLearning | Technical post | v1.2.0 |
| Twitter/X | Thread + video demo | v1.0.0 |
| HuggingFace | Upload model configs | v1.2.0 |
| awesome-ai-agents | PR to add OpenCrew | v1.1.0 |

### Academic Paper

**Title:** "OpenCrew: A Protocol-First Multi-Agent System for Autonomous Software Development"

**Novelty:**
1. 11-role SDLC coverage (most comprehensive)
2. A2A + MCP protocol integration (first for software teams)
3. Debate-based conflict resolution
4. Token budget analysis across model tiers

**Target:** NeurIPS 2026 Workshop / ICLR 2027 Workshop

---

## Token Consumption Analysis

### Chi phí theo model

| Model | Cost/1K tokens | Cost/task (~81K) | Cost/100 tasks | Cost/1000 tasks |
|---|---|---|---|---|
| Ollama (local) | $0 | $0 | $0 | $0 |
| Gemini Flash (free) | $0 | $0 | $0 | $0* |
| Qwen (free tier) | $0 | $0 | $0 | $0* |
| MiMo v2.5 Pro | $0.001 | $0.08 | $8 | $80 |
| GPT-4o Mini | $0.00015 | $0.012 | $1.2 | $12 |
| Claude 3.5 Sonnet | $0.003 | $0.24 | $24 | $240 |
| GPT-4o | $0.005 | $0.41 | $41 | $410 |

*Free tier có rate limit

### Kết luận

```
Người dùng bình thường:
  → Dùng Ollama (local) hoặc Gemini Free
  → Chi phí: $0
  → Chất lượng: đủ dùng cho task đơn giản

Người dùng chuyên nghiệp:
  → Dùng MiMo hoặc GPT-4o Mini
  → Chi phí: $0.01 - $0.08 per task
  → Chất lượng: tốt cho production

Người dùng enterprise:
  → Dùng Claude 3.5 / GPT-4o cho critical agents
  → Dùng MiMo cho routine agents
  → Chi phí: $0.10 - $0.50 per task
  → Chất lượng: xuất sắc
```

---

## Checklist Phase 2

- [ ] `shared/llm_client.py` — multi-provider LLM client
- [ ] `shared/agent_loop.py` — autonomous agent loop
- [ ] `shared/tool_registry.py` — MCP tool loader
- [ ] `agents/*/config.yaml` — per-agent config
- [ ] `setup.py` — one-command setup wizard
- [ ] `.env.example` — template with all options
- [ ] `docker-compose.yml` — all services
- [ ] `docker-compose.prod.yml` — production config
- [ ] Free model support (Ollama, Gemini, Qwen)
- [ ] Token budget calculator
- [ ] Test: 3 agents (PO→PM→BA) chạy thật
- [ ] Test: 11 agents full pipeline
- [ ] README.md update
- [ ] GitHub release v1.1.0
