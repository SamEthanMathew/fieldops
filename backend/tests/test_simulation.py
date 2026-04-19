from fastapi.testclient import TestClient

from app.main import app


def test_start_and_step_standard_scenario():
    client = TestClient(app)
    start_response = client.post("/api/scenarios/bridge-collapse-standard/start")
    assert start_response.status_code == 200
    incident = start_response.json()
    incident_id = incident["incident_id"]
    assert incident["patients"]

    step_response = client.post(
        "/api/scenarios/bridge-collapse-standard/control",
        json={"incident_id": incident_id, "action": "step", "steps": 3},
    )
    assert step_response.status_code == 200
    stepped = step_response.json()
    assert stepped["current_minute"] == 3
    assert len(stepped["dispatches"]) >= 1
    assert "baseline" in stepped
