from __future__ import annotations

import re
from typing import Iterable

from .models import ProtocolCitation, TriageAssessment, TriageCategory, Vitals
from .rag import LocalProtocolRag
from .utils import clamp


AGE_RE = re.compile(r"(?:age\s+|approximately\s+)?(\d{1,2})")
RESP_RE = re.compile(r"resp(?:irations?| rate)?\s*(?:now)?\s*(\d{1,2})", re.IGNORECASE)
GCS_RE = re.compile(r"gcs\s*(?:dropped to\s*)?(\d{1,2})", re.IGNORECASE)
PULSE_RE = re.compile(r"radial pulse\s*(strong|present|weak|absent)", re.IGNORECASE)


class TriageAgent:
    def __init__(self, rag: LocalProtocolRag) -> None:
        self.rag = rag

    def assess(
        self,
        patient_id: str,
        report: str,
        timestamp: str,
        special_notes: Iterable[str] | None = None,
    ) -> TriageAssessment:
        special_notes = list(special_notes or [])
        lowered = report.lower()
        age_match = AGE_RE.search(lowered)
        age = int(age_match.group(1)) if age_match else None
        pediatric = "boy" in lowered or "girl" in lowered or "pediatric" in lowered or (age is not None and age < 10)

        vitals = Vitals(
            resp_rate=self._extract_int(RESP_RE, lowered),
            gcs=self._extract_int(GCS_RE, lowered),
            radial_pulse=self._extract_pulse(lowered),
        )
        injuries, special_flags, needs, ambulatory = self._extract_features(lowered, special_notes)
        data_quality_flags = self._validate_vitals(vitals)

        category = self._classify(lowered, vitals, ambulatory, pediatric, special_flags)
        citation = self._citation_for(category, pediatric, special_flags)
        reasoning = self._reasoning_for(category, vitals, ambulatory, injuries, special_flags, citation)

        confidence = 0.55
        if vitals.resp_rate is not None:
            confidence += 0.1
        if vitals.gcs is not None:
            confidence += 0.1
        if vitals.radial_pulse is not None:
            confidence += 0.1
        if injuries:
            confidence += 0.07
        if special_flags:
            confidence += 0.05
        if data_quality_flags:
            confidence -= 0.2
        confidence = clamp(confidence, 0.35, 0.97)

        review_required = confidence < 0.6 or bool(data_quality_flags)
        if review_required and category == TriageCategory.GREEN:
            category = TriageCategory.YELLOW
            reasoning += " Conservative escalation applied because data quality or confidence was insufficient."
        elif review_required and category == TriageCategory.YELLOW:
            category = TriageCategory.RED
            reasoning += " Conservative escalation applied because data quality or confidence was insufficient."

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
            data_quality_flags=data_quality_flags,
        )

    @staticmethod
    def _extract_int(pattern: re.Pattern[str], lowered: str) -> int | None:
        match = pattern.search(lowered)
        return int(match.group(1)) if match else None

    @staticmethod
    def _extract_pulse(lowered: str) -> bool | None:
        match = PULSE_RE.search(lowered)
        if not match:
            return None
        value = match.group(1).lower()
        if value == "absent":
            return False
        return True

    def _extract_features(
        self,
        lowered: str,
        special_notes: list[str],
    ) -> tuple[list[str], list[str], list[str], bool]:
        injuries: list[str] = []
        special_flags: list[str] = list(special_notes)
        needs: set[str] = set()

        keyword_map = {
            "fracture": ("fracture", "orthopedic_surgery"),
            "deformity": ("limb deformity", "orthopedic_surgery"),
            "leg pain": ("leg injury", "orthopedic_surgery"),
            "burn": ("burn injury", "burn_center"),
            "chest": ("chest trauma", "trauma_center"),
            "pelvis": ("pelvic trauma", "trauma_center"),
            "pelvic": ("pelvic trauma", "trauma_center"),
            "abdominal": ("abdominal trauma", "trauma_center"),
            "head": ("head injury", "neurosurgery"),
            "back pain": ("spinal concern", "neurosurgery"),
            "numb legs": ("neurologic deficit", "neurosurgery"),
            "numb": ("neurologic deficit", "neurosurgery"),
            "spinal": ("spinal injury", "neurosurgery"),
        }
        for keyword, (injury, need) in keyword_map.items():
            if keyword in lowered:
                injuries.append(injury)
                needs.add(need)

        if "crush" in lowered:
            special_flags.append("crush_injury")
            needs.add("trauma_center")
        if "hoarse" in lowered or "soot" in lowered:
            special_flags.append("airway_burn_risk")
            needs.add("burn_center")
        if "boy" in lowered or "girl" in lowered or "pediatric" in special_notes:
            needs.add("pediatric_trauma")
        if "walking" in lowered or "ambulatory" in lowered:
            ambulatory = True
        else:
            ambulatory = False

        for note in special_notes:
            if note == "orthopedic":
                needs.add("orthopedic_surgery")
            if note == "burn":
                needs.add("burn_center")
            if note == "neuro":
                needs.add("neurosurgery")
            if note == "pediatric":
                needs.add("pediatric_trauma")
            if note == "trauma":
                needs.add("trauma_center")
            if note == "crush_injury":
                needs.add("trauma_center")

        if not needs:
            needs.add("general_emergency")
        return injuries, sorted(set(special_flags)), sorted(needs), ambulatory

    @staticmethod
    def _validate_vitals(vitals: Vitals) -> list[str]:
        flags = []
        if vitals.resp_rate is not None and not (0 <= vitals.resp_rate <= 60):
            flags.append("resp_rate_out_of_range")
        if vitals.gcs is not None and not (3 <= vitals.gcs <= 15):
            flags.append("gcs_out_of_range")
        return flags

    def _classify(
        self,
        lowered: str,
        vitals: Vitals,
        ambulatory: bool,
        pediatric: bool,
        special_flags: list[str],
    ) -> TriageCategory:
        if ("not breathing" in lowered or "no respirations" in lowered or "pulseless" in lowered) and "after airway reposition" in lowered:
            return TriageCategory.BLACK
        if ("not breathing" in lowered or "pulseless" in lowered) and "resp rate" not in lowered:
            return TriageCategory.BLACK
        if any(flag == "airway_burn_risk" for flag in special_flags):
            return TriageCategory.RED
        if vitals.resp_rate is not None and (vitals.resp_rate > 30 or vitals.resp_rate < 10):
            return TriageCategory.RED
        if vitals.gcs is not None and vitals.gcs <= 12:
            return TriageCategory.RED
        if "confused" in lowered or "unable to follow commands" in lowered:
            return TriageCategory.RED
        if "weak radial pulse" in lowered or "radial pulse weak" in lowered or "shock" in lowered:
            return TriageCategory.RED
        if "severe leg pain" in lowered or "numb legs" in lowered or "back pain" in lowered:
            return TriageCategory.YELLOW
        if pediatric and ("trapped" in lowered or "deformity" in lowered or "abdominal" in lowered):
            return TriageCategory.YELLOW
        if ambulatory and all(word not in lowered for word in ["burn", "fracture", "chest", "difficulty breathing"]):
            return TriageCategory.GREEN
        if any(word in lowered for word in ["fracture", "deformity", "burn", "chest", "abdominal", "pelvis", "pelvic", "head", "spinal", "back pain", "numb"]):
            return TriageCategory.YELLOW
        return TriageCategory.GREEN

    def _citation_for(
        self,
        category: TriageCategory,
        pediatric: bool,
        special_flags: list[str],
    ) -> ProtocolCitation:
        sources = ["jumpstart"] if pediatric else ["start"]
        if "airway_burn_risk" in special_flags:
            sources.append("salt")
        question = f"triage {category.value} pediatric={pediatric} flags={' '.join(special_flags)}"
        return self.rag.query(question, preferred_sources=sources)

    @staticmethod
    def _reasoning_for(
        category: TriageCategory,
        vitals: Vitals,
        ambulatory: bool,
        injuries: list[str],
        special_flags: list[str],
        citation: ProtocolCitation,
    ) -> str:
        fragments = []
        if ambulatory:
            fragments.append("patient is ambulatory")
        if vitals.resp_rate is not None:
            fragments.append(f"respiratory rate {vitals.resp_rate}")
        if vitals.gcs is not None:
            fragments.append(f"GCS {vitals.gcs}")
        if vitals.radial_pulse is not None:
            fragments.append(f"radial pulse {'present' if vitals.radial_pulse else 'absent'}")
        if injuries:
            fragments.append("injuries include " + ", ".join(injuries))
        if special_flags:
            fragments.append("special flags " + ", ".join(special_flags))
        basis = "; ".join(fragments) if fragments else "limited field information"
        return f"Classified {category.value} because {basis}. Protocol support: {citation.excerpt}"
