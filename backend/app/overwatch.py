from __future__ import annotations

from .models import AgentState, Alert, IncidentPhase, IncidentState, Sitrep, TriageCategory
from .utils import iso_at_minute, next_id


class OverwatchAgent:
    def generate(self, state: IncidentState, current_minute: int) -> Sitrep:
        patients = list(state.patients.values())
        by_category = {category.value: 0 for category in TriageCategory}
        for patient in patients:
            if patient.triage_category:
                by_category[patient.triage_category] += 1

        available_ambulances = sum(1 for ambulance in state.ambulances.values() if ambulance.status == "AVAILABLE")
        network_capacity = sum(h.capacity.available_beds for h in state.hospitals.values())
        network_total = sum(h.capacity.total_beds for h in state.hospitals.values())
        capacity_pct = (network_capacity / network_total) if network_total else 0

        alerts: list[Alert] = []
        if by_category["RED"] and by_category["RED"] / max(len(patients), 1) > 0.4:
            alerts.append(Alert(type="SURGE_WARNING", message="RED patient ratio exceeds 40%. Consider expanded response.", severity="HIGH"))
        if available_ambulances / max(len(state.ambulances), 1) < 0.2:
            alerts.append(Alert(type="RESOURCE_WARNING", message="Ambulance availability below 20% of fleet.", severity="HIGH"))
        if capacity_pct < 0.25:
            alerts.append(Alert(type="CAPACITY_WARNING", message="Hospital network capacity below 25%. Consider mutual aid.", severity="HIGH"))
        if state.pending_approvals:
            alerts.append(Alert(type="APPROVAL_QUEUE", message=f"{len(state.pending_approvals)} RED dispatches awaiting IC approval.", severity="MODERATE"))
        for name, health in state.agent_health.items():
            if health.status != AgentState.NOMINAL:
                alerts.append(Alert(type="AGENT_DEGRADED", message=f"{name} agent status is {health.status}.", severity="MODERATE"))

        recommendations = []
        if available_ambulances <= 3:
            recommendations.append("Pre-position returning ambulances at the staging area to reduce next-dispatch latency.")
        if capacity_pct < 0.35:
            recommendations.append("Reduce low-acuity routing to Level 1 centers to protect critical capacity.")
        if not recommendations:
            recommendations.append("Maintain current routing and continue monitoring hospital saturation.")

        incident_phase = IncidentPhase.ACTIVE
        if current_minute > 25:
            incident_phase = IncidentPhase.STABILIZING
        if current_minute >= max(state.meta.get("duration_minutes", 45) - 5, 1):
            incident_phase = IncidentPhase.RECOVERY

        summary = (
            f"{len(patients)} patients triaged. "
            f"{by_category['RED']} RED, {by_category['YELLOW']} YELLOW, {by_category['GREEN']} GREEN, {by_category['BLACK']} BLACK. "
            f"{state.metrics.transported} transported, {state.metrics.awaiting_dispatch} awaiting dispatch. "
            f"Hospital capacity at {capacity_pct:.0%}. Ambulance availability {available_ambulances}/{len(state.ambulances)}."
        )
        return Sitrep(
            sitrep_id=next_id("SR"),
            timestamp=iso_at_minute(state.start_time, current_minute),
            minute=current_minute,
            incident_phase=incident_phase,
            summary=summary,
            alerts=alerts,
            recommendations=recommendations,
            agent_health={name: health.status for name, health in state.agent_health.items()},
        )

