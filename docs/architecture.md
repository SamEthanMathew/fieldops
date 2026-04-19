# FieldOps Architecture

FieldOps uses a blackboard architecture:

1. The simulation engine injects scenario events into shared incident state.
2. The Triage agent classifies patients and emits structured assessments.
3. Hospital Intel refreshes capacity, ETAs, and facility availability.
4. Logistics scores patient, ambulance, and hospital combinations and emits dispatch recommendations.
5. Overwatch periodically reads the full state and emits SITREPs and alerts.
6. FastAPI exposes control APIs and a WebSocket stream for the dashboard.

Agents never call each other directly. They coordinate only through `IncidentState`.

