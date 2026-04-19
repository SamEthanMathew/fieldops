from __future__ import annotations

import asyncio
import os
from copy import deepcopy
from typing import Any

from .evaluation import simulate_baseline, update_metrics
from .hospital_intel import HospitalIntelAgent
from .llamaindex_rag import LlamaIndexRag
from .llm_client import is_llm_available
from .llm_triage import LLMTriageAgent
from .logistics import LogisticsAgent
from .models import (
    AgentHealth,
    AgentMessage,
    AgentState,
    BaselineState,
    DecisionLogEntry,
    HistoryEntry,
    IncidentPhase,
    IncidentState,
    InjectEventRequest,
    PatientRecord,
    PatientStatus,
    ScenarioControlRequest,
    ScenarioDefinition,
    ScenarioEvent,
)
from .orchestrator import OrchestratorAgent
from .overwatch import OverwatchAgent
from .pre_notification import generate_pre_notification
from .rag import LocalProtocolRag
from .scenario_loader import load_scenario, load_seed_ambulances, load_seed_hospitals
from .triage import TriageAgent
from .utils import iso_at_minute, next_id


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
    ) -> None:
        self.scenario = scenario
        self.triage_agent = triage_agent
        self.hospital_intel = hospital_intel
        self.logistics = logistics
        self.overwatch = overwatch
        self.orchestrator = orchestrator
        self._rule_based_triage = rule_based_triage or (triage_agent if isinstance(triage_agent, TriageAgent) else None)
        self.speed = 1.0
        self.is_running = False
        self.lock = asyncio.Lock()
        self.listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self.worker: asyncio.Task[None] | None = None
        incident_id = next_id("INC")
        self.state = IncidentState(
            incident_id=incident_id,
            scenario_id=scenario.scenario_id,
            incident_type=scenario.incident_type,
            incident_phase=IncidentPhase.ACTIVE,
            location=scenario.scene,
            start_time="2026-04-18T15:00:00Z",
            current_time="2026-04-18T15:00:00Z",
            current_minute=0,
            hospitals=load_seed_hospitals(),
            ambulances=load_seed_ambulances(),
            baseline=BaselineState(scenario_id=scenario.scenario_id),
            agent_health={
                "triage": AgentHealth(status=AgentState.NOMINAL, last_updated_minute=0, llm_mode=is_llm_available()),
                "hospital_intel": AgentHealth(status=AgentState.NOMINAL, last_updated_minute=0, llm_mode=False),
                "logistics": AgentHealth(status=AgentState.NOMINAL, last_updated_minute=0, llm_mode=False),
                "overwatch": AgentHealth(status=AgentState.NOMINAL, last_updated_minute=0, llm_mode=False),
                "pre_notification": AgentHealth(status=AgentState.NOMINAL, last_updated_minute=0, llm_mode=is_llm_available()),
                "orchestrator": AgentHealth(status=AgentState.NOMINAL, last_updated_minute=0, llm_mode=is_llm_available()),
            },
            meta={"duration_minutes": scenario.duration_minutes, "scenario_name": scenario.name},
        )
        baseline_triage = self._rule_based_triage or (triage_agent if isinstance(triage_agent, TriageAgent) else triage_agent)
        self.state.baseline = simulate_baseline(deepcopy(self.state), scenario, baseline_triage)
        self._process_minute(0)

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
                    self.scenario, self.triage_agent, self.hospital_intel,
                    self.logistics, self.overwatch, self.orchestrator,
                    rule_based_triage=self._rule_based_triage,
                )
                self.state = new_session.state
                self.speed = 1.0
            await self.broadcast()
            return self.state

    async def approve_dispatch(self, dispatch_id: str) -> IncidentState:
        async with self.lock:
            self.logistics.approve_dispatch(self.state, dispatch_id, self.state.current_minute)
            update_metrics(self.state)
            await self.broadcast()
        self._trigger_pre_notification(dispatch_id, self.state.current_minute)
        return self.state

    async def inject_event(self, request: InjectEventRequest) -> IncidentState:
        async with self.lock:
            self._apply_event(request.event, injected=True)
            self.hospital_intel.refresh(self.state, self.state.current_minute)
            self.logistics.recommend_dispatches(self.state, self.state.current_minute)
            update_metrics(self.state)
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
        for event in [event for event in self.scenario.events if event.minute == minute]:
            self._apply_event(event)

        self.hospital_intel.refresh(self.state, minute)
        self.state.agent_health["hospital_intel"].last_updated_minute = minute
        new_dispatches_before = len(self.state.dispatches)
        self.logistics.recommend_dispatches(self.state, minute)
        self.state.agent_health["logistics"].last_updated_minute = minute
        for dispatch in self.state.dispatches[new_dispatches_before:]:
            if dispatch.status == "EXECUTED":
                self._trigger_pre_notification(dispatch.dispatch_id, minute)
        if minute % 5 == 0 or any(event.minute == minute for event in self.scenario.events):
            sitrep = self.overwatch.generate(self.state, minute)
            self.state.sitreps.append(sitrep)
            self.state.decision_log.append(
                DecisionLogEntry(
                    minute=minute,
                    timestamp=self.state.current_time,
                    agent="OVERWATCH",
                    message=sitrep.summary,
                    severity="INFO",
                    related_ids=[sitrep.sitrep_id],
                )
            )
            self.state.agent_health["overwatch"].last_updated_minute = minute
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
        update_metrics(self.state)

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
            self.state.decision_log.append(
                DecisionLogEntry(
                    minute=minute,
                    timestamp=timestamp,
                    agent="HOSPITAL_INTEL",
                    message=f"{hospital.name} status changed to {hospital.status}",
                    severity="WARNING",
                    related_ids=[hospital.hospital_id],
                )
            )
        elif event.type == "AMBULANCE_STATUS_CHANGED" and event.ambulance_id and event.ambulance_id in self.state.ambulances:
            ambulance = self.state.ambulances[event.ambulance_id]
            self._release_impacted_dispatches(minute, ambulance_id=ambulance.ambulance_id)
            ambulance.status = event.status or ambulance.status
            ambulance.current_patient = None
            ambulance.eta_available = None
            self.state.decision_log.append(
                DecisionLogEntry(
                    minute=minute,
                    timestamp=timestamp,
                    agent="SIMULATION",
                    message=f"{ambulance.ambulance_id} changed to {ambulance.status}: {event.reason or 'no reason supplied'}",
                    severity="WARNING",
                    related_ids=[ambulance.ambulance_id],
                )
            )
        elif event.type == "AGENT_TIMEOUT" and event.reason:
            agent_name = event.reason
            if agent_name in self.state.agent_health:
                self.state.agent_health[agent_name].status = AgentState.DEGRADED
                self.state.agent_health[agent_name].last_error = "Injected timeout"
        elif event.type == "HOSPITAL_STALE" and event.hospital_id and event.hospital_id in self.state.hospitals:
            self.state.hospitals[event.hospital_id].last_updated_minute = max(0, minute - 11)

        if injected:
            self.state.decision_log.append(
                DecisionLogEntry(
                    minute=minute,
                    timestamp=timestamp,
                    agent="OPERATOR",
                    message=f"Injected event {event.type}",
                    severity="INFO",
                    related_ids=[event.patient_id or event.hospital_id or event.ambulance_id or event.type],
                )
            )

    def _triage_patient(self, patient: PatientRecord, report: str, minute: int, timestamp: str) -> None:
        assessment = self.triage_agent.assess(patient.patient_id, report, timestamp, patient.special_notes)
        patient.triage_category = assessment.triage_category
        patient.confidence = assessment.confidence
        patient.vitals = assessment.vitals
        patient.injuries = assessment.injuries
        patient.special_flags = assessment.special_flags
        patient.needs = assessment.needs
        patient.pediatric = assessment.pediatric
        patient.review_required = assessment.review_required
        patient.data_quality_flags = assessment.data_quality_flags
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
        self.state.decision_log.append(
            DecisionLogEntry(
                minute=minute,
                timestamp=timestamp,
                agent="TRIAGE",
                message=f"{patient.patient_id} classified {assessment.triage_category} ({assessment.confidence:.2f})",
                severity="WARNING" if assessment.review_required else "INFO",
                related_ids=[patient.patient_id],
            )
        )

    def _release_impacted_dispatches(
        self,
        current_minute: int,
        hospital_id: str | None = None,
        ambulance_id: str | None = None,
    ) -> None:
        impacted = [
            dispatch.dispatch_id
            for dispatch in self.state.dispatches
            if dispatch.status == "PENDING_APPROVAL"
            and ((hospital_id and dispatch.destination_hospital == hospital_id) or (ambulance_id and dispatch.ambulance_id == ambulance_id))
        ]
        for dispatch_id in impacted:
            reason_parts = []
            if hospital_id:
                reason_parts.append(f"hospital {hospital_id} unavailable")
            if ambulance_id:
                reason_parts.append(f"ambulance {ambulance_id} unavailable")
            self.logistics.release_dispatch(self.state, dispatch_id, current_minute, " and ".join(reason_parts))

    async def _run_orchestrator(self, minute: int) -> None:
        if self.orchestrator is None:
            return
        try:
            async with self.lock:
                await self.orchestrator.run(self.state, minute)
                self.state.agent_health["orchestrator"].last_updated_minute = minute
                await self.broadcast()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Orchestrator error: %s", exc)

    def _trigger_pre_notification(self, dispatch_id: str, minute: int) -> None:
        dispatch = next((d for d in self.state.dispatches if d.dispatch_id == dispatch_id), None)
        if not dispatch:
            return
        patient = self.state.patients.get(dispatch.patient_id)
        ambulance = self.state.ambulances.get(dispatch.ambulance_id)
        hospital = self.state.hospitals.get(dispatch.destination_hospital)
        if not (patient and ambulance and hospital):
            return
        timestamp = iso_at_minute(self.state.start_time, minute)
        coro = self._async_pre_notify(patient, dispatch, ambulance, hospital, timestamp, minute)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            import threading
            threading.Thread(target=lambda: asyncio.run(coro), daemon=True).start()

    async def _async_pre_notify(self, patient, dispatch, ambulance, hospital, timestamp, minute) -> None:
        try:
            notification = await generate_pre_notification(patient, dispatch, ambulance, hospital, timestamp, minute)
            async with self.lock:
                self.state.pre_notifications.append(notification)
                self.state.agent_health["pre_notification"].last_updated_minute = minute
                self.state.agent_health["pre_notification"].last_thought = notification.alert_message[:120]
                self.state.decision_log.append(
                    DecisionLogEntry(
                        minute=minute,
                        timestamp=timestamp,
                        agent="PRE_NOTIFICATION",
                        message=f"Hospital pre-alert sent to {hospital.name} for {patient.patient_id} (ETA {dispatch.eta_minutes}min)",
                        severity="INFO",
                        related_ids=[notification.notification_id, patient.patient_id],
                    )
                )
                await self.broadcast()
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Pre-notification error: %s", exc)


class SimulationManager:
    def __init__(self) -> None:
        self.rag = LlamaIndexRag()
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
            scenario, self.triage_agent, self.hospital_intel,
            self.logistics, self.overwatch, self.orchestrator,
            rule_based_triage=self.rule_based_triage,
        )
        self.sessions[session.state.incident_id] = session
        return session.state

    def get(self, incident_id: str) -> SimulationSession:
        if incident_id not in self.sessions:
            raise KeyError(f"Incident {incident_id} not found")
        return self.sessions[incident_id]
