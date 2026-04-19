import type { EmailDeliveryRecord, IncidentSnapshot, AgentMessage, DecisionLogEntry } from "../types";

const AGENT_COLORS: Record<string, string> = {
  TRIAGE: "#f59e0b",
  HOSPITAL_INTEL: "#3b82f6",
  LOGISTICS: "#8b5cf6",
  OVERWATCH: "#10b981",
  PRE_NOTIFICATION: "#ef4444",
  ORCHESTRATOR: "#ec4899",
  OPERATOR: "#6b7280",
  SIMULATION: "#6b7280",
  BLACKBOARD: "#38bdf8",
};

const AGENT_LABELS: Record<string, string> = {
  TRIAGE: "Triage",
  HOSPITAL_INTEL: "Hospital Intel",
  LOGISTICS: "Logistics",
  OVERWATCH: "Overwatch",
  PRE_NOTIFICATION: "Pre-Notify",
  ORCHESTRATOR: "Orchestrator",
  OPERATOR: "Operator",
  SIMULATION: "Simulation",
  BLACKBOARD: "Blackboard",
};

function LogEntry({ entry }: { entry: DecisionLogEntry }) {
  const color = AGENT_COLORS[entry.agent] ?? "#6b7280";
  const severityColor =
    entry.severity === "CRITICAL" ? "#ef4444" :
    entry.severity === "WARNING" ? "#f59e0b" :
    "#3b82f6";

  return (
    <div className="feed-entry" style={{ borderLeftColor: severityColor }}>
      <div className="feed-entry-header">
        <span className="feed-agent-tag" style={{ color, borderColor: `${color}44`, background: `${color}11` }}>
          {AGENT_LABELS[entry.agent] ?? entry.agent}
        </span>
        <span className="feed-severity" style={{ color: severityColor, fontSize: "0.65rem" }}>
          {entry.severity}
        </span>
        <span className="feed-time">T+{String(entry.minute).padStart(2, "0")}</span>
      </div>
      <p className="feed-message">{entry.message}</p>
    </div>
  );
}

function CommEntry({ msg }: { msg: AgentMessage }) {
  const fromColor = AGENT_COLORS[msg.from_agent] ?? "#6b7280";
  const toColor = AGENT_COLORS[msg.to_agent] ?? "#94a3b8";
  const typeColor =
    msg.message_type === "DIRECTIVE" ? "#ec4899" :
    msg.message_type === "ALERT" ? "#ef4444" :
    msg.message_type === "UPDATE" ? "#3b82f6" :
    "#64748b";

  return (
    <div className="comm-entry">
      <div className="comm-entry-header">
        <span style={{ color: fromColor, fontWeight: 700, fontSize: "0.75rem" }}>
          {AGENT_LABELS[msg.from_agent] ?? msg.from_agent}
        </span>
        <span style={{ color: "#475569", fontSize: "0.75rem" }}>{"->"}</span>
        <span style={{ color: toColor, fontSize: "0.75rem" }}>
          {AGENT_LABELS[msg.to_agent] ?? msg.to_agent}
        </span>
        <span style={{
          marginLeft: "auto", padding: "1px 6px", borderRadius: 4,
          background: `${typeColor}22`, color: typeColor,
          fontSize: "0.65rem", fontWeight: 700,
        }}>{msg.message_type}</span>
        <span className="feed-time">T+{String(msg.minute).padStart(2, "0")}</span>
      </div>
      <p className="feed-message">{msg.message}</p>
    </div>
  );
}

function EmailEntry({ email }: { email: EmailDeliveryRecord }) {
  const color = email.status === "sent" ? "#10b981" : email.status === "failed" ? "#ef4444" : "#f59e0b";
  return (
    <div className="comm-entry">
      <div className="comm-entry-header">
        <span style={{ color, fontWeight: 700, fontSize: "0.75rem" }}>EMAIL</span>
        <span style={{ color: "#94a3b8", fontSize: "0.75rem" }}>{email.hospital_name}</span>
        <span className="feed-time">T+{String(email.minute).padStart(2, "0")}</span>
      </div>
      <p className="feed-message">{email.subject}</p>
      <p className="feed-message" style={{ color }}>{email.status.replace("_", " ")}</p>
    </div>
  );
}

function AgentNetwork({ snapshot }: { snapshot: IncidentSnapshot }) {
  const positions: Record<string, { x: number; y: number }> = {
    TRIAGE: { x: 80, y: 42 },
    HOSPITAL_INTEL: { x: 80, y: 142 },
    LOGISTICS: { x: 210, y: 142 },
    OVERWATCH: { x: 340, y: 42 },
    ORCHESTRATOR: { x: 340, y: 142 },
    PRE_NOTIFICATION: { x: 210, y: 42 },
    BLACKBOARD: { x: 210, y: 92 },
  };
  const recentEdges = snapshot.agent_messages.slice(-10);

  return (
    <div className="network-wrap">
      <svg className="network-svg" viewBox="0 0 420 190" preserveAspectRatio="xMidYMid meet">
        {recentEdges.map((edge) => {
          const from = positions[edge.from_agent];
          const to = positions[edge.to_agent];
          if (!from || !to) return null;
          const color = AGENT_COLORS[edge.from_agent] ?? "#64748b";
          return (
            <g key={edge.message_id}>
              <line
                x1={from.x}
                y1={from.y}
                x2={to.x}
                y2={to.y}
                stroke={color}
                strokeWidth="2.5"
                strokeDasharray={edge.message_type === "DIRECTIVE" ? "6 5" : undefined}
                opacity="0.75"
              />
            </g>
          );
        })}
        {Object.entries(positions).map(([name, pos]) => {
          const health = snapshot.agent_health[name.toLowerCase()];
          const color = AGENT_COLORS[name] ?? "#64748b";
          const tone = health?.status === "FAILED" ? "#ef4444" : health?.status === "DEGRADED" ? "#f59e0b" : color;
          return (
            <g key={name}>
              <circle cx={pos.x} cy={pos.y} r="24" fill="#0f1e35" stroke={tone} strokeWidth="2.5" />
              <text x={pos.x} y={pos.y - 3} textAnchor="middle" fill="#e2e8f0" fontSize="9" fontWeight="700">
                {AGENT_LABELS[name] ?? name}
              </text>
              <text x={pos.x} y={pos.y + 11} textAnchor="middle" fill="#94a3b8" fontSize="8">
                {health?.latency?.last_ms ? `${Math.round(health.latency.last_ms)}ms` : "idle"}
              </text>
            </g>
          );
        })}
      </svg>
      <div className="tradeoff-box-v2">
        <div className="network-panel-title">System Tradeoffs</div>
        <div className="tradeoff-row-v2">
          <span>Accuracy delta</span>
          <strong>{snapshot.live_metrics.tradeoffs.accuracy_delta >= 0 ? "+" : ""}{Math.round(snapshot.live_metrics.tradeoffs.accuracy_delta * 100)}%</strong>
        </div>
        <div className="tradeoff-row-v2">
          <span>Latency delta</span>
          <strong>+{Math.round(snapshot.live_metrics.tradeoffs.latency_delta_ms)}ms</strong>
        </div>
        <div className="tradeoff-summary">{snapshot.live_metrics.tradeoffs.summary}</div>
      </div>
    </div>
  );
}

interface AgentFeedProps {
  snapshot: IncidentSnapshot;
  activeTab: "log" | "comms" | "network" | "email";
  onTabChange: (tab: "log" | "comms" | "network" | "email") => void;
}

export function AgentFeed({ snapshot, activeTab, onTabChange }: AgentFeedProps) {
  const logs = snapshot.decision_log.slice().reverse();
  const comms = snapshot.agent_messages.slice().reverse();
  const emails = snapshot.email_log.slice().reverse();

  return (
    <div className="agent-feed-panel">
      <div className="feed-tab-bar">
        {(["log", "comms", "network", "email"] as const).map((tab) => (
          <button
            key={tab}
            className={`feed-tab ${activeTab === tab ? "feed-tab--active" : ""}`}
            onClick={() => onTabChange(tab)}
          >
            {tab === "log" ? "Decision Log" : tab === "comms" ? `Agent Comms ${comms.length ? `(${comms.length})` : ""}` : tab === "network" ? "Network" : `Email Feed ${emails.length ? `(${emails.length})` : ""}`}
          </button>
        ))}
      </div>

      <div className="feed-scroll">
        {activeTab === "log" && (
          logs.length === 0
            ? <p className="feed-empty">No log entries yet.</p>
            : logs.map((entry, i) => <LogEntry key={`${entry.timestamp}-${i}`} entry={entry} />)
        )}

        {activeTab === "comms" && (
          comms.length === 0
            ? <p className="feed-empty">No agent-to-agent messages yet.</p>
            : comms.map((msg) => <CommEntry key={msg.message_id} msg={msg} />)
        )}

        {activeTab === "email" && (
          emails.length === 0
            ? <p className="feed-empty">No outbound email activity yet.</p>
            : emails.map((email) => <EmailEntry key={`${email.notification_id}-${email.minute}`} email={email} />)
        )}

        {activeTab === "network" && <AgentNetwork snapshot={snapshot} />}
      </div>
    </div>
  );
}
