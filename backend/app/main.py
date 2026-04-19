from __future__ import annotations

import asyncio
import os
import smtplib
import warnings
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

warnings.filterwarnings("ignore", category=FutureWarning, module="llama_index")

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .engine import SimulationManager
from .models import ApproveDispatchRequest, InjectEventRequest, ScenarioControlRequest
from .scenario_loader import list_scenarios


app = FastAPI(title="FieldOps API", version="0.1.0")
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
    import logging, traceback
    try:
        return manager.start(scenario_id).model_dump(mode="json")
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logging.getLogger(__name__).error("start_scenario error: %s\n%s", exc, traceback.format_exc())
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
    """Send (or draft) a pre-hospital notification email via Gmail SMTP."""
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")

    log_line = (
        f"EMAIL REQUEST | to={request.recipient_email} | "
        f"subject={request.subject[:60]} | notif={request.notification_id}"
    )

    if gmail_user and gmail_password:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = request.subject
            msg["From"] = gmail_user
            msg["To"] = request.recipient_email
            msg.attach(MIMEText(request.body, "plain"))

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(gmail_user, gmail_password)
                server.sendmail(gmail_user, request.recipient_email, msg.as_string())

            print(f"EMAIL SENT | {log_line}")
            return {
                "mode": "sent",
                "message": f"Email sent to {request.recipient_email}",
                "notification_id": request.notification_id,
            }
        except Exception as exc:
            print(f"EMAIL SEND FAILED ({exc}) — returning draft | {log_line}")

    # Fallback: return as draft
    print(f"EMAIL DRAFT | {log_line}")
    return {
        "mode": "draft",
        "message": "Email composed as draft (set GMAIL_USER + GMAIL_APP_PASSWORD to send)",
        "notification_id": request.notification_id,
        "composed": {
            "to": request.recipient_email,
            "subject": request.subject,
            "body": request.body,
        },
    }


@app.get("/api/metrics/{incident_id}")
def get_metrics(incident_id: str):
    try:
        snapshot = manager.get(incident_id).snapshot()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"metrics": snapshot["metrics"], "baseline": snapshot["baseline"]}


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
