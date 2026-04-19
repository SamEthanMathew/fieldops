from __future__ import annotations

import logging
from typing import Iterable

from .llm_client import call_llm, extract_xml_tag, is_llm_available
from .models import ProtocolCitation, TriageAssessment, TriageCategory, Vitals
from .triage import TriageAgent

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """You are a field triage medic AI. You classify mass casualty patients using START (adults) and JumpStart (pediatric <8yo) protocols.

TRIAGE CATEGORIES:
- BLACK: Not breathing after airway repositioning, or pulseless with no respirations
- RED (Immediate): Resp rate >30 or <10, GCS ≤12, radial pulse absent/weak, airway burn risk, confusion
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

_NEEDS_MAP = {
    "neurosurgery": "neurosurgery",
    "trauma": "trauma_center",
    "burn": "burn_center",
    "orthopedic": "orthopedic_surgery",
    "pediatric": "pediatric_trauma",
    "general": "general_emergency",
    "icu": "icu",
}


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
    ) -> TriageAssessment:
        import asyncio
        import concurrent.futures
        special_notes = list(special_notes or [])
        if not is_llm_available():
            return self._fallback.assess(patient_id, report, timestamp, special_notes)

        def _run() -> TriageAssessment:
            return asyncio.run(self._assess_async(patient_id, report, timestamp, special_notes))

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            try:
                return pool.submit(_run).result(timeout=20)
            except Exception as exc:
                logger.warning("LLM triage failed, using fallback: %s", exc)
                return self._fallback.assess(patient_id, report, timestamp, special_notes)

    async def _assess_async(
        self,
        patient_id: str,
        report: str,
        timestamp: str,
        special_notes: list[str],
    ) -> TriageAssessment:
        is_pediatric_hint = any(n in report.lower() for n in ["boy", "girl", "child", "pediatric"]) or any(
            n == "pediatric" for n in special_notes
        )
        protocol_query = f"triage {'pediatric' if is_pediatric_hint else 'adult'} patient {report[:100]}"
        protocol_context = self._rag.query_text(protocol_query)

        system = _SYSTEM_PROMPT.format(protocol_context=protocol_context[:800])
        user = f"Patient ID: {patient_id}\nField Report: {report}\nSpecial Notes: {', '.join(special_notes) or 'none'}\n\nClassify this patient:"

        response = await call_llm(system, user)
        if not response:
            return self._fallback.assess(patient_id, report, timestamp, special_notes)

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

        citation_source = "llamaindex_gemini_rag"
        citation = ProtocolCitation(source=citation_source, excerpt=protocol_context[:200])

        fallback = self._fallback.assess(patient_id, report, timestamp, special_notes)
        vitals = fallback.vitals
        injuries = fallback.injuries
        special_flags = fallback.special_flags

        logger.info("LLM triage %s → %s (conf=%.2f)", patient_id, category, confidence)
        return TriageAssessment(
            patient_id=patient_id,
            triage_category=category,
            confidence=confidence,
            vitals=vitals,
            injuries=injuries,
            special_flags=special_flags,
            needs=needs,
            pediatric=pediatric,
            timestamp=timestamp,
            reasoning=reasoning,
            citation=citation,
            review_required=review_required,
            data_quality_flags=fallback.data_quality_flags,
        )
