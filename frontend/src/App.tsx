import { useEffect, useRef, useState } from "react";
import { approveDispatch, controlScenario, getIncident, getIncidentWebSocketUrl, getScenarios, injectEvent, startScenario } from "./api";
import type { AgentHealth, DecisionLogEntry, IncidentSnapshot, ScenarioSummary } from "./types";
import PittsburghMap from "./components/PittsburghMap";
import { PatientTable } from "./components/PatientTable";
import { PreNotifCard } from "./components/PreNotifCard";
import { AgentFeed } from "./components/AgentFeed";

const triageRank: Record<string, number> = { RED: 4, YELLOW: 3, GREEN: 2, BLACK: 1 };
const triageColor: Record<string, string> = { RED: "#ef4444", YELLOW: "#f59e0b", GREEN: "#10b981", BLACK: "#64748b" };

const AGENT_COLORS: Record<string, string> = {
  TRIAGE: "#f59e0b",
  HOSPITAL_INTEL: "#3b82f6",
  LOGISTICS: "#8b5cf6",
  OVERWATCH: "#10b981",
  PRE_NOTIFICATION: "#ef4444",
  ORCHESTRATOR: "#ec4899",
  OPERATOR: "#6b7280",
  SIMULATION: "#6b7280",
};

function statusTone(status: string) {
  if (["RED", "DIVERT", "OUT_OF_SERVICE", "FAILED", "critical"].includes(status)) return "critical";
  if (["YELLOW", "UNKNOWN", "AWAITING_APPROVAL", "DEGRADED", "degraded", "warning"].includes(status)) return "warning";
  return "ok";
}

function LiveClock({ startTime, simMinute }: { startTime?: string; simMinute?: number }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!startTime) { setElapsed(0); return; }
    const base = new Date(startTime).getTime();
    const tick = () => setElapsed(Math.floor((Date.now() - base) / 1000));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [startTime]);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    <div className="timer-block">
      <div className="timer-real">
        <span className="timer-label">LIVE</span>
        <span className="live-clock">{pad(m)}:{pad(s)}</span>
      </div>
      {simMinute !== undefined && (
        <div className="timer-sim">
          <span className="timer-label">SIM</span>
          <span className="sim-min">T+{simMinute}m</span>
        </div>
      )}
    </div>
  );
}

function AgentHealthPills({ agentHealth }: { agentHealth: Record<string, AgentHealth> }) {
  const entries = Object.entries(agentHealth).filter(([n]) => n !== "SIMULATION" && n !== "OPERATOR");
  return (
    <div className="agent-pills">
      {entries.map(([name, health]) => {
        const color = AGENT_COLORS[name.toUpperCase()] ?? "#6b7280";
        const dotColor = health.status === "NOMINAL" ? "#10b981" : health.status === "DEGRADED" ? "#f59e0b" : "#ef4444";
        return (
          <div key={name} className="agent-pill" title={`${name}: ${health.status}${health.llm_mode ? " (LLM active)" : ""}`}>
            <div className="agent-pill-dot" style={{ background: dotColor }} />
            <span className="agent-pill-name" style={{ color }}>{name.slice(0, 3).toUpperCase()}</span>
            {health.llm_mode && <div className="agent-pill-llm" />}
          </div>
        );
      })}
    </div>
  );
}

function TriageSummary({ snapshot }: { snapshot: IncidentSnapshot }) {
  const patients = Object.values(snapshot.patients);
  const counts = { RED: 0, YELLOW: 0, GREEN: 0, BLACK: 0 };
  patients.forEach(p => {
    if (p.triage_category) counts[p.triage_category as keyof typeof counts]++;
  });
  const ambulances = Object.values(snapshot.ambulances);
  const available = ambulances.filter(a => a.status === "AVAILABLE").length;
  const enRoute = ambulances.filter(a => a.status === "EN_ROUTE" || a.status === "DISPATCHED").length;

  return (
    <div className="triage-summary-bar">
      {(["RED", "YELLOW", "GREEN", "BLACK"] as const).map(cat => (
        <div key={cat} className="triage-count-chip" style={{ borderColor: triageColor[cat] + "55", background: triageColor[cat] + "12" }}>
          <div className="triage-dot" style={{ background: triageColor[cat] }} />
          <span className="triage-count-num" style={{ color: triageColor[cat] }}>{counts[cat]}</span>
          <span className="triage-count-label">{cat}</span>
        </div>
      ))}
      <div className="triage-divider" />
      <div className="amb-status-chip">
        <span className="amb-icon" style={{ color: "#10b981" }}>●</span>
        <span className="amb-num">{available}</span>
        <span className="amb-label">avail</span>
      </div>
      <div className="amb-status-chip">
        <span className="amb-icon" style={{ color: "#f59e0b" }}>●</span>
        <span className="amb-num">{enRoute}</span>
        <span className="amb-label">en route</span>
      </div>
    </div>
  );
}

function ActivityTicker({ log }: { log: DecisionLogEntry[] }) {
  const recent = [...log].reverse().slice(0, 5);
  const severityColor = (s: string) => s === "CRITICAL" ? "#ef4444" : s === "WARNING" ? "#f59e0b" : "#94a3b8";
  return (
    <div className="activity-ticker">
      {recent.map((entry, i) => (
        <div key={`${entry.minute}-${i}`} className="ticker-entry" style={{ opacity: 1 - i * 0.17 }}>
          <span className="ticker-agent" style={{ color: AGENT_COLORS[entry.agent] ?? "#6b7280" }}>
            {entry.agent.replace("_", " ").slice(0, 12)}
          </span>
          <span className="ticker-msg" style={{ color: severityColor(entry.severity) }}>
            {entry.message.slice(0, 70)}{entry.message.length > 70 ? "…" : ""}
          </span>
        </div>
      ))}
    </div>
  );
}

function MetricBar({ label, value, compare, pct = false, lowerIsBetter = false }: {
  label: string; value: number; compare?: number; pct?: boolean; lowerIsBetter?: boolean;
}) {
  const fmt = (v: number) => pct ? `${Math.round(v * 100)}%` : v.toFixed(1);
  const better = compare !== undefined ? (lowerIsBetter ? value <= compare : value >= compare) : undefined;
  const diffRaw = compare !== undefined ? value - compare : undefined;
  const diffLabel = diffRaw !== undefined
    ? (pct ? `${diffRaw > 0 ? "+" : ""}${Math.round(diffRaw * 100)}pp` : `${diffRaw > 0 ? "+" : ""}${diffRaw.toFixed(1)}`)
    : null;
  const barPct = Math.min(pct ? value * 100 : Math.min(value / 100, 1) * 100, 100);
  const barColor = better === true ? "#10b981" : better === false ? "#ef4444" : "#3b82f6";

  return (
    <div className="metric-bar-item">
      <div className="metric-bar-header">
        <span className="metric-bar-label">{label}</span>
        <div className="metric-bar-values">
          <strong className="metric-bar-value">{fmt(value)}</strong>
          {diffLabel && (
            <span className={`metric-bar-diff ${better ? "diff-up" : "diff-down"}`}>
              {diffLabel}
            </span>
          )}
        </div>
      </div>
      <div className="metric-bar-track">
        <div className="metric-bar-fill" style={{ width: `${barPct}%`, background: barColor }} />
      </div>
    </div>
  );
}

export default function App() {
  const [scenarios, setScenarios] = useState<ScenarioSummary[]>([]);
  const [selectedScenario, setSelectedScenario] = useState("bridge-collapse-standard");
  const [snapshot, setSnapshot] = useState<IncidentSnapshot | null>(null);
  const [selectedHospitalId, setSelectedHospitalId] = useState<string | null>(null);
  const [selectedPatientId, setSelectedPatientId] = useState<string | null>(null);
  const [speed, setSpeed] = useState(3);
  const [isPlaying, setIsPlaying] = useState(false);
  const [socketState, setSocketState] = useState("idle");
  const [error, setError] = useState<string | null>(null);
  const [rightTab, setRightTab] = useState<"patients" | "approvals" | "prenotif" | "metrics">("patients");
  const [feedTab, setFeedTab] = useState<"log" | "comms" | "network">("log");
  const [compareBaseline, setCompareBaseline] = useState(true);
  const wsRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<IncidentSnapshot | null>(null);
  const [approvingId, setApprovingId] = useState<string | null>(null);

  // Keep ref in sync so approve handler always has the latest snapshot
  useEffect(() => { snapshotRef.current = snapshot; }, [snapshot]);

  useEffect(() => {
    getScenarios().then(setScenarios).catch(() => setError("Could not load scenarios."));
  }, []);

  // WebSocket connection
  useEffect(() => {
    if (!snapshot?.incident_id) return;
    const ws = new WebSocket(getIncidentWebSocketUrl(snapshot.incident_id));
    wsRef.current = ws;
    setSocketState("connecting");
    ws.onopen = () => setSocketState("live");
    ws.onmessage = (e) => setSnapshot(JSON.parse(e.data) as IncidentSnapshot);
    ws.onerror = () => setSocketState("degraded");
    ws.onclose = () => setSocketState("closed");
    return () => ws.close();
  }, [snapshot?.incident_id]);

  // Polling fallback
  useEffect(() => {
    if (!snapshot?.incident_id || socketState === "live") return;
    const id = window.setInterval(async () => {
      try { setSnapshot(await getIncident(snapshot.incident_id)); }
      catch { setSocketState("degraded"); }
    }, 1200);
    return () => window.clearInterval(id);
  }, [snapshot?.incident_id, socketState]);

  const patients = snapshot
    ? Object.values(snapshot.patients).sort((a, b) => {
        const td = (triageRank[b.triage_category ?? "GREEN"] ?? 0) - (triageRank[a.triage_category ?? "GREEN"] ?? 0);
        return td || a.reported_minute - b.reported_minute;
      })
    : [];

  const preNotifications = snapshot?.pre_notifications ?? [];
  const pendingDispatches = snapshot
    ? snapshot.dispatches.filter(d => snapshot.pending_approvals.includes(d.dispatch_id))
    : [];
  const llmCount = snapshot ? Object.values(snapshot.agent_health).filter(h => h.llm_mode).length : 0;
  const baselineMetrics = snapshot?.baseline.current ?? snapshot?.baseline.final_metrics;
  const latestSitrep = snapshot?.sitreps[snapshot.sitreps.length - 1] ?? null;
  const hasPending = pendingDispatches.length > 0;
  const hasPreNotifs = preNotifications.length > 0;

  async function handleStart() {
    try {
      setError(null);
      const incident = await startScenario(selectedScenario);
      setSnapshot(incident);
      setIsPlaying(false);
      setSelectedHospitalId(null);
      setSelectedPatientId(null);
      // Auto-play after a brief pause
      setTimeout(async () => {
        try {
          const updated = await controlScenario(incident.scenario_id, incident.incident_id, "play", speed);
          setSnapshot(updated);
          setIsPlaying(true);
        } catch { /* ignore */ }
      }, 600);
    } catch (e) { setError("Could not start scenario."); }
  }

  async function handleControl(action: string, steps?: number) {
    if (!snapshot) return;
    try {
      setError(null);
      if (action === "play") setIsPlaying(true);
      if (action === "pause") setIsPlaying(false);
      const updated = await controlScenario(snapshot.scenario_id, snapshot.incident_id, action, speed, steps);
      setSnapshot(updated);
    } catch { setError(`Control action '${action}' failed.`); }
  }

  async function handleApprove(dispatchId: string) {
    const current = snapshotRef.current;
    if (!current || approvingId) return;
    setApprovingId(dispatchId);
    setError(null);
    try {
      const updated = await approveDispatch(dispatchId, current.incident_id);
      setSnapshot(updated);
    } catch (e) {
      setError(`Approval failed for ${dispatchId}: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApprovingId(null);
    }
  }

  async function handleInject(kind: "diversion" | "ambulance" | "stale") {
    if (!snapshot) return;
    const events = {
      diversion: { minute: snapshot.current_minute, type: "HOSPITAL_STATUS_CHANGED", hospital_id: "H-003", status: "DIVERT", divert_status: true, reason: "ED at capacity — manual diversion" },
      ambulance: { minute: snapshot.current_minute, type: "AMBULANCE_STATUS_CHANGED", ambulance_id: "A-009", status: "OUT_OF_SERVICE", reason: "Mechanical failure" },
      stale: { minute: snapshot.current_minute, type: "HOSPITAL_STALE", hospital_id: "H-001" },
    };
    try {
      setError(null);
      setSnapshot(await injectEvent(snapshot.incident_id, events[kind]));
    } catch { setError("Event injection failed."); }
  }

  const phase = snapshot?.incident_phase ?? "";
  const phaseColor = phase === "ACTIVE" ? "#ef4444" : phase === "STABILIZING" ? "#f59e0b" : "#10b981";

  return (
    <div className="app-shell">
      {/* ═══ TOP BAR ═══ */}
      <header className="topbar">
        <div className="topbar-brand">
          {snapshot && <span className="active-dot" />}
          <span className="brand-name">FIELDOPS</span>
          <span className="brand-sub">MCI Command · Pittsburgh</span>
        </div>

        <div className="topbar-controls">
          <select className="ctrl-select" value={selectedScenario} onChange={e => setSelectedScenario(e.target.value)}>
            {scenarios.map(s => <option key={s.scenario_id} value={s.scenario_id}>{s.name}</option>)}
          </select>
          <select className="ctrl-select" value={speed} onChange={e => setSpeed(Number(e.target.value))}>
            {[1, 2, 3, 5, 10].map(v => <option key={v} value={v}>{v}x</option>)}
          </select>
          <button className="ctrl-btn ctrl-btn--primary" onClick={handleStart}>
            {snapshot ? "↺ Restart" : "▶ Launch"}
          </button>
          {snapshot && (
            <>
              <button className="ctrl-btn ctrl-btn--play" onClick={() => handleControl(isPlaying ? "pause" : "play")} title={isPlaying ? "Pause" : "Play"}>
                {isPlaying ? "⏸ Pause" : "▶ Play"}
              </button>
              <button className="ctrl-btn" onClick={() => handleControl("step", 1)}>Step →</button>
            </>
          )}
          <div className="inject-group">
            <span className="inject-label">Inject:</span>
            <button className="ctrl-btn ctrl-btn--warn" onClick={() => handleInject("diversion")} disabled={!snapshot}>Divert</button>
            <button className="ctrl-btn ctrl-btn--warn" onClick={() => handleInject("ambulance")} disabled={!snapshot}>A-Fail</button>
            <button className="ctrl-btn ctrl-btn--warn" onClick={() => handleInject("stale")} disabled={!snapshot}>Stale</button>
          </div>
        </div>

        <div className="topbar-right">
          {snapshot && <AgentHealthPills agentHealth={snapshot.agent_health} />}

          <div className="status-pills">
            <span className={`spill spill--${statusTone(socketState === "live" ? "ok" : socketState)}`}>
              {socketState === "live" ? "● LIVE" : socketState.toUpperCase()}
            </span>
            {llmCount > 0 && <span className="spill spill--ok">{llmCount} LLM</span>}
            {snapshot && <span className="spill" style={{ background: phaseColor + "18", color: phaseColor, border: `1px solid ${phaseColor}44` }}>{phase}</span>}
            {hasPending && (
              <button className="spill spill--critical blink approval-alert-btn" onClick={() => setRightTab("approvals")}>
                ⚠ {pendingDispatches.length} APPROVAL{pendingDispatches.length > 1 ? "S" : ""}
              </button>
            )}
          </div>

          <LiveClock startTime={snapshot?.start_time} simMinute={snapshot?.current_minute} />
        </div>
      </header>

      {error && (
        <div className="error-strip">
          <span>⚠ {error}</span>
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}

      {/* ═══ SPLASH ═══ */}
      {!snapshot ? (
        <main className="splash">
          <div className="splash-card">
            <div className="splash-logo">
              <div className="splash-pulse-ring" />
              <div className="splash-dot-core" />
            </div>
            <h1 className="splash-title">FieldOps</h1>
            <p className="splash-sub">Multi-Agent AI Mass Casualty Incident Command</p>
            <p className="splash-desc">Gemini 2.5 Flash · LlamaIndex RAG · Real-time Pittsburgh EMS · Gmail pre-notifications</p>

            <div className="splash-features">
              {[
                { icon: "🧠", label: "AI Triage", desc: "Gemini classifies patients using START/JumpStart protocols via LlamaIndex RAG" },
                { icon: "🚑", label: "Pre-Notification", desc: "AI-generated hospital alerts before arrival — 8+ minutes advance warning" },
                { icon: "🎯", label: "Orchestrator", desc: "Master AI coordinates all agents, detects conflicts, issues directives" },
                { icon: "🗺️", label: "Live Map", desc: "Real-time ambulance movement across Pittsburgh with animated routes" },
              ].map(f => (
                <div key={f.label} className="splash-feature">
                  <span className="splash-icon">{f.icon}</span>
                  <strong>{f.label}</strong>
                  <span>{f.desc}</span>
                </div>
              ))}
            </div>
            <button className="splash-start-btn" onClick={handleStart}>
              Launch Demo Scenario →
            </button>
            <p className="splash-hint">Pittsburgh Bridge Collapse — 19 patients, 15 ambulances, 6 hospitals</p>
          </div>
        </main>
      ) : (
        <main className="dashboard">
          {/* ═══ LEFT: Map ═══ */}
          <section className="map-section">
            <div className="map-header">
              <div className="map-header-left">
                <span className="map-title">Pittsburgh Live Incident Map</span>
                {isPlaying && <span className="map-playing-badge">● LIVE</span>}
              </div>
              <TriageSummary snapshot={snapshot} />
            </div>

            <div className="map-container">
              <PittsburghMap
                snapshot={snapshot}
                onHospitalClick={id => { setSelectedHospitalId(id); }}
                selectedHospitalId={selectedHospitalId}
              />
            </div>

            {/* Hospital detail */}
            {selectedHospitalId && snapshot.hospitals[selectedHospitalId] && (() => {
              const h = snapshot.hospitals[selectedHospitalId];
              const alerts = preNotifications.filter(n => n.hospital_id === h.hospital_id);
              const loadPct = Math.round(h.current_load_pct * 100);
              const loadColor = loadPct > 85 ? "#ef4444" : loadPct > 60 ? "#f59e0b" : "#10b981";
              return (
                <div className="hosp-detail-strip">
                  <button className="hosp-close" onClick={() => setSelectedHospitalId(null)}>✕</button>
                  <div className="hosp-detail-main">
                    <span className="hosp-detail-name">{h.name}</span>
                    <span className={`hosp-status-badge ${h.divert_status ? "critical" : h.status === "OPEN" ? "ok" : "warning"}`}>
                      {h.divert_status ? "⛔ DIVERT" : h.status}
                    </span>
                    <span className="hosp-level">Level {h.trauma_level} Trauma</span>
                  </div>
                  <div className="hosp-detail-stats">
                    <div className="hosp-stat"><span className="hosp-stat-label">Beds</span><strong>{h.capacity.available_beds}/{h.capacity.total_beds}</strong></div>
                    <div className="hosp-stat"><span className="hosp-stat-label">ICU</span><strong>{h.capacity.icu_available}</strong></div>
                    <div className="hosp-stat"><span className="hosp-stat-label">OR</span><strong>{h.capacity.or_available}</strong></div>
                    <div className="hosp-stat"><span className="hosp-stat-label">ETA</span><strong>{h.eta_from_scene_minutes}m</strong></div>
                    <div className="hosp-stat">
                      <span className="hosp-stat-label">Load</span>
                      <div className="hosp-load-bar">
                        <div className="hosp-load-fill" style={{ width: `${Math.min(loadPct, 100)}%`, background: loadColor }} />
                      </div>
                      <strong style={{ color: loadColor }}>{loadPct}%</strong>
                    </div>
                  </div>
                  {alerts.length > 0 && (
                    <div className="hosp-incoming-alerts">
                      {alerts.map(a => (
                        <span key={a.notification_id} className="hosp-incoming-badge">
                          🚑 {a.ambulance_id} ETA {a.eta_minutes}m — {a.triage_category}
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              );
            })()}

            {/* Activity ticker */}
            {snapshot.decision_log.length > 0 && (
              <ActivityTicker log={snapshot.decision_log} />
            )}

            {/* Metrics strip */}
            <div className="metrics-strip">
              <MetricBar label="Triage Acc" value={snapshot.metrics.triage_accuracy} compare={compareBaseline ? baselineMetrics?.triage_accuracy : undefined} pct />
              <MetricBar label="Transport" value={snapshot.metrics.transport_match_score} compare={compareBaseline ? baselineMetrics?.transport_match_score : undefined} pct />
              <MetricBar label="Survival" value={snapshot.metrics.survival_proxy_score} compare={compareBaseline ? baselineMetrics?.survival_proxy_score : undefined} pct />
              <MetricBar label="Load Gini" value={snapshot.metrics.hospital_load_gini} compare={compareBaseline ? baselineMetrics?.hospital_load_gini : undefined} lowerIsBetter />
              <div className="metrics-strip-actions">
                <button
                  className={`ctrl-btn ctrl-btn--xs ${compareBaseline ? "ctrl-btn--active" : ""}`}
                  onClick={() => setCompareBaseline(v => !v)}
                >vs Baseline</button>
                <span className="metrics-transported">
                  {snapshot.metrics.transported}/{Object.keys(snapshot.patients).length} transported
                </span>
              </div>
            </div>
          </section>

          {/* ═══ RIGHT PANEL ═══ */}
          <aside className="right-panel">
            <div className="right-tab-bar">
              <button className={`rtab ${rightTab === "patients" ? "rtab--active" : ""}`} onClick={() => setRightTab("patients")}>
                Patients {patients.length > 0 && <span className="rtab-badge">{patients.length}</span>}
              </button>
              <button className={`rtab ${rightTab === "approvals" ? "rtab--active" : ""}`} onClick={() => setRightTab("approvals")}>
                Approvals {hasPending && <span className="rtab-badge rtab-badge--red blink">{pendingDispatches.length}</span>}
              </button>
              <button className={`rtab ${rightTab === "prenotif" ? "rtab--active" : ""}`} onClick={() => setRightTab("prenotif")}>
                Pre-Alerts {hasPreNotifs && <span className="rtab-badge rtab-badge--amber">{preNotifications.length}</span>}
              </button>
              <button className={`rtab ${rightTab === "metrics" ? "rtab--active" : ""}`} onClick={() => setRightTab("metrics")}>
                SITREP
              </button>
            </div>

            <div className="right-panel-content">
              {rightTab === "patients" && (
                <PatientTable
                  patients={patients}
                  snapshot={snapshot}
                  selectedPatientId={selectedPatientId}
                  onSelectPatient={setSelectedPatientId}
                />
              )}

              {rightTab === "approvals" && (
                <div className="approvals-panel">
                  {pendingDispatches.length === 0 ? (
                    <div className="empty-panel">
                      <div className="empty-icon-ring">✓</div>
                      <p>No pending approvals</p>
                      <span>RED patient dispatches require human review before execution</span>
                    </div>
                  ) : (
                    pendingDispatches.map(dispatch => {
                      const patient = snapshot.patients[dispatch.patient_id];
                      const hospital = snapshot.hospitals[dispatch.destination_hospital];
                      return (
                        <div key={dispatch.dispatch_id} className="approval-card-v2">
                          <div className="approval-header">
                            <div className="approval-header-left">
                              <div className="triage-dot" style={{ background: "#ef4444", width: 10, height: 10, borderRadius: "50%" }} />
                              <span className="approval-patient-id">{dispatch.patient_id}</span>
                              <span className="approval-unit">{dispatch.ambulance_id}</span>
                            </div>
                            <span className="approval-priority-badge">RED — HUMAN REQUIRED</span>
                          </div>
                          <p className="approval-report">
                            {patient?.latest_report?.slice(0, 140)}{(patient?.latest_report?.length ?? 0) > 140 ? "…" : ""}
                          </p>
                          <div className="approval-route">
                            <span className="approval-route-from">Scene</span>
                            <div className="approval-route-line">
                              <div className="approval-route-dot" />
                            </div>
                            <span className="approval-route-to">{hospital?.name ?? dispatch.destination_hospital}</span>
                            <span className="approval-eta">ETA {dispatch.eta_minutes}min</span>
                          </div>
                          {dispatch.reasoning && (
                            <p className="approval-reasoning">
                              AI: "{dispatch.reasoning.slice(0, 160)}{dispatch.reasoning.length > 160 ? "…" : ""}"
                            </p>
                          )}
                          <div className="approval-conf">
                            <div className="conf-bar-track">
                              <div className="conf-bar-fill" style={{ width: `${Math.round(dispatch.confidence * 100)}%` }} />
                            </div>
                            <span>{Math.round(dispatch.confidence * 100)}% confidence</span>
                          </div>
                          <button
                            className="approve-btn"
                            onClick={() => handleApprove(dispatch.dispatch_id)}
                            disabled={approvingId === dispatch.dispatch_id}
                            style={{ opacity: approvingId === dispatch.dispatch_id ? 0.6 : 1 }}
                          >
                            {approvingId === dispatch.dispatch_id ? "⏳ Approving…" : "✓ Approve Dispatch"}
                          </button>
                        </div>
                      );
                    })
                  )}
                </div>
              )}

              {rightTab === "prenotif" && (
                <div className="prenotif-panel">
                  {preNotifications.length === 0 ? (
                    <div className="empty-panel">
                      <div className="empty-icon-ring">📡</div>
                      <p>No pre-notifications yet</p>
                      <span>AI-generated hospital alerts appear when ambulances are dispatched</span>
                    </div>
                  ) : (
                    [...preNotifications].reverse().map(n => (
                      <PreNotifCard
                        key={n.notification_id}
                        notif={n}
                        patient={snapshot.patients[n.patient_id]}
                      />
                    ))
                  )}
                </div>
              )}

              {rightTab === "metrics" && (
                <div className="sitrep-panel">
                  {latestSitrep && (
                    <div className="sitrep-card-v2">
                      <div className="sitrep-header">
                        <span className="sitrep-id">{latestSitrep.sitrep_id}</span>
                        <span className="sitrep-phase" style={{ color: phaseColor }}>{latestSitrep.incident_phase}</span>
                      </div>
                      <p className="sitrep-summary">{latestSitrep.summary}</p>
                      {latestSitrep.alerts.length > 0 && (
                        <div className="sitrep-alerts">
                          {latestSitrep.alerts.map(alert => (
                            <span key={`${alert.type}-${alert.message}`} className={`sitrep-alert-pill ${statusTone(alert.severity)}`}>
                              {alert.type}
                            </span>
                          ))}
                        </div>
                      )}
                      {latestSitrep.recommendations.length > 0 && (
                        <div className="sitrep-recs">
                          {latestSitrep.recommendations.map((rec, i) => (
                            <p key={i} className="sitrep-rec">• {rec}</p>
                          ))}
                        </div>
                      )}
                    </div>
                  )}
                  <div className="metrics-full-grid">
                    <div className="metrics-full-section-label">PERFORMANCE vs BASELINE</div>
                    <MetricBar label="Triage Accuracy" value={snapshot.metrics.triage_accuracy} compare={compareBaseline ? baselineMetrics?.triage_accuracy : undefined} pct />
                    <MetricBar label="Transport Match" value={snapshot.metrics.transport_match_score} compare={compareBaseline ? baselineMetrics?.transport_match_score : undefined} pct />
                    <MetricBar label="Survival Proxy" value={snapshot.metrics.survival_proxy_score} compare={compareBaseline ? baselineMetrics?.survival_proxy_score : undefined} pct />
                    <MetricBar label="Hospital Load Gini" value={snapshot.metrics.hospital_load_gini} compare={compareBaseline ? baselineMetrics?.hospital_load_gini : undefined} lowerIsBetter />
                    <div className="metrics-full-section-label" style={{ marginTop: 12 }}>COUNTS</div>
                    <div className="metrics-counts-grid">
                      <div className="metric-count-box"><strong>{snapshot.metrics.transported}</strong><span>transported</span></div>
                      <div className="metric-count-box"><strong>{snapshot.metrics.awaiting_dispatch}</strong><span>awaiting</span></div>
                      <div className="metric-count-box"><strong>{preNotifications.length}</strong><span>pre-alerts</span></div>
                      <div className="metric-count-box"><strong>{snapshot.agent_messages?.length ?? 0}</strong><span>agent msgs</span></div>
                    </div>
                  </div>
                  {compareBaseline && baselineMetrics && (
                    <div className="baseline-note">Baseline: deterministic nearest-hospital algorithm at T+{snapshot.current_minute}</div>
                  )}
                </div>
              )}
            </div>

            {/* Agent Feed */}
            <div className="agent-feed-section">
              <AgentFeed snapshot={snapshot} activeTab={feedTab} onTabChange={setFeedTab} />
            </div>
          </aside>
        </main>
      )}
    </div>
  );
}
