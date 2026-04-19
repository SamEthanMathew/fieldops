from __future__ import annotations

import logging
from dataclasses import dataclass

from .models import (
    AlternativeOption,
    AmbulanceRecord,
    AmbulanceStatus,
    DecisionLogEntry,
    DispatchRecommendation,
    DispatchStatus,
    HistoryEntry,
    HospitalRecord,
    HospitalStatus,
    IncidentState,
    PatientRecord,
    PatientStatus,
    TriageCategory,
)
from .utils import clamp, iso_at_minute, next_id

logger = logging.getLogger(__name__)


SEVERITY_PRIORITY = {
    TriageCategory.RED: 3,
    TriageCategory.YELLOW: 2,
    TriageCategory.GREEN: 1,
    TriageCategory.BLACK: 0,
}


@dataclass
class Candidate:
    hospital: HospitalRecord
    ambulance: AmbulanceRecord
    score: float
    reason: str


class LogisticsAgent:
    def recommend_dispatches(self, state: IncidentState, current_minute: int) -> list[DispatchRecommendation]:
        recommendations: list[DispatchRecommendation] = []
        candidate_ambulances = self._candidate_ambulances(state, current_minute)
        patients = self._dispatchable_patients(state)

        for patient in patients:
            if not candidate_ambulances:
                break
            candidates = self._score_candidates(state, patient, candidate_ambulances, list(state.hospitals.values()), current_minute)
            if not candidates:
                continue
            chosen = candidates[0]
            alternatives = self._build_alternatives(candidates)
            severity = patient.triage_category or TriageCategory.GREEN
            confidence = clamp((chosen.score + 40) / 100, 0.45, 0.96)
            requires_approval = severity == TriageCategory.RED or (
                severity == TriageCategory.YELLOW and (patient.confidence or 0.0) < 0.7
            )

            recommendation = DispatchRecommendation(
                dispatch_id=next_id("D"),
                patient_id=patient.patient_id,
                ambulance_id=chosen.ambulance.ambulance_id,
                destination_hospital=chosen.hospital.hospital_id,
                priority="IMMEDIATE" if severity == TriageCategory.RED else "ROUTINE",
                eta_minutes=chosen.hospital.eta_from_scene_minutes,
                reasoning=self._build_reasoning(patient, chosen, alternatives[1:]),
                alternatives_considered=alternatives,
                confidence=confidence,
                requires_ic_approval=requires_approval,
                status=DispatchStatus.PENDING_APPROVAL if requires_approval else DispatchStatus.EXECUTED,
                created_minute=current_minute,
            )
            state.dispatches.append(recommendation)
            self._reserve_assignment(state, patient.patient_id, chosen.ambulance.ambulance_id, chosen.hospital.hospital_id, current_minute)
            state.decision_log.append(
                DecisionLogEntry(
                    minute=current_minute,
                    timestamp=iso_at_minute(state.start_time, current_minute),
                    agent="LOGISTICS",
                    message=f"Recommended {patient.patient_id} -> {chosen.hospital.name} via {chosen.ambulance.ambulance_id}",
                    severity="INFO",
                    related_ids=[patient.patient_id, recommendation.dispatch_id],
                )
            )
            if requires_approval:
                patient.status = PatientStatus.AWAITING_APPROVAL
                if recommendation.dispatch_id not in state.pending_approvals:
                    state.pending_approvals.append(recommendation.dispatch_id)
            else:
                self.execute_dispatch(state, recommendation.dispatch_id, current_minute, approved=False)
            recommendations.append(recommendation)
            candidate_ambulances = self._candidate_ambulances(state, current_minute)
        return recommendations

    def approve_dispatch(self, state: IncidentState, dispatch_id: str, current_minute: int) -> DispatchRecommendation:
        dispatch = self._find_dispatch(state, dispatch_id)
        dispatch.status = DispatchStatus.APPROVED
        dispatch.approved_minute = current_minute
        self.execute_dispatch(state, dispatch_id, current_minute, approved=True)
        return dispatch

    def execute_dispatch(self, state: IncidentState, dispatch_id: str, current_minute: int, approved: bool) -> None:
        dispatch = self._find_dispatch(state, dispatch_id)
        patient = state.patients[dispatch.patient_id]
        ambulance = state.ambulances[dispatch.ambulance_id]
        hospital = state.hospitals[dispatch.destination_hospital]

        if dispatch_id in state.pending_approvals:
            state.pending_approvals.remove(dispatch_id)
        dispatch.status = DispatchStatus.EXECUTED
        if ambulance.status == AmbulanceStatus.EN_ROUTE and ambulance.current_patient:
            dispatch.status = DispatchStatus.QUEUED
            if dispatch.dispatch_id not in ambulance.queued_dispatch_ids:
                ambulance.queued_dispatch_ids.append(dispatch.dispatch_id)
            patient.status = PatientStatus.AWAITING_DISPATCH
            state.decision_log.append(
                DecisionLogEntry(
                    minute=current_minute,
                    timestamp=iso_at_minute(state.start_time, current_minute),
                    agent="LOGISTICS",
                    message=f"Queued dispatch {dispatch.dispatch_id} behind {ambulance.current_patient} on {ambulance.ambulance_id}",
                    severity="INFO",
                    related_ids=[dispatch.dispatch_id, patient.patient_id, ambulance.ambulance_id],
                )
            )
        else:
            self._start_dispatch_trip(state, dispatch, current_minute)

        state.decision_log.append(
            DecisionLogEntry(
                minute=current_minute,
                timestamp=iso_at_minute(state.start_time, current_minute),
                agent="LOGISTICS",
                message=(
                    f"{'Approved and a' if approved else 'A'}ctivated dispatch {dispatch.dispatch_id} "
                    f"for {patient.patient_id} to {hospital.name}"
                ),
                severity="INFO",
                related_ids=[dispatch.dispatch_id, patient.patient_id, ambulance.ambulance_id],
            )
        )

    def update_ambulance_positions(self, state: IncidentState, current_minute: int) -> None:
        """Interpolate en-route ambulance positions toward their destination hospital."""
        for ambulance in state.ambulances.values():
            if ambulance.status != AmbulanceStatus.EN_ROUTE or not ambulance.current_patient:
                continue
            patient = state.patients.get(ambulance.current_patient)
            if not patient or not patient.assigned_hospital:
                continue
            hospital = state.hospitals.get(patient.assigned_hospital)
            if not hospital:
                continue
            # Move 15% of remaining distance each minute for smooth animation
            dlat = hospital.location.lat - ambulance.position.lat
            dlng = hospital.location.lng - ambulance.position.lng
            ambulance.position.lat = round(ambulance.position.lat + dlat * 0.15, 6)
            ambulance.position.lng = round(ambulance.position.lng + dlng * 0.15, 6)

    def release_ambulances(self, state: IncidentState, current_minute: int) -> None:
        for ambulance in state.ambulances.values():
            if ambulance.status == AmbulanceStatus.EN_ROUTE and ambulance.eta_available is not None and ambulance.eta_available <= current_minute:
                patient_id = ambulance.current_patient
                if patient_id and patient_id in state.patients:
                    state.patients[patient_id].status = PatientStatus.TRANSPORTED
                ambulance.history.append(
                    HistoryEntry(
                        minute=current_minute,
                        time=iso_at_minute(state.start_time, current_minute),
                        event="AVAILABLE",
                        agent="SIMULATION",
                        detail="Returned to service",
                    )
                )
                next_dispatch = ambulance.queued_dispatch_ids.pop(0) if ambulance.queued_dispatch_ids else None
                ambulance.current_patient = None
                ambulance.eta_available = None
                if next_dispatch:
                    self._start_dispatch_trip(state, self._find_dispatch(state, next_dispatch), current_minute)
                else:
                    ambulance.status = AmbulanceStatus.AVAILABLE

    def release_dispatch(self, state: IncidentState, dispatch_id: str, current_minute: int, reason: str) -> None:
        dispatch = self._find_dispatch(state, dispatch_id)
        if dispatch.status not in {DispatchStatus.PENDING_APPROVAL, DispatchStatus.APPROVED, DispatchStatus.QUEUED}:
            return
        patient = state.patients[dispatch.patient_id]
        ambulance = state.ambulances[dispatch.ambulance_id]
        hospital = state.hospitals[dispatch.destination_hospital]
        dispatch.status = DispatchStatus.RELEASED
        if dispatch_id in state.pending_approvals:
            state.pending_approvals.remove(dispatch_id)
        if dispatch_id in ambulance.queued_dispatch_ids:
            ambulance.queued_dispatch_ids = [item for item in ambulance.queued_dispatch_ids if item != dispatch_id]
        if ambulance.status == AmbulanceStatus.RESERVED and ambulance.current_patient == patient.patient_id:
            ambulance.status = AmbulanceStatus.AVAILABLE
            ambulance.current_patient = None
            ambulance.eta_available = None
        if patient.assigned_hospital == hospital.hospital_id:
            hospital.capacity.available_beds = min(hospital.capacity.total_beds, hospital.capacity.available_beds + 1)
            hospital.last_updated_minute = current_minute
        patient.assigned_ambulance = None
        patient.assigned_hospital = None
        patient.status = PatientStatus.AWAITING_DISPATCH
        patient.history.append(
            HistoryEntry(
                minute=current_minute,
                time=iso_at_minute(state.start_time, current_minute),
                event="REQUEUED",
                agent="LOGISTICS",
                detail=reason,
            )
        )
        state.decision_log.append(
            DecisionLogEntry(
                minute=current_minute,
                timestamp=iso_at_minute(state.start_time, current_minute),
                agent="LOGISTICS",
                message=f"Released {dispatch.dispatch_id} for {patient.patient_id}: {reason}",
                severity="WARNING",
                related_ids=[dispatch.dispatch_id, patient.patient_id],
            )
        )

    @staticmethod
    def _find_dispatch(state: IncidentState, dispatch_id: str) -> DispatchRecommendation:
        for dispatch in state.dispatches:
            if dispatch.dispatch_id == dispatch_id:
                return dispatch
        raise KeyError(f"Dispatch {dispatch_id} not found")

    @staticmethod
    def _candidate_ambulances(state: IncidentState, current_minute: int) -> list[AmbulanceRecord]:
        return sorted(
            [
                ambulance
                for ambulance in state.ambulances.values()
                if ambulance.status in {AmbulanceStatus.AVAILABLE, AmbulanceStatus.EN_ROUTE}
                and len(ambulance.queued_dispatch_ids) == 0
                and (ambulance.status == AmbulanceStatus.AVAILABLE or (ambulance.eta_available is not None and ambulance.eta_available - current_minute <= 12))
            ],
            key=lambda ambulance: (
                ambulance.type != "ALS",
                ambulance.status != AmbulanceStatus.AVAILABLE,
                ambulance.eta_available or current_minute,
                ambulance.ambulance_id,
            ),
        )

    @staticmethod
    def _dispatchable_patients(state: IncidentState) -> list[PatientRecord]:
        patients = [
            patient
            for patient in state.patients.values()
            if patient.triage_category
            and patient.triage_category != TriageCategory.BLACK
            and patient.status in {PatientStatus.TRIAGED, PatientStatus.AWAITING_DISPATCH}
            and not patient.assigned_ambulance
        ]
        return sorted(
            patients,
            key=lambda patient: (-SEVERITY_PRIORITY[patient.triage_category], patient.reported_minute, patient.patient_id),
        )

    def _score_candidates(
        self,
        state: IncidentState,
        patient: PatientRecord,
        ambulances: list[AmbulanceRecord],
        hospitals: list[HospitalRecord],
        current_minute: int,
    ) -> list[Candidate]:
        severity = patient.triage_category or TriageCategory.GREEN
        severity_weight = SEVERITY_PRIORITY[severity]
        distribution = self._assignment_counts(state)
        candidates: list[Candidate] = []
        for ambulance in ambulances:
            if severity == TriageCategory.RED and ambulance.type != "ALS":
                continue
            for hospital in hospitals:
                if hospital.status in {HospitalStatus.CLOSED, HospitalStatus.DIVERT} or hospital.divert_status:
                    continue
                if hospital.capacity.available_beds <= 0:
                    continue
                match_score, mismatch_reason = self._specialty_match(patient, hospital)
                trauma_bonus = max(0, 4 - hospital.trauma_level) * 4
                if self._preserve_tertiary_capacity(patient, hospital):
                    trauma_bonus -= 24
                elif patient.triage_category in {TriageCategory.GREEN, TriageCategory.YELLOW} and hospital.trauma_level >= 2:
                    trauma_bonus += 6
                projected_load = 1 - ((hospital.capacity.available_beds - 1) / max(hospital.capacity.total_beds, 1))
                load_penalty = hospital.current_load_pct * 18 + projected_load * 26
                balance_penalty = distribution.get(hospital.hospital_id, 0) * 10
                als_bonus = 8 if severity == TriageCategory.RED and ambulance.type == "ALS" else 0
                unknown_penalty = 12 if hospital.status == HospitalStatus.UNKNOWN else 0
                queue_wait = max(0, (ambulance.eta_available or current_minute) - current_minute) if ambulance.status != AmbulanceStatus.AVAILABLE else 0
                queue_penalty = queue_wait * (3 if severity == TriageCategory.RED else 1.5)
                eta_penalty = hospital.eta_from_scene_minutes * (3 if severity == TriageCategory.RED else 2)
                score = severity_weight * 34 + trauma_bonus + match_score + als_bonus - eta_penalty - load_penalty - balance_penalty - unknown_penalty - queue_penalty
                reason = mismatch_reason or f"ETA {hospital.eta_from_scene_minutes} min, load {hospital.current_load_pct:.0%}, ambulance wait {queue_wait} min"
                candidates.append(Candidate(hospital=hospital, ambulance=ambulance, score=score, reason=reason))
        return sorted(candidates, key=lambda candidate: candidate.score, reverse=True)

    @staticmethod
    def _specialty_match(patient: PatientRecord, hospital: HospitalRecord) -> tuple[float, str]:
        needs = patient.needs or ["general_emergency"]
        specialties = set(hospital.specialties)
        matched = sum(1 for need in needs if need in specialties or (need == "trauma_center" and "trauma" in specialties))
        missing = [need for need in needs if need not in specialties and not (need == "trauma_center" and "trauma" in specialties)]
        if matched == len(needs):
            return 18 + matched * 3, ""
        if missing:
            return -20.0, "Missing specialty support: " + ", ".join(missing)
        return 0.0, ""

    @staticmethod
    def _build_alternatives(candidates: list[Candidate]) -> list[AlternativeOption]:
        alternatives: list[AlternativeOption] = []
        seen_hospitals: set[str] = set()
        for candidate in candidates:
            if candidate.hospital.hospital_id in seen_hospitals:
                continue
            seen_hospitals.add(candidate.hospital.hospital_id)
            alternatives.append(
                AlternativeOption(
                    hospital_id=candidate.hospital.hospital_id,
                    hospital_name=candidate.hospital.name,
                    score=round(candidate.score, 2),
                    reason_rejected="Higher-ranked candidate selected." if alternatives else "Top candidate selected.",
                )
            )
            if len(alternatives) == 3:
                break
        return alternatives

    @staticmethod
    def _preserve_tertiary_capacity(patient: PatientRecord, hospital: HospitalRecord) -> bool:
        needs = set(patient.needs)
        low_acuity = patient.triage_category in {TriageCategory.GREEN, TriageCategory.YELLOW}
        no_rare_specialty = needs.issubset({"general_emergency", "trauma_center", "orthopedic_surgery"})
        return low_acuity and hospital.trauma_level == 1 and no_rare_specialty

    @staticmethod
    def _assignment_counts(state: IncidentState) -> dict[str, int]:
        counts: dict[str, int] = {}
        for patient in state.patients.values():
            if patient.assigned_hospital:
                counts[patient.assigned_hospital] = counts.get(patient.assigned_hospital, 0) + 1
        return counts

    @staticmethod
    def _reserve_assignment(
        state: IncidentState,
        patient_id: str,
        ambulance_id: str,
        hospital_id: str,
        current_minute: int,
    ) -> None:
        patient = state.patients[patient_id]
        ambulance = state.ambulances[ambulance_id]
        hospital = state.hospitals[hospital_id]
        patient.assigned_ambulance = ambulance_id
        patient.assigned_hospital = hospital_id
        if ambulance.status == AmbulanceStatus.AVAILABLE:
            ambulance.status = AmbulanceStatus.RESERVED
            ambulance.current_patient = patient_id
            ambulance.eta_available = None
        hospital.capacity.available_beds = max(0, hospital.capacity.available_beds - 1)
        hospital.last_updated_minute = current_minute

    @staticmethod
    def _start_dispatch_trip(state: IncidentState, dispatch: DispatchRecommendation, current_minute: int) -> None:
        patient = state.patients[dispatch.patient_id]
        ambulance = state.ambulances[dispatch.ambulance_id]
        hospital = state.hospitals[dispatch.destination_hospital]
        patient.status = PatientStatus.DISPATCHED
        patient.history.append(
            HistoryEntry(
                minute=current_minute,
                time=iso_at_minute(state.start_time, current_minute),
                event="DISPATCHED",
                agent="LOGISTICS",
                detail=f"Assigned {ambulance.ambulance_id} -> {hospital.hospital_id}",
            )
        )
        ambulance.status = AmbulanceStatus.EN_ROUTE
        ambulance.current_patient = patient.patient_id
        ambulance.eta_available = current_minute + dispatch.eta_minutes + 4 + max(4, dispatch.eta_minutes // 2)
        hospital.last_updated_minute = current_minute
        hospital.divert_status = hospital.capacity.available_beds == 0
        if hospital.divert_status:
            hospital.status = HospitalStatus.DIVERT

    @staticmethod
    def _build_reasoning(
        patient: PatientRecord,
        chosen: Candidate,
        alternatives: list[AlternativeOption],
    ) -> str:
        category = patient.triage_category or TriageCategory.GREEN
        category_label = getattr(category, "value", category)
        reasons = [
            f"Patient {patient.patient_id} is {category_label}",
            f"{chosen.hospital.name} has ETA {chosen.hospital.eta_from_scene_minutes} minutes",
            f"hospital load is {chosen.hospital.current_load_pct:.0%}",
        ]
        if patient.needs:
            reasons.append("needs " + ", ".join(patient.needs))
        if alternatives:
            reasons.append("alternatives were rejected for capacity, specialty, or ETA reasons")
        return ". ".join(reasons) + "."
