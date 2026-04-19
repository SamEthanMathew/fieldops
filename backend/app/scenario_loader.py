from __future__ import annotations

import json
from pathlib import Path

from .models import (
    AmbulanceRecord,
    AmbulanceStatus,
    Capacity,
    Coordinates,
    HospitalRecord,
    HospitalStatus,
    ScenarioDefinition,
)


ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"


def load_json(relative_path: str):
    with (DATA_DIR / relative_path).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def load_seed_hospitals() -> dict[str, HospitalRecord]:
    hospitals = {}
    for item in load_json("hospitals.json"):
        record = HospitalRecord(
            hospital_id=item["hospital_id"],
            name=item["name"],
            email=item.get("email"),
            location=Coordinates(**item["location"]),
            trauma_level=item["trauma_level"],
            specialties=item["specialties"],
            capacity=Capacity(**item["capacity"]),
            status=HospitalStatus(item["status"]),
            divert_status=item["divert_status"],
            eta_from_scene_minutes=item["base_eta_minutes"],
            last_updated="2026-04-18T15:00:00Z",
            last_updated_minute=0,
        )
        hospitals[record.hospital_id] = record
    return hospitals


def load_seed_ambulances() -> dict[str, AmbulanceRecord]:
    ambulances = {}
    for item in load_json("ambulances.json"):
        record = AmbulanceRecord(
            ambulance_id=item["ambulance_id"],
            type=item["type"],
            status=AmbulanceStatus.AVAILABLE,
            position=Coordinates(**item["position"]),
        )
        ambulances[record.ambulance_id] = record
    return ambulances


def load_scenario(scenario_id: str) -> ScenarioDefinition:
    mapping = {
        "bridge-collapse-standard": "scenarios/bridge-collapse-standard.json",
        "bridge-collapse-light": "scenarios/light.json",
        "bridge-collapse-heavy": "scenarios/heavy.json",
    }
    if scenario_id not in mapping:
        raise KeyError(f"Unknown scenario: {scenario_id}")
    return ScenarioDefinition.model_validate(load_json(mapping[scenario_id]))


def list_scenarios() -> list[dict[str, str]]:
    return [
        {"scenario_id": "bridge-collapse-light", "name": "Bridge Collapse Light"},
        {"scenario_id": "bridge-collapse-standard", "name": "Pittsburgh Bridge Collapse"},
        {"scenario_id": "bridge-collapse-heavy", "name": "Bridge Collapse Heavy"},
    ]
