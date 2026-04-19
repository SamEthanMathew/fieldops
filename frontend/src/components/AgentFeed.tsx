import type { IncidentSnapshot, AgentMessage, DecisionLogEntry } from "../types";

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

const AGENT_LABELS: Record<string, string> = {
  TRIAGE: "Triage",
  HOSPITAL_INTEL: "Hospital Intel",
  LOGISTICS: "Logistics",
  OVERWATCH: "Overwatch",
  PRE_NOTIFICATION: "Pre-Notify",
  ORCHESTRATOR: "Orchestrator",
  OPERATOR: "Operator",
  SIMULATION: "Simulation",
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
        <span className="feed-agent-tag" style={{ color, borderColor: color + "44", background: color + "11" }}>
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
        <span style={{ color: "#475569", fontSize: "0.75rem" }}>→</span>
        <span style={{ color: toColor, fontSize: "0.75rem" }}>
          {AGENT_LABELS[msg.to_agent] ?? msg.to_agent}
        </span>
        <span style={{
          marginLeft: "auto", padding: "1px 6px", borderRadius: 4,
          background: typeColor + "22", color: typeColor,
          fontSize: "0.65rem", fontWeight: 700,
        }}>{msg.message_type}</span>
        <span className="feed-time">T+{String(msg.minute).padStart(2, "0")}</span>
      </div>
      <p className="feed-message">{msg.message}</p>
    </div>
  );
}

interface AgentHealthBarProps {
  snapshot: IncidentSnapshot;
}

function AgentHealthBar({ snapshot }: AgentHealthBarProps) {
  return (
    <div className="agent-health-bar">
      {Object.entries(snapshot.agent_health).map(([name, health]) => {
        const color = AGENT_COLORS[name.toUpperCase()] ?? "#6b7280";
        const dotColor =
          health.status === "NOMINAL" ? "#10b981" :
          health.status === "DEGRADED" ? "#f59e0b" :
          health.status === "FAILED" ? "#ef4444" :
          "#64748b";
        return (
          <div key={name} className="agent-health-item" title={`${AGENT_LABELS[name.toUpperCase()] ?? name}: ${health.status}${health.last_thought ? ` — ${health.last_thought}` : ""}`}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: dotColor, flexShrink: 0 }} />
            <span style={{ color, fontSize: "0.65rem", fontWeight: 600 }}>
              {name.slice(0, 3).toUpperCase()}
            </span>
            {health.llm_mode && (
              <span style={{
                fontSize: "0.55rem", padding: "0px 3px", borderRadius: 3,
                background: "rgba(16,185,129,0.15)", color: "#10b981",
                border: "1px solid rgba(16,185,129,0.3)",
              }}>LLM</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

interface AgentFeedProps {
  snapshot: IncidentSnapshot;
  activeTab: "log" | "comms" | "network";
  onTabChange: (tab: "log" | "comms" | "network") => void;
}

export function AgentFeed({ snapshot, activeTab, onTabChange }: AgentFeedProps) {
  const logs = snapshot.decision_log.slice().reverse();
  const comms = snapshot.agent_messages.slice().reverse();

  return (
    <div className="agent-feed-panel">
      <div className="feed-tab-bar">
        {(["log", "comms", "network"] as const).map((tab) => (
          <button
            key={tab}
            className={`feed-tab ${activeTab === tab ? "feed-tab--active" : ""}`}
            onClick={() => onTabChange(tab)}
          >
            {tab === "log" ? "Decision Log" : tab === "comms" ? `Agent Comms ${comms.length > 0 ? `(${comms.length})` : ""}` : "Agent Health"}
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
            ? <p className="feed-empty">No agent-to-agent messages yet. Agents coordinate after first triage.</p>
            : comms.map((msg) => <CommEntry key={msg.message_id} msg={msg} />)
        )}

        {activeTab === "network" && (
          <div>
            <AgentHealthBar snapshot={snapshot} />
            <div style={{ marginTop: 12, display: "flex", flexDirection: "column", gap: 6 }}>
              {Object.entries(snapshot.agent_health).map(([name, health]) => {
                const color = AGENT_COLORS[name.toUpperCase()] ?? "#6b7280";
                const dotColor =
                  health.status === "NOMINAL" ? "#10b981" :
                  health.status === "DEGRADED" ? "#f59e0b" :
                  health.status === "FAILED" ? "#ef4444" :
                  "#64748b";
                return (
                  <div key={name} className="agent-health-row-v2">
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", background: dotColor }} />
                      <span style={{ fontSize: "0.8rem", color: "#cbd5e1" }}>{AGENT_LABELS[name.toUpperCase()] ?? name}</span>
                      {health.llm_mode && (
                        <span className="llm-pill">LLM</span>
                      )}
                    </div>
                    <span style={{ fontSize: "0.72rem", color: "#475569" }}>T+{health.last_updated_minute}</span>
                    {health.last_thought && (
                      <p style={{ margin: "2px 0 0", fontSize: "0.71rem", color: "#4b5563", fontStyle: "italic", gridColumn: "1/-1" }}>
                        "{health.last_thought.slice(0, 90)}{health.last_thought.length > 90 ? "…" : ""}"
                      </p>
                    )}
                  </div>
                );
              })}
            </div>

            <div className="tradeoff-box-v2">
              <div style={{ fontSize: "0.7rem", color: "#475569", textTransform: "uppercase", letterSpacing: "0.1em", marginBottom: 8 }}>System Architecture</div>
              {[
                ["LLM Mode", "+reasoning +nuance, +15-40ms/decision"],
                ["Rule-based", "<1ms/decision, deterministic"],
                ["RAG Engine", "LlamaIndex + Gemini embeddings"],
                ["Pre-notify", "Ambulance agent → hospital charge nurse"],
              ].map(([label, val]) => (
                <div key={label} className="tradeoff-row-v2">
                  <span style={{ fontSize: "0.75rem", fontWeight: 600, color: "#94a3b8" }}>{label}</span>
                  <span style={{ fontSize: "0.72rem", color: "#475569" }}>{val}</span>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
