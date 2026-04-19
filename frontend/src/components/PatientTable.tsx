import type { PatientRecord, IncidentSnapshot } from "../types";

interface PatientTableProps {
  patients: PatientRecord[];
  snapshot: IncidentSnapshot;
  selectedPatientId: string | null;
  onSelectPatient: (id: string) => void;
}

const triageColor = (cat?: string | null) =>
  cat === "RED" ? "#ef4444" : cat === "YELLOW" ? "#f59e0b" : cat === "GREEN" ? "#10b981" : "#64748b";

const triageRowClass = (cat?: string | null) =>
  cat === "RED" ? "triage-red" : cat === "YELLOW" ? "triage-yellow" : cat === "GREEN" ? "triage-green" : "triage-black";

const statusColor = (status: string) => {
  if (["DISPATCHED", "EN_ROUTE", "TRANSPORTED"].includes(status)) return "#10b981";
  if (["AWAITING_DISPATCH", "TRIAGED"].includes(status)) return "#f59e0b";
  return "#94a3b8";
};

export function PatientTable({ patients, snapshot, selectedPatientId, onSelectPatient }: PatientTableProps) {
  return (
    <div className="ptable-area">
      <table className="ptable">
        <thead>
          <tr>
            <th>Triage</th>
            <th>Patient</th>
            <th>Status</th>
            <th>Hospital</th>
            <th>Conf</th>
          </tr>
        </thead>
        <tbody>
          {patients.map((p) => {
            const isSelected = selectedPatientId === p.patient_id;
            const color = triageColor(p.triage_category);
            return [
              <tr
                key={p.patient_id}
                className={`ptrow ${triageRowClass(p.triage_category)}${isSelected ? " selected" : ""}`}
                onClick={() => onSelectPatient(p.patient_id)}
              >
                <td>
                  <span style={{ display: "inline-block", width: 8, height: 8, borderRadius: "50%", background: color }} />
                </td>
                <td>
                  <span className="pid">{p.patient_id}</span>
                  {p.pediatric && (
                    <span style={{ fontSize: "0.58rem", color: "#8b5cf6", marginLeft: 5, fontWeight: 700, fontFamily: "var(--font-mono)" }}>PEDS</span>
                  )}
                </td>
                <td>
                  <span style={{ fontSize: "0.72rem", color: statusColor(p.status) }}>
                    {p.status.replace(/_/g, " ")}
                  </span>
                </td>
                <td>
                  <span style={{ fontSize: "0.72rem", color: "var(--text-2)" }}>
                    {p.assigned_hospital ? p.assigned_hospital.replace("H-", "").slice(0, 14) : "—"}
                  </span>
                </td>
                <td>
                  <span
                    className="conf-pct"
                    style={{ color: !p.confidence ? "#64748b" : p.confidence >= 0.9 ? "#10b981" : p.confidence >= 0.75 ? "#f59e0b" : "#ef4444" }}
                  >
                    {p.confidence ? `${Math.round(p.confidence * 100)}%` : "—"}
                  </span>
                </td>
              </tr>,

              // Inline expand row
              isSelected && (
                <tr key={`${p.patient_id}-expand`} className="expand-row">
                  <td colSpan={5}>
                    <div className="vitals-chips">
                      <div className="vital-chip">
                        <span className="vital-label">GCS</span>
                        <span className="vital-val">{p.vitals.gcs ?? "—"}</span>
                      </div>
                      <div className="vital-chip">
                        <span className="vital-label">RR</span>
                        <span className="vital-val">{p.vitals.resp_rate != null ? `${p.vitals.resp_rate}/min` : "—"}</span>
                      </div>
                      <div className="vital-chip">
                        <span className="vital-label">Pulse</span>
                        <span className="vital-val" style={{ color: p.vitals.radial_pulse === false ? "#ef4444" : undefined }}>
                          {p.vitals.radial_pulse == null ? "—" : p.vitals.radial_pulse ? "Present" : "Absent"}
                        </span>
                      </div>
                      {(p.injuries ?? []).slice(0, 3).map((inj, i) => (
                        <div key={i} className="vital-chip" style={{ borderColor: "rgba(30,58,95,0.5)" }}>
                          <span className="vital-val" style={{ color: "var(--text-2)", fontWeight: 400 }}>{inj}</span>
                        </div>
                      ))}
                    </div>
                    {p.needs.length > 0 && (
                      <div style={{ marginTop: 5, fontSize: "0.68rem", color: "var(--text-3)" }}>
                        Needs: {p.needs.join(", ")}
                      </div>
                    )}
                    {p.citation && (
                      <div style={{ marginTop: 6, padding: "4px 7px", background: "rgba(56,189,248,0.07)", borderLeft: "2px solid #38bdf8", borderRadius: "0 3px 3px 0" }}>
                        <div style={{ fontSize: "0.62rem", color: "#38bdf8", fontWeight: 700, fontFamily: "var(--font-mono)", marginBottom: 2 }}>
                          PROTOCOL: {p.citation.source}
                        </div>
                        {p.citation.excerpt && (
                          <div style={{ fontSize: "0.65rem", color: "var(--text-3)", lineHeight: 1.35, fontStyle: "italic" }}>
                            "{p.citation.excerpt.slice(0, 120)}{p.citation.excerpt.length > 120 ? "…" : ""}"
                          </div>
                        )}
                      </div>
                    )}
                    {p.memory_summary && (
                      <div style={{ marginTop: 5, padding: "4px 7px", background: "rgba(139,92,246,0.07)", borderLeft: "2px solid #8b5cf6", borderRadius: "0 3px 3px 0" }}>
                        <div style={{ fontSize: "0.62rem", color: "#8b5cf6", fontWeight: 700, fontFamily: "var(--font-mono)", marginBottom: 2 }}>
                          SIMILAR CASES (LlamaIndex Memory)
                        </div>
                        <div style={{ fontSize: "0.65rem", color: "var(--text-3)", lineHeight: 1.35 }}>
                          {p.memory_summary.slice(0, 160)}{p.memory_summary.length > 160 ? "…" : ""}
                        </div>
                      </div>
                    )}
                    {p.data_quality_flags.length > 0 && (
                      <div style={{ marginTop: 3, fontSize: "0.65rem", color: "var(--warn)" }}>
                        Flags: {p.data_quality_flags.join(", ")}
                      </div>
                    )}
                  </td>
                </tr>
              ),
            ].filter(Boolean);
          })}
        </tbody>
      </table>
    </div>
  );
}
