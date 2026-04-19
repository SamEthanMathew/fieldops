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

export type AgentHealth = {
  status: string;
  last_updated_minute: number;
  last_error?: string | null;
  llm_mode?: boolean;
  last_thought?: string | null;
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
  alert_message: string;
  prep_needed: string[];
  eta_minutes: number;
  minute: number;
  timestamp: string;
  triage_category: string;
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
  baseline: {
    scenario_id: string;
    current_minute: number;
    final_metrics: MetricSnapshot;
    timeline: Record<string, MetricSnapshot>;
    current?: MetricSnapshot;
  };
  meta: Record<string, string | number>;
};

