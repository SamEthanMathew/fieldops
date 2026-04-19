import type { PatientRecord, IncidentSnapshot } from "../types";

interface PatientTableProps {
  patients: PatientRecord[];
  snapshot: IncidentSnapshot;
  selectedPatientId: string | null;
  onSelectPatient: (id: string) => void;
}

function triageColor(cat?: string | null): string {
  if (cat === "RED") return "#ef4444";
  if (cat === "YELLOW") return "#f59e0b";
  if (cat === "GREEN") return "#10b981";
  if (cat === "BLACK") return "#4b5563";
  return "#64748b";
}

function triageBg(cat?: string | null): string {
  if (cat === "RED") return "rgba(239,68,68,0.12)";
  if (cat === "YELLOW") return "rgba(245,158,11,0.10)";
  if (cat === "GREEN") return "rgba(16,185,129,0.08)";
  if (cat === "BLACK") return "rgba(75,85,99,0.15)";
  return "transparent";
}

export function PatientTable({ patients, snapshot, selectedPatientId, onSelectPatient }: PatientTableProps) {
  const selected = selectedPatientId ? snapshot.patients[selectedPatientId] : null;

  const counts = { RED: 0, YELLOW: 0, GREEN: 0, BLACK: 0 };
  for (const p of patients) {
    const cat = p.triage_category ?? "GREEN";
    if (cat in counts) counts[cat as keyof typeof counts]++;
  }

  return (
    <div className="patient-panel">
      <div className="patient-counts">
        {(["RED", "YELLOW", "GREEN", "BLACK"] as const).map((cat) => (
          <div key={cat} className="triage-count" style={{ borderColor: triageColor(cat), background: triageBg(cat) }}>
            <span style={{ color: triageColor(cat), fontWeight: 800, fontSize: "1.1rem" }}>{counts[cat]}</span>
            <span style={{ fontSize: "0.65rem", color: triageColor(cat), opacity: 0.8, letterSpacing: "0.05em" }}>{cat}</span>
          </div>
        ))}
      </div>

      <div className="patient-table-wrap">
        <table className="patient-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Triage</th>
              <th>Status</th>
              <th>Hospital</th>
              <th>Conf</th>
            </tr>
          </thead>
          <tbody>
            {patients.map((patient) => {
              const color = triageColor(patient.triage_category);
              const isSelected = selectedPatientId === patient.patient_id;
              return (
                <tr
                  key={patient.patient_id}
                  onClick={() => onSelectPatient(patient.patient_id)}
                  style={{
                    borderLeft: `3px solid ${color}`,
                    background: isSelected ? "rgba(59,130,246,0.08)" : undefined,
                    cursor: "pointer",
                  }}
                >
                  <td style={{ fontSize: "0.78rem", color: "#94a3b8" }}>{patient.patient_id}</td>
                  <td>
                    <span style={{
                      padding: "2px 7px", borderRadius: 4,
                      background: triageBg(patient.triage_category),
                      border: `1px solid ${color}55`,
                      color, fontSize: "0.72rem", fontWeight: 700,
                    }}>
                      {patient.triage_category ?? "?"}
                    </span>
                  </td>
                  <td style={{ fontSize: "0.78rem", color: "#64748b" }}>{patient.status}</td>
                  <td style={{ fontSize: "0.78rem", color: "#64748b" }}>{patient.assigned_hospital ?? "—"}</td>
                  <td style={{ fontSize: "0.78rem", color: "#94a3b8" }}>
                    {patient.confidence ? `${Math.round(patient.confidence * 100)}%` : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {selected && (
        <div className="patient-detail-card" style={{ borderColor: triageColor(selected.triage_category) + "55" }}>
          <div className="patient-detail-header">
            <span style={{ fontWeight: 700, color: "#f1f5f9", fontSize: "0.85rem" }}>{selected.patient_id}</span>
            <span style={{
              padding: "2px 8px", borderRadius: 4,
              background: triageBg(selected.triage_category),
              color: triageColor(selected.triage_category),
              fontSize: "0.7rem", fontWeight: 800,
              border: `1px solid ${triageColor(selected.triage_category)}55`,
            }}>{selected.triage_category}</span>
            {selected.pediatric && <span className="peds-badge">PEDS</span>}
          </div>
          <p style={{ margin: "6px 0", fontSize: "0.8rem", color: "#cbd5e1", lineHeight: 1.5 }}>{selected.latest_report}</p>
          <div className="vitals-row">
            <span>RR: <strong>{selected.vitals.resp_rate ?? "—"}</strong></span>
            <span>GCS: <strong>{selected.vitals.gcs ?? "—"}</strong></span>
            <span>Pulse: <strong style={{ color: selected.vitals.radial_pulse === false ? "#ef4444" : undefined }}>
              {selected.vitals.radial_pulse == null ? "—" : selected.vitals.radial_pulse ? "✓" : "ABSENT"}
            </strong></span>
          </div>
          {selected.needs.length > 0 && (
            <div style={{ fontSize: "0.75rem", color: "#64748b", marginTop: 4 }}>
              Needs: {selected.needs.join(", ")}
            </div>
          )}
          {selected.data_quality_flags.length > 0 && (
            <div style={{ fontSize: "0.72rem", color: "#f59e0b", marginTop: 4 }}>
              Flags: {selected.data_quality_flags.join(", ")}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
