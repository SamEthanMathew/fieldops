from __future__ import annotations

import asyncio
import csv
import io
from email.message import EmailMessage
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .artifacts import attempt_smtp_send
from .engine import SimulationManager
from .models import ApproveDispatchRequest, IncidentModeRequest, InjectEventRequest, ScenarioControlRequest
from .scenario_loader import list_scenarios


app = FastAPI(title="FieldOps API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

manager = SimulationManager()
ROOT = Path(__file__).resolve().parents[2]
FRONTEND_DIST = ROOT / "frontend" / "dist"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/scenarios")
def scenarios():
    return list_scenarios()


@app.post("/api/scenarios/{scenario_id}/start")
def start_scenario(scenario_id: str):
    try:
        return manager.start(scenario_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/scenarios/{scenario_id}/control")
async def control_scenario(scenario_id: str, request: ScenarioControlRequest):
    try:
        session = manager.get(request.incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if session.scenario.scenario_id != scenario_id:
        raise HTTPException(status_code=400, detail="Scenario does not match incident")
    state = await session.control(request)
    return state.model_dump(mode="json")


@app.get("/api/incidents/{incident_id}")
def get_incident(incident_id: str):
    try:
        return manager.get(incident_id).snapshot()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/incidents/{incident_id}/mode")
async def set_incident_mode(incident_id: str, request: IncidentModeRequest):
    try:
        session = manager.get(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    state = await session.set_mode(request.mode)
    return state.model_dump(mode="json")


@app.get("/api/incidents/{incident_id}/metrics/live")
def get_live_metrics(incident_id: str):
    try:
        session = manager.get(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return session.get_live_metrics().model_dump(mode="json")


@app.post("/api/events/inject")
async def inject_event(request: InjectEventRequest):
    try:
        session = manager.get(request.incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    state = await session.inject_event(request)
    return state.model_dump(mode="json")


@app.post("/api/dispatches/{dispatch_id}/approve")
async def approve_dispatch(dispatch_id: str, request: ApproveDispatchRequest):
    try:
        session = manager.get(request.incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    state = await session.approve_dispatch(dispatch_id)
    return state.model_dump(mode="json")


class EmailNotifyRequest(BaseModel):
    notification_id: str
    recipient_email: str
    subject: str
    body: str


@app.post("/api/notify/email")
async def send_notification_email(request: EmailNotifyRequest):
    message = EmailMessage()
    message["To"] = request.recipient_email
    message["From"] = "fieldops@example.test"
    message["Subject"] = request.subject
    message.set_content(request.body)
    status, error = attempt_smtp_send(message)
    return {
        "mode": "sent" if status == "sent" else "draft",
        "message": "Email sent" if status == "sent" else "Email saved only",
        "notification_id": request.notification_id,
        "error": error,
    }


@app.get("/api/metrics/{incident_id}")
def get_metrics(incident_id: str):
    try:
        snapshot = manager.get(incident_id).snapshot()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"metrics": snapshot["metrics"], "baseline": snapshot["baseline"]}


def _find_notification(notification_id: str):
    for session in manager.sessions.values():
        notification = session.get_notification(notification_id)
        if notification is not None:
            return session, notification
    raise HTTPException(status_code=404, detail=f"Notification {notification_id} not found")


@app.get("/api/pre-notifications/{notification_id}/pdf")
def get_pre_notification_pdf(notification_id: str):
    _, notification = _find_notification(notification_id)
    if not notification.pdf_path:
        raise HTTPException(status_code=404, detail="PDF not generated")
    path = Path(notification.pdf_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="PDF missing on disk")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/emails/{notification_id}/eml")
def get_email_eml(notification_id: str):
    _, notification = _find_notification(notification_id)
    if not notification.eml_path:
        raise HTTPException(status_code=404, detail="EML not generated")
    path = Path(notification.eml_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="EML missing on disk")
    return FileResponse(path, media_type="message/rfc822", filename=path.name)


@app.get("/api/incidents/{incident_id}/report")
def get_incident_report(incident_id: str):
    try:
        session = manager.get(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    artifact = session.ensure_report_artifact()
    path = Path(artifact.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report missing on disk")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/incidents/{incident_id}/audit.json")
def get_incident_audit_json(incident_id: str):
    try:
        session = manager.get(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return JSONResponse(content=[entry.model_dump(mode="json") for entry in session.state.audit_log])


@app.get("/api/incidents/{incident_id}/audit.csv")
def get_incident_audit_csv(incident_id: str):
    try:
        session = manager.get(incident_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["audit_id", "minute", "timestamp", "event_type", "agent", "status", "message", "data"])
    for entry in session.state.audit_log:
        writer.writerow(
            [
                entry.audit_id,
                entry.minute,
                entry.timestamp,
                entry.event_type,
                entry.agent,
                entry.status,
                entry.message,
                entry.data,
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{incident_id}-audit.csv"'},
    )


@app.websocket("/ws/incidents/{incident_id}")
async def incident_updates(websocket: WebSocket, incident_id: str):
    try:
        session = manager.get(incident_id)
    except KeyError:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    queue = await session.subscribe()
    try:
        while True:
            payload = await queue.get()
            await websocket.send_json(payload)
    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    except Exception:
        pass
    finally:
        session.unsubscribe(queue)


if FRONTEND_DIST.exists():
    assets_dir = FRONTEND_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/")
    def root():
        return FileResponse(FRONTEND_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str):
        if full_path.startswith(("api/", "ws/", "health")):
            raise HTTPException(status_code=404, detail="Not found")
        target = FRONTEND_DIST / full_path
        if target.exists() and target.is_file():
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
