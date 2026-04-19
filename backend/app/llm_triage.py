from __future__ import annotations

import logging
from typing import Iterable

from .llm_client import call_llm_sync, extract_xml_tag, is_llm_available
from .models import ProtocolCitation, TriageAssessment, TriageCategory
from .triage import TriageAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a field triage medic AI. You classify mass casualty patients using START (adults) and JumpStart (pediatric <8yo) protocols.

TRIAGE CATEGORIES:
- BLACK: Not breathing after airway repositioning, or pulseless with no respirations
- RED (Immediate): Resp rate >30 or <10, GCS <=12, radial pulse absent/weak, airway burn risk, confusion
- YELLOW (Delayed): Ambulatory with significant injuries, stable vitals but needs intervention
- GREEN (Minor): Walking wounded, minor injuries, normal vitals

PROTOCOL CONTEXT:
{protocol_context}

You must return ONLY valid XML in this exact format:
<triage_category>RED</triage_category>
<confidence>0.87</confidence>
<reasoning>Brief clinical reasoning citing protocol step</reasoning>
<needs>comma,separated,needs</needs>
<review_required>false</review_required>
<pediatric>false</pediatric>"""

_ADJUDICATION_PROMPT = """You are reviewing two triage opinions for a mass casualty patient.
Choose the single safest final triage category.

Return ONLY:
<triage_category>RED</triage_category>
<reasoning>One sentence explaining the choice</reasoning>"""


class LLMTriageAgent:
    """Gemini-powered triage agent with rule-based fallback."""

    def __init__(self, rag, rule_based: TriageAgent) -> None:
        self._rag = rag
        self._fallback = rule_based

    def assess(
        self,
        patient_id: str,
        report: str,
        timestamp: str,
        special_notes: Iterable[str] | None = None,
        memory_context: str | None = None,
        rule_based_assessment: TriageAssessment | None = None,
        accuracy_review: bool = False,
    ) -> TriageAssessment:
        special_notes = list(special_notes or [])
        fallback_assessment = rule_based_assessment or self._fallback.assess(patient_id, report, timestamp, special_notes)
        if not is_llm_available():
            return fallback_assessment
        try:
            return self._assess_sync(
                patient_id=patient_id,
                report=report,
                timestamp=timestamp,
                special_notes=special_notes,
                memory_context=memory_context,
                fallback_assessment=fallback_assessment,
                accuracy_review=accuracy_review,
            )
        except Exception as exc:
            logger.warning("LLM triage failed, using fallback: %s", exc)
            return fallback_assessment

    def _assess_sync(
        self,
        *,
        patient_id: str,
        report: str,
        timestamp: str,
        special_notes: list[str],
        memory_context: str | None,
        fallback_assessment: TriageAssessment,
        accuracy_review: bool,
    ) -> TriageAssessment:
        is_pediatric_hint = any(n in report.lower() for n in ["boy", "girl", "child", "pediatric"]) or any(
            n == "pediatric" for n in special_notes
        )
        protocol_query = f"triage {'pediatric' if is_pediatric_hint else 'adult'} patient {report[:100]}"
        protocol_context = self._rag.query_text(protocol_query)

        response = call_llm_sync(
            _SYSTEM_PROMPT.format(protocol_context=protocol_context[:800]),
            (
                f"Patient ID: {patient_id}\n"
                f"Field Report: {report}\n"
                f"Special Notes: {', '.join(special_notes) or 'none'}\n"
                f"Prior similar cases: {memory_context or 'none'}\n\n"
                "Classify this patient:"
            ),
        )
        if not response:
            return fallback_assessment

        category_str = extract_xml_tag(response, "triage_category") or "GREEN"
        try:
            category = TriageCategory(category_str.upper())
        except ValueError:
            category = TriageCategory.GREEN

        confidence_str = extract_xml_tag(response, "confidence") or "0.7"
        try:
            confidence = float(confidence_str)
        except ValueError:
            confidence = 0.7

        reasoning = extract_xml_tag(response, "reasoning") or "LLM assessment"
        needs_str = extract_xml_tag(response, "needs") or "general_emergency"
        needs = [n.strip() for n in needs_str.split(",") if n.strip()]
        if not needs:
            needs = ["general_emergency"]

        review_str = extract_xml_tag(response, "review_required") or "false"
        review_required = review_str.lower() == "true" or confidence < 0.6

        pediatric_str = extract_xml_tag(response, "pediatric") or "false"
        pediatric = pediatric_str.lower() == "true" or is_pediatric_hint

        if accuracy_review and fallback_assessment.triage_category != category:
            adjudicated = self._adjudicate_disagreement(
                report=report,
                protocol_context=protocol_context,
                llm_category=category,
                llm_reasoning=reasoning,
                rule_category=fallback_assessment.triage_category,
                rule_reasoning=fallback_assessment.reasoning,
                memory_context=memory_context,
            )
            if adjudicated is not None:
                category, adjudication_reason = adjudicated
                reasoning = f"{reasoning} {adjudication_reason}".strip()

        if memory_context:
            reasoning = f"{reasoning} {memory_context}".strip()

        citation = ProtocolCitation(source="llamaindex_gemini_rag", excerpt=protocol_context[:200])
        logger.info("LLM triage %s -> %s (conf=%.2f)", patient_id, category, confidence)
        return TriageAssessment(
            patient_id=patient_id,
            triage_category=category,
            confidence=confidence,
            vitals=fallback_assessment.vitals,
            injuries=fallback_assessment.injuries,
            special_flags=fallback_assessment.special_flags,
            needs=needs,
            pediatric=pediatric,
            timestamp=timestamp,
            reasoning=reasoning,
            citation=citation,
            review_required=review_required,
            data_quality_flags=fallback_assessment.data_quality_flags,
        )

    def _adjudicate_disagreement(
        self,
        *,
        report: str,
        protocol_context: str,
        llm_category: TriageCategory,
        llm_reasoning: str,
        rule_category: TriageCategory,
        rule_reasoning: str,
        memory_context: str | None,
    ) -> tuple[TriageCategory, str] | None:
        response = call_llm_sync(
            _ADJUDICATION_PROMPT,
            (
                f"Field report: {report}\n"
                f"Protocol context: {protocol_context[:500]}\n"
                f"LLM opinion: {llm_category} because {llm_reasoning}\n"
                f"Rule-based opinion: {rule_category} because {rule_reasoning}\n"
                f"Memory context: {memory_context or 'none'}"
            ),
        )
        if not response:
            return None
        category_text = extract_xml_tag(response, "triage_category") or ""
        reasoning = extract_xml_tag(response, "reasoning") or ""
        try:
            return TriageCategory(category_text.upper()), reasoning
        except ValueError:
            return None
