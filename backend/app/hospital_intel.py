from __future__ import annotations

from .models import HospitalStatus, IncidentState
from .utils import haversine_minutes, iso_at_minute


class HospitalIntelAgent:
    def refresh(self, state: IncidentState, current_minute: int) -> None:
        scene = state.location
        for hospital in state.hospitals.values():
            hospital.eta_from_scene_minutes = haversine_minutes(
                scene.lat,
                scene.lng,
                hospital.location.lat,
                hospital.location.lng,
            )
            hospital.current_load_pct = 1 - (hospital.capacity.available_beds / max(hospital.capacity.total_beds, 1))
            stale_minutes = current_minute - hospital.last_updated_minute
            hospital.stale = stale_minutes > 10
            if hospital.stale and hospital.status == HospitalStatus.OPEN:
                hospital.status = HospitalStatus.UNKNOWN
            elif not hospital.stale and not hospital.divert_status and hospital.status == HospitalStatus.UNKNOWN:
                hospital.status = HospitalStatus.OPEN
            if hospital.capacity.available_beds <= 0 and hospital.status != HospitalStatus.CLOSED:
                hospital.status = HospitalStatus.DIVERT
                hospital.divert_status = True
            if hospital.current_load_pct >= 0.85 and hospital.status == HospitalStatus.OPEN:
                hospital.reason = "Approaching saturation"
            hospital.last_updated = iso_at_minute(state.start_time, current_minute)

