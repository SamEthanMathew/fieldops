from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class FieldOpsModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True, populate_by_name=True)


class TriageCategory(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    BLACK = "BLACK"


class PatientStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    AWAITING_DISPATCH = "AWAITING_DISPATCH"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    DISPATCHED = "DISPATCHED"
    TRANSPORTED = "TRANSPORTED"
    CLOSED = "CLOSED"


class HospitalStatus(str, Enum):
    OPEN = "OPEN"
    DIVERT = "DIVERT"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


class AmbulanceStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    EN_ROUTE = "EN_ROUTE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DispatchStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    QUEUED = "QUEUED"
    EXECUTED = "EXECUTED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class IncidentPhase(str, Enum):
    ACTIVE = "ACTIVE"
    STABILIZING = "STABILIZING"
    RECOVERY = "RECOVERY"


class IncidentMode(str, Enum):
    SPEED = "speed"
    BALANCED = "balanced"
    ACCURACY = "accuracy"


class AgentState(str, Enum):
    NOMINAL = "NOMINAL"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"


class Coordinates(FieldOpsModel):
    lat: float
    lng: float
    description: str | None = None


class Vitals(FieldOpsModel):
    gcs: int | None = None
    resp_rate: int | None = None
    radial_pulse: bool | None = None


class ProtocolCitation(FieldOpsModel):
    source: str
    excerpt: str


class TriageAssessment(FieldOpsModel):
    patient_id: str
    triage_category: TriageCategory
    confidence: float
    vitals: Vitals
    injuries: list[str] = Field(default_factory=list)
    special_flags: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    pediatric: bool = False
    timestamp: str
    reasoning: str
    citation: ProtocolCitation
    review_required: bool = False
    data_quality_flags: list[str] = Field(default_factory=list)


class HistoryEntry(FieldOpsModel):
    minute: int
    time: str
    event: str
    agent: str
    detail: str


class PatientRecord(FieldOpsModel):
    patient_id: str
    raw_report: str
    latest_report: str
    reported_minute: int
    triage_category: TriageCategory | None = None
    confidence: float | None = None
    vitals: Vitals = Field(default_factory=Vitals)
    injuries: list[str] = Field(default_factory=list)
    special_flags: list[str] = Field(default_factory=list)
    needs: list[str] = Field(default_factory=list)
    pediatric: bool = False
    review_required: bool = False
    data_quality_flags: list[str] = Field(default_factory=list)
    status: PatientStatus = PatientStatus.REPORTED
    assigned_ambulance: str | None = None
    assigned_hospital: str | None = None
    ground_truth_triage: str | None = None
    special_notes: list[str] = Field(default_factory=list)
    shadow_triage_category: TriageCategory | None = None
    shadow_confidence: float | None = None
    shadow_reasoning: str | None = None
    memory_summary: str | None = None
    citation: ProtocolCitation | None = None
    history: list[HistoryEntry] = Field(default_factory=list)


class Capacity(FieldOpsModel):
    total_beds: int
    available_beds: int
    icu_available: int
    or_available: int


class HospitalRecord(FieldOpsModel):
    hospital_id: str
    name: str
    email: str | None = None
    location: Coordinates
    trauma_level: int
    specialties: list[str]
    capacity: Capacity
    current_load_pct: float = 0.0
    status: HospitalStatus = HospitalStatus.OPEN
    divert_status: bool = False
    eta_from_scene_minutes: int
    last_updated: str
    last_updated_minute: int = 0
    stale: bool = False
    reason: str | None = None


class AmbulanceRecord(FieldOpsModel):
    ambulance_id: str
    type: str
    status: AmbulanceStatus = AmbulanceStatus.AVAILABLE
    position: Coordinates
    current_patient: str | None = None
    eta_available: int | None = None
    queued_dispatch_ids: list[str] = Field(default_factory=list)
    history: list[HistoryEntry] = Field(default_factory=list)


class AlternativeOption(FieldOpsModel):
    hospital_id: str
    hospital_name: str
    score: float
    reason_rejected: str


class DispatchRecommendation(FieldOpsModel):
    dispatch_id: str
    patient_id: str
    ambulance_id: str
    destination_hospital: str
    priority: str
    eta_minutes: int
    reasoning: str
    alternatives_considered: list[AlternativeOption] = Field(default_factory=list)
    confidence: float
    requires_ic_approval: bool
    status: DispatchStatus
    created_minute: int
    approved_minute: int | None = None


class Alert(FieldOpsModel):
    type: str
    message: str
    severity: str


class Sitrep(FieldOpsModel):
    sitrep_id: str
    timestamp: str
    minute: int
    incident_phase: IncidentPhase
    summary: str
    alerts: list[Alert] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    agent_health: dict[str, str] = Field(default_factory=dict)


class MetricSnapshot(FieldOpsModel):
    total_patients: int = 0
    by_category: dict[str, int] = Field(default_factory=lambda: {"RED": 0, "YELLOW": 0, "GREEN": 0, "BLACK": 0})
    transported: int = 0
    awaiting_dispatch: int = 0
    mean_dispatch_latency_sec: float = 0.0
    hospital_load_gini: float = 0.0
    triage_accuracy: float = 0.0
    accuracy_by_category: dict[str, float] = Field(default_factory=lambda: {"RED": 0.0, "YELLOW": 0.0, "GREEN": 0.0, "BLACK": 0.0})
    transport_match_score: float = 0.0
    survival_proxy_score: float = 0.0


class ArtifactRef(FieldOpsModel):
    label: str
    kind: str
    path: str
    download_url: str | None = None


class LatencyStats(FieldOpsModel):
    last_ms: float = 0.0
    avg_ms: float = 0.0
    p95_ms: float = 0.0
    call_count: int = 0
    success_count: int = 0
    fallback_count: int = 0


class CostEstimate(FieldOpsModel):
    total_usd: float = 0.0
    by_agent: dict[str, float] = Field(default_factory=dict)


class AgreementRates(FieldOpsModel):
    active_vs_ground_truth: float = 0.0
    shadow_vs_ground_truth: float = 0.0
    active_vs_shadow: float = 0.0
    three_way_agreement: float = 0.0


class LeadTimeStats(FieldOpsModel):
    last_minutes: float = 0.0
    avg_minutes: float = 0.0
    p95_minutes: float = 0.0


class CircuitBreakerStatus(FieldOpsModel):
    available: bool = False
    circuit_open: bool = False
    fail_count: int = 0
    retry_after_seconds: float = 0.0
    model: str | None = None


class TradeoffSummary(FieldOpsModel):
    compare_mode: IncidentMode = IncidentMode.SPEED
    accuracy_delta: float = 0.0
    latency_delta_ms: float = 0.0
    summary: str = ""


class LiveMetrics(FieldOpsModel):
    current_mode: IncidentMode = IncidentMode.BALANCED
    active_accuracy: float = 0.0
    shadow_accuracy: float = 0.0
    agreement: AgreementRates = Field(default_factory=AgreementRates)
    per_agent_latency: dict[str, LatencyStats] = Field(default_factory=dict)
    pre_notification_lead_time: LeadTimeStats = Field(default_factory=LeadTimeStats)
    cost_estimate: CostEstimate = Field(default_factory=CostEstimate)
    tradeoffs: TradeoffSummary = Field(default_factory=TradeoffSummary)
    circuit_breaker: CircuitBreakerStatus = Field(default_factory=CircuitBreakerStatus)
    emails_sent: int = 0
    emails_total: int = 0
    rag_queries: int = 0
    memory_retrievals: int = 0
    memory_llamaindex_hits: int = 0


class DecisionLogEntry(FieldOpsModel):
    minute: int
    timestamp: str
    agent: str
    message: str
    severity: str = "INFO"
    related_ids: list[str] = Field(default_factory=list)


class AuditLogEntry(FieldOpsModel):
    audit_id: str
    minute: int
    timestamp: str
    event_type: str
    agent: str
    message: str
    status: str = "INFO"
    data: dict[str, Any] = Field(default_factory=dict)


class GuardrailRule(FieldOpsModel):
    rule_id: str
    title: str
    description: str
    active: bool = True


class AgentHealth(FieldOpsModel):
    status: AgentState = AgentState.NOMINAL
    last_updated_minute: int = 0
    last_error: str | None = None
    llm_mode: bool = False
    last_thought: str | None = None
    latency: LatencyStats = Field(default_factory=LatencyStats)
    estimated_tokens: int = 0
    estimated_cost_usd: float = 0.0


class AgentMessage(FieldOpsModel):
    message_id: str
    from_agent: str
    to_agent: str
    message: str
    minute: int
    timestamp: str
    message_type: str = "DIRECTIVE"


class PreHospitalNotification(FieldOpsModel):
    notification_id: str
    patient_id: str
    ambulance_id: str
    hospital_id: str
    hospital_name: str
    recipient_email: str | None = None
    alert_message: str
    prep_needed: list[str] = Field(default_factory=list)
    eta_minutes: int
    minute: int
    timestamp: str
    triage_category: str
    lead_time_minutes: float = 0.0
    email_status: str = "pending"
    pdf_path: str | None = None
    eml_path: str | None = None
    pdf_artifact: ArtifactRef | None = None
    eml_artifact: ArtifactRef | None = None


class EmailDeliveryRecord(FieldOpsModel):
    notification_id: str
    hospital_id: str
    hospital_name: str
    recipient_email: str
    subject: str
    status: str
    minute: int
    timestamp: str
    eml_path: str | None = None
    error: str | None = None


class BaselineState(FieldOpsModel):
    scenario_id: str
    current_minute: int = 0
    final_metrics: MetricSnapshot = Field(default_factory=MetricSnapshot)
    timeline: dict[str, MetricSnapshot] = Field(default_factory=dict)


class IncidentState(FieldOpsModel):
    incident_id: str
    scenario_id: str
    incident_type: str
    incident_phase: IncidentPhase
    mode: IncidentMode = IncidentMode.BALANCED
    location: Coordinates
    start_time: str
    current_time: str
    current_minute: int = 0
    patients: dict[str, PatientRecord] = Field(default_factory=dict)
    hospitals: dict[str, HospitalRecord] = Field(default_factory=dict)
    ambulances: dict[str, AmbulanceRecord] = Field(default_factory=dict)
    dispatches: list[DispatchRecommendation] = Field(default_factory=list)
    sitreps: list[Sitrep] = Field(default_factory=list)
    metrics: MetricSnapshot = Field(default_factory=MetricSnapshot)
    decision_log: list[DecisionLogEntry] = Field(default_factory=list)
    pending_approvals: list[str] = Field(default_factory=list)
    agent_health: dict[str, AgentHealth] = Field(default_factory=dict)
    agent_messages: list[AgentMessage] = Field(default_factory=list)
    pre_notifications: list[PreHospitalNotification] = Field(default_factory=list)
    email_log: list[EmailDeliveryRecord] = Field(default_factory=list)
    audit_log: list[AuditLogEntry] = Field(default_factory=list)
    guardrails: list[GuardrailRule] = Field(default_factory=list)
    artifacts: list[ArtifactRef] = Field(default_factory=list)
    report_artifact: ArtifactRef | None = None
    live_metrics: LiveMetrics = Field(default_factory=LiveMetrics)
    degraded_mode: bool = False
    degraded_reason: str | None = None
    baseline: BaselineState
    meta: dict[str, Any] = Field(default_factory=dict)


class ScenarioEvent(FieldOpsModel):
    minute: int
    type: str
    patient_id: str | None = None
    hospital_id: str | None = None
    ambulance_id: str | None = None
    report: str | None = None
    ground_truth_triage: str | None = None
    special_notes: list[str] = Field(default_factory=list)
    status: str | None = None
    divert_status: bool | None = None
    reason: str | None = None


class ScenarioDefinition(FieldOpsModel):
    scenario_id: str
    name: str
    incident_type: str
    duration_minutes: int
    scene: Coordinates
    events: list[ScenarioEvent]


class ScenarioControlRequest(FieldOpsModel):
    incident_id: str
    action: str
    speed: float | None = None
    steps: int | None = None


class InjectEventRequest(FieldOpsModel):
    incident_id: str
    event: ScenarioEvent


class ApproveDispatchRequest(FieldOpsModel):
    incident_id: str


class IncidentModeRequest(FieldOpsModel):
    mode: IncidentMode
