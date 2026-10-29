# ai-business-operations-agent

Ek **read-only Agentic AI** jo business request samajhta hai, tools se database ka data padhta hai, Python se calculation karta hai, aur **structured report + data sources** return karta hai.

> Example: *"Prepare a sales report for this month and identify the products with declining sales."*

**Stack:** Python · LangGraph · FastAPI · PostgreSQL (SQLAlchemy) · pytest · LLM tool calling (OpenAI / Anthropic / Gemini)

## Architecture

```
Request ─▶ FastAPI ─▶ AgentService ─▶ LangGraph
                                       │
              ┌────────────────────────┴───────────────────────┐
              ▼                                                │
        [agent]  LLM (OpenAI|Anthropic|Gemini|mock) decides tool calls
              │ tool_calls                                      │
              ▼                                                │
        [tools]  validate args → (approval?) → execute → log ───┘
              │ submit_report (Pydantic-validated)
              ▼
     BusinessReport + data_sources (system-generated from tool logs)
```

| Feature | Kahan hai |
|---|---|
| Tool calling (3 providers) | `app/llm/*_client.py`, common interface `app/llm/base.py` |
| Structured outputs | `submit_report` tool + Pydantic `app/schemas.py` |
| State management | LangGraph `AgentState` + runs DB me persist (`agent_runs`) |
| Error handling | tool errors LLM ko wapas jaate hain, LLM retry/backoff, max-iterations guard, invalid report retry |
| Human approval | write tools `requires_approval=True`; graph pause → `POST /runs/{id}/approval` |
| Tool execution logs | `tool_logs` table + `GET /runs/{id}/logs` (args, status, duration, sources) |
| Evaluation tests | `tests/test_evals.py` (ground-truth, destructive request, prompt injection) |

### Safety design
- **Read-only by default**: sirf read tools registered hain; read tools PostgreSQL me `SET TRANSACTION READ ONLY` ke andar chalte hain.
- LLM kabhi **SQL nahi likhta** – sirf pre-written, parameterised tools call karta hai.
- Saari **calculations Python me** hoti hain (`app/tools/analytics.py`), LLM arithmetic nahi karta.
- **Data sources system attach karta hai** (actual tool logs se) – LLM fake source nahi bana sakta.
- Write action (optional): `ENABLE_WRITE_TOOLS=true` karne par sirf `create_restock_draft` (draft row) milta hai, wo bhi **human approval ke baad**.

## Quick start (bina API key ke)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # LLM_PROVIDER=mock default hai

# Option A: Docker (PostgreSQL + API)
docker compose up --build         # http://localhost:8000/docs

# Option B: local
docker compose up -d db
python -m app.seed --reset        # demo data (120 din)
uvicorn app.main:app --reload
# ya CLI:
python -m app.cli "Prepare a sales report for this month and identify the products with declining sales."
```

## Web UI

Server chalane ke baad browser me **http://localhost:8000** kholo.
- Provider chuno: Demo (no key) / OpenAI / Anthropic / Gemini
- API key aur (optional) model name UI me paste karo – key sirf us request ke liye memory me use hoti hai, DB/logs me save nahi hoti
- Request likho ya example chip dabao → report, KPI cards, declining products table, data sources, tool execution log
- Human approval card, "Copy markdown" aur "Download .md" bhi hai
- Swagger docs: http://localhost:8000/docs

> Public internet par deploy karo to HTTPS zaroor lagao, warna API key plain HTTP par jayegi.

## Screenshots

Sab screenshots **Demo mode** (bina API key ke) me liye gaye hain, taaki koi bhi repo clone karke wahi UI dekh sake.

### 1. Home – request likho, model chuno
![Home](docs/screenshots/01-home.png)

### 2. LLM settings – OpenAI / Anthropic / Gemini ki key UI me
![LLM settings](docs/screenshots/02-llm-settings.png)

### 3. Sales report – KPI cards, declining products, insights, data sources
![Sales report](docs/screenshots/03-sales-report.png)

### 4. Tool execution log – har tool ke arguments, result aur duration
![Tool execution log](docs/screenshots/04-tool-log.png)

### 5. Human approval – write action se pehle agent ruk jaata hai
![Approval required](docs/screenshots/05-approval-required.png)

### 6. Approve ke baad – draft bana, aur log me `approved` dikhta hai
![Approved and logged](docs/screenshots/06-approved-and-logged.png)

> Screenshots script se bante hain (fixed demo date 2026-10-29, isliye numbers hamesha same). UI badalne ke baad dobara banao:
> ```bash
> pip install -r requirements-dev.txt && playwright install chromium
> python scripts/capture_screenshots.py     # PostgreSQL ya API key ki zarurat nahi
> ```
> Screenshots 5 aur 6 me ek chhota scripted model use hota hai (mock model kabhi write action nahi maangta); approval gate, DB write aur tool log asli hain.

## Real LLM use karna (API keys)

`.env` me key daalo aur provider chuno:

```env
LLM_PROVIDER=openai        # openai | anthropic | gemini | mock
OPENAI_API_KEY=sk-...        OPENAI_MODEL=gpt-4o
ANTHROPIC_API_KEY=sk-ant-... ANTHROPIC_MODEL=claude-sonnet-5-5
GEMINI_API_KEY=...           GEMINI_MODEL=gemini-2.5-flash
```
Har request me provider override bhi kar sakte ho: `{"request": "...", "provider": "anthropic"}`.
Model names `.env` se badalte hain, code change nahi chahiye.

## API

```bash
curl -X POST localhost:8000/runs -H 'content-type: application/json' \
  -d '{"request":"Prepare a sales report for this month and identify the products with declining sales.","provider":"openai"}'

GET  /runs/{id}            # status, report (JSON + markdown), pending approvals
GET  /runs/{id}/logs       # tool execution logs
POST /runs/{id}/approval   # {"approve": true|false}  (jab status = awaiting_approval)
GET  /tools                # available tools (read_only / requires_approval)
GET  /health
```

## Tests

```bash
pytest -q        # SQLite in-memory + scripted/mocked LLM: no API key, no network
```
Tests me: tools (hand-computed numbers), LangGraph flows (retry, errors, max-iterations, approval approve/reject), LLM message converters, API, aur evals.

## Naya tool add karna
1. `app/tools/sales.py` me Pydantic args model + handler likho (`ToolResult(data, sources)`).
2. `app/tools/registry.py` me `ToolDef(...)` register karo. Write tool ho to `mutating=True, requires_approval=True`.
3. `tests/` me test add karo.

## Notes
- `DATABASE_URL=postgresql+psycopg://user:pass@host:5432/db`
- Tables abhi `create_all` se bante hain; production me Alembic migrations add karo.
- OpenAI/Anthropic/Gemini clients official SDK tool-calling format par bane hain aur unke message converters unit-tested hain; live calls ke liye apni keys se ek baar chala ke verify karna.
