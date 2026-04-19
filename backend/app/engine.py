from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any

from .artifacts import (
    attempt_smtp_send,
    create_email_message,
    generate_incident_report_pdf,
    generate_prealert_pdf,
    write_eml_file,
)
from .evaluation import simulate_baseline, update_metrics
from .hospital_intel import HospitalIntelAgent
from .llamaindex_rag import LlamaIndexRag
from .llm_client import get_circuit_breaker_status, is_llm_available, llm_capture
from .llm_triage import LLMTriageAgent
from .logistics import LogisticsAgent
from .memory import TriageMemoryStore
from .models import (
    AgentHealth,
    AgentMessage,
    AgentState,
    AgreementRates,
    ArtifactRef,
    AuditLogEntry,
    BaselineState,
    CostEstimate,
    DecisionLogEntry,
    DispatchStatus,
    EmailDeliveryRecord,
    GuardrailRule,
    HistoryEntry,
    IncidentMode,
    IncidentPhase,
    IncidentState,
    InjectEventRequest,
    LeadTimeStats,
    LiveMetrics,
    PatientRecord,
    PatientStatus,
    ScenarioControlRequest,
    ScenarioDefinition,
    ScenarioEvent,
    TriageCategory,
)
from .orchestrator import OrchestratorAgent
from .overwatch import OverwatchAgent
from .pre_notification import generate_pre_notification
from .scenario_loader import load_scenario, load_seed_ambulances, load_seed_hospitals
from .triage import TriageAgent
from .utils import iso_at_minute, next_id

LLM_ENABLED_AGENTS = {"triage", "pre_notification", "overwatch", "orchestrator"}


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, int(round(0.95 * (len(ordered) - 1))))
    return round(ordered[index], 2)


class SimulationSession:
    def __init__(
        self,
        scenario: ScenarioDefinition,
        triage_agent: TriageAgent | LLMTriageAgent,
        hospital_intel: HospitalIntelAgent,
        logistics: LogisticsAgent,
        overwatch: OverwatchAgent,
        orchestrator: OrchestratorAgent | None = None,
        rule_based_triage: TriageAgent | None = None,
        memory_store: TriageMemoryStore | None = None,
    ) -> None:
        self.scenario = scenario
        self.triage_agent = triage_agent
        self.hospital_intel = hospital_intel
        self.logistics = logistics
        self.overwatch = overwatch
        self.orchestrator = orchestrator
        self._rule_based_triage = rule_based_triage or (triage_agent if isinstance(triage_agent, TriageAgent) else None)
        self.memory_store = memory_store or TriageMemoryStore()
        self.speed = 1.0
        self.is_running = False
        self.lock = asyncio.Lock()
        self._events_by_minute: dict[int, list[ScenarioEvent]] = {}
        self._agent_latency_samples: dict[str, list[float]] = {}
        self._pending_pre_notifications: set[tuple[str, int]] = set()
        self._last_degraded_mode = False
        for evt in scenario.events:
            self._events_by_minute.setdefault(evt.minute, []).append(evt)
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self.worker: asyncio.Task[None] | None = None
        incident_id = next_id("INC")
        self.state = IncidentState(
            incident_id=incident_id,
            scenario_id=scenario.scenario_id,
            incident_type=scenario.incident_type,
            incident_phase=IncidentPhase.ACTIVE,
            mode=IncidentMode.BALANCED,
            location=scenario.scene,
            start_time="2026-04-18T15:00:00Z",
            current_time="2026-04-18T15:00:00Z",
            current_minute=0,
            hospitals=load_seed_hospitals(),
            ambulances=load_seed_ambulances(),
            baseline=BaselineState(scenario_id=scenario.scenario_id),
            agent_health=self._build_agent_health(),
            guardrails=self._default_guardrails(),
            meta={
                "duration_minutes": scenario.duration_minutes,
                "scenario_name": scenario.name,
                "memory_backend": self.memory_store.backend,
                "rag_backend": getattr(getattr(self.triage_agent, "_rag", None), "backend", "local_keyword"),
            },
        )
        baseline_triage = self._rule_based_triage or (triage_agent if isinstance(triage_agent, TriageAgent) else triage_agent)
        self.state.baseline = simulate_baseline(deepcopy(self.state), scenario, baseline_triage)
        self._append_audit(
            event_type="incident_started",
            agent="SIMULATION",
            message=f"Scenario {scenario.name} launched",
            data={"scenario_id": scenario.scenario_id},
        )
        self._refresh_runtime_state()
        self._process_minute(0)

    def _build_agent_health(self) -> dict[str, AgentHealth]:
        return {
            "triage": AgentHealth(status=AgentState.NOMINAL),
            "hospital_intel": AgentHealth(status=AgentState.NOMINAL, llm_mode=False),
            "logistics": AgentHealth(status=AgentState.NOMINAL, llm_mode=False),
            "overwatch": AgentHealth(status=AgentState.NOMINAL),
            "pre_notification": AgentHealth(status=AgentState.NOMINAL),
            "orchestrator": AgentHealth(status=AgentState.NOMINAL),
        }

    @staticmethod
    def _default_guardrails() -> list[GuardrailRule]:
        return [
            GuardrailRule(
                rule_id="red-human-approval",
                title="RED dispatches require human approval",
                description="All RED dispatches remain queued for incident commander approval regardless of LLM confidence.",
            ),
            GuardrailRule(
                rule_id="black-no-dispatch",
                title="BLACK patients are never auto-dispatched",
                description="Patients classified BLACK remain excluded from dispatch recommendations.",
            ),
            GuardrailRule(
                rule_id="hospital-filtering",
                title="Diverted and unknown hospitals are excluded",
                description="Hospitals on divert or with stale/unknown status are removed from routing candidates.",
            ),
            GuardrailRule(
                rule_id="stale-hospital-intel",
                title="Stale hospital intel is marked low trust",
                description="Hospital intel older than 10 minutes is marked stale and downgraded in decision-making.",
            ),
            GuardrailRule(
                rule_id="low-confidence-escalation",
                title="Low-confidence triage is escalated conservatively",
                description="Uncertain or low-quality triage is escalated upward and highlighted for review.",
            ),
            GuardrailRule(
                rule_id="circuit-breaker-fallback",
                title="Circuit breaker forces degraded mode",
                description="When the LLM is unavailable or the breaker is open, the system falls back to deterministic behavior.",
            ),
        ]

    async def control(self, request: ScenarioControlRequest) -> IncidentState:
        async with self.lock:
            if request.speed is not None:
                self.speed = max(0.25, min(request.speed, 10.0))
            if request.action == "play":
                self.is_running = True
                if self.worker is None or self.worker.done():
                    self.worker = asyncio.create_task(self._run())
            elif request.action == "pause":
                self.is_running = False
            elif request.action == "step":
                steps = request.steps or 1
                for _ in range(steps):
                    if self.state.current_minute < self.scenario.duration_minutes:
                        self._process_minute(self.state.current_minute + 1)
            elif request.action == "reset":
                self.is_running = False
                new_session = SimulationSession(
                    self.scenario,
                    self.triage_agent,
                    self.hospital_intel,
                    self.logistics,
                    self.overwatch,
                    self.orchestrator,
                    rule_based_triage=self._rule_based_triage,
                    memory_store=self.memory_store,
                )
                self.state = new_session.state
                self._agent_latency_samples = new_session._agent_latency_samples
                self.speed = 1.0
            self._refresh_runtime_state()
            await self.broadcast()
            return self.state

    async def set_mode(self, mode: IncidentMode) -> IncidentState:
        async with self.lock:
            previous_mode = self.state.mode
            if mode == previous_mode:
                return self.state
            self.state.mode = mode
            self._append_audit(
                event_type="mode_switch",
                agent="OPERATOR",
                message=f"Mode switched from {_enum_value(previous_mode)} to {_enum_value(mode)}",
                data={"from": _enum_value(previous_mode), "to": _enum_value(mode)},
            )
            self._emit_message("OPERATOR", "BLACKBOARD", f"Mode switched to {_enum_value(mode)}", "UPDATE")
            self._retriage_active_patients()
            self.hospital_intel.refresh(self.state, self.state.current_minute)
            self._refresh_pending_dispatches(reason=f"mode switch to {mode}")
            self._refresh_runtime_state()
            await self.broadcast()
            return self.state

    async def approve_dispatch(self, dispatch_id: str) -> IncidentState:
        async with self.lock:
            self.logistics.approve_dispatch(self.state, dispatch_id, self.state.current_minute)
            self._append_audit(
                event_type="dispatch_approved",
                agent="OPERATOR",
                message=f"Dispatch {dispatch_id} approved",
                data={"dispatch_id": dispatch_id},
            )
            self._emit_message("OPERATOR", "LOGISTICS", f"Approved dispatch {dispatch_id}", "DIRECTIVE")
            self._refresh_runtime_state()
            await self.broadcast()
        self._trigger_pre_notification(dispatch_id, self.state.current_minute)
        return self.state

    def approve_dispatch_sync(self, dispatch_id: str) -> IncidentState:
        self.logistics.approve_dispatch(self.state, dispatch_id, self.state.current_minute)
        self._append_audit(
            event_type="dispatch_approved",
            agent="OPERATOR",
            message=f"Dispatch {dispatch_id} approved",
            data={"dispatch_id": dispatch_id},
        )
        self._emit_message("OPERATOR", "LOGISTICS", f"Approved dispatch {dispatch_id}", "DIRECTIVE")
        self._refresh_runtime_state()
        self._trigger_pre_notification(dispatch_id, self.state.current_minute)
        return self.state

    async def inject_event(self, request: InjectEventRequest) -> IncidentState:
        async with self.lock:
            self._apply_event(request.event, injected=True)
            self.hospital_intel.refresh(self.state, self.state.current_minute)
            self.logistics.recommend_dispatches(self.state, self.state.current_minute)
            self._refresh_runtime_state()
            await self.broadcast()
            return self.state

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.listeners.add(queue)
        await queue.put(self.snapshot())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        self.listeners.discard(queue)

    def snapshot(self) -> dict[str, Any]:
        baseline_current = self.state.baseline.timeline.get(str(self.state.current_minute), self.state.baseline.final_metrics)
        payload = self.state.model_dump(mode="json")
        payload["baseline"]["current"] = baseline_current.model_dump(mode="json")
        return payload

    async def broadcast(self) -> None:
        payload = self.snapshot()
        stale = []
        for queue in self.listeners:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                stale.append(queue)
        for queue in stale:
            self.listeners.discard(queue)

    async def _run(self) -> None:
        while self.is_running and self.state.current_minute < self.scenario.duration_minutes:
            await asyncio.sleep(max(0.15, 1 / self.speed))
            async with self.lock:
                if not self.is_running:
                    break
                self._process_minute(self.state.current_minute + 1)
                await self.broadcast()
        self.is_running = False

    def _process_minute(self, minute: int) -> None:
        self.state.current_minute = minute
        self.state.current_time = iso_at_minute(self.state.start_time, minute)
        self.logistics.update_ambulance_positions(self.state, minute)
        self.logistics.release_ambulances(self.state, minute)

        for event in self._events_by_minute.get(minute, []):
            self._apply_event(event)

        self.hospital_intel.refresh(self.state, minute)
        self.state.agent_health["hospital_intel"].last_updated_minute = minute
        self.state.agent_health["hospital_intel"].last_thought = "Capacity refresh completed"
        self._emit_message("HOSPITAL_INTEL", "BLACKBOARD", "Hospital capacity and staleness refreshed", "UPDATE")

        new_dispatches_before = len(self.state.dispatches)
        self.logistics.recommend_dispatches(self.state, minute)
        self.state.agent_health["logistics"].last_updated_minute = minute
        for dispatch in self.state.dispatches[new_dispatches_before:]:
            self._emit_message(
                "LOGISTICS",
                "BLACKBOARD",
                f"{dispatch.patient_id} assigned toward {dispatch.destination_hospital}",
                "UPDATE",
            )
            if dispatch.requires_ic_approval:
                self._append_audit(
                    event_type="guardrail_red_approval",
                    agent="LOGISTICS",
                    message=f"RED dispatch {dispatch.dispatch_id} queued for approval",
                    data={"dispatch_id": dispatch.dispatch_id, "patient_id": dispatch.patient_id},
                )
            if dispatch.status == DispatchStatus.EXECUTED:
                self._trigger_pre_notification(dispatch.dispatch_id, minute)

        if minute % 5 == 0 or minute in self._events_by_minute:
            sitrep = self.overwatch.generate(self.state, minute)
            self.state.sitreps.append(sitrep)
            self._append_decision(
                agent="OVERWATCH",
                message=sitrep.summary,
                severity="INFO",
                related_ids=[sitrep.sitrep_id],
            )
            self.state.agent_health["overwatch"].last_updated_minute = minute
            self._emit_message("OVERWATCH", "BLACKBOARD", sitrep.summary[:90], "UPDATE")
            if self._agent_uses_llm("overwatch"):
                user_prompt = self.overwatch.build_llm_prompt(self.state, minute)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(self._run_overwatch_llm(sitrep.sitrep_id, user_prompt, minute))
                except RuntimeError:
                    pass
            if self.orchestrator:
                coro = self._run_orchestrator(minute)
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(coro)
                except RuntimeError:
                    import threading

                    threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()

        if minute >= self.scenario.duration_minutes:
            self.state.incident_phase = IncidentPhase.RECOVERY
        elif minute > self.scenario.duration_minutes * 0.65:
            self.state.incident_phase = IncidentPhase.STABILIZING

        self._refresh_runtime_state()
        if self.state.incident_phase == IncidentPhase.RECOVERY and self.state.report_artifact is None:
            self._ensure_report_artifact()

    def _apply_event(self, event: ScenarioEvent, injected: bool = False) -> None:
        minute = self.state.current_minute
        timestamp = iso_at_minute(self.state.start_time, minute)
        if event.type == "PATIENT_REPORTED" and event.patient_id:
            patient = PatientRecord(
                patient_id=event.patient_id,
                raw_report=event.report or "",
                latest_report=event.report or "",
                reported_minute=minute,
                status=PatientStatus.REPORTED,
                ground_truth_triage=event.ground_truth_triage,
                special_notes=event.special_notes,
            )
            self.state.patients[patient.patient_id] = patient
            self._triage_patient(patient, event.report or "", minute, timestamp)
        elif event.type == "PATIENT_UPDATED" and event.patient_id and event.patient_id in self.state.patients:
            patient = self.state.patients[event.patient_id]
            patient.latest_report = event.report or patient.latest_report
            if event.ground_truth_triage:
                patient.ground_truth_triage = event.ground_truth_triage
            self._triage_patient(patient, patient.latest_report, minute, timestamp)
        elif event.type == "HOSPITAL_STATUS_CHANGED" and event.hospital_id and event.hospital_id in self.state.hospitals:
            hospital = self.state.hospitals[event.hospital_id]
            if event.status:
                hospital.status = event.status
            if event.divert_status is not None:
                hospital.divert_status = event.divert_status
            hospital.reason = event.reason
            hospital.last_updated_minute = minute
            self._release_impacted_dispatches(minute, hospital_id=hospital.hospital_id)
            self._append_decision(
                agent="HOSPITAL_INTEL",
                message=f"{hospital.name} status changed to {hospital.status}",
                severity="WARNING",
                related_ids=[hospital.hospital_id],
            )
            self._append_audit(
                event_type="hospital_status_changed",
                agent="HOSPITAL_INTEL",
                message=f"{hospital.name} status changed to {hospital.status}",
                status="WARNING",
                data={"hospital_id": hospital.hospital_id, "reason": event.reason},
            )
        elif event.type == "AMBULANCE_STATUS_CHANGED" and event.ambulance_id and event.ambulance_id in self.state.ambulances:
            ambulance = self.state.ambulances[event.ambulance_id]
            self._release_impacted_dispatches(minute, ambulance_id=ambulance.ambulance_id)
            ambulance.status = event.status or ambulance.status
            ambulance.current_patient = None
            ambulance.eta_available = None
            self._append_decision(
                agent="SIMULATION",
                message=f"{ambulance.ambulance_id} changed to {ambulance.status}: {event.reason or 'no reason supplied'}",
                severity="WARNING",
                related_ids=[ambulance.ambulance_id],
            )
            self._append_audit(
                event_type="ambulance_status_changed",
                agent="SIMULATION",
                message=f"{ambulance.ambulance_id} changed to {ambulance.status}",
                status="WARNING",
                data={"ambulance_id": ambulance.ambulance_id, "reason": event.reason},
            )
        elif event.type == "AGENT_TIMEOUT" and event.reason:
            agent_name = event.reason
            if agent_name in self.state.agent_health:
                self.state.agent_health[agent_name].status = AgentState.DEGRADED
                self.state.agent_health[agent_name].last_error = "Injected timeout"
                self._append_audit(
                    event_type="agent_timeout",
                    agent=agent_name.upper(),
                    message=f"{agent_name} marked degraded by injected timeout",
                    status="WARNING",
                )
        elif event.type == "HOSPITAL_STALE" and event.hospital_id and event.hospital_id in self.state.hospitals:
            self.state.hospitals[event.hospital_id].last_updated_minute = max(0, minute - 11)
            self._append_audit(
                event_type="guardrail_stale_hospital",
                agent="HOSPITAL_INTEL",
                message=f"{event.hospital_id} forced stale for degraded routing test",
                status="WARNING",
                data={"hospital_id": event.hospital_id},
            )

        if injected:
            self._append_decision(
                agent="OPERATOR",
                message=f"Injected event {event.type}",
                severity="INFO",
                related_ids=[event.patient_id or event.hospital_id or event.ambulance_id or event.type],
            )
            self._append_audit(
                event_type="injected_event",
                agent="OPERATOR",
                message=f"Injected event {event.type}",
                data={"event_type": event.type},
            )

    def _triage_patient(self, patient: PatientRecord, report: str, minute: int, timestamp: str) -> None:
        shadow_assessment = self._rule_based_triage.assess(patient.patient_id, report, timestamp, patient.special_notes)
        patient.shadow_triage_category = shadow_assessment.triage_category
        patient.shadow_confidence = shadow_assessment.confidence
        patient.shadow_reasoning = shadow_assessment.reasoning

        memory_summary = None
        if self.state.mode != IncidentMode.SPEED:
            memory_hits = self.memory_store.query_similar(report, patient.special_notes, k=3)
            memory_summary = self.memory_store.summarize_hits(memory_hits)

        if self._agent_uses_llm("triage") and isinstance(self.triage_agent, LLMTriageAgent):
            with llm_capture("triage", self._record_llm_event):
                assessment = self.triage_agent.assess(
                    patient.patient_id,
                    report,
                    timestamp,
                    patient.special_notes,
                    memory_context=memory_summary,
                    rule_based_assessment=shadow_assessment,
                    accuracy_review=self.state.mode == IncidentMode.ACCURACY,
                )
        else:
            assessment = shadow_assessment

        patient.triage_category = assessment.triage_category
        patient.confidence = assessment.confidence
        patient.vitals = assessment.vitals
        patient.injuries = assessment.injuries
        patient.special_flags = assessment.special_flags
        patient.needs = assessment.needs
        patient.pediatric = assessment.pediatric
        patient.review_required = assessment.review_required
        patient.data_quality_flags = assessment.data_quality_flags
        patient.memory_summary = memory_summary
        if patient.status not in {PatientStatus.DISPATCHED, PatientStatus.TRANSPORTED, PatientStatus.CLOSED}:
            patient.status = PatientStatus.TRIAGED
        patient.history.append(
            HistoryEntry(
                minute=minute,
                time=timestamp,
                event="TRIAGED",
                agent="TRIAGE",
                detail=f"{assessment.triage_category} ({assessment.confidence:.2f}) - {assessment.citation.source}",
            )
        )
        self.state.agent_health["triage"].last_updated_minute = minute
        self.state.agent_health["triage"].last_thought = assessment.reasoning[:120]
        self._append_decision(
            agent="TRIAGE",
            message=f"{patient.patient_id} classified {assessment.triage_category} ({assessment.confidence:.2f})",
            severity="WARNING" if assessment.review_required else "INFO",
            related_ids=[patient.patient_id],
        )
        self._append_audit(
            event_type="triage_decision",
            agent="TRIAGE",
            message=f"{patient.patient_id} classified {assessment.triage_category}",
            status="WARNING" if assessment.review_required else "INFO",
            data={
                "patient_id": patient.patient_id,
                "mode": _enum_value(self.state.mode),
                "shadow_triage_category": _enum_value(patient.shadow_triage_category),
                "memory_summary": memory_summary,
            },
        )
        if patient.review_required:
            self._append_audit(
                event_type="guardrail_low_confidence",
                agent="TRIAGE",
                message=f"{patient.patient_id} escalated due to low confidence",
                status="WARNING",
                data={"patient_id": patient.patient_id},
            )
        if patient.triage_category == TriageCategory.BLACK:
            self._append_audit(
                event_type="guardrail_black_hold",
                agent="TRIAGE",
                message=f"{patient.patient_id} held from dispatch after BLACK triage",
                status="WARNING",
                data={"patient_id": patient.patient_id},
            )
        self._emit_message("TRIAGE", "BLACKBOARD", f"{patient.patient_id} triaged {assessment.triage_category}", "UPDATE")
        self.memory_store.record_decision(
            {
                "incident_id": self.state.incident_id,
                "patient_id": patient.patient_id,
                "report": report,
                "triage_category": _enum_value(assessment.triage_category),
                "special_notes": patient.special_notes,
                "injuries": patient.injuries,
                "reasoning": assessment.reasoning,
                "minute": minute,
                "mode": _enum_value(self.state.mode),
            }
        )

    def _refresh_pending_dispatches(self, *, reason: str) -> None:
        active_dispatches = [
            dispatch.dispatch_id
            for dispatch in self.state.dispatches
            if dispatch.status in {DispatchStatus.PENDING_APPROVAL, DispatchStatus.APPROVED, DispatchStatus.QUEUED}
        ]
        for dispatch_id in active_dispatches:
            self.logistics.release_dispatch(self.state, dispatch_id, self.state.current_minute, reason)
            self._append_audit(
                event_type="dispatch_released",
                agent="LOGISTICS",
                message=f"Released {dispatch_id} for refresh",
                status="WARNING",
                data={"dispatch_id": dispatch_id, "reason": reason},
            )
        self.logistics.recommend_dispatches(self.state, self.state.current_minute)

    def _retriage_active_patients(self) -> None:
        minute = self.state.current_minute
        timestamp = self.state.current_time
        for patient in self.state.patients.values():
            if patient.status == PatientStatus.TRANSPORTED:
                continue
            self._triage_patient(patient, patient.latest_report, minute, timestamp)

    def _release_impacted_dispatches(
        self,
        current_minute: int,
        hospital_id: str | None = None,
        ambulance_id: str | None = None,
    ) -> None:
        impacted = [
            dispatch.dispatch_id
            for dispatch in self.state.dispatches
            if dispatch.status == DispatchStatus.PENDING_APPROVAL
            and ((hospital_id and dispatch.destination_hospital == hospital_id) or (ambulance_id and dispatch.ambulance_id == ambulance_id))
        ]
        for dispatch_id in impacted:
            reason_parts = []
            if hospital_id:
                reason_parts.append(f"hospital {hospital_id} unavailable")
            if ambulance_id:
                reason_parts.append(f"ambulance {ambulance_id} unavailable")
            reason = " and ".join(reason_parts)
            self.logistics.release_dispatch(self.state, dispatch_id, current_minute, reason)
            self._append_audit(
                event_type="dispatch_released",
                agent="LOGISTICS",
                message=f"Released {dispatch_id}: {reason}",
                status="WARNING",
                data={"dispatch_id": dispatch_id, "reason": reason},
            )

    async def _run_overwatch_llm(self, sitrep_id: str, user_prompt: str, minute: int) -> None:
        try:
            with llm_capture("overwatch", self._record_llm_event):
                summary, recommendations = await asyncio.to_thread(self.overwatch.call_llm_enrichment, user_prompt)
            if not summary:
                return
            async with self.lock:
                for sitrep in self.state.sitreps:
                    if sitrep.sitrep_id == sitrep_id:
                        sitrep.summary = summary
                        if recommendations:
                            sitrep.recommendations = recommendations
                        break
                self.state.agent_health["overwatch"].last_thought = summary[:120]
                self._refresh_runtime_state()
                await self.broadcast()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Overwatch LLM error: %s", exc)

    async def _run_orchestrator(self, minute: int) -> None:
        if self.orchestrator is None:
            return
        try:
            async with self.lock:
                if self._agent_uses_llm("orchestrator"):
                    with llm_capture("orchestrator", self._record_llm_event):
                        await self.orchestrator.run(self.state, minute, use_llm=True)
                else:
                    await self.orchestrator.run(self.state, minute, use_llm=False)
                self.state.agent_health["orchestrator"].last_updated_minute = minute
                self._refresh_runtime_state()
                await self.broadcast()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Orchestrator error: %s", exc)

    def _trigger_pre_notification(self, dispatch_id: str, minute: int) -> None:
        dispatch = next((d for d in self.state.dispatches if d.dispatch_id == dispatch_id), None)
        if not dispatch or dispatch.status != DispatchStatus.EXECUTED:
            return
        patient = self.state.patients.get(dispatch.patient_id)
        ambulance = self.state.ambulances.get(dispatch.ambulance_id)
        hospital = self.state.hospitals.get(dispatch.destination_hospital)
        if not (patient and ambulance and hospital):
            return
        notification_key = (patient.patient_id, minute)
        if any(notification for notification in self.state.pre_notifications if notification.patient_id == patient.patient_id and notification.minute == minute):
            return
        if notification_key in self._pending_pre_notifications:
            return
        timestamp = iso_at_minute(self.state.start_time, minute)
        self._pending_pre_notifications.add(notification_key)
        coro = self._async_pre_notify(patient, dispatch, ambulance, hospital, timestamp, minute, notification_key)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            asyncio.run(coro)

    async def _async_pre_notify(
        self,
        patient: PatientRecord,
        dispatch,
        ambulance,
        hospital,
        timestamp: str,
        minute: int,
        notification_key: tuple[str, int],
    ) -> None:
        try:
            notification, email_record = await self._prepare_pre_notification(
                patient,
                dispatch,
                ambulance,
                hospital,
                timestamp,
                minute,
            )
            try:
                loop = asyncio.get_running_loop()
                lock_loop = getattr(self.lock, "_loop", None)
                can_use_lock = lock_loop is None or lock_loop is loop
            except RuntimeError:
                can_use_lock = False

            if can_use_lock:
                async with self.lock:
                    self._record_pre_notification(notification, email_record, patient, hospital, dispatch, minute)
                    if self.state.incident_phase == IncidentPhase.RECOVERY:
                        self._ensure_report_artifact()
                    await self.broadcast()
            else:
                self._record_pre_notification(notification, email_record, patient, hospital, dispatch, minute)
                if self.state.incident_phase == IncidentPhase.RECOVERY:
                    self._ensure_report_artifact()
        except Exception as exc:
            import logging

            logging.getLogger(__name__).warning("Pre-notification error: %s", exc)
        finally:
            self._pending_pre_notifications.discard(notification_key)

    async def _prepare_pre_notification(
        self,
        patient: PatientRecord,
        dispatch,
        ambulance,
        hospital,
        timestamp: str,
        minute: int,
    ) -> tuple[Any, EmailDeliveryRecord]:
        if self._agent_uses_llm("pre_notification"):
            with llm_capture("pre_notification", self._record_llm_event):
                notification = await generate_pre_notification(
                    patient,
                    dispatch,
                    ambulance,
                    hospital,
                    timestamp,
                    minute,
                    use_llm=True,
                )
        else:
            notification = await generate_pre_notification(
                patient,
                dispatch,
                ambulance,
                hospital,
                timestamp,
                minute,
                use_llm=False,
            )

        notification.recipient_email = notification.recipient_email or hospital.email
        notification.pdf_artifact = generate_prealert_pdf(self.state.incident_id, notification, patient.latest_report)
        notification.pdf_path = notification.pdf_artifact.path
        message = create_email_message(notification, notification.recipient_email or "unknown@example.test", patient.latest_report)
        notification.eml_artifact = write_eml_file(self.state.incident_id, notification, message)
        notification.eml_path = notification.eml_artifact.path
        email_status, email_error = attempt_smtp_send(message)
        notification.email_status = email_status

        return notification, EmailDeliveryRecord(
            notification_id=notification.notification_id,
            hospital_id=notification.hospital_id,
            hospital_name=notification.hospital_name,
            recipient_email=notification.recipient_email or "unknown@example.test",
            subject=message["Subject"],
            status=email_status,
            minute=minute,
            timestamp=timestamp,
            eml_path=notification.eml_path,
            error=email_error,
        )

    def _record_pre_notification(
        self,
        notification,
        email_record: EmailDeliveryRecord,
        patient: PatientRecord,
        hospital,
        dispatch,
        minute: int,
    ) -> None:
        self.state.pre_notifications.append(notification)
        self.state.email_log.append(email_record)
        self.state.artifacts.extend([notification.pdf_artifact, notification.eml_artifact])
        self.state.agent_health["pre_notification"].last_updated_minute = minute
        self.state.agent_health["pre_notification"].last_thought = notification.alert_message[:120]
        self._append_decision(
            agent="PRE_NOTIFICATION",
            message=f"Hospital pre-alert sent to {hospital.name} for {patient.patient_id} (ETA {dispatch.eta_minutes}min)",
            severity="INFO",
            related_ids=[notification.notification_id, patient.patient_id],
        )
        self._append_audit(
            event_type="pre_notification_generated",
            agent="PRE_NOTIFICATION",
            message=f"Generated PDF and email draft for {patient.patient_id}",
            data={
                "notification_id": notification.notification_id,
                "email_status": notification.email_status,
                "recipient_email": notification.recipient_email,
            },
        )
        self._emit_message("PRE_NOTIFICATION", "BLACKBOARD", f"Artifacts ready for {notification.notification_id}", "ALERT")
        self._refresh_runtime_state()

    def _ensure_report_artifact(self) -> ArtifactRef:
        artifact = generate_incident_report_pdf(self.state)
        self.state.report_artifact = artifact
        if not any(existing.path == artifact.path for existing in self.state.artifacts):
            self.state.artifacts.append(artifact)
        self._append_audit(
            event_type="incident_report_generated",
            agent="OVERWATCH",
            message="Generated incident report PDF",
            data={"path": artifact.path},
        )
        return artifact

    def _append_decision(self, *, agent: str, message: str, severity: str, related_ids: list[str] | None = None) -> None:
        self.state.decision_log.append(
            DecisionLogEntry(
                minute=self.state.current_minute,
                timestamp=self.state.current_time,
                agent=agent,
                message=message,
                severity=severity,
                related_ids=related_ids or [],
            )
        )

    def _append_audit(
        self,
        *,
        event_type: str,
        agent: str,
        message: str,
        status: str = "INFO",
        data: dict[str, Any] | None = None,
    ) -> None:
        self.state.audit_log.append(
            AuditLogEntry(
                audit_id=next_id("AUD"),
                minute=self.state.current_minute,
                timestamp=self.state.current_time,
                event_type=event_type,
                agent=agent,
                message=message,
                status=status,
                data=data or {},
            )
        )

    def _emit_message(self, from_agent: str, to_agent: str, message: str, message_type: str = "UPDATE") -> None:
        self.state.agent_messages.append(
            AgentMessage(
                message_id=next_id("MSG"),
                from_agent=from_agent,
                to_agent=to_agent,
                message=message,
                minute=self.state.current_minute,
                timestamp=self.state.current_time,
                message_type=message_type,
            )
        )

    def _record_llm_event(self, agent_name: str, event: dict[str, Any]) -> None:
        agent_key = agent_name.lower()
        if agent_key not in self.state.agent_health:
            return
        health = self.state.agent_health[agent_key]
        samples = self._agent_latency_samples.setdefault(agent_key, [])
        duration_ms = float(event.get("duration_ms", 0.0))
        samples.append(duration_ms)
        latency = health.latency
        latency.last_ms = round(duration_ms, 2)
        latency.call_count += 1
        if event.get("success"):
            latency.success_count += 1
            health.status = AgentState.NOMINAL
            health.last_error = None
        else:
            latency.fallback_count += 1
            health.status = AgentState.DEGRADED
            health.last_error = str(event.get("error") or "LLM fallback engaged")
        latency.avg_ms = round(sum(samples) / len(samples), 2)
        latency.p95_ms = _p95(samples)
        health.estimated_tokens += int(event.get("input_tokens", 0)) + int(event.get("output_tokens", 0))
        health.estimated_cost_usd = round(health.estimated_cost_usd + float(event.get("cost_usd", 0.0)), 6)
        health.last_updated_minute = self.state.current_minute

    def _agent_uses_llm(self, agent_name: str) -> bool:
        return agent_name in LLM_ENABLED_AGENTS and self.state.mode != IncidentMode.SPEED

    def _refresh_agent_modes(self) -> None:
        for name, health in self.state.agent_health.items():
            health.llm_mode = self._agent_uses_llm(name)

    def _build_live_metrics(self) -> LiveMetrics:
        patients = [patient for patient in self.state.patients.values() if patient.ground_truth_triage]
        active_correct = sum(
            1
            for patient in patients
            if patient.triage_category is not None and _enum_value(patient.triage_category) == patient.ground_truth_triage
        )
        shadow_correct = sum(
            1
            for patient in patients
            if patient.shadow_triage_category is not None and _enum_value(patient.shadow_triage_category) == patient.ground_truth_triage
        )
        active_accuracy = active_correct / len(patients) if patients else 0.0
        shadow_accuracy = shadow_correct / len(patients) if patients else 0.0
        active_vs_shadow = (
            sum(
                1
                for patient in self.state.patients.values()
                if patient.triage_category is not None
                and patient.shadow_triage_category is not None
                and _enum_value(patient.triage_category) == _enum_value(patient.shadow_triage_category)
            )
            / max(
                1,
                sum(1 for patient in self.state.patients.values() if patient.triage_category is not None and patient.shadow_triage_category is not None),
            )
        )
        three_way = (
            sum(
                1
                for patient in patients
                if patient.triage_category is not None
                and patient.shadow_triage_category is not None
                and _enum_value(patient.triage_category) == patient.ground_truth_triage
                and _enum_value(patient.shadow_triage_category) == patient.ground_truth_triage
            )
            / len(patients)
            if patients
            else 0.0
        )
        lead_times = [notification.lead_time_minutes for notification in self.state.pre_notifications]
        per_agent_cost = {
            name: round(health.estimated_cost_usd, 6)
            for name, health in self.state.agent_health.items()
            if health.estimated_cost_usd
        }
        latency_delta_ms = 0.0
        if self.state.mode != IncidentMode.SPEED:
            latency_delta_ms = sum(
                health.latency.avg_ms
                for name, health in self.state.agent_health.items()
                if self._agent_uses_llm(name)
            )
        accuracy_delta = active_accuracy - shadow_accuracy
        circuit_status = get_circuit_breaker_status()
        return LiveMetrics(
            current_mode=self.state.mode,
            active_accuracy=round(active_accuracy, 3),
            shadow_accuracy=round(shadow_accuracy, 3),
            agreement=AgreementRates(
                active_vs_ground_truth=round(active_accuracy, 3),
                shadow_vs_ground_truth=round(shadow_accuracy, 3),
                active_vs_shadow=round(active_vs_shadow, 3),
                three_way_agreement=round(three_way, 3),
            ),
            per_agent_latency={name: health.latency for name, health in self.state.agent_health.items()},
            pre_notification_lead_time=LeadTimeStats(
                last_minutes=round(lead_times[-1], 2) if lead_times else 0.0,
                avg_minutes=round(sum(lead_times) / len(lead_times), 2) if lead_times else 0.0,
                p95_minutes=_p95(lead_times),
            ),
            cost_estimate=CostEstimate(
                total_usd=round(sum(per_agent_cost.values()), 6),
                by_agent=per_agent_cost,
            ),
            tradeoffs={
                "compare_mode": IncidentMode.SPEED,
                "accuracy_delta": round(accuracy_delta, 3),
                "latency_delta_ms": round(latency_delta_ms, 2),
                "summary": (
                    f"{accuracy_delta * 100:+.0f}% accuracy, +{latency_delta_ms:.0f}ms latency in {_enum_value(self.state.mode)} mode"
                    if self.state.mode != IncidentMode.SPEED
                    else "Rule-based mode: no LLM latency overhead."
                ),
            },
            circuit_breaker=circuit_status,
            emails_sent=sum(1 for email in self.state.email_log if email.status == "sent"),
            emails_total=len(self.state.email_log),
        )

    def _refresh_runtime_state(self) -> None:
        self._refresh_agent_modes()
        update_metrics(self.state)
        self.state.live_metrics = self._build_live_metrics()
        circuit = self.state.live_metrics.circuit_breaker
        degraded = self.state.mode != IncidentMode.SPEED and (not circuit.available or circuit.circuit_open)
        self.state.degraded_mode = degraded
        self.state.degraded_reason = (
            f"LLM unavailable for {_enum_value(self.state.mode)} mode; deterministic fallbacks active."
            if degraded
            else None
        )
        if degraded and not self._last_degraded_mode:
            self._append_audit(
                event_type="degraded_mode_entered",
                agent="SYSTEM",
                message=self.state.degraded_reason or "Degraded mode entered",
                status="WARNING",
                data=circuit.model_dump(mode="json"),
            )
        elif not degraded and self._last_degraded_mode:
            self._append_audit(
                event_type="degraded_mode_cleared",
                agent="SYSTEM",
                message="LLM path restored",
                data=circuit.model_dump(mode="json"),
            )
        self._last_degraded_mode = degraded
        for name, health in self.state.agent_health.items():
            if degraded and self._agent_uses_llm(name) and health.status == AgentState.NOMINAL:
                health.status = AgentState.DEGRADED
                if not health.last_error:
                    health.last_error = "Running with deterministic fallback"

    def get_notification(self, notification_id: str):
        return next((notification for notification in self.state.pre_notifications if notification.notification_id == notification_id), None)

    def get_email_record(self, notification_id: str):
        return next((email for email in self.state.email_log if email.notification_id == notification_id), None)

    def get_live_metrics(self) -> LiveMetrics:
        self._refresh_runtime_state()
        return self.state.live_metrics

    def ensure_report_artifact(self) -> ArtifactRef:
        if self.state.report_artifact is None:
            return self._ensure_report_artifact()
        return self.state.report_artifact


class SimulationManager:
    def __init__(self) -> None:
        self.rag = LlamaIndexRag()
        self.memory_store = TriageMemoryStore()
        self.rule_based_triage = TriageAgent(rag=self.rag._fallback)
        self.triage_agent: TriageAgent | LLMTriageAgent
        if is_llm_available():
            self.triage_agent = LLMTriageAgent(rag=self.rag, rule_based=self.rule_based_triage)
        else:
            self.triage_agent = self.rule_based_triage
        self.hospital_intel = HospitalIntelAgent()
        self.logistics = LogisticsAgent()
        self.overwatch = OverwatchAgent()
        self.orchestrator = OrchestratorAgent()
        self.sessions: dict[str, SimulationSession] = {}

    def start(self, scenario_id: str) -> IncidentState:
        scenario = load_scenario(scenario_id)
        session = SimulationSession(
            scenario,
            self.triage_agent,
            self.hospital_intel,
            self.logistics,
            self.overwatch,
            self.orchestrator,
            rule_based_triage=self.rule_based_triage,
            memory_store=self.memory_store,
        )
        self.sessions[session.state.incident_id] = session
        return session.state

    def get(self, incident_id: str) -> SimulationSession:
        if incident_id not in self.sessions:
            raise KeyError(f"Incident {incident_id} not found")
        return self.sessions[incident_id]
