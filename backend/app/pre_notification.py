from __future__ import annotations

import logging

from .llm_client import call_llm, extract_xml_tag, is_llm_available
from .models import (
    AmbulanceRecord,
    DispatchRecommendation,
    HospitalRecord,
    PatientRecord,
    PreHospitalNotification,
)
from .utils import next_id

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are an ambulance pre-notification AI in a Mass Casualty Incident.
When an ambulance is dispatched, you alert the receiving hospital BEFORE the patient arrives.
This allows the hospital to prepare the right team, room, and resources.

Your alert must be:
- 2-3 sentences maximum
- Clinically specific (mention suspected injuries, vitals summary, special needs)
- Actionable (the charge nurse reads this aloud to prepare the team)
- Urgent but calm

Return ONLY this XML:
<alert>2-3 sentence pre-alert for the charge nurse</alert>
<prep_needed>comma,separated,resource,list</prep_needed>"""


async def generate_pre_notification(
    patient: PatientRecord,
    dispatch: DispatchRecommendation,
    ambulance: AmbulanceRecord,
    hospital: HospitalRecord,
    timestamp: str,
    minute: int,
    *,
    use_llm: bool = True,
) -> PreHospitalNotification:
    notification_id = next_id("PN")
    triage_cat = patient.triage_category or "UNKNOWN"
    vitals_parts = []
    if patient.vitals.resp_rate is not None:
        vitals_parts.append(f"RR {patient.vitals.resp_rate}")
    if patient.vitals.gcs is not None:
        vitals_parts.append(f"GCS {patient.vitals.gcs}")
    if patient.vitals.radial_pulse is not None:
        vitals_parts.append(f"pulse {'present' if patient.vitals.radial_pulse else 'ABSENT'}")
    vitals_summary = ", ".join(vitals_parts) or "vitals not captured"

    injuries_summary = ", ".join(patient.injuries) if patient.injuries else "injuries under assessment"
    needs_summary = ", ".join(patient.needs) if patient.needs else "general_emergency"
    flags_summary = ", ".join(patient.special_flags) if patient.special_flags else "none"

    if use_llm and is_llm_available():
        response = await call_llm(
            _SYSTEM_PROMPT,
            f"""Mass Casualty Pre-Notification:

Hospital: {hospital.name} (Level {hospital.trauma_level} Trauma)
Ambulance: {ambulance.ambulance_id} ({ambulance.type})
ETA: {dispatch.eta_minutes} minutes

Patient Assessment:
- Triage: {triage_cat}
- Pediatric: {patient.pediatric}
- Report: {patient.latest_report[:300]}
- Suspected injuries: {injuries_summary}
- Vitals: {vitals_summary}
- Special flags: {flags_summary}
- Medical needs: {needs_summary}

Generate the hospital pre-alert:""",
        )
        if response:
            alert_msg = extract_xml_tag(response, "alert")
            prep_str = extract_xml_tag(response, "prep_needed") or needs_summary
            prep_needed = [p.strip() for p in prep_str.split(",") if p.strip()]
            if alert_msg:
                logger.info("Pre-notification generated for %s -> %s", patient.patient_id, hospital.name)
                return PreHospitalNotification(
                    notification_id=notification_id,
                    patient_id=patient.patient_id,
                    ambulance_id=ambulance.ambulance_id,
                    hospital_id=hospital.hospital_id,
                    hospital_name=hospital.name,
                    recipient_email=hospital.email,
                    alert_message=alert_msg,
                    prep_needed=prep_needed,
                    eta_minutes=dispatch.eta_minutes,
                    minute=minute,
                    timestamp=timestamp,
                    triage_category=str(triage_cat),
                    lead_time_minutes=float(dispatch.eta_minutes),
                )

    alert_msg = (
        f"Incoming {triage_cat} patient via {ambulance.type} ambulance {ambulance.ambulance_id}, "
        f"ETA {dispatch.eta_minutes} min. "
        f"Suspected: {injuries_summary}. Vitals: {vitals_summary}. "
        f"Needs: {needs_summary}."
    )
    if patient.special_flags:
        alert_msg += f" Flags: {flags_summary}."

    return PreHospitalNotification(
        notification_id=notification_id,
        patient_id=patient.patient_id,
        ambulance_id=ambulance.ambulance_id,
        hospital_id=hospital.hospital_id,
        hospital_name=hospital.name,
        recipient_email=hospital.email,
        alert_message=alert_msg,
        prep_needed=patient.needs or ["general_emergency"],
        eta_minutes=dispatch.eta_minutes,
        minute=minute,
        timestamp=timestamp,
        triage_category=str(triage_cat),
        lead_time_minutes=float(dispatch.eta_minutes),
    )
