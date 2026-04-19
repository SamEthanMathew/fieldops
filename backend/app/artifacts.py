from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path

try:
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.colors import HexColor
    from reportlab.pdfgen import canvas
    _RL_COLORS = True
except Exception:  # pragma: no cover - exercised only when dependency missing
    letter = (612.0, 792.0)
    canvas = None
    _RL_COLORS = False

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


def _triage_color(category: str):
    mapping = {"RED": "#ef4444", "YELLOW": "#f59e0b", "GREEN": "#22c55e", "BLACK": "#374151"}
    return HexColor(mapping.get(str(category).upper(), "#6b7280")) if _RL_COLORS else None


def _pdf_header(c, width: float, height: float, title: str, subtitle: str) -> float:
    """Dark header band. Returns y position below the header."""
    c.setFillColor(HexColor("#0d1a2e"))
    c.rect(0, height - 72, width, 72, fill=1, stroke=0)
    c.setFillColor(HexColor("#38bdf8"))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(50, height - 18, "FIELDOPS  ·  MASS CASUALTY COMMAND")
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, height - 38, title)
    c.setFillColor(HexColor("#94a3b8"))
    c.setFont("Helvetica", 9)
    c.drawString(50, height - 56, subtitle)
    return height - 90


def _pdf_section(c, y: float, label: str, width: float) -> float:
    """Draws a section header rule. Returns y below it."""
    c.setFillColor(HexColor("#1e3a5f"))
    c.rect(50, y - 2, width - 100, 18, fill=1, stroke=0)
    c.setFillColor(HexColor("#38bdf8"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(56, y + 3, label.upper())
    return y - 26


def _pdf_kv(c, x: float, y: float, key: str, value: str, col_w: float = 230) -> None:
    c.setFillColor(HexColor("#64748b"))
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x, y, key.upper())
    c.setFillColor(HexColor("#e2e8f0"))
    c.setFont("Helvetica", 10)
    c.drawString(x, y - 13, str(value)[:48])


def _pdf_body_text(c, y: float, text: str, width: float, line_h: int = 14) -> float:
    """Word-wrapped body text. Returns updated y."""
    import textwrap
    c.setFillColor(HexColor("#cbd5e1"))
    c.setFont("Helvetica", 9)
    max_chars = int((width - 100) / 5.4)
    for raw_line in text.splitlines():
        for wrapped in textwrap.wrap(raw_line or " ", max_chars) or [" "]:
            if y < 60:
                c.showPage()
                y = letter[1] - 50
                c.setFont("Helvetica", 9)
                c.setFillColor(HexColor("#cbd5e1"))
            c.drawString(50, y, wrapped)
            y -= line_h
    return y


def _pdf_triage_badge(c, x: float, y: float, category: str) -> None:
    color = _triage_color(category)
    c.setFillColor(color)
    c.roundRect(x, y - 2, 54, 16, 4, fill=1, stroke=0)
    c.setFillColor(HexColor("#ffffff"))
    c.setFont("Helvetica-Bold", 10)
    c.drawCentredString(x + 27, y + 3, str(category).upper())


def generate_prealert_pdf(
    incident_id: str,
    notification: PreHospitalNotification,
    patient_report: str,
) -> ArtifactRef:
    output_dir = incident_output_dir(ALERTS_DIR, incident_id)
    pdf_path = output_dir / f"{notification.notification_id}.pdf"

    if canvas is None:
        lines = [
            f"Notification: {notification.notification_id}",
            f"Hospital: {notification.hospital_name}",
            f"Recipient: {notification.recipient_email or 'unknown'}",
            f"Patient: {notification.patient_id}",
            f"Ambulance: {notification.ambulance_id}",
            f"Triage: {notification.triage_category}",
            f"ETA: {notification.eta_minutes} minutes",
            "", "Alert message:", notification.alert_message,
            "", "Preparation needed:",
            ", ".join(notification.prep_needed) or "standard trauma bay setup",
            "", "Field report:", patient_report[:800],
        ]
        _write_fallback_pdf(pdf_path, "FieldOps Pre-Alert Report", lines)
    else:
        width, height = letter
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.setFillColor(HexColor("#060d1b"))
        c.rect(0, 0, width, height, fill=1, stroke=0)

        y = _pdf_header(
            c, width, height,
            "Pre-Hospital Notification",
            f"Issued T+{notification.minute:02d}  ·  {notification.notification_id}",
        )

        # Triage badge + ETA pill row
        _pdf_triage_badge(c, 50, y - 4, str(notification.triage_category))
        c.setFillColor(HexColor("#1e3a5f"))
        c.roundRect(112, y - 6, 90, 18, 4, fill=1, stroke=0)
        c.setFillColor(HexColor("#f59e0b"))
        c.setFont("Helvetica-Bold", 9)
        c.drawString(118, y - 1, f"ETA  {notification.eta_minutes} MIN")
        y -= 36

        # Two-column metadata
        y = _pdf_section(c, y, "Patient & Dispatch", width)
        _pdf_kv(c, 50, y, "Patient ID", notification.patient_id)
        _pdf_kv(c, 310, y, "Ambulance", notification.ambulance_id)
        y -= 30
        _pdf_kv(c, 50, y, "Destination", notification.hospital_name)
        _pdf_kv(c, 310, y, "Recipient", notification.recipient_email or "—")
        y -= 36

        # Alert message
        y = _pdf_section(c, y, "Alert Message", width)
        y -= 4
        y = _pdf_body_text(c, y, notification.alert_message, width)
        y -= 12

        # Prep needed
        y = _pdf_section(c, y, "Preparation Required", width)
        y -= 4
        prep = ", ".join(notification.prep_needed) if notification.prep_needed else "Standard trauma bay setup"
        y = _pdf_body_text(c, y, prep, width)
        y -= 12

        # Field report
        y = _pdf_section(c, y, "Field Report", width)
        y -= 4
        _pdf_body_text(c, y, patient_report[:1200], width)

        # Footer
        c.setFillColor(HexColor("#1e3a5f"))
        c.rect(0, 0, width, 28, fill=1, stroke=0)
        c.setFillColor(HexColor("#475569"))
        c.setFont("Helvetica", 7)
        c.drawString(50, 10, f"FieldOps AI Command  ·  Incident {incident_id}  ·  CONFIDENTIAL — FOR RECEIVING FACILITY USE ONLY")

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


def _pdf_metric_box(c, x: float, y: float, label: str, value: str, box_w: float = 110) -> None:
    c.setFillColor(HexColor("#0d1a2e"))
    c.roundRect(x, y - 32, box_w, 40, 5, fill=1, stroke=0)
    c.setStrokeColor(HexColor("#1e3a5f"))
    c.roundRect(x, y - 32, box_w, 40, 5, fill=0, stroke=1)
    c.setFillColor(HexColor("#38bdf8"))
    c.setFont("Helvetica-Bold", 14)
    c.drawCentredString(x + box_w / 2, y - 14, str(value))
    c.setFillColor(HexColor("#64748b"))
    c.setFont("Helvetica", 7)
    c.drawCentredString(x + box_w / 2, y - 28, label.upper())


def generate_incident_report_pdf(state: IncidentState) -> ArtifactRef:
    output_dir = incident_output_dir(REPORTS_DIR, state.incident_id)
    pdf_path = output_dir / "incident-report.pdf"

    if canvas is None:
        lines = [
            f"Incident: {state.incident_id}",
            f"Scenario: {state.meta.get('scenario_name', state.scenario_id)}",
            f"Mode: {state.mode}",
            f"Current minute: {state.current_minute}",
            f"Phase: {state.incident_phase}",
            "", "Performance summary:",
            f"Active triage accuracy: {state.live_metrics.active_accuracy:.3f}",
            f"Shadow triage accuracy: {state.live_metrics.shadow_accuracy:.3f}",
            f"Transport match: {state.metrics.transport_match_score:.3f}",
            f"Survival proxy: {state.metrics.survival_proxy_score:.3f}",
            "", "Operations:",
            f"Patients: {len(state.patients)}",
            f"Dispatches: {len(state.dispatches)}",
            f"Pre-alert PDFs: {len([n for n in state.pre_notifications if n.pdf_path])}",
            f"Email attempts: {len(state.email_log)}",
        ]
        for audit in state.audit_log[-12:]:
            lines.append(f"- T+{audit.minute}: [{audit.agent}] {audit.message}")
        _write_fallback_pdf(pdf_path, "FieldOps Incident Report", lines)
    else:
        width, height = letter
        c = canvas.Canvas(str(pdf_path), pagesize=letter)
        c.setFillColor(HexColor("#060d1b"))
        c.rect(0, 0, width, height, fill=1, stroke=0)

        scenario_name = state.meta.get("scenario_name", state.scenario_id)
        y = _pdf_header(
            c, width, height,
            "Incident After-Action Report",
            f"{scenario_name}  ·  {state.incident_id}  ·  T+{state.current_minute:02d} min",
        )

        # Metric boxes row
        y -= 8
        triage_counts = {"RED": 0, "YELLOW": 0, "GREEN": 0, "BLACK": 0}
        for p in state.patients.values():
            cat = str(getattr(p.triage_category, "value", p.triage_category) or "").upper()
            if cat in triage_counts:
                triage_counts[cat] += 1

        box_gap = 6
        box_w = (width - 100 - box_gap * 5) / 6
        metrics = [
            ("Patients", str(len(state.patients))),
            ("RED", str(triage_counts["RED"])),
            ("YELLOW", str(triage_counts["YELLOW"])),
            ("GREEN", str(triage_counts["GREEN"])),
            ("Dispatches", str(len(state.dispatches))),
            ("Emails", str(len(state.email_log))),
        ]
        box_colors = [
            "#38bdf8", "#ef4444", "#f59e0b", "#22c55e", "#8b5cf6", "#10b981",
        ]
        for i, (label, val) in enumerate(metrics):
            bx = 50 + i * (box_w + box_gap)
            c.setFillColor(HexColor("#0d1a2e"))
            c.roundRect(bx, y - 32, box_w, 40, 5, fill=1, stroke=0)
            c.setStrokeColor(HexColor("#1e3a5f"))
            c.roundRect(bx, y - 32, box_w, 40, 5, fill=0, stroke=1)
            c.setFillColor(HexColor(box_colors[i]))
            c.setFont("Helvetica-Bold", 14)
            c.drawCentredString(bx + box_w / 2, y - 12, val)
            c.setFillColor(HexColor("#64748b"))
            c.setFont("Helvetica", 7)
            c.drawCentredString(bx + box_w / 2, y - 27, label.upper())
        y -= 54

        # Performance section
        y = _pdf_section(c, y, "Performance Metrics", width)
        _pdf_kv(c, 50,  y, "Active Triage Accuracy", f"{state.live_metrics.active_accuracy:.1%}")
        _pdf_kv(c, 200, y, "Shadow Accuracy",         f"{state.live_metrics.shadow_accuracy:.1%}")
        _pdf_kv(c, 350, y, "Transport Match",          f"{state.metrics.transport_match_score:.1%}")
        _pdf_kv(c, 480, y, "Survival Proxy",           f"{state.metrics.survival_proxy_score:.1%}")
        y -= 36

        y = _pdf_section(c, y, "Mode & Tradeoffs", width)
        y -= 4
        mode_str = str(getattr(state.mode, "value", state.mode)).upper()
        phase_str = str(getattr(state.incident_phase, "value", state.incident_phase)).upper()
        _pdf_kv(c, 50, y, "Incident Mode", mode_str)
        _pdf_kv(c, 310, y, "Phase", phase_str)
        y -= 30
        tradeoff = getattr(state.live_metrics.tradeoffs, "summary", str(state.live_metrics.tradeoffs))
        y = _pdf_body_text(c, y, tradeoff, width)
        y -= 12

        # Guardrails
        y = _pdf_section(c, y, "Active Guardrails", width)
        y -= 4
        for gr in state.guardrails:
            c.setFillColor(HexColor("#38bdf8"))
            c.setFont("Helvetica-Bold", 8)
            c.drawString(50, y, f"▸  {gr.title}")
            y -= 12
            c.setFillColor(HexColor("#94a3b8"))
            c.setFont("Helvetica", 8)
            import textwrap
            for line in textwrap.wrap(gr.description, 100):
                c.drawString(62, y, line)
                y -= 11
            y -= 4
            if y < 80:
                c.showPage()
                c.setFillColor(HexColor("#060d1b"))
                c.rect(0, 0, width, height, fill=1, stroke=0)
                y = height - 50
        y -= 8

        # Audit log
        y = _pdf_section(c, y, f"Recent Audit Events  (last {min(16, len(state.audit_log))})", width)
        y -= 4
        for audit in state.audit_log[-16:]:
            if y < 60:
                c.showPage()
                c.setFillColor(HexColor("#060d1b"))
                c.rect(0, 0, width, height, fill=1, stroke=0)
                y = height - 50
            sev_color = "#ef4444" if audit.status == "CRITICAL" else "#f59e0b" if audit.status == "WARNING" else "#38bdf8"
            c.setFillColor(HexColor(sev_color))
            c.setFont("Helvetica-Bold", 8)
            c.drawString(50, y, f"T+{audit.minute:02d}")
            c.setFillColor(HexColor("#64748b"))
            c.drawString(76, y, f"[{audit.agent}]")
            c.setFillColor(HexColor("#cbd5e1"))
            c.setFont("Helvetica", 8)
            c.drawString(140, y, audit.message[:80])
            y -= 13

        # Footer
        c.setFillColor(HexColor("#1e3a5f"))
        c.rect(0, 0, width, 28, fill=1, stroke=0)
        c.setFillColor(HexColor("#475569"))
        c.setFont("Helvetica", 7)
        c.drawString(50, 10, f"FieldOps AI Command  ·  Incident {state.incident_id}  ·  CONFIDENTIAL")

        c.save()

    return ArtifactRef(
        label="Download Incident Report",
        kind="pdf",
        path=str(pdf_path.resolve()),
        download_url=f"/api/incidents/{state.incident_id}/report",
    )
