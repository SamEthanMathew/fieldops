from __future__ import annotations

import logging

from .llm_client import call_llm_sync, extract_xml_tag, is_llm_available
from .models import AgentState, Alert, IncidentPhase, IncidentState, Sitrep, TriageCategory
from .utils import iso_at_minute, next_id

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Medical Incident Commander AI for a Mass Casualty Incident (MCI).
Generate a concise tactical SITREP and actionable recommendations for the Incident Commander.
Base your assessment on patient counts, resource availability, and hospital capacity trends.

Respond ONLY with this XML (no other text):
<summary>2-3 sentence operational summary describing current incident status and trajectory</summary>
<recommendation_1>specific, actionable directive for the IC right now</recommendation_1>
<recommendation_2>second priority action, or empty string if nothing else critical</recommendation_2>"""


class OverwatchAgent:
    def generate(self, state: IncidentState, current_minute: int) -> Sitrep:
        """Generate a rule-based SITREP synchronously. LLM enrichment runs async separately."""
        patients = list(state.patients.values())
        by_category = {category.value: 0 for category in TriageCategory}
        for patient in patients:
            if patient.triage_category:
                by_category[patient.triage_category] += 1

        available_ambulances = sum(1 for amb in state.ambulances.values() if amb.status == "AVAILABLE")
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

        incident_phase = IncidentPhase.ACTIVE
        if current_minute > 25:
            incident_phase = IncidentPhase.STABILIZING
        if current_minute >= max(state.meta.get("duration_minutes", 45) - 5, 1):
            incident_phase = IncidentPhase.RECOVERY

        transported = state.metrics.transported if state.metrics else 0
        awaiting = state.metrics.awaiting_dispatch if state.metrics else 0
        summary = (
            f"{len(patients)} patients triaged — "
            f"{by_category['RED']} RED, {by_category['YELLOW']} YELLOW, {by_category['GREEN']} GREEN. "
            f"{transported} transported, {awaiting} awaiting dispatch. "
            f"Hospital network at {capacity_pct:.0%} capacity. "
            f"{available_ambulances}/{len(state.ambulances)} ambulances available."
        )

        if available_ambulances <= 3:
            recommendations = ["Pre-position returning ambulances at staging area to reduce next-dispatch latency."]
        elif capacity_pct < 0.35:
            recommendations = ["Reduce low-acuity routing to Level 1 centers to protect critical capacity."]
        else:
            recommendations = ["Maintain current routing and continue monitoring hospital saturation."]

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

    def build_llm_prompt(self, state: IncidentState, current_minute: int) -> str:
        """Build the user prompt for LLM enrichment (call before releasing the lock)."""
        patients = list(state.patients.values())
        by_category = {category.value: 0 for category in TriageCategory}
        for patient in patients:
            if patient.triage_category:
                by_category[patient.triage_category] += 1

        available_ambulances = sum(1 for amb in state.ambulances.values() if amb.status == "AVAILABLE")
        network_capacity = sum(h.capacity.available_beds for h in state.hospitals.values())
        network_total = sum(h.capacity.total_beds for h in state.hospitals.values())
        capacity_pct = (network_capacity / network_total) if network_total else 0
        transported = state.metrics.transported if state.metrics else 0
        awaiting = state.metrics.awaiting_dispatch if state.metrics else 0

        recent_patients = sorted(patients, key=lambda p: p.reported_minute, reverse=True)[:8]
        patient_lines = "\n".join(
            f"  {p.patient_id}: {p.triage_category} | {p.status} | {(p.latest_report or '')[:70]}"
            for p in recent_patients
        )
        hospital_lines = "\n".join(
            f"  {h.name}: {h.capacity.available_beds}/{h.capacity.total_beds} beds, "
            f"load {h.current_load_pct:.0%}, status {h.status}"
            for h in state.hospitals.values()
        )

        return (
            f"Incident minute: {current_minute}\n"
            f"Patients: {len(patients)} total — {by_category.get('RED',0)} RED, "
            f"{by_category.get('YELLOW',0)} YELLOW, {by_category.get('GREEN',0)} GREEN, "
            f"{by_category.get('BLACK',0)} BLACK\n"
            f"Transported: {transported} | Awaiting dispatch: {awaiting}\n"
            f"Ambulances available: {available_ambulances}/{len(state.ambulances)}\n"
            f"Hospital capacity remaining: {capacity_pct:.0%}\n"
            f"Pending IC approvals: {len(state.pending_approvals)}\n"
            f"\nHospitals:\n{hospital_lines}\n"
            f"\nRecent patients:\n{patient_lines}"
        )

    @staticmethod
    def call_llm_enrichment(user_prompt: str) -> tuple[str | None, list[str] | None]:
        """Synchronous LLM call — safe to run in a thread pool executor."""
        if not is_llm_available():
            return None, None
        try:
            result = call_llm_sync(_SYSTEM_PROMPT, user_prompt, timeout=7.0)
        except Exception as exc:
            logger.warning("Overwatch LLM failed: %s", exc)
            return None, None
        if not result:
            return None, None
        summary = extract_xml_tag(result, "summary")
        r1 = extract_xml_tag(result, "recommendation_1")
        r2 = extract_xml_tag(result, "recommendation_2")
        recommendations = [r for r in [r1, r2] if r and r.strip()]
        return summary, recommendations or None
