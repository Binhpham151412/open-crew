# 🤖 OPENHAND — Multi-Agent AI System Blueprint
> **Version:** 1.0.0 — Kim chỉ nam phát triển  
> **Author:** Personal AI Workspace  
> **Status:** Foundation Document — DO NOT MODIFY without versioning  
> **AI Coding Target:** Mistral Codestral / Qwen3-Coder via OpenRouter  

---

## 📌 TL;DR — Một câu mô tả

> **OpenCrew** là một hệ thống multi-agent AI cá nhân, nơi mỗi agent đóng vai một chuyên gia (BA, Dev, UIUX, Tester, DevOps, TechLead, PM...), kết nối với nhau và với các IDE/tool thực tế qua MCP protocol, được điều phối bởi một Orchestrator trung tâm — cho phép bạn chỉ cần ra lệnh một lần và cả đội làm việc cho bạn.

---

## 🎯 Vision & Goals

### Vision
Xây dựng một "virtual software team" cá nhân, hoạt động 24/7, không tốn lương, có thể được gọi bất cứ lúc nào để hỗ trợ toàn bộ vòng đời phát triển phần mềm — từ ý tưởng đến deployment.

### Goals
- **G1:** Mỗi agent có chuyên môn riêng, không bị "jack of all trades"
- **G2:** Agents giao tiếp với nhau qua MCP protocol — chuẩn hóa, mở rộng được
- **G3:** Agents kết nối trực tiếp với tools thực tế (OpenCode, Figma/OpenDesign, GitHub,...)
- **G4:** Chi phí vận hành tối thiểu — ưu tiên free/cheap models qua OpenRouter
- **G5:** Bạn luôn là người ra lệnh và approve cuối cùng — không để agent tự chạy 100%
- **G6:** Deploy trên HuggingFace Spaces — không cần server riêng

---

## 🏗️ System Architecture Overview

```
╔══════════════════════════════════════════════════════════════════╗
║                        BẠN (Commander)                          ║
║              Ra lệnh qua Chat UI / Terminal / API               ║
╚══════════════════════════╦═══════════════════════════════════════╝
                           ║ HTTP / MCP
╔══════════════════════════▼═══════════════════════════════════════╗
║                   ORCHESTRATOR AGENT (PM)                       ║
║  - Nhận lệnh từ bạn                                             ║
║  - Phân tích intent → routing đến đúng agent                   ║
║  - Tổng hợp output từ nhiều agents                              ║
║  - Báo cáo kết quả lại cho bạn                                  ║
║  - Model: Claude Sonnet / DeepSeek-V3 (judgment cao)           ║
╚══╦════════╦══════════╦════════════╦═══════════╦══════════════════╝
   ║        ║          ║            ║           ║
   ║ MCP    ║ MCP      ║ MCP        ║ MCP       ║ MCP
╔══▼══╗  ╔══▼══╗  ╔════▼════╗  ╔═══▼═══╗  ╔════▼════╗
║ BA  ║  ║UIUX ║  ║ CODING  ║  ║TESTER ║  ║ DEVOPS  ║
║Agent║  ║Agent║  ║  Agent  ║  ║ Agent ║  ║  Agent  ║
╚══╦══╝  ╚══╦══╝  ╚════╦════╝  ╚═══╦═══╝  ╚════╦════╝
   ║        ║          ║            ║           ║
   ║ MCP    ║ MCP      ║ MCP        ║ MCP       ║ MCP
╔══▼══╗  ╔══▼══╗  ╔════▼════╗  ╔═══▼═══╗  ╔════▼════╗
║Docs ║  ║Figma║  ║OpenCode ║  ║ Test  ║  ║ GitHub  ║
║/Git ║  ║ /OD ║  ║  / IDE  ║  ║Runner ║  ║ Actions ║
╚═════╝  ╚═════╝  ╚═════════╝  ╚═══════╝  ╚═════════╝

                    ╔═══════════════════════╗
                    ║    MODEL ROUTER       ║
                    ║    OpenRouter API     ║
                    ║                       ║
                    ║ Qwen3-Coder (free)    ║
                    ║ DeepSeek-R1 (free)    ║
                    ║ Llama-3.3-70B (free)  ║
                    ║ Gemini Flash (rẻ)     ║
                    ║ Claude Sonnet (xịn)   ║
                    ╚═══════════════════════╝

                    ╔═══════════════════════╗
                    ║  SHARED ARTIFACT      ║
                    ║     STORE             ║
                    ║  (GitHub Repo / KV)   ║
                    ║ PRD, Designs, Code,   ║
                    ║ Test Results, Logs    ║
                    ╚═══════════════════════╝
```

---

## 👥 Agent Roster — Full Team

| Agent | Role | Chuyên môn | Model Recommended | Priority |
|-------|------|-----------|-------------------|----------|
| **Orchestrator** | PM / Dispatcher | Intent parsing, routing, summarizing | Claude Sonnet / DeepSeek-V3 | Phase 1 |
| **Coding Agent** | Senior Developer | Code review, suggest fixes, debug, refactor | DeepSeek-R1 / Qwen3-Coder | Phase 1 |
| **BA Agent** | Business Analyst | Requirements, user stories, PRD, acceptance criteria | Llama-3.3-70B | Phase 2 |
| **UIUX Agent** | UI/UX Designer | Design review, accessibility, UX patterns, component audit | Gemini Flash (multimodal) | Phase 2 |
| **Tester Agent** | QA Engineer | Test cases, test scripts, bug reports, coverage analysis | Qwen3-32B | Phase 2 |
| **DevOps Agent** | DevOps Engineer | CI/CD config, Dockerfile, deployment, infra review | DeepSeek-V3 | Phase 3 |
| **TechLead Agent** | Tech Lead | Architecture review, PR review, tech debt, ADR | Claude Sonnet | Phase 3 |
| **Security Agent** | Security Reviewer | Vuln scan, OWASP checklist, secret detection | DeepSeek-R1 | Phase 4 |
| **Docs Agent** | Technical Writer | README, API docs, changelog, wiki | Llama-3.3-70B | Phase 4 |

---

## 🔌 MCP Connection Map

```
Orchestrator ←→ ALL agents (hub-and-spoke)

BA Agent        ←→ UIUX Agent       (design matches requirements?)
BA Agent        ←→ Tester Agent     (acceptance criteria → test cases)
BA Agent        ←→ TechLead Agent   (feasibility check)

UIUX Agent      ←→ Coding Agent     (design token handoff)
UIUX Agent      ←→ Figma/OD MCP     (read + write design files)

Coding Agent    ←→ OpenCode MCP     (read files, run commands, apply fixes)
Coding Agent    ←→ GitHub MCP       (PR, diff, branch)
Coding Agent    ←→ Tester Agent     (run test after fix)

Tester Agent    ←→ GitHub MCP       (create issues)
Tester Agent    ←→ Test Runner MCP  (execute tests, get results)

DevOps Agent    ←→ GitHub Actions   (trigger pipelines)
DevOps Agent    ←→ Docker MCP       (build, inspect images)

TechLead Agent  ←→ Coding Agent     (review code)
TechLead Agent  ←→ DevOps Agent     (review infra)
```

---

## 📦 Final Output — Hệ thống trông như thế nào khi hoàn chỉnh

### Từ góc nhìn của bạn (User Experience)

```
Bạn gõ:
"Review PR #42, check code quality, check test coverage, 
 nếu ổn thì merge, nếu không thì comment lên PR"

Hệ thống tự động:
1. Orchestrator nhận lệnh → parse intent
2. Coding Agent đọc PR diff qua GitHub MCP
3. Tester Agent check test coverage report
4. TechLead Agent review architecture impact
5. Tổng hợp → nếu pass: merge PR
              → nếu fail: comment chi tiết lên PR
6. Orchestrator báo cáo lại bạn: "PR #42 đã được merge" 
   hoặc "PR #42 có 3 vấn đề, đã comment lên GitHub"
```

```
Bạn gõ:
"Tôi muốn thêm feature login bằng Google OAuth"

Hệ thống tự động:
1. BA Agent viết user story + acceptance criteria
2. UIUX Agent suggest UI pattern cho OAuth button
3. Coding Agent suggest implementation approach
4. Tester Agent tạo test cases
5. Orchestrator tổng hợp → trả về bạn full plan
```

### Cấu trúc thư mục project

```
opencrew/
├── orchestrator/          # Orchestrator Agent (HF Space)
│   ├── app.py
│   ├── mcp_server.py
│   └── prompts/
│       └── system.md
├── agents/
│   ├── coding/            # Coding Agent (HF Space)
│   │   ├── app.py
│   │   ├── mcp_server.py
│   │   └── prompts/system.md
│   ├── ba/
│   ├── uiux/
│   ├── tester/
│   ├── devops/
│   └── techlead/
├── mcp-tools/             # MCP wrappers cho external tools
│   ├── opencode-mcp/      # Wrapper cho OpenCode
│   ├── figma-mcp/         # Wrapper cho Figma API
│   └── github-mcp/        # Wrapper cho GitHub API
├── shared/
│   ├── artifact-store/    # Shared context/state
│   ├── model-router/      # OpenRouter integration
│   └── utils/
├── infra/
│   ├── keep-alive/        # UptimeRobot config
│   └── hf-spaces/         # HF deployment configs
└── OPENHAND_BLUEPRINT.md  # File này
```

---

## 🗺️ Implementation Roadmap

---

### ✅ PHASE 0 — Foundation (Tuần 1)
**Mục tiêu:** Setup infrastructure cơ bản, đảm bảo mọi thứ kết nối được

#### 0.1 OpenRouter Integration
```
Setup account OpenRouter
Test gọi Qwen3-Coder, DeepSeek-R1, Llama-3.3-70B
Viết model-router util: chọn model theo agent type
```

#### 0.2 HuggingFace Spaces Setup
```
Tạo 1 HF Space test (CPU, Python/Gradio hoặc FastAPI)
Deploy simple "hello world" MCP server
Test keep-alive với UptimeRobot free
```

#### 0.3 Shared Artifact Store
```
Tạo private GitHub repo: opencrew-workspace
Cấu trúc thư mục: /prd, /designs, /code-context, /test-results
Agents sẽ read/write qua GitHub API
```

**→ Prompt cho AI code Phase 0:**
```
"Tạo một FastAPI server đơn giản deploy được trên HuggingFace Spaces.
Server này là MCP server với 2 endpoints:
- POST /mcp/call : nhận tool_name + params, gọi OpenRouter API với model được config
- GET /health : health check để keep-alive ping

OpenRouter base_url: https://openrouter.ai/api/v1
Hỗ trợ các model: qwen/qwen3-coder, deepseek/deepseek-r1, meta-llama/llama-3.3-70b
Config model qua env var AGENT_MODEL
Include requirements.txt và README.md để deploy lên HF Spaces"
```

---

### 🔨 PHASE 1 — Core Agents (Tuần 2-3)
**Mục tiêu:** Build 2 agents quan trọng nhất: Orchestrator + Coding Agent

#### 1.1 Coding Agent

**Capabilities:**
- Nhận code context (file content, error message, git diff)
- Review code quality
- Suggest fixes với explanation
- Gọi OpenCode MCP để apply fixes
- Chạy lại test sau khi fix

**System Prompt Core:**
```markdown
Bạn là một Senior Software Engineer với 10 năm kinh nghiệm.
Chuyên môn: code review, debugging, refactoring, performance optimization.
Ngôn ngữ: Java, JavaScript/TypeScript, Python.
Khi review code, bạn LUÔN:
1. Chỉ ra vấn đề cụ thể với line number
2. Giải thích TẠI SAO đó là vấn đề
3. Đưa ra code fix cụ thể
4. Ưu tiên: Security > Correctness > Performance > Style
Bạn KHÔNG tự apply fix mà không được approve.
```

**→ Prompt cho AI code Coding Agent:**
```
"Tạo một MCP Server cho Coding Agent với các tools sau:

Tools:
1. review_code(file_path, code_content, language) 
   → trả về list issues với severity, line_number, explanation, suggested_fix

2. explain_error(error_message, code_context)
   → trả về root cause analysis và fix steps

3. suggest_refactor(code_content, goals)
   → goals: ['readability', 'performance', 'testability']
   → trả về refactored code + explanation

4. apply_fix(file_path, original_code, fixed_code)
   → gọi OpenCode MCP để apply thay đổi
   → trả về success/failure + diff

Stack: FastAPI + Python
Model: qwen/qwen3-coder qua OpenRouter
System prompt: [dán system prompt ở trên vào đây]
MCP protocol: JSON-RPC 2.0 over HTTP
Include error handling, logging, và unit tests"
```

#### 1.2 Orchestrator Agent

**Capabilities:**
- Parse intent từ natural language command của bạn
- Route task đến đúng agent(s)
- Manage conversation context
- Aggregate results
- Human-in-the-loop: hỏi bạn khi không chắc

**→ Prompt cho AI code Orchestrator:**
```
"Tạo Orchestrator Agent với chức năng:

1. Intent Parser: phân tích lệnh của user thành:
   {
     primary_agent: string,      // agent chính cần gọi
     secondary_agents: string[], // agents phụ nếu cần
     task_type: string,          // 'review' | 'create' | 'fix' | 'analyze'
     requires_approval: boolean, // có cần user approve trước khi execute?
     context_needed: string[]    // những info cần thu thập thêm
   }

2. Agent Router: gọi đúng agent(s) theo thứ tự, pass context giữa agents

3. Result Aggregator: tổng hợp output từ nhiều agents thành 1 report dễ đọc

4. Approval Gate: nếu requires_approval=true, 
   dừng lại và hỏi user trước khi execute

UI: Simple Gradio chat interface
Model: deepseek/deepseek-v3 qua OpenRouter
Agents config: đọc từ agents.yaml (tên, URL, capabilities)
Include agents.yaml template với Coding Agent"
```

---

### 🎨 PHASE 2 — Design & Business Agents (Tuần 4-5)
**Mục tiêu:** Add BA Agent + UIUX Agent

#### 2.1 BA Agent

**Capabilities:**
- Viết User Stories từ mô tả tính năng
- Tạo Acceptance Criteria (Given/When/Then format)
- Viết PRD (Product Requirements Document)
- Review design/code có match requirements không
- Connect với UIUX Agent để validate viewpoints

**→ Prompt cho AI code BA Agent:**
```
"Tạo BA Agent MCP Server với tools:

1. write_user_story(feature_description)
   → format: As a [user], I want [goal], So that [benefit]
   → include acceptance criteria (Given/When/Then)

2. create_prd(feature_list, project_context)
   → tạo PRD document với sections:
     Overview, User Stories, Functional Requirements, 
     Non-functional Requirements, Out of Scope

3. review_design_vs_requirements(prd_content, design_description)
   → check xem design có cover hết requirements không
   → trả về: covered[], missing[], ambiguous[]

4. define_viewpoints(feature, stakeholders)
   → định nghĩa các viewpoints từ góc độ từng stakeholder
   → format output để UIUX Agent và Tester Agent có thể đọc

Output format: Markdown
Model: meta-llama/llama-3.3-70b qua OpenRouter
Include tool để save PRD lên GitHub Artifact Store"
```

#### 2.2 UIUX Agent

**Capabilities:**
- Review design file (từ Figma/OpenDesign)
- Check WCAG accessibility (contrast ratio, font size,...)
- Check consistency với design system
- Suggest improvements
- Gọi Figma MCP để apply basic fixes

**→ Prompt cho AI code UIUX Agent:**
```
"Tạo UIUX Agent MCP Server với tools:

1. review_design(design_json, design_system_tokens)
   → check: contrast_ratio, spacing_consistency, 
             typography_scale, component_naming, ux_patterns
   → trả về issues list với severity + fix suggestion

2. check_accessibility(design_json)
   → WCAG 2.1 AA compliance check
   → trả về: pass[], fail[], warnings[]

3. review_ux_flow(screens_list, user_story)
   → check xem flow có match user story không
   → identify missing states (empty, loading, error)

4. apply_design_fix(figma_file_id, fix_instructions)
   → gọi Figma API để apply basic fixes:
     - Thay màu sắc
     - Update text
     - Fix spacing/padding
   → trả về before/after diff

Model: google/gemini-flash-1.5 (multimodal, đọc được ảnh design)
Include Figma API integration với env var FIGMA_TOKEN
Note: apply_design_fix chỉ thực thi khi được user approve"
```

---

### 🧪 PHASE 3 — Testing & DevOps (Tuần 6-7)
**Mục tiêu:** Add Tester Agent + DevOps Agent

#### 3.1 Tester Agent

**→ Prompt cho AI code Tester Agent:**
```
"Tạo Tester Agent MCP Server với tools:

1. generate_test_cases(user_story, acceptance_criteria)
   → tạo test cases theo format: 
     ID, Title, Preconditions, Steps, Expected Result, Priority

2. write_test_script(test_cases, language, framework)
   → language: javascript/python/java
   → framework: jest/pytest/junit
   → tạo executable test code

3. analyze_coverage(test_results_json, source_files)
   → phân tích coverage report
   → highlight uncovered critical paths

4. create_bug_report(issue_description, steps_to_reproduce, environment)
   → tạo bug report markdown
   → gọi GitHub MCP để tạo Issue

Model: qwen/qwen3-32b qua OpenRouter"
```

#### 3.2 DevOps Agent

**→ Prompt cho AI code DevOps Agent:**
```
"Tạo DevOps Agent MCP Server với tools:

1. review_dockerfile(dockerfile_content)
   → check: security best practices, layer optimization, 
             base image recommendations

2. review_cicd(workflow_yaml, project_type)
   → check GitHub Actions / GitLab CI config
   → suggest improvements cho speed và security

3. generate_deployment_config(project_info, target_env)
   → target_env: docker-compose / kubernetes / hf-spaces
   → tạo deployment config files

4. check_infra_cost(resources_config)
   → estimate monthly cost cho config đã cho
   → suggest cost optimization

Model: deepseek/deepseek-v3 qua OpenRouter"
```

---

### 🎓 PHASE 4 — TechLead + Polish (Tuần 8-9)

#### 4.1 TechLead Agent

**→ Prompt cho AI code TechLead Agent:**
```
"Tạo TechLead Agent MCP Server với tools:

1. review_architecture(diagram_or_description, requirements)
   → evaluate: scalability, maintainability, security, performance
   → suggest improvements với trade-off analysis

2. review_pr(pr_diff, pr_description, coding_standards)
   → full PR review: logic, style, tests, docs
   → output format: GitHub PR review với inline comments

3. create_adr(decision_title, context, options_considered, decision_made)
   → tạo Architecture Decision Record (ADR) document

4. assess_tech_debt(codebase_summary, age_of_code)
   → estimate tech debt
   → prioritize refactoring tasks

Model: claude-sonnet (reasoning cao nhất trong team)
Note: đây là agent dùng model đắt nhất — chỉ gọi khi thực sự cần"
```

#### 4.2 End-to-End Integration Test
```
Test full workflow:
"Tôi muốn add feature X"
→ BA viết PRD
→ UIUX suggest mockup
→ Coding suggest implementation
→ Tester tạo test cases
→ TechLead review plan
→ Orchestrator tổng hợp → trả về bạn full package
```

---

### 🚀 PHASE 5 — Production Ready (Tuần 10)

#### 5.1 Reliability
```
- UptimeRobot monitor tất cả HF Spaces
- Retry logic khi model timeout
- Fallback model chain (primary → secondary → tertiary)
- Error notifications qua Telegram Bot / Email
```

#### 5.2 Cost Optimization
```
- Token counting trước mỗi request
- Truncate context thông minh (chỉ gửi relevant parts)
- Cache kết quả review giống nhau
- Daily cost tracking dashboard
```

#### 5.3 Security
```
- API key rotation
- Rate limiting per agent
- Input sanitization
- Audit log mọi agent actions
```

**→ Prompt cho AI code Phase 5:**
```
"Tạo monitoring dashboard cho OpenCrew system:

1. Hiển thị status của tất cả agents (online/offline)
2. Hiển thị token usage per agent per day
3. Show recent actions log (agent, tool_called, result, timestamp)
4. Cost calculator: token_used × model_price = daily/monthly cost
5. Alert nếu 1 agent offline > 5 phút

Stack: Gradio hoặc simple HTML/JS
Deploy: HuggingFace Spaces
Data source: đọc từ GitHub repo opencrew-workspace/logs/"
```

---

## 🔧 Technical Specifications

### MCP Protocol

Tất cả agents expose MCP server theo spec:

```json
// Request format
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "review_code",
    "arguments": {
      "file_path": "src/auth.js",
      "code_content": "...",
      "language": "javascript"
    }
  },
  "id": "req-001"
}

// Response format
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Review result here..."
      }
    ]
  },
  "id": "req-001"
}
```

### OpenRouter Integration

```python
# model-router/router.py
AGENT_MODELS = {
    "coding":       "qwen/qwen3-coder:free",
    "ba":           "meta-llama/llama-3.3-70b-instruct:free",
    "uiux":         "google/gemini-flash-1.5",
    "tester":       "qwen/qwen3-32b:free",
    "devops":       "deepseek/deepseek-v3:free",
    "techlead":     "anthropic/claude-sonnet-4",
    "orchestrator": "deepseek/deepseek-v3:free",
    "fallback":     "meta-llama/llama-3.1-8b-instruct:free"
}

BASE_URL = "https://openrouter.ai/api/v1"
```

### HuggingFace Deployment

```yaml
# hf-spaces/coding-agent/README.md (HF Space config)
---
title: OpenCrew Coding Agent
emoji: 💻
colorFrom: blue
colorTo: purple
sdk: gradio
sdk_version: 4.0.0
app_file: app.py
pinned: false
---
```

### Keep-Alive Strategy

```
UptimeRobot (free) → ping mỗi 5 phút
Endpoints được ping:
  - https://[username]-opencrew-coding.hf.space/health
  - https://[username]-opencrew-ba.hf.space/health
  - https://[username]-opencrew-uiux.hf.space/health
  - ... (tất cả agents)
```

---

## 📊 Cost Estimation

| Agent | Model | Est. tokens/day | Est. cost/day |
|-------|-------|----------------|---------------|
| Orchestrator | DeepSeek-V3 free | 10K | $0 |
| Coding | Qwen3-Coder free | 30K | $0 |
| BA | Llama-3.3-70B free | 10K | $0 |
| UIUX | Gemini Flash | 10K | ~$0.01 |
| Tester | Qwen3-32B free | 10K | $0 |
| DevOps | DeepSeek-V3 free | 5K | $0 |
| TechLead | Claude Sonnet | 5K | ~$0.08 |

**Estimated total: < $3/month** cho heavy personal use.

---

## ⚠️ Constraints & Principles

### Golden Rules
1. **Bạn luôn là approver cuối** — không agent nào được execute destructive actions mà không có approval
2. **Fail loudly** — khi không chắc, agent phải hỏi, không được đoán
3. **Context is king** — agent thiếu context thì output kém, luôn feed đủ context
4. **One agent, one job** — không cho agent làm việc ngoài chuyên môn
5. **Free first** — luôn thử free model trước, chỉ escalate lên model xịn khi cần

### Known Limitations
- HF free tier: có thể slow cold start (~10-30s sau thời gian idle)
- Free models: rate limit, có thể không stable 100%
- Context window: free models thường giới hạn 32K-128K tokens
- MCP over HTTP: latency cao hơn local stdio (chấp nhận được cho personal use)

---

## 🚀 Quick Start Guide (sau khi build xong)

```bash
# 1. Clone repo
git clone https://github.com/you/opencrew
cd opencrew

# 2. Config API keys
cp .env.example .env
# Điền: OPENROUTER_API_KEY, GITHUB_TOKEN, FIGMA_TOKEN

# 3. Deploy lên HuggingFace (từng agent)
./infra/deploy.sh coding    # deploy Coding Agent
./infra/deploy.sh ba        # deploy BA Agent
./infra/deploy.sh uiux      # deploy UIUX Agent
./infra/deploy.sh orchestrator  # deploy Orchestrator (cuối cùng)

# 4. Config MCP trong OpenCode
# Thêm vào .opencode/config.json:
{
  "mcp_servers": {
    "opencrew-coding": {
      "url": "https://[you]-opencrew-coding.hf.space/mcp"
    }
  }
}

# 5. Test
# Trong OpenCode chat: "Review file src/auth.js"
# Orchestrator sẽ route đến Coding Agent tự động
```

---

## 📝 Changelog

| Version | Date | Note |
|---------|------|------|
| 1.0.0 | 2025 | Initial blueprint |

---

*"Build it once, use it forever."*
*— OpenCrew is your team that never sleeps.*
