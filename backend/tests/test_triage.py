from app.rag import LocalProtocolRag
from app.triage import TriageAgent


def test_red_classification_for_respiratory_distress():
    agent = TriageAgent(LocalProtocolRag())
    assessment = agent.assess(
        patient_id="P-001",
        report="Male approximately 40 with chest trauma, resp rate 34, radial pulse weak, GCS 12.",
        timestamp="2026-04-18T15:00:00Z",
        special_notes=["trauma"],
    )
    assert assessment.triage_category == "RED"
    assert "trauma_center" in assessment.needs
    assert assessment.citation.source


def test_green_classification_for_ambulatory_patient():
    agent = TriageAgent(LocalProtocolRag())
    assessment = agent.assess(
        patient_id="P-002",
        report="Female approximately 22 walking wounded with minor abrasions, resp rate 18, radial pulse strong, GCS 15.",
        timestamp="2026-04-18T15:00:00Z",
    )
    assert assessment.triage_category == "GREEN"
    assert assessment.review_required is False

