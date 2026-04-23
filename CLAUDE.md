<<<<<<< HEAD
---
trigger: always_on
---

Use `uv` syntax for all Python operations in this project (Python 3.11).

## Virtual Environment Location

**CRITICAL**: The project's virtual environment (`.venv`) is located in the **PROJECT ROOT DIRECTORY** (`f:\opinion-system\.venv`), NOT in the `backend` folder.

- **DO NOT** move `.venv` to `backend/` or any other subdirectory
- **DO NOT** create a separate venv in `backend/`
- All Python operations must use the root `.venv`

## Python/Dependency Command Rules

- Sync lockfile dependencies:
  - `uv sync`
- Install/repair a package into the project venv:
  - `uv pip install --python .venv\Scripts\python.exe <package>`
- Run Python scripts without re-resolving environment:
  - `uv run --no-sync python <script.py>`

Do not use bare `pip install ...` or `python ...` directly unless explicitly required by workflow docs.

## CUDA Support for BERTopic

PyTorch CUDA 11.8 installation must still use `uv pip` targeting the project venv:

```powershell
uv pip install --python .venv\Scripts\python.exe --force-reinstall torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

After CUDA install, prefer `uv run --no-sync python ...` to avoid lockfile-driven environment mutation.

Examples:
- Backend server: `uv run --no-sync python backend/server.py`
- Other scripts: `uv run --no-sync python <your_script.py>`

See workflow: `/setup-cuda` for full instructions.
=======
# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

This repository is an opinion analysis system (舆情分析系统) with a Vue 3 frontend and a Python/Flask backend. It supports the classic data pipeline (merge → clean → filter → upload → analyze/report) and multiple retrieval modes, including GraphRAG.

The current product direction is visible in `README.md`: topic/project-based workflow, AI filtering, basic analysis, BERTopic topic analysis, report generation, and hybrid retrieval that combines GraphRAG, NormalRAG, and TagRAG.

## Common commands

### Backend setup and run

From the repo root:

```bash
uv sync
```

Note: `pyproject.toml` is backend-oriented, but some runtime dependencies and local workflows still rely on `backend/requirements.txt`. If `uv sync` is not sufficient for your environment, also use:

```bash
cd backend
uv pip install -r requirements.txt
```

Run the Flask backend:

```bash
cd backend
uv run python server.py
```

Default backend URL: `http://127.0.0.1:8000`

PyTorch CUDA is not fully managed by the default `uv sync`; `pyproject.toml` notes that CUDA 11.8 builds may need manual installation.

### Frontend setup and run

```bash
cd frontend
npm install
npm run dev
```

Other frontend commands:

```bash
cd frontend
npm run build
npm run preview
```

Default frontend URL: `http://localhost:5173`

### CLI pipeline commands

Most data processing workflows still exist as CLI entrypoints in `backend/main.py`, even though the web app is the main entry.

Core pipeline commands:

```bash
cd backend
uv run python main.py Merge --topic <topic> --date YYYY-MM-DD
uv run python main.py Clean --topic <topic> --date YYYY-MM-DD
uv run python main.py Filter --topic <topic> --date YYYY-MM-DD
uv run python main.py Upload --topic <topic> --date YYYY-MM-DD
uv run python main.py GraphSync --topic <topic> --date YYYY-MM-DD
uv run python main.py Fetch --topic <topic> --start YYYY-MM-DD --end YYYY-MM-DD
uv run python main.py Analyze --topic <topic> --start YYYY-MM-DD --end YYYY-MM-DD
uv run python main.py FetchAvailability --topic <topic>
uv run python main.py Query --json
```

Additional CLI commands currently present in `backend/main.py`:

```bash
cd backend
uv run python main.py FluidAnalysis --topic <topic> --start YYYY-MM-DD [--end YYYY-MM-DD]
uv run python main.py ContentAnalyze --topic <topic> --start YYYY-MM-DD --end YYYY-MM-DD
uv run python main.py Explain --topic <topic> --start YYYY-MM-DD --end YYYY-MM-DD
uv run python main.py Report --topic <topic> --start YYYY-MM-DD --end YYYY-MM-DD
uv run python main.py DataPipeline --topic <topic> --date YYYY-MM-DD
uv run python main.py AnalyzePipeline --topic <topic> --start YYYY-MM-DD --end YYYY-MM-DD
uv run python main.py TagVectorize --topic <topic>
uv run python main.py TagRetrieve --topic <topic> --query "<query>"
uv run python main.py RouterVectorize --topic <topic>
uv run python main.py RouterRetrieve --topic <topic> --query "<query>"
uv run python main.py EvalRAG --topic <topic>
```

Graph rebuild helpers:

```bash
cd backend
uv run python -m src.graph.build_graph --topic <topic> --date <date-or-range>
uv run python scripts/rebuild_graph.py
```

### Retrieval / GraphRAG debug scripts

There is no single formal test suite configured at the repo level. Validation is mostly done through targeted scripts and manual flows.

Useful script-style checks:

```bash
uv run python backend/scripts/test_routerrag_expert_overlay.py --config backend/scripts/routerrag_expert_test_config.json
uv run python backend/scripts/test_graphrag_retrieval.py
uv run python backend/scripts/test_neo4j_graphrag_only.py
uv run python backend/scripts/test_neo4j_graphrag_hybrid.py
uv run python backend/scripts/test_neo4j_conn.py
uv run python scripts/test_neo4j_connection.py
```

If you need a “single test”, run the specific validation script for the subsystem you changed rather than assuming pytest is available.

## Environment and configuration

Backend runtime and LLM/database settings are split across:

- `backend/.env`
- `backend/configs/`
- config endpoints exposed by `backend/server.py` and `backend/server_support/`

README-documented variables to expect:

- `DASHSCOPE_API_KEY`
- `VITE_API_BASE_URL` in `frontend/.env.local`
- optional `OPINION_BACKEND_PORT` for backend binding

Python requirement is `>=3.11` (`pyproject.toml`).

Important repo-specific detail: the active config directory in the current codebase is `backend/configs/`, not a root-level `configs/` directory.

## Architecture

### Top-level split

- `frontend/`: Vue 3 + Vite SPA
- `backend/`: Flask API server, CLI pipeline, RAG/GraphRAG logic, project storage and analysis code

### Backend request surface

The backend entrypoint is `backend/server.py`.

Key patterns:

- `server.py` is the integration layer and route host.
- New helper logic is expected to live under `backend/server_support/`, not directly inside `server.py`.
- Route modules are also mounted from feature blueprints in `backend/src/*/api.py`.
- `server.py` also defines many first-party `/api/...` endpoints directly, including project management, filter status streaming, AI chat, settings/config, fetch cache, and RAG endpoints.

Important blueprints wired into Flask:

- `src/fluid/api.py`: fluid-dynamics analysis endpoints
- `src/analyze/api.py`: basic analysis execution/history/results
- `src/topic/api.py`: BERTopic analysis execution and availability checks

`backend/server_support/__init__.py` is effectively the façade for route helpers: config loading/persistence, project/topic resolution, dataset handling, RAG build orchestration, response helpers, filter progress tracking, and archive discovery.


### Project-centric storage model

The system is organized around projects/topics, not flat folders.

The canonical storage rules live in `backend/src/utils/setting/paths.py` and `backend/src/project/manager.py`:

- project data lives under `backend/data/projects/<project-identifier>/`
- stage folders include `raw`, `merge`, `clean`, `filter`, `fetch`, `analyze`, `reports`, `results`, and upload/cache subfolders
- `bucket(layer, topic, date)` is the standard way to resolve per-stage paths
- `ProjectManager` persists project metadata and operation history in `backend/data/projects.json` / `projects.pkl` and keeps project identifiers stable

When editing pipeline code, keep path resolution consistent with `bucket(...)` and project identifier resolution. Do not invent ad-hoc directories.

### Data processing pipeline

The legacy CLI pipeline in `backend/main.py` still reflects the main backend workflow:

1. `Merge`: combine raw TRS/source files
2. `Clean`: normalize and deduplicate
3. `Filter`: AI relevance filtering/classification
4. `Upload`: persist filtered results into the relational store
5. optional `GraphSync`: push uploaded/local content into Neo4j
6. `Fetch` / `Analyze`: retrieve data and generate analysis outputs

The web UI calls the same backend capabilities through API routes and server-support helpers.

### Frontend structure

The frontend is a route-driven SPA. The main route map is in `frontend/src/router/index.js`.

The app is organized around feature areas instead of a single dashboard:

- topic creation workflow (`/topics/new/...`)
- project data management (`/datasets`)
- basic analysis (`/analysis/basic/...`)
- content analysis and report generation
- BERTopic analysis (`/topic/bertopic/...`)
- deep analysis / fluid dynamics
- retrieval / RAG views, including RouterRAG, TagRAG, and a dedicated GraphRAG lab page
- settings pages for backend, AI, databases, archives, theme, RAG, BERTopic, and experimental features

`frontend/src/App.vue` contains the overall shell, navigation groups, project switcher integration, and AI sidebar.

### RAG / GraphRAG architecture

The repository supports multiple retrieval modes and hybrid routing.

Important pieces:

- `backend/src/rag/`: newer RAG pipeline components and retrievers
- `backend/src/utils/rag/ragrouter/`: RouterRAG retrieval/build logic still used by parts of the system
- `backend/src/graph/`: graph construction, Neo4j sync, embeddings, schema, event clustering, and graph-based retrieval support
- `frontend/src/composables/useRAGTopics.js`: frontend state for RAG topics, build/import flow, retrieval, and RLHF-style tuning UX
- `frontend/src/views/retrieval/RouterRAGView.vue`: current retrieval lab/UI for topic selection, retrieval mode selection, LLM summary, export, feedback, and tuning

Conceptually:

- TagRAG: tag-oriented/vectorized retrieval
- NormalRAG: chunk/vector retrieval from local corpora
- GraphRAG: Neo4j-backed entity/event/topic graph retrieval
- RouterRAG: combines multiple retrieval sources and can optionally add expert/planner overlays

`backend/src/rag/retrievers/expert_retriever.py` shows an important recent pattern: retrieval can be augmented by an expert planning graph stored in a dedicated Neo4j database (`opinion-expert`), including vector lookup plus structured expansion.

### Graph build flow

`backend/src/graph/build_graph.py` is a good overview of the full graph pipeline:

1. sync uploaded/local data into Neo4j via `sync_mysql_to_neo4j.py`
2. run entity extraction and chunk creation/embedding
3. run BERTopic if needed
4. sync BERTopic results back into the graph
5. cluster posts into events
6. rebuild NormalRAG vectors from graph-derived content

`backend/src/graph/sync_mysql_to_neo4j.py` is also important because it supports both DB-backed inputs and direct local file ingestion (`jsonl`, `csv`, `pdf`, `docx`, `txt`, `md`) when syncing graph content.

## Working conventions for this repo

- Prefer reading `backend/server.py` plus the relevant `server_support/` or `src/*/api.py` module before changing backend behavior.
- Prefer extending `server_support/` for backend route helpers; keep `server.py` focused on wiring and route logic.
- Prefer `bucket(...)` and project-manager helpers for file locations; avoid hardcoding paths.
- For retrieval work, check both `backend/src/rag/` and `backend/src/utils/rag/ragrouter/` because the codebase currently contains both newer and legacy RAG layers.
- For frontend changes, update `frontend/src/router/index.js` and `frontend/src/App.vue` navigation together when a page is added or moved.
- There is no obvious repo-wide lint/test command configured yet; use targeted scripts and the actual UI/backend flow you touched.
>>>>>>> 8e5bf16 (针对控烟报告构造graphRAG)
