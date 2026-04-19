import { useState } from "react";
import type { IncidentSnapshot, AgentHealth } from "../types";

const AGENT_COLORS: Record<string, string> = {
  TRIAGE: "#f59e0b", HOSPITAL_INTEL: "#3b82f6", LOGISTICS: "#8b5cf6",
  OVERWATCH: "#10b981", PRE_NOTIFICATION: "#ef4444", ORCHESTRATOR: "#ec4899",
  OPERATOR: "#6b7280", SIMULATION: "#6b7280", BLACKBOARD: "#38bdf8",
};

const AGENT_LABELS: Record<string, string> = {
  TRIAGE: "Triage", HOSPITAL_INTEL: "Hosp Intel", LOGISTICS: "Logistics",
  OVERWATCH: "Overwatch", PRE_NOTIFICATION: "Pre-Notify", ORCHESTRATOR: "Orchestrator",
  OPERATOR: "Operator", SIMULATION: "Simulation", BLACKBOARD: "Blackboard",
};

const MSG_TYPE_COLOR: Record<string, string> = {
  DIRECTIVE: "#ec4899", ALERT: "#ef4444", UPDATE: "#3b82f6", STATUS: "#94a3b8",
};

const SEV_CLASS: Record<string, string> = {
  CRITICAL: "log-entry--crit", WARNING: "log-entry--warn", INFO: "log-entry--info",
};

// ── Network Graph ───────────────────────────────────────────
function NetworkGraph({ snapshot }: { snapshot: IncidentSnapshot }) {
  const POS: Record<string, { x: number; y: number; label: string; color: string }> = {
    TRIAGE:        { x: 90,  y: 55,  label: "Triage",     color: "#f59e0b" },
    HOSPITAL_INTEL:{ x: 90,  y: 130, label: "Hosp Intel", color: "#3b82f6" },
    LOGISTICS:     { x: 220, y: 130, label: "Logistics",  color: "#8b5cf6" },
    OVERWATCH:     { x: 350, y: 55,  label: "Overwatch",  color: "#10b981" },
    ORCHESTRATOR:  { x: 350, y: 130, label: "Orchestr.",  color: "#ec4899" },
    PRE_NOTIFICATION: { x: 220, y: 55, label: "Pre-Notify", color: "#ef4444" },
    BLACKBOARD:    { x: 220, y: 92,  label: "Blackboard", color: "#06b6d4" },
  };

  const STATIC_EDGES = [
    ["TRIAGE", "BLACKBOARD"], ["HOSPITAL_INTEL", "BLACKBOARD"],
    ["LOGISTICS", "BLACKBOARD"], ["OVERWATCH", "BLACKBOARD"],
    ["ORCHESTRATOR", "BLACKBOARD"], ["PRE_NOTIFICATION", "BLACKBOARD"],
  ];

  const recentEdges = snapshot.agent_messages.slice(-8);

  return (
    <div className="network-svg-wrap">
      <svg className="network-svg" viewBox="0 0 460 185" preserveAspectRatio="xMidYMid meet"
        style={{ background: "linear-gradient(180deg,rgba(13,26,46,0.9),rgba(6,13,27,0.95))", display: "block" }}>
        {/* Static edges */}
        {STATIC_EDGES.map(([a, b], i) => {
          const p1 = POS[a], p2 = POS[b];
          if (!p1 || !p2) return null;
          return <line key={i} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y} stroke={p1.color} strokeWidth={1.5} opacity={0.25} />;
        })}
        {/* Recent message edges */}
        {recentEdges.map((edge) => {
          const p1 = POS[edge.from_agent], p2 = POS[edge.to_agent];
          if (!p1 || !p2) return null;
          const color = AGENT_COLORS[edge.from_agent] ?? "#64748b";
          return (
            <line key={edge.message_id} x1={p1.x} y1={p1.y} x2={p2.x} y2={p2.y}
              stroke={color} strokeWidth={2} opacity={0.8}
              strokeDasharray={edge.message_type === "DIRECTIVE" ? "5 4" : undefined}
            />
          );
        })}
        {/* Nodes */}
        {Object.entries(POS).map(([name, pos]) => {
          const health = snapshot.agent_health[name.toLowerCase()] as AgentHealth | undefined;
          const color = pos.color;
          const borderColor = health?.status === "FAILED" ? "#ef4444" : health?.status === "DEGRADED" ? "#f59e0b" : color;
          const latency = health?.latency?.last_ms ? `${Math.round(health.latency.last_ms)}ms` : "idle";
          return (
            <g key={name}>
              <circle cx={pos.x} cy={pos.y} r={22} fill="#0d1a2e" stroke={borderColor} strokeWidth={2} />
              <text x={pos.x} y={pos.y - 2} textAnchor="middle" fill="#e2e8f0" fontSize={8} fontFamily="Inter,sans-serif" fontWeight={700}>{pos.label}</text>
              <text x={pos.x} y={pos.y + 11} textAnchor="middle" fill="#4a6080" fontSize={7} fontFamily="JetBrains Mono,monospace">{latency}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ── Intel Strip (full-width bottom panel) ───────────────────
interface AgentFeedProps {
  snapshot: IncidentSnapshot;
}

export function AgentFeed({ snapshot }: AgentFeedProps) {
  const [tab, setTab] = useState<"log" | "comms" | "network" | "email">("log");

  const logs = [...snapshot.decision_log].reverse();
  const comms = [...snapshot.agent_messages].reverse();
  const emails = [...snapshot.email_log].reverse();

  return (
    <div className="intel-strip">
      <div className="intel-tab-bar">
        <button className={`intel-tab${tab === "log" ? " intel-tab--active" : ""}`} onClick={() => setTab("log")}>
          Decision Log {logs.length > 0 && <span className="intel-tab-badge">{logs.length}</span>}
        </button>
        <button className={`intel-tab${tab === "comms" ? " intel-tab--active" : ""}`} onClick={() => setTab("comms")}>
          Agent Comms {comms.length > 0 && <span className="intel-tab-badge">{comms.length}</span>}
        </button>
        <button className={`intel-tab${tab === "network" ? " intel-tab--active" : ""}`} onClick={() => setTab("network")}>
          Network
        </button>
        <button className={`intel-tab${tab === "email" ? " intel-tab--active" : ""}`} onClick={() => setTab("email")}>
          Email Feed {emails.length > 0 && <span className="intel-tab-badge">{emails.length}</span>}
        </button>
      </div>

      {/* Decision Log — horizontal scroll */}
      {tab === "log" && (
        <div className="intel-content">
          {logs.length === 0 ? (
            <div style={{ padding: "16px", fontSize: "0.75rem", color: "var(--text-3)" }}>No log entries yet.</div>
          ) : (
            logs.map((entry, i) => {
              const color = AGENT_COLORS[entry.agent] ?? "#6b7280";
              const sevColor = entry.severity === "CRITICAL" ? "#ef4444" : entry.severity === "WARNING" ? "#f59e0b" : "#3b82f6";
              return (
                <div key={`${entry.timestamp}-${i}`} className={`log-entry ${SEV_CLASS[entry.severity] ?? "log-entry--info"}`}>
                  <span className="log-agent-tag" style={{ color, borderColor: `${color}44`, background: `${color}15` }}>
                    {AGENT_LABELS[entry.agent] ?? entry.agent}
                  </span>
                  <span className="log-time">T+{String(entry.minute).padStart(2, "0")}</span>
                  <span className="log-msg">{entry.message}</span>
                  <span style={{ fontSize: "0.6rem", fontWeight: 700, color: sevColor, flexShrink: 0 }}>{entry.severity}</span>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Agent Comms — horizontal scroll */}
      {tab === "comms" && (
        <div className="intel-content">
          {comms.length === 0 ? (
            <div style={{ padding: "16px", fontSize: "0.75rem", color: "var(--text-3)" }}>No agent messages yet.</div>
          ) : (
            comms.map((msg) => {
              const fromColor = AGENT_COLORS[msg.from_agent] ?? "#6b7280";
              const toColor = AGENT_COLORS[msg.to_agent] ?? "#94a3b8";
              const typeColor = MSG_TYPE_COLOR[msg.message_type] ?? "#94a3b8";
              return (
                <div key={msg.message_id} className="comm-entry">
                  <div className="comm-head">
                    <span style={{ color: fromColor, fontWeight: 700, fontSize: "0.72rem", fontFamily: "var(--font-mono)" }}>
                      {AGENT_LABELS[msg.from_agent] ?? msg.from_agent}
                    </span>
                    <span className="comm-arrow">→</span>
                    <span style={{ color: toColor, fontSize: "0.72rem", fontFamily: "var(--font-mono)" }}>
                      {AGENT_LABELS[msg.to_agent] ?? msg.to_agent}
                    </span>
                    <span className="comm-type-badge" style={{ background: `${typeColor}22`, color: typeColor }}>
                      {msg.message_type}
                    </span>
                    <span className="log-time">T+{String(msg.minute).padStart(2, "0")}</span>
                  </div>
                  <p className="comm-msg">{msg.message}</p>
                </div>
              );
            })
          )}
        </div>
      )}

      {/* Network — fills full width */}
      {tab === "network" && (
        <div className="intel-content" style={{ padding: 0, overflow: "hidden" }}>
          <NetworkGraph snapshot={snapshot} />
        </div>
      )}

      {/* Email Feed — horizontal scroll */}
      {tab === "email" && (
        <div className="intel-content">
          {emails.length === 0 ? (
            <div style={{ padding: "16px", fontSize: "0.75rem", color: "var(--text-3)" }}>No email activity yet.</div>
          ) : (
            emails.map((email) => {
              const statusClass = email.status === "sent" ? "email-status-badge--sent" : email.status === "failed" ? "email-status-badge--fail" : "email-status-badge--pend";
              const statusLabel = email.status === "sent" ? "SENT ✓" : email.status === "failed" ? "FAILED" : "PENDING";
              const hosColor = email.status === "sent" ? "#10b981" : email.status === "failed" ? "#ef4444" : "#f59e0b";
              return (
                <div key={`${email.notification_id}-${email.minute}`} className="email-entry">
                  <div className="email-head">
                    <span style={{ color: hosColor, fontWeight: 700, fontSize: "0.72rem" }}>EMAIL</span>
                    <span style={{ color: "#94a3b8", fontSize: "0.75rem", fontWeight: 600 }}>{email.hospital_name}</span>
                    <span className="log-time">T+{String(email.minute).padStart(2, "0")}</span>
                    <span className={`email-status-badge ${statusClass}`}>{statusLabel}</span>
                  </div>
                  <p className="email-subject">{email.subject}</p>
                </div>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
