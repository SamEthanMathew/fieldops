# FieldOps

FieldOps is a demo-first multi-agent mass casualty incident command system built for hackathon delivery. It simulates a Pittsburgh bridge collapse, classifies incoming patients, recommends hospital routing, monitors hospital capacity, and streams the full incident picture to a live operator dashboard.

## Repo layout

- `backend/` FastAPI API, orchestration engine, agents, tests
- `frontend/` React + Vite operator dashboard
- `shared/` JSON schema and shared contracts
- `data/` seeded hospitals, ambulances, scenarios, and protocol docs
- `docs/` architecture notes and generated evaluation output

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -e .[dev]
uvicorn app.main:app --reload
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the backend on `http://localhost:8000`.

### Single-container run

```bash
docker compose up --build
```

Then open `http://localhost:8000`.

## Demo flow

1. Start the backend and frontend.
2. Click `Start Standard Scenario`.
3. Use play, pause, step, and speed controls to drive the simulation.
4. Review pending RED dispatches and approve them from the dashboard.
5. Toggle baseline comparison and inject failures or diversions during the run.

## Current standard-scenario metrics

- `Triage Accuracy`: `1.00`
- `Transport Match Score`: `0.964`
- `Mean Dispatch Latency`: `0.0s` for assignment recommendations
- `Hospital Load Gini`: `0.179`
- `Survival Proxy Score`: `0.954`

## Notes

- The RAG layer defaults to local keyword retrieval over the protocol documents in `data/rag/`.
- Claude, Tavily, and LlamaIndex are represented behind clean service interfaces so the demo runs without external credentials.
- Evaluation artifacts can be generated with `python -m app.scripts.run_evaluations`.
