from __future__ import annotations

from copy import deepcopy

from .models import (
    AmbulanceStatus,
    BaselineState,
    IncidentState,
    MetricSnapshot,
    PatientRecord,
    PatientStatus,
    ScenarioDefinition,
    TriageCategory,
)
from .triage import TriageAgent
from .utils import gini, iso_at_minute


def update_metrics(state: IncidentState) -> None:
    patients = list(state.patients.values())
    by_category = {category.value: 0 for category in TriageCategory}
    dispatch_latencies: list[float] = []
    specialty_total = 0
    specialty_correct = 0

    for patient in patients:
        if patient.triage_category:
            by_category[patient.triage_category] += 1
        matching_dispatch = next((dispatch for dispatch in state.dispatches if dispatch.patient_id == patient.patient_id and dispatch.status == "EXECUTED"), None)
        if matching_dispatch and patient.triage_category:
            dispatch_latencies.append((matching_dispatch.created_minute - patient.reported_minute) * 60)
        if patient.needs and patient.assigned_hospital:
            specialty_total += 1
            hospital = state.hospitals[patient.assigned_hospital]
            if all(
                need in hospital.specialties or (need == "trauma_center" and "trauma" in hospital.specialties) or (need == "general_emergency")
                for need in patient.needs
            ):
                specialty_correct += 1

    correct_triage = sum(
        1
        for patient in patients
        if patient.triage_category is not None
        and patient.ground_truth_triage
        and getattr(patient.triage_category, "value", patient.triage_category) == patient.ground_truth_triage
    )
    transport_distribution = [
        sum(1 for patient in patients if patient.assigned_hospital == hospital_id)
        for hospital_id in state.hospitals.keys()
    ]
    mean_dispatch_latency = sum(dispatch_latencies) / len(dispatch_latencies) if dispatch_latencies else 0.0
    triage_accuracy = correct_triage / len([patient for patient in patients if patient.ground_truth_triage]) if patients else 0.0
    transport_match = specialty_correct / specialty_total if specialty_total else 0.0
    hospital_gini = gini(transport_distribution)
    inverse_transport_component = max(0.0, 1 - mean_dispatch_latency / 300)
    survival_proxy = (
        triage_accuracy * 0.3
        + transport_match * 0.3
        + inverse_transport_component * 0.2
        + (1 - hospital_gini) * 0.2
    )

    state.metrics = MetricSnapshot(
        total_patients=len(patients),
        by_category=by_category,
        transported=sum(1 for patient in patients if patient.status == PatientStatus.TRANSPORTED),
        awaiting_dispatch=sum(
            1 for patient in patients if patient.status in {PatientStatus.TRIAGED, PatientStatus.AWAITING_DISPATCH, PatientStatus.AWAITING_APPROVAL}
        ),
        mean_dispatch_latency_sec=round(mean_dispatch_latency, 1),
        hospital_load_gini=round(hospital_gini, 3),
        triage_accuracy=round(triage_accuracy, 3),
        transport_match_score=round(transport_match, 3),
        survival_proxy_score=round(survival_proxy, 3),
    )


def simulate_baseline(state: IncidentState, scenario: ScenarioDefinition, triage_agent: TriageAgent) -> BaselineState:
    working_state = deepcopy(state)
    timeline: dict[str, MetricSnapshot] = {}

    for minute in range(scenario.duration_minutes + 1):
        for ambulance in working_state.ambulances.values():
            if ambulance.status == AmbulanceStatus.EN_ROUTE and ambulance.eta_available is not None and ambulance.eta_available <= minute:
                ambulance.status = AmbulanceStatus.AVAILABLE
                if ambulance.current_patient and ambulance.current_patient in working_state.patients:
                    working_state.patients[ambulance.current_patient].status = PatientStatus.TRANSPORTED
                ambulance.current_patient = None
                ambulance.eta_available = None

        for event in [item for item in scenario.events if item.minute == minute]:
            if event.type == "PATIENT_REPORTED":
                assessment = triage_agent.assess(
                    patient_id=event.patient_id or "UNKNOWN",
                    report=event.report or "",
                    timestamp=iso_at_minute(working_state.start_time, minute),
                    special_notes=event.special_notes,
                )
                working_state.patients[event.patient_id] = PatientRecord(
                    patient_id=event.patient_id,
                    raw_report=event.report or "",
                    latest_report=event.report or "",
                    reported_minute=minute,
                    triage_category=assessment.triage_category,
                    confidence=assessment.confidence,
                    vitals=assessment.vitals,
                    injuries=assessment.injuries,
                    special_flags=assessment.special_flags,
                    needs=assessment.needs,
                    pediatric=assessment.pediatric,
                    review_required=assessment.review_required,
                    data_quality_flags=assessment.data_quality_flags,
                    status=PatientStatus.TRIAGED,
                    ground_truth_triage=event.ground_truth_triage,
                    special_notes=event.special_notes,
                )
            elif event.type == "PATIENT_UPDATED" and event.patient_id in working_state.patients:
                patient = working_state.patients[event.patient_id]
                assessment = triage_agent.assess(
                    patient_id=patient.patient_id,
                    report=event.report or patient.latest_report,
                    timestamp=iso_at_minute(working_state.start_time, minute),
                    special_notes=patient.special_notes,
                )
                patient.latest_report = event.report or patient.latest_report
                patient.triage_category = assessment.triage_category
                patient.confidence = assessment.confidence
                patient.vitals = assessment.vitals
                patient.injuries = assessment.injuries
                patient.special_flags = assessment.special_flags
                patient.needs = assessment.needs

        available = sorted(
            [ambulance for ambulance in working_state.ambulances.values() if ambulance.status == AmbulanceStatus.AVAILABLE],
            key=lambda ambulance: (ambulance.type != "ALS", ambulance.ambulance_id),
        )
        candidates = sorted(
            [
                patient
                for patient in working_state.patients.values()
                if patient.triage_category and patient.triage_category != TriageCategory.BLACK and patient.status == PatientStatus.TRIAGED
            ],
            key=lambda patient: (
                -({"RED": 3, "YELLOW": 2, "GREEN": 1}[getattr(patient.triage_category, "value", patient.triage_category)]),
                patient.reported_minute,
                patient.patient_id,
            ),
        )

        for patient in candidates:
            if not available:
                break
            ambulance = available.pop(0 if patient.triage_category != TriageCategory.RED else 0)
            nearest_hospital = min(working_state.hospitals.values(), key=lambda hospital: hospital.eta_from_scene_minutes)
            patient.status = PatientStatus.DISPATCHED
            patient.assigned_ambulance = ambulance.ambulance_id
            patient.assigned_hospital = nearest_hospital.hospital_id
            ambulance.status = AmbulanceStatus.EN_ROUTE
            ambulance.current_patient = patient.patient_id
            ambulance.eta_available = minute + nearest_hospital.eta_from_scene_minutes * 2 + 5

        working_state.current_minute = minute
        update_metrics(working_state)
        timeline[str(minute)] = deepcopy(working_state.metrics)

    return BaselineState(
        scenario_id=scenario.scenario_id,
        current_minute=0,
        final_metrics=deepcopy(working_state.metrics),
        timeline=timeline,
    )
