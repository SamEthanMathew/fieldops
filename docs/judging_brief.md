# FieldOps Judging Brief

This brief maps the working product directly to the judging rubric and gives a concise presentation narrative with evidence.

## 1. Problem and Use Case Clarity

FieldOps is scoped to one user and one bottleneck:

- User: the Medical Branch Director / Incident Commander during the acute phase of a mass casualty incident.
- Problem: dispatch optimization between field triage and hospital arrival.
- Why it matters: trauma outcomes improve when critically injured patients go directly to trauma centers rather than to non-trauma hospitals first.

Evidence:

- A 2022 JACS study using NEMSIS data found that only `56.0%` of critically injured patients in the studied cohort were transported directly to trauma centers.
- JAMA’s Boston Marathon response writeup reported that Boston EMS and partner agencies transported casualties to hospitals within `90 minutes`, and that no patient who arrived alive at a hospital later died.
- ASTHO’s Route 91 festival response summary noted that many victims arrived by private vehicle or rideshare, which complicated situational awareness and patient tracking.

Sources:

- https://pubmed.ncbi.nlm.nih.gov/35703965/
- https://jamanetwork.com/journals/jama/article-abstract/1684255
- https://www.astho.org/globalassets/report/public-health-and-medical-preparedness-and-response-activities-at-the-2017-route-91-harvest-music-festival.pdf

## 2. Agent Design and System Architecture

FieldOps is a blackboard-style multi-agent system, not a single chat prompt.

- `TRIAGE`: parses field reports, applies protocol-grounded classification, emits structured assessments with citations.
- `HOSPITAL INTEL`: maintains facility capability, diversion state, ETA, and staleness awareness.
- `LOGISTICS`: matches patients to ambulances and hospitals with deterministic scoring, resource reservation, queued future assignments, and alternatives.
- `OVERWATCH`: monitors the global state, raises alerts, and produces SITREPs without directly dispatching.

Working architecture artifacts:

- [docs/architecture.md](</c:/Users/samet/AI-Agents Hackathon/docs/architecture.md>)
- [backend/app/engine.py](</c:/Users/samet/AI-Agents Hackathon/backend/app/engine.py>)
- [backend/app/triage.py](</c:/Users/samet/AI-Agents Hackathon/backend/app/triage.py>)
- [backend/app/logistics.py](</c:/Users/samet/AI-Agents Hackathon/backend/app/logistics.py>)
- [backend/app/overwatch.py](</c:/Users/samet/AI-Agents Hackathon/backend/app/overwatch.py>)

## 3. Evaluation and Metrics

Saved results are in [docs/results/evaluation_results.json](</c:/Users/samet/AI-Agents Hackathon/docs/results/evaluation_results.json>).

Standard scenario results:

- `Triage Accuracy`: `1.00`
- `Transport Match Score`: `0.964`
- `Mean Dispatch Latency`: `0.0s`
- `Hospital Load Gini`: `0.179`
- `Survival Proxy Score`: `0.954`

Baseline comparison on the same standard scenario:

- `Transport Match Score`: `0.679`
- `Hospital Load Gini`: `0.833`
- `Survival Proxy Score`: `0.687`

Interpretation:

- FieldOps materially improves destination matching and load balancing over the naive dispatcher.
- The stress scenarios still degrade, but the system continues to function and produce SITREPs rather than collapsing.

## 4. Risk, Failure Modes, and Guardrails

Guardrails already implemented:

- RED dispatches stay human-approved in the UI.
- Triage outputs are structured and citation-backed.
- Pending dispatches reserve resources so the optimizer does not double-book ambulances or hospitals.
- Pending routes are released and re-queued when a hospital diverts or an ambulance fails.
- Stale hospital feeds and agent timeout injections are supported in the dashboard.

Live demo controls expose these behaviors directly in the product.

## 5. Tradeoffs and Product Thinking

The strongest product decisions to call out:

- Multi-agent over single-agent: better separation of concerns, clearer debugging, and less context bloat.
- Human-in-the-loop for RED: speed is important, but the highest-stakes decisions stay reviewable.
- Deterministic logistics over opaque RL: easier to audit, easier to explain, and better suited to a demo with limited data.
- Local RAG fallback plus optional LlamaIndex integration: the demo runs reliably even without remote API dependencies.

## 6. Technical Implementation

Live product surfaces:

- FastAPI API and realtime incident session manager
- React dashboard with controls, map, tracker, agent log, metrics, approvals, and failure injection
- Docker packaging for single-service deployment
- Polling fallback when WebSockets are unavailable

Verification already run:

- `pytest -q`
- `npm run build`
- `python -m app.scripts.run_evaluations`

## 7. Innovation and Novelty

What is genuinely novel here:

- The system re-optimizes as state changes rather than producing one static plan.
- Overwatch reasons over inter-agent disagreement and system-wide risk instead of merely displaying data.
- The dispatcher can commit the next returning ambulance before it is physically back, which mirrors real incident command planning more closely than naive “available now only” routing.

## 8. Ambition and Scope

This is an ambitious but still demoable scope:

- 4 cooperating agents
- protocol-backed triage
- dynamic routing and queued transport commitments
- simulation engine with baseline comparison
- live operator dashboard
- packaged deployment path

The honest framing for judges is: this is a strong, simulation-driven decision-support demo that proves the core intelligence and coordination layer, not a finished production emergency-response platform.
