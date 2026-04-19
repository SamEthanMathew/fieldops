import time

from fastapi.testclient import TestClient

from app.engine import SimulationSession
from app.hospital_intel import HospitalIntelAgent
from app.logistics import LogisticsAgent
from app.main import app
from app.overwatch import OverwatchAgent
from app.rag import LocalProtocolRag
from app.scenario_loader import load_scenario
from app.triage import TriageAgent


def _wait_for_pre_notification(client: TestClient, incident_id: str, timeout_s: float = 4.0):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        incident = client.get(f"/api/incidents/{incident_id}").json()
        if incident["pre_notifications"]:
            return incident
        time.sleep(0.1)
    return client.get(f"/api/incidents/{incident_id}").json()


def test_live_metrics_endpoint_and_mode_switch():
    client = TestClient(app)
    incident = client.post("/api/scenarios/bridge-collapse-standard/start").json()
    incident_id = incident["incident_id"]

    metrics_response = client.get(f"/api/incidents/{incident_id}/metrics/live")
    assert metrics_response.status_code == 200
    live_metrics = metrics_response.json()
    assert live_metrics["current_mode"] == "balanced"
    assert "agreement" in live_metrics
    assert "pre_notification_lead_time" in live_metrics
    assert "tradeoffs" in live_metrics

    switch_response = client.post(f"/api/incidents/{incident_id}/mode", json={"mode": "speed"})
    assert switch_response.status_code == 200
    switched = switch_response.json()
    assert switched["mode"] == "speed"
    assert switched["live_metrics"]["current_mode"] == "speed"
    assert switched["live_metrics"]["active_accuracy"] == switched["live_metrics"]["shadow_accuracy"]


def test_artifacts_and_audit_exports_are_available():
    client = TestClient(app)
    incident = client.post("/api/scenarios/bridge-collapse-standard/start").json()
    incident_id = incident["incident_id"]

    incident = _wait_for_pre_notification(client, incident_id)
    assert incident["pre_notifications"]
    notification = incident["pre_notifications"][0]
    assert notification["pdf_artifact"]["download_url"]
    assert notification["eml_artifact"]["download_url"]
    assert notification["email_status"] in {"saved_only", "failed", "sent"}

    pdf_response = client.get(notification["pdf_artifact"]["download_url"])
    assert pdf_response.status_code == 200

    eml_response = client.get(notification["eml_artifact"]["download_url"])
    assert eml_response.status_code == 200

    client.post(
        "/api/scenarios/bridge-collapse-standard/control",
        json={"incident_id": incident_id, "action": "step", "steps": 60},
    )

    report_response = client.get(f"/api/incidents/{incident_id}/report")
    assert report_response.status_code == 200

    audit_json = client.get(f"/api/incidents/{incident_id}/audit.json")
    assert audit_json.status_code == 200
    assert isinstance(audit_json.json(), list)
    assert audit_json.json()

    audit_csv = client.get(f"/api/incidents/{incident_id}/audit.csv")
    assert audit_csv.status_code == 200
    assert "event_type" in audit_csv.text


def test_sync_dispatch_approval_generates_pre_notification_artifacts():
    session = SimulationSession(
        scenario=load_scenario("bridge-collapse-standard"),
        triage_agent=TriageAgent(LocalProtocolRag()),
        hospital_intel=HospitalIntelAgent(),
        logistics=LogisticsAgent(),
        overwatch=OverwatchAgent(),
    )

    for minute in range(1, session.scenario.duration_minutes + 1):
        session._process_minute(minute)
        for dispatch_id in list(session.state.pending_approvals):
            session.approve_dispatch_sync(dispatch_id)

    assert session.state.pre_notifications
    assert session.state.email_log
    first_notification = session.state.pre_notifications[0]
    assert first_notification.pdf_path
    assert first_notification.eml_path
