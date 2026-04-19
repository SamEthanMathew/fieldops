import type { PreHospitalNotification, PatientRecord } from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

interface PreNotifCardProps {
  notif: PreHospitalNotification;
  patient?: PatientRecord;
}

export function PreNotifCard({ notif, patient: _patient }: PreNotifCardProps) {
  const triageColor =
    notif.triage_category === "RED" ? "#ef4444" :
    notif.triage_category === "YELLOW" ? "#f59e0b" :
    "#10b981";

  const isSent = notif.email_status === "sent";
  const isFailed = notif.email_status === "failed";
  const isPending = !isSent && !isFailed;

  return (
    <div className="prenotif-card">
      <div className="prenotif-head">
        <span className="triage-label" style={{
          background: `${triageColor}20`, color: triageColor,
          border: `1px solid ${triageColor}44`,
        }}>
          {notif.triage_category}
        </span>
        <span className="prenotif-hosp">{notif.hospital_name}</span>
        <span className="prenotif-eta">ETA {notif.eta_minutes}m</span>
        <span className={`sent-badge ${isSent ? "sent-badge--ok" : isFailed ? "sent-badge--fail" : "sent-badge--pend"}`}>
          {isSent ? "SENT ✓" : isFailed ? "FAILED" : "PENDING"}
        </span>
      </div>
      <p className="prenotif-msg">
        {notif.alert_message.slice(0, 110)}{notif.alert_message.length > 110 ? "…" : ""}
      </p>
      {(notif.pdf_artifact?.download_url || notif.eml_artifact?.download_url) && (
        <div className="prenotif-actions">
          {notif.pdf_artifact?.download_url && (
            <a className="link-btn link-btn--accent" href={`${API_BASE}${notif.pdf_artifact.download_url}`} target="_blank" rel="noreferrer">
              PDF
            </a>
          )}
          {notif.eml_artifact?.download_url && (
            <a className="link-btn" href={`${API_BASE}${notif.eml_artifact.download_url}`} target="_blank" rel="noreferrer">
              .eml
            </a>
          )}
        </div>
      )}
    </div>
  );
}
