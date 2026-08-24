# Deployment Checklist — Vercel (frontend) + Render free (backend)

Progress against [the plan](.cursor/plans/deploy_vercel_and_render_e5eb5787.plan.md).
Goal: a public URL where someone can upload a CSV and get an analysis, running
entirely on free tiers, degrading gracefully when the free instance sleeps.

## Phase 1 — Backend deployment files

- [x] `backend/requirements.txt` mirroring the runtime deps in `backend/pyproject.toml`
      (Render's Python runtime detection needs it; no `pip install -e .` required
      because `app.agent.skills.load_skill` reads markdown relative to `__file__`)
- [x] `backend/.python-version` pinned to `3.12`
- [x] Root `render.yaml` blueprint: `rootDir: backend`, `plan: free`,
      `buildCommand: pip install -r requirements.txt`,
      `startCommand: uvicorn app.main:app --host 0.0.0.0 --port $PORT --workers 1`,
      `healthCheckPath: /health`
- [x] Confirm `--workers 1` is in the start command — the `SessionManager`
      singleton holds sessions, SSE queues and the analysis task in memory, so a
      second worker would 404 on `/sessions/{id}/stream`

## Phase 2 — Backend code changes for the free tier

- [x] `cors_origin_regex` setting in `backend/app/config.py`, passed as
      `allow_origin_regex` in `backend/app/main.py` so per-commit Vercel preview
      hostnames are allowed
- [x] `max_upload_mb` setting (default 15) enforced in
      `backend/app/api/datasets.py` via a chunked, byte-counting copy that
      unlinks the partial file and returns 413 — the main OOM guard, since every
      `execute_step` reopens an in-memory DuckDB over the whole CSV
- [x] `DATA_DIR=/tmp/data` set explicitly to signal that storage is ephemeral
- [x] `backend/tests/test_datasets.py` covers the 413, the cleanup of the
      partial write, and a normal upload

## Phase 3 — Frontend resilience

- [x] `GET /health` warm-up ping on mount with a "waking up the analysis server"
      state, and one retry on the first request (free instances take ~1 min to
      spin back up)
- [x] Inbound keepalive: poll `GET /sessions/{id}` every ~5 min while an analysis
      is running, so outbound-only SSE heartbeats don't let Render spin the
      instance down mid-run
- [x] 404 on `/sessions/{id}` or `/stream` treated as "server restarted": clear
      dataset/session state and prompt for a re-upload instead of hanging on a
      dead `EventSource` (`SessionGoneError` in `frontend/src/lib/api.ts`)
- [x] `frontend/.env.example` documenting `NEXT_PUBLIC_API_URL`

## Phase 4 — Provisioning

Everything below happens in the Render and Vercel dashboards.

- [ ] Branch pushed
- [ ] Render service created from the blueprint (New > Blueprint), `GROQ_API_KEY`
      filled in
- [ ] `https://<service>.onrender.com/health` returns `{"status":"ok"}`
- [ ] Vercel project imported with Root Directory `frontend`, install `npm ci`
- [ ] `NEXT_PUBLIC_API_URL` set on Vercel for Production, Preview and Development
- [ ] `CORS_ORIGINS` set to the Vercel production URL and `CORS_ORIGIN_REGEX` to
      the preview pattern on Render

## Phase 5 — Verification

- [ ] Upload `sample-data/04-01-Financial Sample Data.csv` from the deployed frontend
- [ ] Ask a question; SSE events appear in the activity feed
- [ ] Report, charts and evidence all render
- [ ] Oversized CSV rejected with a clear 413 message rather than killing the instance
- [ ] Cold start path checked: leave it idle 15+ min, reload, confirm the
      waking-up state and a successful re-upload
- [x] `README.md` deployment section updated with both hosts, the env var table,
      the `--workers 1` requirement and the free-tier caveats
- [x] Local checks green: 138 backend tests pass, `tsc --noEmit` and
      `next lint` clean, `next build` succeeds
