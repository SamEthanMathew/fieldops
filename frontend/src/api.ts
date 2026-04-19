import type { IncidentSnapshot, ScenarioSummary } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw new Error(`API request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function getScenarios() {
  return apiRequest<ScenarioSummary[]>("/api/scenarios");
}

export function startScenario(scenarioId: string) {
  return apiRequest<IncidentSnapshot>(`/api/scenarios/${scenarioId}/start`, { method: "POST" });
}

export function getIncident(incidentId: string) {
  return apiRequest<IncidentSnapshot>(`/api/incidents/${incidentId}`);
}

export function controlScenario(scenarioId: string, incidentId: string, action: string, speed?: number, steps?: number) {
  return apiRequest<IncidentSnapshot>(`/api/scenarios/${scenarioId}/control`, {
    method: "POST",
    body: JSON.stringify({ incident_id: incidentId, action, speed, steps }),
  });
}

export function approveDispatch(dispatchId: string, incidentId: string) {
  return apiRequest<IncidentSnapshot>(`/api/dispatches/${dispatchId}/approve`, {
    method: "POST",
    body: JSON.stringify({ incident_id: incidentId }),
  });
}

export function injectEvent(incidentId: string, event: Record<string, unknown>) {
  return apiRequest<IncidentSnapshot>("/api/events/inject", {
    method: "POST",
    body: JSON.stringify({ incident_id: incidentId, event }),
  });
}

export function getIncidentWebSocketUrl(incidentId: string) {
  const base = API_BASE.replace("http://", "ws://").replace("https://", "wss://");
  return `${base}/ws/incidents/${incidentId}`;
}

export function sendNotificationEmail(payload: {
  notification_id: string;
  recipient_email: string;
  subject: string;
  body: string;
}) {
  return apiRequest<{ mode: string; message: string; notification_id: string }>("/api/notify/email", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
