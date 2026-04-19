import { useEffect, useRef, useState } from "react";
import {
  approveDispatch,
  controlScenario,
  getIncident,
  getIncidentWebSocketUrl,
  getScenarios,
  injectEvent,
  setIncidentMode,
  startScenario,
} from "./api";
import type { AgentHealth, IncidentSnapshot, ScenarioSummary } from "./types";
import PittsburghMap from "./components/PittsburghMap";
import { PatientTable } from "./components/PatientTable";
import { PreNotifCard } from "./components/PreNotifCard";
import { AgentFeed } from "./components/AgentFeed";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

const triageRank: Record<string, number> = { RED: 4, YELLOW: 3, GREEN: 2, BLACK: 1 };

const AGENT_COLORS: Record<string, string> = {
  TRIAGE: "#f59e0b", HOSPITAL_INTEL: "#3b82f6", LOGISTICS: "#8b5cf6",
  OVERWATCH: "#10b981", PRE_NOTIFICATION: "#ef4444", ORCHESTRATOR: "#ec4899",
  OPERATOR: "#6b7280", SIMULATION: "#6b7280",
};

const AGENT_META: { key: string; label: string; color: string; fullKey: string }[] = [
  { key: "TRI", label: "Triage",       color: "#f59e0b", fullKey: "TRIAGE" },
  { key: "HOS", label: "Hosp Intel",   color: "#3b82f6", fullKey: "HOSPITAL_INTEL" },
  { key: "LOG", label: "Logistics",    color: "#8b5cf6", fullKey: "LOGISTICS" },
  { key: "OVR", label: "Overwatch",    color: "#10b981", fullKey: "OVERWATCH" },
  { key: "PRE", label: "Pre-Notify",   color: "#ef4444", fullKey: "PRE_NOTIFICATION" },
  { key: "ORC", label: "Orchestrator", color: "#ec4899", fullKey: "ORCHESTRATOR" },
];

// ── Live Clock ──────────────────────────────────────────────
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
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    <div className="timer-block">
      <div className="timer-real">
        <span className="timer-label">LIVE</span>
        <span className="live-clock">{pad(Math.floor(elapsed / 60))}:{pad(elapsed % 60)}</span>
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

// ── Command Bar ─────────────────────────────────────────────
interface CommandBarProps {
  snapshot: IncidentSnapshot | null;
  scenarios: ScenarioSummary[];
  selectedScenario: string;
  onSelectScenario: (s: string) => void;
  speed: number;
  onSpeed: (s: number) => void;
  isPlaying: boolean;
  socketState: string;
  modeUpdating: boolean;
  pendingCount: number;
  onStart: () => void;
  onControl: (action: string, steps?: number) => void;
  onModeChange: (mode: string) => void;
  onInject: (kind: "diversion" | "ambulance" | "stale") => void;
  onBellClick: () => void;
}

function CommandBar({
  snapshot, scenarios, selectedScenario, onSelectScenario,
  speed, onSpeed, isPlaying, socketState, modeUpdating,
  pendingCount, onStart, onControl, onModeChange, onInject, onBellClick,
}: CommandBarProps) {
  const [injOpen, setInjOpen] = useState(false);

  const wsClass = socketState === "live" ? "ws-pill--live" : socketState === "degraded" ? "ws-pill--deg" : "ws-pill--closed";
  const wsLabel = socketState === "live" ? "LIVE" : socketState.toUpperCase();

  const agentHealth = snapshot?.agent_health ?? {};
  const dotColor = (status: string) =>
    status === "NOMINAL" ? "#10b981" : status === "DEGRADED" ? "#f59e0b" : "#ef4444";

  const llmCount = Object.values(agentHealth).filter((h: AgentHealth) => h.llm_mode).length;

  const phaseClass = snapshot?.incident_phase === "ACTIVE" ? "phase-badge--active"
    : snapshot?.incident_phase === "STABILIZING" ? "phase-badge--stab" : "phase-badge--recovery";

  return (
    <header className="cmd-bar">
      {/* LEFT */}
      <div className="cmd-bar-left">
        {snapshot && <div className="live-dot" />}
        <span className="wordmark">FIELDOPS</span>
        {snapshot && (
          <>
            <span className="incident-chip">{snapshot.incident_id.slice(0, 12)}</span>
            <LiveClock startTime={snapshot.start_time} simMinute={snapshot.current_minute} />
          </>
        )}
      </div>

      {/* CENTER */}
      <div className="cmd-bar-center">
        {snapshot && (
          <>
            <span className="scenario-label">Bridge Collapse — Pittsburgh, PA</span>
            <span className={`phase-badge ${phaseClass}`}>{snapshot.incident_phase}</span>
          </>
        )}
      </div>

      {/* RIGHT */}
      <div className="cmd-bar-right">
        {snapshot && (
          <div className="mode-seg">
            {(["speed", "balanced", "accuracy"] as const).map((m) => (
              <button
                key={m} disabled={modeUpdating}
                className={`mode-btn${snapshot.mode === m ? " mode-btn--active" : ""}`}
                onClick={() => onModeChange(m)}
              >
                {m.toUpperCase()}
              </button>
            ))}
          </div>
        )}

        <select className="ctrl-select" value={speed} onChange={(e) => onSpeed(Number(e.target.value))}>
          {[1, 2, 3, 5, 10].map((v) => <option key={v} value={v}>{v}×</option>)}
        </select>

        <select
          className="ctrl-select"
          value={selectedScenario}
          onChange={(e) => onSelectScenario(e.target.value)}
        >
          {scenarios.map((s) => <option key={s.scenario_id} value={s.scenario_id}>{s.name}</option>)}
        </select>

        {snapshot && (
          <div className="inject-wrap">
            <button className="ctrl-btn ctrl-btn--warn ctrl-btn--xs" onClick={() => setInjOpen((o) => !o)}>
              ⚡ Inject
            </button>
            {injOpen && (
              <div className="inject-dropdown" onMouseLeave={() => setInjOpen(false)}>
                <button className="inject-option" onClick={() => { onInject("diversion"); setInjOpen(false); }}>Hospital Divert</button>
                <button className="inject-option" onClick={() => { onInject("ambulance"); setInjOpen(false); }}>Ambulance Fail</button>
                <button className="inject-option" onClick={() => { onInject("stale"); setInjOpen(false); }}>Stale Feed</button>
              </div>
            )}
          </div>
        )}

        {snapshot && (
          <>
            <button
              className={`ctrl-btn ${isPlaying ? "ctrl-btn--warn" : "ctrl-btn--play"}`}
              onClick={() => onControl(isPlaying ? "pause" : "play")}
            >
              {isPlaying ? "⏸ Pause" : "▶ Play"}
            </button>
            <button className="ctrl-btn" onClick={() => onControl("step", 1)}>⏭ Step</button>
          </>
        )}

        <button className="ctrl-btn ctrl-btn--primary" onClick={onStart}>
          {snapshot ? "Restart" : "Launch"}
        </button>

        {snapshot && pendingCount > 0 && (
          <button className="bell-btn bell-btn--alert" onClick={onBellClick} title={`${pendingCount} pending approvals`}>
            🔔
            <span className="bell-badge">{pendingCount}</span>
          </button>
        )}

        <div className="divider-v" />

        <div className="status-cluster">
          <span className={`ws-pill ${wsClass}`}>{wsLabel}</span>
          <div className="agent-dots">
            {AGENT_META.map((a) => {
              const h = agentHealth[a.fullKey.toLowerCase()] as AgentHealth | undefined;
              return (
                <div key={a.key} className="agent-dot-item" title={`${a.label}: ${h?.status ?? "unknown"}`}>
                  <div className="agent-dot" style={{ background: h ? dotColor(h.status) : "#64748b" }} />
                  <span className="agent-dot-label" style={{ color: a.color }}>{a.key}</span>
                </div>
              );
            })}
          </div>
          {llmCount > 0 && <span className="stat-mini"><span>{llmCount}</span> LLM</span>}
          {snapshot && (
            <span className="stat-mini">$<span>{snapshot.live_metrics.cost_estimate.total_usd.toFixed(3)}</span></span>
          )}
          {snapshot?.meta?.rag_backend && (
            <span className="stat-mini rag-badge" title="LlamaIndex RAG backend">
              RAG:<span>{String(snapshot.meta.rag_backend).replace("llamaindex_", "LI/")}</span>
            </span>
          )}
        </div>
      </div>
    </header>
  );
}

// ── Ops Column (IC Approvals + Patients + Pre-Notifications) ──
interface OpsColumnProps {
  snapshot: IncidentSnapshot;
  approvingId: string | null;
  onApprove: (id: string) => void;
  selectedPatientId: string | null;
  onSelectPatient: (id: string) => void;
}

function OpsColumn({ snapshot, approvingId, onApprove, selectedPatientId, onSelectPatient }: OpsColumnProps) {
  const patients = Object.values(snapshot.patients).sort((a, b) => {
    const td = (triageRank[b.triage_category ?? "GREEN"] ?? 0) - (triageRank[a.triage_category ?? "GREEN"] ?? 0);
    return td || a.reported_minute - b.reported_minute;
  });

  const pendingDispatches = snapshot.dispatches.filter((d) => snapshot.pending_approvals.includes(d.dispatch_id));
  const preNotifications = [...(snapshot.pre_notifications ?? [])].reverse();

  return (
    <section className="ops-col">
      {/* IC Approvals */}
      <div className="ops-section">
        <div className="section-header">
          <span className="section-title">IC Approval Required</span>
          {pendingDispatches.length > 0 && (
            <span className="count-badge count-badge--red blink">{pendingDispatches.length}</span>
          )}
        </div>
        <div className="approval-area">
          {pendingDispatches.length === 0 ? (
            <div className="empty-state">
              <div className="empty-check">✓</div>
              <div className="empty-title">All dispatches approved</div>
              <div className="empty-sub">No pending IC decisions</div>
            </div>
          ) : (
            pendingDispatches.map((dispatch) => {
              const hospital = snapshot.hospitals[dispatch.destination_hospital];
              return (
                <div key={dispatch.dispatch_id} className="approval-card">
                  <div className="approval-top">
                    <span className="patient-id-badge">{dispatch.patient_id}</span>
                    <span className="triage-label triage-label--red">RED</span>
                    <span className="amb-badge">{dispatch.ambulance_id}</span>
                  </div>
                  <div className="approval-route">
                    <span className="route-from">Scene</span>
                    <div className="route-line"><div className="route-dot" /></div>
                    <span className="route-to">{hospital?.name ?? dispatch.destination_hospital}</span>
                    <span className="route-eta">ETA {dispatch.eta_minutes}m</span>
                  </div>
                  <p className="reasoning-text">AI: "{dispatch.reasoning.slice(0, 140)}{dispatch.reasoning.length > 140 ? "…" : ""}"</p>
                  <div className="conf-row">
                    <div className="conf-track">
                      <div className="conf-fill" style={{ width: `${Math.round(dispatch.confidence * 100)}%` }} />
                    </div>
                    <span>{Math.round(dispatch.confidence * 100)}% conf</span>
                  </div>
                  <button
                    className="approve-btn"
                    onClick={() => onApprove(dispatch.dispatch_id)}
                    disabled={approvingId === dispatch.dispatch_id}
                  >
                    {approvingId === dispatch.dispatch_id ? "Approving…" : `APPROVE DISPATCH — ${dispatch.patient_id}`}
                  </button>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* Active Patients */}
      <div className="ops-section ops-section-scroll">
        <div className="section-header">
          <span className="section-title">Active Patients</span>
          <span className="count-badge count-badge--dim">{patients.length}</span>
        </div>
        <PatientTable
          patients={patients}
          snapshot={snapshot}
          selectedPatientId={selectedPatientId}
          onSelectPatient={onSelectPatient}
        />
      </div>

      {/* Pre-Hospital Notifications */}
      <div className="ops-section">
        <div className="section-header">
          <span className="section-title">Pre-Hospital Notifications</span>
          <span className="count-badge count-badge--dim">{preNotifications.length}</span>
        </div>
        {preNotifications.length === 0 ? (
          <div className="empty-state">
            <div className="empty-sub">No notifications yet</div>
          </div>
        ) : (
          <div className="prenotif-area">
            {preNotifications.map((n) => (
              <PreNotifCard key={n.notification_id} notif={n} patient={snapshot.patients[n.patient_id]} />
            ))}
          </div>
        )}
      </div>
    </section>
  );
}

// ── Command Column (SITREP / METRICS / AGENTS / EXPORTS) ────
function CommandColumn({ snapshot, compareBaseline, onToggleBaseline }: {
  snapshot: IncidentSnapshot;
  compareBaseline: boolean;
  onToggleBaseline: () => void;
}) {
  const [tab, setTab] = useState<"sitrep" | "metrics" | "agents" | "exports">("sitrep");
  const live = snapshot.live_metrics;
  const latestSitrep = snapshot.sitreps[snapshot.sitreps.length - 1];
  const baselineMetrics = snapshot.baseline.current ?? snapshot.baseline.final_metrics;

  const alertToneClass = (sev: string) =>
    sev === "critical" || sev === "CRITICAL" ? "alert-pill--crit"
    : sev === "warning" || sev === "WARNING" ? "alert-pill--warn"
    : "alert-pill--ok";

  return (
    <section className="cmd-col">
      <div className="cmd-tab-bar">
        {(["sitrep", "metrics", "agents", "exports"] as const).map((t) => (
          <button key={t} className={`cmd-tab${tab === t ? " cmd-tab--active" : ""}`} onClick={() => setTab(t)}>
            {t.toUpperCase()}
          </button>
        ))}
      </div>

      <div className="cmd-content">
        {/* SITREP */}
        {tab === "sitrep" && (
          <>
            {latestSitrep ? (
              <div className="sitrep-card">
                <div className="sitrep-header">
                  <span className="sitrep-id">{latestSitrep.sitrep_id}</span>
                  <span className={`phase-badge ${latestSitrep.incident_phase === "ACTIVE" ? "phase-badge--active" : latestSitrep.incident_phase === "STABILIZING" ? "phase-badge--stab" : "phase-badge--recovery"}`}>
                    {latestSitrep.incident_phase}
                  </span>
                </div>
                <p className="sitrep-summary">{latestSitrep.summary}</p>
                {latestSitrep.alerts.length > 0 && (
                  <div className="alert-pills">
                    {latestSitrep.alerts.map((a, i) => (
                      <span key={i} className={`alert-pill ${alertToneClass(a.severity)}`}>{a.type}</span>
                    ))}
                  </div>
                )}
                {latestSitrep.recommendations.length > 0 && (
                  <ul className="rec-list">
                    {latestSitrep.recommendations.map((r, i) => <li key={i}>{r}</li>)}
                  </ul>
                )}
              </div>
            ) : (
              <div className="empty-state" style={{ paddingTop: 32 }}>
                <div className="empty-sub">No SITREP generated yet</div>
              </div>
            )}

            {baselineMetrics && (
              <div className="info-card">
                <div className="info-card-title" style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                  Baseline Comparison
                  <button
                    className={`ctrl-btn ctrl-btn--xs ${compareBaseline ? "ctrl-btn--active" : ""}`}
                    style={{ marginLeft: "auto" }}
                    onClick={onToggleBaseline}
                  >
                    {compareBaseline ? "ON" : "OFF"}
                  </button>
                </div>
                <div className="info-row">
                  <span>Active accuracy</span>
                  <strong>{Math.round(live.active_accuracy * 100)}% {compareBaseline && baselineMetrics.triage_accuracy ? `(+${Math.round((live.active_accuracy - baselineMetrics.triage_accuracy) * 100)}pp)` : ""}</strong>
                </div>
                <div className="info-row">
                  <span>Transport match</span>
                  <strong>{live.agreement.active_vs_ground_truth.toFixed(3)} {compareBaseline && baselineMetrics.transport_match_score ? `vs ${baselineMetrics.transport_match_score.toFixed(3)}` : ""}</strong>
                </div>
                <div className="info-row">
                  <span>Load Gini</span>
                  <strong>{live.tradeoffs.accuracy_delta.toFixed(3)}</strong>
                </div>
              </div>
            )}
          </>
        )}

        {/* METRICS */}
        {tab === "metrics" && (
          <>
            <div className="metrics-grid">
              {[
                { label: "Active Accuracy", value: `${Math.round(live.active_accuracy * 100)}%`, delta: compareBaseline && baselineMetrics?.triage_accuracy ? `+${Math.round((live.active_accuracy - baselineMetrics.triage_accuracy) * 100)}pp` : undefined, up: true },
                { label: "Shadow Accuracy", value: `${Math.round(live.shadow_accuracy * 100)}%`, delta: undefined, up: undefined },
                { label: "Agreement Rate",  value: `${Math.round(live.agreement.active_vs_shadow * 100)}%`, delta: undefined, up: undefined },
                { label: "Lead Time",       value: `${live.pre_notification_lead_time.avg_minutes.toFixed(1)}m`, delta: undefined, up: undefined },
                { label: "Load Balance",    value: live.tradeoffs.latency_delta_ms > 0 ? `+${Math.round(live.tradeoffs.latency_delta_ms)}ms` : "0ms", delta: undefined, up: undefined },
                { label: "LLM Cost",        value: `$${live.cost_estimate.total_usd.toFixed(4)}`, delta: undefined, up: undefined },
              ].map((m) => (
                <div key={m.label} className="metric-card">
                  <div className="metric-label">{m.label}</div>
                  <div className="metric-value">{m.value}</div>
                  {m.delta && <div className={`metric-delta metric-delta--${m.up ? "up" : "dn"}`}>{m.delta}</div>}
                </div>
              ))}
            </div>

            <div className={`info-card${live.circuit_breaker.circuit_open ? " info-card--open" : ""}`}>
              <div className="info-card-title">Circuit Breaker</div>
              <div className="info-row"><span>Model</span><strong>{live.circuit_breaker.model ?? "Unavailable"}</strong></div>
              <div className="info-row">
                <span>Status</span>
                <strong style={{ color: live.circuit_breaker.circuit_open ? "#ef4444" : live.circuit_breaker.available ? "#10b981" : "#f59e0b" }}>
                  {live.circuit_breaker.circuit_open ? "OPEN" : live.circuit_breaker.available ? "READY" : "OFFLINE"}
                </strong>
              </div>
              <div className="info-row"><span>Failures / Threshold</span><strong>{live.circuit_breaker.fail_count} / 3</strong></div>
              <div className="info-row"><span>Retry after</span><strong>{live.circuit_breaker.retry_after_seconds.toFixed(1)}s</strong></div>
            </div>

            <div className="info-card">
              <div className="info-card-title">System Tradeoffs</div>
              <div className="info-row"><span>Mode</span><strong>{snapshot.mode.toUpperCase()}</strong></div>
              <div className="info-row"><span>Accuracy delta</span><strong>{live.tradeoffs.accuracy_delta >= 0 ? "+" : ""}{Math.round(live.tradeoffs.accuracy_delta * 100)}%</strong></div>
              <div className="info-row"><span>Latency delta</span><strong>+{Math.round(live.tradeoffs.latency_delta_ms)}ms</strong></div>
              <div className="info-row"><span>Emails sent</span><strong>{live.emails_sent}</strong></div>
              {live.tradeoffs.summary && (
                <p style={{ marginTop: 8, fontSize: "0.72rem", color: "var(--text-3)", lineHeight: 1.4 }}>{live.tradeoffs.summary}</p>
              )}
            </div>
          </>
        )}

        {/* AGENTS */}
        {tab === "agents" && (
          <>
            {AGENT_META.map((meta) => {
              const h = snapshot.agent_health[meta.fullKey.toLowerCase()] as AgentHealth | undefined;
              const statusClass = !h ? "agent-status-badge--ok" : h.status === "NOMINAL" ? "agent-status-badge--ok" : h.status === "DEGRADED" ? "agent-status-badge--deg" : "agent-status-badge--fail";
              const status = h?.status ?? "UNKNOWN";
              return (
                <div key={meta.key} className="agent-health-card">
                  <div className="agent-hc-top">
                    <div className="agent-color-dot" style={{ background: meta.color }} />
                    <span className="agent-hc-name">{meta.label}</span>
                    <span className={`agent-status-badge ${statusClass}`}>{status}</span>
                    {h?.llm_mode && <span className="llm-badge">LLM</span>}
                  </div>
                  {h?.latency && (
                    <div className="agent-hc-stats">
                      <span>Last: {Math.round(h.latency.last_ms ?? 0)}ms</span>
                      <span>Avg: {Math.round(h.latency.avg_ms ?? 0)}ms</span>
                      <span>Calls: {h.latency.call_count ?? 0}</span>
                    </div>
                  )}
                  {h?.last_thought && (
                    <div className="agent-thought">"{h.last_thought}"</div>
                  )}
                </div>
              );
            })}

            {/* LlamaIndex integration card */}
            <div className="info-card" style={{ borderColor: "rgba(139,92,246,0.35)" }}>
              <div className="info-card-title" style={{ color: "#8b5cf6" }}>LlamaIndex Integration</div>
              <div className="info-row">
                <span>RAG Backend</span>
                <strong style={{ color: "#a78bfa" }}>{String(snapshot.meta?.rag_backend ?? "local_keyword")}</strong>
              </div>
              <div className="info-row">
                <span>Memory Backend</span>
                <strong style={{ color: "#a78bfa" }}>{String(snapshot.meta?.memory_backend ?? "local_keyword")}</strong>
              </div>
              <div className="info-row">
                <span>Memory Queries</span>
                <strong>{live.memory_retrievals ?? 0}</strong>
              </div>
              <div className="info-row">
                <span>LlamaIndex Hits</span>
                <strong style={{ color: live.memory_llamaindex_hits > 0 ? "#10b981" : "var(--text-3)" }}>
                  {live.memory_llamaindex_hits ?? 0} / {live.memory_retrievals ?? 0}
                </strong>
              </div>
              <div className="info-row">
                <span>RAG Queries (Triage)</span>
                <strong>{live.rag_queries ?? 0}</strong>
              </div>
            </div>
          </>
        )}

        {/* EXPORTS */}
        {tab === "exports" && (
          <>
            <div className="exports-section">
              <div className="export-title">Audit Trail</div>
              <div className="export-btn-stack">
                <a className="export-btn export-btn--accent" href={`${API_BASE}/api/incidents/${snapshot.incident_id}/audit.json`} target="_blank" rel="noreferrer">↓ Audit Log (JSON)</a>
                <a className="export-btn export-btn--accent" href={`${API_BASE}/api/incidents/${snapshot.incident_id}/audit.csv`} target="_blank" rel="noreferrer">↓ Audit Log (CSV)</a>
                <a
                  className={`export-btn${snapshot.incident_phase !== "RECOVERY" ? " export-btn--disabled" : " export-btn--accent"}`}
                  href={snapshot.incident_phase === "RECOVERY" ? `${API_BASE}/api/incidents/${snapshot.incident_id}/report` : undefined}
                  target="_blank" rel="noreferrer"
                  title={snapshot.incident_phase !== "RECOVERY" ? "Available after RECOVERY phase" : undefined}
                >
                  ↓ Incident Report (PDF){snapshot.incident_phase !== "RECOVERY" ? " — after RECOVERY" : ""}
                </a>
              </div>
            </div>

            <div className="exports-section">
              <div className="export-title">Evaluation</div>
              <div className="export-btn-stack">
                <a className="export-btn export-btn--accent" href={`${API_BASE}/api/incidents/${snapshot.incident_id}/eval`} target="_blank" rel="noreferrer">
                  ↓ Threshold Report (JSON)
                </a>
              </div>
              <div style={{ marginTop: 8 }}>
                {(["RED", "YELLOW", "GREEN", "BLACK"] as const).map((cat) => {
                  const acc = snapshot.metrics.accuracy_by_category?.[cat];
                  const color = acc == null ? "#64748b" : acc >= 0.95 ? "#10b981" : acc >= 0.80 ? "#f59e0b" : "#ef4444";
                  return acc != null ? (
                    <div key={cat} className="info-row">
                      <span>{cat} accuracy</span>
                      <strong style={{ color }}>{Math.round(acc * 100)}%</strong>
                    </div>
                  ) : null;
                })}
              </div>
            </div>

            {snapshot.guardrails?.length > 0 && (
              <div className="exports-section">
                <div className="export-title">Guardrails</div>
                {(() => {
                  const GUARDRAIL_EVENT_MAP: Record<string, string> = {
                    "red-human-approval": "guardrail_red_approval",
                    "black-no-dispatch": "guardrail_black_hold",
                    "stale-hospital-intel": "guardrail_stale_hospital",
                    "low-confidence-escalation": "guardrail_low_confidence",
                  };
                  const fireCounts: Record<string, number> = {};
                  for (const entry of (snapshot.audit_log ?? [])) {
                    if (entry.event_type.startsWith("guardrail_")) {
                      fireCounts[entry.event_type] = (fireCounts[entry.event_type] ?? 0) + 1;
                    }
                  }
                  return snapshot.guardrails.map((g) => {
                    const evtKey = GUARDRAIL_EVENT_MAP[g.rule_id];
                    const count = evtKey ? (fireCounts[evtKey] ?? 0) : 0;
                    return (
                      <div key={g.rule_id} className="guardrail-item">
                        <div className="gr-dot" style={{ background: count > 0 ? "#10b981" : "#475569" }} />
                        <div style={{ flex: 1 }}>
                          <div className="gr-title" style={{ display: "flex", justifyContent: "space-between" }}>
                            <span>{g.title}</span>
                            {count > 0 && <span style={{ fontSize: "0.65rem", color: "#10b981", fontFamily: "var(--font-mono)", fontWeight: 700 }}>{count}×</span>}
                          </div>
                          <div className="gr-desc">{g.description}</div>
                        </div>
                      </div>
                    );
                  });
                })()}
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

// ── Splash Screen ────────────────────────────────────────────
function Splash({ scenarios, selectedScenario, onSelect, onLaunch }: {
  scenarios: ScenarioSummary[];
  selectedScenario: string;
  onSelect: (s: string) => void;
  onLaunch: () => void;
}) {
  const [backendOk, setBackendOk] = useState<boolean | null>(null);
  useEffect(() => {
    fetch(`${API_BASE}/health`).then((r) => setBackendOk(r.ok)).catch(() => setBackendOk(false));
  }, []);

  const features = [
    { title: "Live Triage AI", desc: "Protocol-grounded patient classification with citation-backed confidence scores." },
    { title: "Ambulance Routing", desc: "Dynamic dispatch scoring with resource reservation and queued assignments." },
    { title: "Pre-Hospital Alerts", desc: "Automated PDF + email notifications to trauma centers before patient arrival." },
    { title: "Human-in-the-Loop", desc: "RED dispatches require IC approval. Guardrails enforced at every decision point." },
  ];
  return (
    <div className="splash">
      <div className="splash-grid-bg" />
      <div className="splash-content">
        <div className="splash-wordmark">FIELDOPS</div>
        <p className="splash-sub">AI-Powered Mass Casualty Incident Command</p>
        <div className="splash-features">
          {features.map((f) => (
            <div key={f.title} className="splash-feature">
              <div className="splash-feat-title">{f.title}</div>
              <p className="splash-feat-desc">{f.desc}</p>
            </div>
          ))}
        </div>
        <div className="splash-cta-row">
          <select className="splash-scenario-sel" value={selectedScenario} onChange={(e) => onSelect(e.target.value)}>
            {scenarios.map((s) => <option key={s.scenario_id} value={s.scenario_id}>{s.name}</option>)}
          </select>
          <button className="splash-launch-btn" onClick={onLaunch} disabled={scenarios.length === 0 || backendOk === false}>
            Launch Demo
          </button>
        </div>
        <div style={{ marginTop: 16, display: "flex", alignItems: "center", gap: 8, justifyContent: "center" }}>
          <div style={{ width: 8, height: 8, borderRadius: "50%", background: backendOk === null ? "#f59e0b" : backendOk ? "#10b981" : "#ef4444", boxShadow: backendOk ? "0 0 6px #10b981" : undefined }} />
          <span style={{ fontSize: "0.72rem", color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
            {backendOk === null ? "Checking backend…" : backendOk ? "Backend connected" : "Backend offline — start server first"}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Root App ─────────────────────────────────────────────────
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
  const [compareBaseline, setCompareBaseline] = useState(true);
  const [modeUpdating, setModeUpdating] = useState(false);
  const [approvingId, setApprovingId] = useState<string | null>(null);
  const [cmdTab, setCmdTab] = useState<"sitrep" | "metrics" | "agents" | "exports">("sitrep");
  const [guardrailToast, setGuardrailToast] = useState<string | null>(null);
  const lastAuditCountRef = useRef(0);

  const wsRef = useRef<WebSocket | null>(null);
  const snapshotRef = useRef<IncidentSnapshot | null>(null);

  useEffect(() => { snapshotRef.current = snapshot; }, [snapshot]);

  useEffect(() => {
    if (!snapshot) return;
    const auditLog = snapshot.audit_log ?? [];
    if (auditLog.length > lastAuditCountRef.current) {
      const newEntries = auditLog.slice(lastAuditCountRef.current);
      const guardrailEntry = [...newEntries].reverse().find((e: { event_type: string }) => e.event_type.startsWith("guardrail_"));
      if (guardrailEntry) {
        setGuardrailToast(guardrailEntry.message);
        const id = window.setTimeout(() => setGuardrailToast(null), 3500);
        return () => window.clearTimeout(id);
      }
    }
    lastAuditCountRef.current = auditLog.length;
  }, [snapshot?.audit_log?.length]);

  useEffect(() => {
    getScenarios().then(setScenarios).catch(() => setError("Could not load scenarios."));
  }, []);

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

  useEffect(() => {
    if (!snapshot?.incident_id || socketState === "live") return;
    const id = window.setInterval(async () => {
      try { setSnapshot(await getIncident(snapshot.incident_id)); }
      catch { setSocketState("degraded"); }
    }, 1200);
    return () => window.clearInterval(id);
  }, [snapshot?.incident_id, socketState]);

  const pendingDispatches = snapshot
    ? snapshot.dispatches.filter((d) => snapshot.pending_approvals.includes(d.dispatch_id))
    : [];

  async function handleStart() {
    try {
      setError(null);
      const incident = await startScenario(selectedScenario);
      setSnapshot(incident);
      setIsPlaying(false);
      setSelectedHospitalId(null);
      setSelectedPatientId(null);
      setCmdTab("sitrep");
      setTimeout(async () => {
        try {
          const updated = await controlScenario(incident.scenario_id, incident.incident_id, "play", speed);
          setSnapshot(updated);
          setIsPlaying(true);
        } catch { /* ignore autoplay errors */ }
      }, 500);
    } catch {
      setError("Could not start scenario.");
    }
  }

  async function handleControl(action: string, steps?: number) {
    if (!snapshot) return;
    try {
      setError(null);
      if (action === "play") setIsPlaying(true);
      if (action === "pause") setIsPlaying(false);
      const updated = await controlScenario(snapshot.scenario_id, snapshot.incident_id, action, speed, steps);
      setSnapshot(updated);
    } catch {
      setError(`Control action '${action}' failed.`);
    }
  }

  async function handleModeChange(mode: string) {
    if (!snapshot || snapshot.mode === mode || modeUpdating) return;
    try {
      setModeUpdating(true);
      const updated = await setIncidentMode(snapshot.incident_id, mode);
      setSnapshot(updated);
    } catch {
      setError("Mode switch failed.");
    } finally {
      setModeUpdating(false);
    }
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
      setError(`Approval failed: ${e instanceof Error ? e.message : String(e)}`);
    } finally {
      setApprovingId(null);
    }
  }

  async function handleInject(kind: "diversion" | "ambulance" | "stale") {
    if (!snapshot) return;
    const events = {
      diversion: { minute: snapshot.current_minute, type: "HOSPITAL_STATUS_CHANGED", hospital_id: "H-003", status: "DIVERT", divert_status: true, reason: "ED at capacity" },
      ambulance: { minute: snapshot.current_minute, type: "AMBULANCE_STATUS_CHANGED", ambulance_id: "A-009", status: "OUT_OF_SERVICE", reason: "Mechanical failure" },
      stale: { minute: snapshot.current_minute, type: "HOSPITAL_STALE", hospital_id: "H-001" },
    };
    try {
      setError(null);
      setSnapshot(await injectEvent(snapshot.incident_id, events[kind]));
    } catch {
      setError("Event injection failed.");
    }
  }

  return (
    <div className="app-shell">
      <CommandBar
        snapshot={snapshot}
        scenarios={scenarios}
        selectedScenario={selectedScenario}
        onSelectScenario={setSelectedScenario}
        speed={speed}
        onSpeed={setSpeed}
        isPlaying={isPlaying}
        socketState={socketState}
        modeUpdating={modeUpdating}
        pendingCount={pendingDispatches.length}
        onStart={handleStart}
        onControl={handleControl}
        onModeChange={handleModeChange}
        onInject={handleInject}
        onBellClick={() => {}}
      />

      {error && (
        <div className="error-strip">
          <span>{error}</span>
          <button onClick={() => setError(null)}>✕</button>
        </div>
      )}
      {snapshot?.degraded_mode && (
        <div className="error-strip degraded-strip">
          <span>{snapshot.degraded_reason}</span>
        </div>
      )}
      {guardrailToast && (
        <div className="guardrail-toast">
          <span className="guardrail-toast-icon">🛡</span>
          <span>GUARDRAIL: {guardrailToast}</span>
        </div>
      )}

      {!snapshot ? (
        <Splash
          scenarios={scenarios}
          selectedScenario={selectedScenario}
          onSelect={setSelectedScenario}
          onLaunch={handleStart}
        />
      ) : (
        <div className="app-body">
          <div className="main-surface">
            {/* MAP COLUMN */}
            <section className="map-col">
              <div className="map-container">
                <PittsburghMap
                  snapshot={snapshot}
                  onHospitalClick={(id) => setSelectedHospitalId(id)}
                  selectedHospitalId={selectedHospitalId}
                />
                {/* Triage summary overlay */}
                <div className="map-overlay-top">
                  {(["RED", "YELLOW", "GREEN", "BLACK"] as const).map((cat) => {
                    const count = Object.values(snapshot.patients).filter((p) => p.triage_category === cat).length;
                    return (
                      <div key={cat} className={`triage-chip triage-chip--${cat.toLowerCase()}`}>
                        <div className="chip-dot" style={{ background: cat === "RED" ? "#ef4444" : cat === "YELLOW" ? "#f59e0b" : cat === "GREEN" ? "#10b981" : "#64748b" }} />
                        {count} {cat}
                      </div>
                    );
                  })}
                </div>
                {/* Hospital detail overlay */}
                {selectedHospitalId && snapshot.hospitals[selectedHospitalId] && (() => {
                  const h = snapshot.hospitals[selectedHospitalId];
                  const loadPct = Math.round(h.current_load_pct * 100);
                  const loadColor = loadPct > 85 ? "#ef4444" : loadPct > 60 ? "#f59e0b" : "#10b981";
                  const toneClass = loadPct > 85 ? "critical" : loadPct > 60 ? "warning" : "ok";
                  const alerts = (snapshot.pre_notifications ?? []).filter((n) => n.hospital_id === h.hospital_id);
                  return (
                    <div className="hosp-detail-strip">
                      <div className="hosp-detail-top">
                        <span className="hosp-detail-name">{h.name}</span>
                        <span className={`hosp-status-badge ${h.divert_status ? "critical" : toneClass}`}>
                          {h.divert_status ? "DIVERT" : h.status}
                        </span>
                        <span className="hosp-level">Level {h.trauma_level} Trauma</span>
                        <button className="hosp-close" onClick={() => setSelectedHospitalId(null)}>✕</button>
                      </div>
                      <div className="hosp-detail-stats">
                        <div className="hosp-stat">
                          <span className="hosp-stat-label">Beds</span>
                          <strong>{h.capacity.available_beds}/{h.capacity.total_beds}</strong>
                        </div>
                        <div className="hosp-stat">
                          <span className="hosp-stat-label">ICU</span>
                          <strong>{h.capacity.icu_available}</strong>
                        </div>
                        <div className="hosp-stat">
                          <span className="hosp-stat-label">ETA</span>
                          <strong>{h.eta_from_scene_minutes}m</strong>
                        </div>
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
                          {alerts.map((a) => (
                            <span key={a.notification_id} className="hosp-incoming-badge">
                              {a.ambulance_id} ETA {a.eta_minutes}m — {a.triage_category}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </section>

            {/* OPS COLUMN */}
            <OpsColumn
              snapshot={snapshot}
              approvingId={approvingId}
              onApprove={handleApprove}
              selectedPatientId={selectedPatientId}
              onSelectPatient={setSelectedPatientId}
            />

            {/* COMMAND COLUMN */}
            <CommandColumn
              snapshot={snapshot}
              compareBaseline={compareBaseline}
              onToggleBaseline={() => setCompareBaseline((v) => !v)}
            />
          </div>

          {/* INTEL STRIP */}
          <AgentFeed snapshot={snapshot} />
        </div>
      )}
    </div>
  );
}
