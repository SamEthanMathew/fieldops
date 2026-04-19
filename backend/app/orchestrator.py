from __future__ import annotations

import logging

from .llm_client import call_llm, extract_xml_tag, is_llm_available
from .models import AgentMessage, DecisionLogEntry, IncidentState
from .utils import iso_at_minute, next_id

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are the Medical Branch Director AI for a Mass Casualty Incident.
You oversee 4 specialized agents: TRIAGE, HOSPITAL_INTEL, LOGISTICS, and PRE_NOTIFICATION.
Your job is to detect conflicts, resource shortfalls, and issue strategic directives.

You must return ONLY this XML:
<directive>One specific action directive for the most urgent issue</directive>
<priority_alert>Brief alert message (or NONE if everything nominal)</priority_alert>
<addressed_to>LOGISTICS or TRIAGE or HOSPITAL_INTEL or ALL</addressed_to>
<severity>INFO or WARNING or CRITICAL</severity>"""


class OrchestratorAgent:
    async def run(self, state: IncidentState, minute: int, *, use_llm: bool = True) -> None:
        directive, alert, addressed_to, severity = await self._analyze(state, minute, use_llm=use_llm)
        if not directive:
            return

        timestamp = iso_at_minute(state.start_time, minute)
        msg = AgentMessage(
            message_id=next_id("MSG"),
            from_agent="ORCHESTRATOR",
            to_agent=addressed_to,
            message=directive,
            minute=minute,
            timestamp=timestamp,
            message_type="DIRECTIVE",
        )
        state.agent_messages.append(msg)

        if alert and alert.upper() != "NONE":
            state.decision_log.append(
                DecisionLogEntry(
                    minute=minute,
                    timestamp=timestamp,
                    agent="ORCHESTRATOR",
                    message=alert,
                    severity=severity,
                    related_ids=[msg.message_id],
                )
            )
            if state.agent_health.get("overwatch"):
                state.agent_health["overwatch"].last_thought = f"Orchestrator: {alert}"

    async def _analyze(self, state: IncidentState, minute: int, *, use_llm: bool = True) -> tuple[str, str, str, str]:
        if not use_llm or not is_llm_available():
            return self._rule_based_analysis(state)

        red_count = sum(1 for p in state.patients.values() if p.triage_category == "RED")
        yellow_count = sum(1 for p in state.patients.values() if p.triage_category == "YELLOW")
        green_count = sum(1 for p in state.patients.values() if p.triage_category == "GREEN")
        avail_ambulances = sum(1 for a in state.ambulances.values() if a.status == "AVAILABLE")
        total_ambulances = len(state.ambulances)
        avg_load = sum(h.current_load_pct for h in state.hospitals.values()) / max(len(state.hospitals), 1)
        diverted = [h.name for h in state.hospitals.values() if h.divert_status]
        pending = len(state.pending_approvals)

        recent_log = "\n".join(
            f"[{e.agent}] {e.message}" for e in state.decision_log[-8:]
        )

        user_prompt = f"""Current Incident Status at minute {minute}:

Patients: {len(state.patients)} total ({red_count} RED, {yellow_count} YELLOW, {green_count} GREEN)
Ambulances: {avail_ambulances}/{total_ambulances} available
Hospital avg load: {avg_load:.0%}
Diverted hospitals: {', '.join(diverted) or 'none'}
Pending RED approvals: {pending}
Pre-notifications sent: {len(state.pre_notifications)}

Recent agent decisions:
{recent_log}

What is the single most critical directive right now?"""

        response = await call_llm(_SYSTEM_PROMPT, user_prompt)
        if not response:
            return self._rule_based_analysis(state)

        directive = extract_xml_tag(response, "directive") or ""
        alert = extract_xml_tag(response, "priority_alert") or "NONE"
        addressed_to = extract_xml_tag(response, "addressed_to") or "ALL"
        severity = extract_xml_tag(response, "severity") or "INFO"
        return directive, alert, addressed_to, severity

    @staticmethod
    def _rule_based_analysis(state: IncidentState) -> tuple[str, str, str, str]:
        red_awaiting = [
            p for p in state.patients.values()
            if p.triage_category == "RED" and p.status in ("TRIAGED", "AWAITING_DISPATCH")
        ]
        avail_als = [a for a in state.ambulances.values() if a.status == "AVAILABLE" and a.type == "ALS"]
        diverted = [h for h in state.hospitals.values() if h.divert_status]

        if red_awaiting and not avail_als:
            return (
                f"No ALS ambulances available — {len(red_awaiting)} RED patients awaiting transport",
                f"CRITICAL: {len(red_awaiting)} RED patients with no ALS ambulance available",
                "LOGISTICS",
                "CRITICAL",
            )
        if len(diverted) >= 2:
            return (
                f"Route to alternate hospitals — {len(diverted)} hospitals on divert",
                f"WARNING: {len(diverted)} hospitals on divert, routing capacity reduced",
                "LOGISTICS",
                "WARNING",
            )
        if state.pending_approvals:
            return (
                f"Awaiting IC approval for {len(state.pending_approvals)} RED dispatch(es)",
                f"APPROVAL NEEDED: {len(state.pending_approvals)} RED dispatch(es) pending",
                "ALL",
                "WARNING",
            )
        return "", "NONE", "ALL", "INFO"
