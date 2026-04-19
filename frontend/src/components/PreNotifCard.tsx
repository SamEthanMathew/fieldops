import type { PreHospitalNotification, PatientRecord } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

interface PreNotifCardProps {
  notif: PreHospitalNotification;
  patient?: PatientRecord;
}

export function PreNotifCard({ notif, patient }: PreNotifCardProps) {
  const triageColor =
    notif.triage_category === "RED" ? "#ef4444" :
    notif.triage_category === "YELLOW" ? "#f59e0b" :
    "#10b981";

  const emailTone =
    notif.email_status === "sent" ? "#10b981" :
    notif.email_status === "failed" ? "#ef4444" :
    "#f59e0b";

  return (
    <div className="prenotif-card-v2" style={{ borderLeftColor: triageColor }}>
      <div className="prenotif-v2-header">
        <span className="prenotif-v2-badge" style={{ background: triageColor, boxShadow: `0 0 8px ${triageColor}88` }}>
          {notif.triage_category}
        </span>
        <span className="prenotif-v2-hospital">{notif.hospital_name}</span>
        <span className="prenotif-v2-eta" style={{ color: triageColor === "#ef4444" ? "#fca5a5" : "#fcd34d" }}>
          ETA {notif.eta_minutes}m
        </span>
        <span className="prenotif-v2-time">T+{String(notif.minute).padStart(2, "0")}</span>
      </div>

      <p className="prenotif-v2-message">{notif.alert_message}</p>

      {patient?.memory_summary && (
        <p className="prenotif-meta-note">{patient.memory_summary}</p>
      )}

      <div className="prenotif-meta-grid">
        <div className="prenotif-meta-item">
          <span className="prenotif-meta-label">Lead Time</span>
          <strong>{notif.lead_time_minutes.toFixed(1)} min</strong>
        </div>
        <div className="prenotif-meta-item">
          <span className="prenotif-meta-label">Email</span>
          <strong style={{ color: emailTone }}>{notif.email_status.replace("_", " ")}</strong>
        </div>
        <div className="prenotif-meta-item">
          <span className="prenotif-meta-label">Recipient</span>
          <strong>{notif.recipient_email ?? "Unknown"}</strong>
        </div>
      </div>

      {notif.prep_needed.length > 0 && (
        <div className="prenotif-v2-prep">
          {notif.prep_needed.map((item) => (
            <span key={item} className="prep-tag-v2">{item.replace(/_/g, " ")}</span>
          ))}
        </div>
      )}

      <div className="prenotif-v2-footer">
        <div className="prenotif-v2-ids">
          <span className="notif-id-pill">{notif.ambulance_id}</span>
          <span className="notif-id-pill">{notif.patient_id}</span>
        </div>
        <div className="artifact-btn-row">
          {notif.pdf_artifact?.download_url && (
            <a className="draft-email-btn" href={`${API_BASE}${notif.pdf_artifact.download_url}`} target="_blank" rel="noreferrer">
              Download PDF
            </a>
          )}
          {notif.eml_artifact?.download_url && (
            <a className="draft-email-btn draft-email-btn--secondary" href={`${API_BASE}${notif.eml_artifact.download_url}`} target="_blank" rel="noreferrer">
              Open EML
            </a>
          )}
        </div>
      </div>
    </div>
  );
}
