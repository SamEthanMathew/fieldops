export type ScenarioSummary = {
  scenario_id: string;
  name: string;
};

export type Coordinates = {
  lat: number;
  lng: number;
  description?: string | null;
};

export type Vitals = {
  gcs?: number | null;
  resp_rate?: number | null;
  radial_pulse?: boolean | null;
};

export type HistoryEntry = {
  minute: number;
  time: string;
  event: string;
  agent: string;
  detail: string;
};

export type PatientRecord = {
  patient_id: string;
  raw_report: string;
  latest_report: string;
  reported_minute: number;
  triage_category?: "RED" | "YELLOW" | "GREEN" | "BLACK" | null;
  confidence?: number | null;
  vitals: Vitals;
  injuries: string[];
  special_flags: string[];
  needs: string[];
  pediatric: boolean;
  review_required: boolean;
  data_quality_flags: string[];
  status: string;
  assigned_ambulance?: string | null;
  assigned_hospital?: string | null;
  ground_truth_triage?: string | null;
  special_notes: string[];
  shadow_triage_category?: "RED" | "YELLOW" | "GREEN" | "BLACK" | null;
  shadow_confidence?: number | null;
  shadow_reasoning?: string | null;
  memory_summary?: string | null;
  history: HistoryEntry[];
};

export type Capacity = {
  total_beds: number;
  available_beds: number;
  icu_available: number;
  or_available: number;
};

export type HospitalRecord = {
  hospital_id: string;
  name: string;
  email?: string | null;
  location: Coordinates;
  trauma_level: number;
  specialties: string[];
  capacity: Capacity;
  current_load_pct: number;
  status: string;
  divert_status: boolean;
  eta_from_scene_minutes: number;
  last_updated: string;
  stale: boolean;
  reason?: string | null;
};

export type AmbulanceRecord = {
  ambulance_id: string;
  type: string;
  status: string;
  position: Coordinates;
  current_patient?: string | null;
  eta_available?: number | null;
  history: HistoryEntry[];
};

export type AlternativeOption = {
  hospital_id: string;
  hospital_name: string;
  score: number;
  reason_rejected: string;
};

export type DispatchRecommendation = {
  dispatch_id: string;
  patient_id: string;
  ambulance_id: string;
  destination_hospital: string;
  priority: string;
  eta_minutes: number;
  reasoning: string;
  alternatives_considered: AlternativeOption[];
  confidence: number;
  requires_ic_approval: boolean;
  status: string;
  created_minute: number;
  approved_minute?: number | null;
};

export type Alert = {
  type: string;
  message: string;
  severity: string;
};

export type Sitrep = {
  sitrep_id: string;
  timestamp: string;
  minute: number;
  incident_phase: string;
  summary: string;
  alerts: Alert[];
  recommendations: string[];
  agent_health: Record<string, string>;
};

export type MetricSnapshot = {
  total_patients: number;
  by_category: Record<string, number>;
  transported: number;
  awaiting_dispatch: number;
  mean_dispatch_latency_sec: number;
  hospital_load_gini: number;
  triage_accuracy: number;
  transport_match_score: number;
  survival_proxy_score: number;
};

export type ArtifactRef = {
  label: string;
  kind: string;
  path: string;
  download_url?: string | null;
};

export type LatencyStats = {
  last_ms: number;
  avg_ms: number;
  p95_ms: number;
  call_count: number;
  success_count: number;
  fallback_count: number;
};

export type CostEstimate = {
  total_usd: number;
  by_agent: Record<string, number>;
};

export type AgreementRates = {
  active_vs_ground_truth: number;
  shadow_vs_ground_truth: number;
  active_vs_shadow: number;
  three_way_agreement: number;
};

export type LeadTimeStats = {
  last_minutes: number;
  avg_minutes: number;
  p95_minutes: number;
};

export type CircuitBreakerStatus = {
  available: boolean;
  circuit_open: boolean;
  fail_count: number;
  retry_after_seconds: number;
  model?: string | null;
};

export type TradeoffSummary = {
  compare_mode: string;
  accuracy_delta: number;
  latency_delta_ms: number;
  summary: string;
};

export type LiveMetrics = {
  current_mode: string;
  active_accuracy: number;
  shadow_accuracy: number;
  agreement: AgreementRates;
  per_agent_latency: Record<string, LatencyStats>;
  pre_notification_lead_time: LeadTimeStats;
  cost_estimate: CostEstimate;
  tradeoffs: TradeoffSummary;
  circuit_breaker: CircuitBreakerStatus;
  emails_sent: number;
  emails_total: number;
};

export type AuditLogEntry = {
  audit_id: string;
  minute: number;
  timestamp: string;
  event_type: string;
  agent: string;
  message: string;
  status: string;
  data: Record<string, unknown>;
};

export type GuardrailRule = {
  rule_id: string;
  title: string;
  description: string;
  active: boolean;
};

export type AgentHealth = {
  status: string;
  last_updated_minute: number;
  last_error?: string | null;
  llm_mode?: boolean;
  last_thought?: string | null;
  latency: LatencyStats;
  estimated_tokens: number;
  estimated_cost_usd: number;
};

export type AgentMessage = {
  message_id: string;
  from_agent: string;
  to_agent: string;
  message: string;
  minute: number;
  timestamp: string;
  message_type: string;
};

export type PreHospitalNotification = {
  notification_id: string;
  patient_id: string;
  ambulance_id: string;
  hospital_id: string;
  hospital_name: string;
  recipient_email?: string | null;
  alert_message: string;
  prep_needed: string[];
  eta_minutes: number;
  minute: number;
  timestamp: string;
  triage_category: string;
  lead_time_minutes: number;
  email_status: string;
  pdf_path?: string | null;
  eml_path?: string | null;
  pdf_artifact?: ArtifactRef | null;
  eml_artifact?: ArtifactRef | null;
};

export type EmailDeliveryRecord = {
  notification_id: string;
  hospital_id: string;
  hospital_name: string;
  recipient_email: string;
  subject: string;
  status: string;
  minute: number;
  timestamp: string;
  eml_path?: string | null;
  error?: string | null;
};

export type DecisionLogEntry = {
  minute: number;
  timestamp: string;
  agent: string;
  message: string;
  severity: string;
  related_ids: string[];
};

export type IncidentSnapshot = {
  incident_id: string;
  scenario_id: string;
  incident_type: string;
  incident_phase: string;
  mode: string;
  location: Coordinates;
  start_time: string;
  current_time: string;
  current_minute: number;
  patients: Record<string, PatientRecord>;
  hospitals: Record<string, HospitalRecord>;
  ambulances: Record<string, AmbulanceRecord>;
  dispatches: DispatchRecommendation[];
  sitreps: Sitrep[];
  metrics: MetricSnapshot;
  decision_log: DecisionLogEntry[];
  pending_approvals: string[];
  agent_health: Record<string, AgentHealth>;
  agent_messages: AgentMessage[];
  pre_notifications: PreHospitalNotification[];
  email_log: EmailDeliveryRecord[];
  audit_log: AuditLogEntry[];
  guardrails: GuardrailRule[];
  artifacts: ArtifactRef[];
  report_artifact?: ArtifactRef | null;
  live_metrics: LiveMetrics;
  degraded_mode: boolean;
  degraded_reason?: string | null;
  baseline: {
    scenario_id: string;
    current_minute: number;
    final_metrics: MetricSnapshot;
    timeline: Record<string, MetricSnapshot>;
    current?: MetricSnapshot;
  };
  meta: Record<string, string | number>;
};
