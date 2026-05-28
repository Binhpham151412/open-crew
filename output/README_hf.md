---
title: OpenCrew
emoji: 🤖
colorFrom: blue
colorTo: purple
sdk: docker
pinned: true
license: mit
---

# OpenCrew

> 11 AI agents form a software team. You write requirements. They build software.

## Quick Start

1. Open this Space
2. Go to **Tasks** page
3. Submit a task (e.g., "Build a todo app with authentication")
4. Watch the agents work in real-time

## Architecture

```
User → PO → PM → BA + SA → FE + BE → UIUX + Security → QA → DevOps → TechLead → User
```

| Agent | Role | Port |
|---|---|---|
| PO | Product Owner - writes PRD | 8000 |
| PM | Project Manager - splits tasks | 8001 |
| BA | Business Analyst - writes specs | 8002 |
| SA | Solution Architect - designs system | 8003 |
| Frontend Dev | NextJS implementation | 8004 |
| Backend Dev | FastAPI implementation | 8005 |
| UIUX Reviewer | Accessibility & UX review | 8006 |
| Security Reviewer | OWASP Top 10 check | 8007 |
| QA | Testing (pytest + Playwright) | 8008 |
| DevOps | Docker & CI/CD | 8009 |
| TechLead | Final gate & sign-off | 8010 |

## Environment Variables

Set these in Space Settings → Repository Secrets:

| Variable | Required | Description |
|---|---|---|
| `MIMO_API_KEY` | Yes | API key for MiMo LLM |
| `MIMO_BASE_URL` | No | LLM endpoint (default: Xiaomi) |
| `MIMO_MODEL` | No | Model name (default: mimo-v2.5-pro) |
| `GITHUB_TOKEN` | No | For agents to commit code |

## Tech Stack

- **Backend**: Python 3.11, FastAPI, Redis
- **Frontend**: Next.js 14, React 18, Tailwind CSS
- **Protocols**: A2A (agent-to-agent), MCP (model context)
- **LLM**: MiMo v2.5 Pro (OpenAI-compatible API)

## License

MIT
