from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
except Exception:  # pragma: no cover - exercised only when dependency missing
    letter = (612.0, 792.0)
    canvas = None

from .models import ArtifactRef, IncidentState, PreHospitalNotification
from .runtime import ALERTS_DIR, EMAILS_DIR, REPORTS_DIR, incident_output_dir


def _escape_pdf_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _write_fallback_pdf(path: Path, title: str, lines: list[str]) -> None:
    stream_lines = ["BT", "/F1 16 Tf", "50 760 Td", f"({_escape_pdf_text(title)}) Tj", "/F1 11 Tf"]
    cursor_y = 740
    for line in lines:
        safe_line = _escape_pdf_text(str(line)[:100])
        stream_lines.append(f"1 0 0 1 50 {cursor_y} Tm ({safe_line}) Tj")
        cursor_y -= 16
        if cursor_y < 60:
            break
    stream_lines.append("ET")
    stream = "\n".join(stream_lines).encode("utf-8")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj",
        f"4 0 obj << /Length {len(stream)} >> stream\n".encode("utf-8") + stream + b"\nendstream endobj",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj",
    ]
    header = b"%PDF-1.4\n"
    body = bytearray(header)
    offsets = [0]
    for obj in objects:
        offsets.append(len(body))
        body.extend(obj)
        body.extend(b"\n")
    xref_start = len(body)
    body.extend(f"xref\n0 {len(offsets)}\n".encode("utf-8"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("utf-8"))
    body.extend(
        (
            f"trailer << /Size {len(offsets)} /Root 1 0 R >>\n"
            f"startxref\n{xref_start}\n%%EOF"
        ).encode("utf-8")
    )
    path.write_bytes(bytes(body))


def build_notification_subject(notification: PreHospitalNotification) -> str:
    return (
        f"Incoming {notification.triage_category} patient "
        f"- ETA {notification.eta_minutes} min - {notification.hospital_name}"
    )


def build_notification_body(notification: PreHospitalNotification, patient_report: str) -> str:
    prep = ", ".join(notification.prep_needed) or "standard trauma bay setup"
    return (
        "FIELDOPS PRE-HOSPITAL NOTIFICATION\n\n"
        f"Hospital: {notification.hospital_name}\n"
        f"Patient: {notification.patient_id}\n"
        f"Ambulance: {notification.ambulance_id}\n"
        f"Triage: {notification.triage_category}\n"
        f"ETA: {notification.eta_minutes} minutes\n\n"
        "Alert:\n"
        f"{notification.alert_message}\n\n"
        "Field report:\n"
        f"{patient_report}\n\n"
        "Preparation needed:\n"
        f"{prep}\n"
    )


def generate_prealert_pdf(
    incident_id: str,
    notification: PreHospitalNotification,
    patient_report: str,
) -> ArtifactRef:
    output_dir = incident_output_dir(ALERTS_DIR, incident_id)
    pdf_path = output_dir / f"{notification.notification_id}.pdf"
    lines = [
        f"Notification: {notification.notification_id}",
        f"Hospital: {notification.hospital_name}",
        f"Recipient: {notification.recipient_email or 'unknown'}",
        f"Patient: {notification.patient_id}",
        f"Ambulance: {notification.ambulance_id}",
        f"Triage: {notification.triage_category}",
        f"ETA: {notification.eta_minutes} minutes",
        f"Generated at minute: {notification.minute}",
        "",
        "Alert message:",
        notification.alert_message,
        "",
        "Preparation needed:",
        ", ".join(notification.prep_needed) or "standard trauma bay setup",
        "",
        "Field report:",
        patient_report[:800],
    ]
    if canvas is None:
        _write_fallback_pdf(pdf_path, "FieldOps Pre-Alert Report", lines)
    else:
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        _, height = letter
        y = height - 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, "FieldOps Pre-Alert Report")
        y -= 26
        c.setFont("Helvetica", 11)
        for line in lines:
            if y < 60:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - 50
            c.drawString(50, y, str(line))
            y -= 16
        c.save()
    return ArtifactRef(
        label="Download PDF",
        kind="pdf",
        path=str(pdf_path.resolve()),
        download_url=f"/api/pre-notifications/{notification.notification_id}/pdf",
    )


def create_email_message(
    notification: PreHospitalNotification,
    recipient_email: str,
    patient_report: str,
) -> EmailMessage:
    message = EmailMessage()
    sender = os.environ.get("SMTP_FROM") or os.environ.get("SMTP_USERNAME") or os.environ.get("GMAIL_USER") or "fieldops@example.test"
    message["From"] = sender
    message["To"] = recipient_email
    message["Subject"] = build_notification_subject(notification)
    message.set_content(build_notification_body(notification, patient_report))
    return message


def write_eml_file(
    incident_id: str,
    notification: PreHospitalNotification,
    message: EmailMessage,
) -> ArtifactRef:
    output_dir = incident_output_dir(EMAILS_DIR, incident_id)
    eml_path = output_dir / f"{notification.notification_id}.eml"
    eml_path.write_text(message.as_string(), encoding="utf-8")
    return ArtifactRef(
        label="Download EML",
        kind="eml",
        path=str(eml_path.resolve()),
        download_url=f"/api/emails/{notification.notification_id}/eml",
    )


def attempt_smtp_send(message: EmailMessage) -> tuple[str, str | None]:
    host = os.environ.get("SMTP_HOST")
    username = os.environ.get("SMTP_USERNAME") or os.environ.get("GMAIL_USER")
    password = os.environ.get("SMTP_PASSWORD") or os.environ.get("GMAIL_APP_PASSWORD")
    port = int(os.environ.get("SMTP_PORT", "587"))
    use_tls = os.environ.get("SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}

    if not host:
        return "saved_only", None

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if username and password:
                server.login(username, password)
            server.send_message(message)
        return "sent", None
    except Exception as exc:  # pragma: no cover - exercised via integration path
        return "failed", str(exc)


def generate_incident_report_pdf(state: IncidentState) -> ArtifactRef:
    output_dir = incident_output_dir(REPORTS_DIR, state.incident_id)
    pdf_path = output_dir / "incident-report.pdf"
    lines = [
        f"Incident: {state.incident_id}",
        f"Scenario: {state.meta.get('scenario_name', state.scenario_id)}",
        f"Mode: {state.mode}",
        f"Current minute: {state.current_minute}",
        f"Phase: {state.incident_phase}",
        "",
        "Performance summary:",
        f"Active triage accuracy: {state.live_metrics.active_accuracy:.3f}",
        f"Shadow triage accuracy: {state.live_metrics.shadow_accuracy:.3f}",
        f"Transport match: {state.metrics.transport_match_score:.3f}",
        f"Survival proxy: {state.metrics.survival_proxy_score:.3f}",
        f"Tradeoff summary: {state.live_metrics.tradeoffs.summary}",
        "",
        "Operations:",
        f"Patients tracked: {len(state.patients)}",
        f"Dispatches: {len(state.dispatches)}",
        f"Pre-alert PDFs: {len([n for n in state.pre_notifications if n.pdf_path])}",
        f"Email attempts: {len(state.email_log)}",
        "",
        "Guardrails:",
    ]
    for guardrail in state.guardrails:
        lines.append(f"- {guardrail.title}: {guardrail.description}")
    lines.extend(
        [
            "",
            "Recent audit events:",
        ]
    )
    for audit in state.audit_log[-12:]:
        lines.append(f"- T+{audit.minute}: [{audit.agent}] {audit.message}")

    if canvas is None:
        _write_fallback_pdf(pdf_path, "FieldOps Incident Report", lines)
    else:
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        _, height = letter
        y = height - 50
        c.setFont("Helvetica-Bold", 18)
        c.drawString(50, y, "FieldOps Incident Report")
        y -= 24
        c.setFont("Helvetica", 11)
        for line in lines:
            if y < 60:
                c.showPage()
                c.setFont("Helvetica", 11)
                y = height - 50
            c.drawString(50, y, str(line)[:105])
            y -= 16
        c.save()
    return ArtifactRef(
        label="Download Incident Report",
        kind="pdf",
        path=str(pdf_path.resolve()),
        download_url=f"/api/incidents/{state.incident_id}/report",
    )
