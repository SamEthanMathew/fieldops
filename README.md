# FieldOps

> Multi-agent AI co-pilot for mass casualty incident command.

**Most Ambitious — CMU AI Agents Weekend 2026**

---

## What it is

In a mass casualty incident, the bottleneck is not medical skill — it is information coordination under extreme time pressure. Only 56% of critically injured patients in studied cohorts are transported directly to trauma centers (JACS 2022). FieldOps puts a multi-agent AI system in the hands of the Incident Commander to fix that.

It simulates a Pittsburgh bridge collapse, continuously classifies incoming patients using START/JumpStart triage protocols, recommends optimal ambulance-to-hospital routing, monitors hospital capacity in real time, and streams the full incident picture to a live operator dashboard. Agents coordinate through a shared incident state — never calling each other directly — which gives the system traceability, replayability, and graceful degradation when components fail.

---

## Agents

Six agents run concurrently on a blackboard architecture:

| Agent | Role |
|---|---|
| **Triage** | Classifies patients (RED / YELLOW / GREEN / BLACK) using rule-based vitals extraction and Gemini-2.5-flash with RAG-augmented protocol context |
| **Hospital Intel** | Tracks bed availability, ICU/OR capacity, ETA from scene, and diversion status across the hospital network |
| **Logistics** | Scores and recommends patient-to-ambulance-to-hospital assignments; queues future ambulances before they return |
| **Overwatch** | Monitors global incident state, raises alerts, and generates situation reports (SITREPs) every five minutes |
| **Orchestrator** | Detects inter-agent conflicts and issues strategic directives to rebalance the system |
| **Pre-Notification** | Crafts clinical pre-alerts and PDFs when an ambulance is dispatched; attempts SMTP delivery to receiving hospitals |

RED dispatches require explicit Incident Commander approval before execution. If Gemini is unavailable, all agents fall back to deterministic rule-based logic.

---

## Metrics

Standard scenario (Pittsburgh bridge collapse, 25 patients, 45 minutes):

| Metric | FieldOps | Naive baseline |
|---|---|---|
| Triage accuracy | **1.00** | — |
| Transport match score | **0.964** | 0.679 |
| Hospital load Gini | **0.179** | 0.833 |
| Survival proxy score | **0.954** | 0.687 |
| Mean dispatch latency | **0.0 s** | — |

FieldOps improves destination matching by ~42% and reduces hospital load imbalance by ~78% compared to the naive dispatcher on the same scenario.

---

## Tech stack

- **Backend:** Python 3.11, FastAPI, Pydantic, Uvicorn
- **Frontend:** React 18, TypeScript, Vite, Leaflet
- **LLM:** Google Gemini 2.5-flash via `google-genai`
- **RAG:** LlamaIndex with Gemini embeddings over START/JumpStart/ICS-MCI protocol documents
- **PDF generation:** ReportLab
- **Infrastructure:** Docker + Compose

---

## Quick start

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e .[dev]
cp .env.example .env        # add your GEMINI_API_KEY
uvicorn app.main:app --reload --port 8001
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend expects the backend at `http://localhost:8001`. Open `http://localhost:5173`.

### Single-container run

```bash
docker compose up --build
```

Then open `http://localhost:8000`.

---

## Demo flow

1. Select a scenario (light / standard / heavy) and click **Start**.
2. Watch patients arrive, get triaged, and receive dispatch recommendations on the map.
3. Approve pending RED dispatches from the IC Approvals panel.
4. Inject failures mid-run — hospital diversions, ambulance outages, stale intel, agent timeouts.
5. Toggle baseline comparison to see FieldOps vs. the naive dispatcher side-by-side.
6. Export the incident report as a PDF from the Exports tab.

---

## Project layout

```
backend/          FastAPI app, simulation engine, agents, evaluation, tests
frontend/         React operator dashboard
shared/           JSON schema and TypeScript/Python shared contracts
data/
  ambulances.json   Pittsburgh ambulance fleet
  hospitals.json    Regional hospital network with specialties
  scenarios/        light / standard / heavy bridge-collapse scenarios
  rag/              Medical protocol documents (START, JumpStart, ICS-MCI, SALT)
docs/
  architecture.md       Blackboard architecture overview
  results/              Saved evaluation results
scripts/          Utility scripts
Dockerfile        Multi-stage build (frontend → Python runtime)
docker-compose.yml
```

---

## Team

[Sam Mathew](https://github.com/SamEthanMathew) and Darren Pinto
