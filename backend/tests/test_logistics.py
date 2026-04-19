from app.hospital_intel import HospitalIntelAgent
from app.logistics import LogisticsAgent
from app.models import (
    BaselineState,
    Coordinates,
    IncidentPhase,
    IncidentState,
    PatientRecord,
    PatientStatus,
    TriageCategory,
)
from app.scenario_loader import load_seed_ambulances, load_seed_hospitals


def build_state() -> IncidentState:
    return IncidentState(
        incident_id="INC-TEST",
        scenario_id="scenario",
        incident_type="STRUCTURAL_COLLAPSE",
        incident_phase=IncidentPhase.ACTIVE,
        location=Coordinates(lat=40.435, lng=-79.99, description="Scene"),
        start_time="2026-04-18T15:00:00Z",
        current_time="2026-04-18T15:00:00Z",
        current_minute=0,
        hospitals=load_seed_hospitals(),
        ambulances=load_seed_ambulances(),
        baseline=BaselineState(scenario_id="scenario"),
        agent_health={},
    )


def test_red_patient_prefers_specialty_match_and_als():
    state = build_state()
    patient = PatientRecord(
        patient_id="P-RED",
        raw_report="burn injury",
        latest_report="burn injury",
        reported_minute=0,
        triage_category=TriageCategory.RED,
        confidence=0.9,
        needs=["burn_center"],
        status=PatientStatus.TRIAGED,
    )
    state.patients[patient.patient_id] = patient
    HospitalIntelAgent().refresh(state, 0)
    recommendations = LogisticsAgent().recommend_dispatches(state, 0)
    assert recommendations
    recommendation = recommendations[0]
    assert state.ambulances[recommendation.ambulance_id].type == "ALS"
    assert recommendation.destination_hospital == "H-001"

