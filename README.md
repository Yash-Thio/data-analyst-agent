# Autonomous Data Analyst

Upload a CSV, ask analytical questions, and get **explainable** answers backed by SQL evidence — powered by a LangGraph agent (not a chatbot).

## Architecture

- **Frontend:** Next.js + TypeScript + Tailwind + Recharts
- **Backend:** FastAPI + LangGraph + DuckDB + Pandas
- **LLM:** Configurable Groq / OpenAI / Anthropic via environment variables (default: Groq)

The agent follows explicit states:

`profile → interpret → plan → execute → evaluate → charts → build_explanation`

Every claim in the final answer cites evidence (exact SQL + result rows + computed metrics).

## Quick start

### 1. Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# Edit .env and set GROQ_API_KEY
uvicorn app.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
cp .env.local.example .env.local
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

### 3. Try it

Upload [`sample-data/sales.csv`](sample-data/sales.csv) and ask:

> Why did revenue drop in Q3?

## Environment variables

| Variable | Description |
|----------|-------------|
| `LLM_PROVIDER` | `groq` (default), `openai`, or `anthropic` |
| `GROQ_API_KEY` | Required when provider is groq |
| `GROQ_MODEL` | Default `llama-3.3-70b-versatile` |
| `GROQ_BASE_URL` | Default `https://api.groq.com/openai/v1` |
| `OPENAI_API_KEY` | Required when provider is openai |
| `OPENAI_MODEL` | Default `gpt-4o` |
| `ANTHROPIC_API_KEY` | Required when provider is anthropic |
| `ANTHROPIC_MODEL` | Default Claude Sonnet |
| `DATA_DIR` | Local storage root (default `../data`) |
| `CORS_ORIGINS` | Allowed frontend origins |
| `NEXT_PUBLIC_API_URL` | Backend URL for the frontend |

**Never hardcode API keys.** Store them only in `.env` files (gitignored).

## API

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/datasets` | Upload CSV |
| `GET` | `/datasets/{id}` | Dataset profile |
| `POST` | `/sessions` | Create analysis session |
| `POST` | `/sessions/{id}/ask` | Start agent run |
| `GET` | `/sessions/{id}/stream` | SSE agent events |
| `GET` | `/sessions/{id}` | Full session + explanation |

## Explainability

Final output is a structured `Explanation`:

- **Summary** — short direct answer
- **Claims** — numbered conclusions, each linked to evidence IDs
- **Evidence** — exact SQL, result preview, computed metrics
- **Reasoning trace** — auto-built from graph execution
- **Limitations** — period definitions, data gaps, assumptions

Click a claim citation in the UI to inspect the SQL and data that support it.
