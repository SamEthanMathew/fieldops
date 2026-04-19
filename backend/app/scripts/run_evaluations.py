from __future__ import annotations

import json
from pathlib import Path

from app.engine import SimulationSession
from app.hospital_intel import HospitalIntelAgent
from app.logistics import LogisticsAgent
from app.overwatch import OverwatchAgent
from app.rag import LocalProtocolRag
from app.scenario_loader import load_scenario
from app.triage import TriageAgent


ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "docs" / "results"


def run_scenario(scenario_id: str) -> dict:
    session = SimulationSession(
        scenario=load_scenario(scenario_id),
        triage_agent=TriageAgent(LocalProtocolRag()),
        hospital_intel=HospitalIntelAgent(),
        logistics=LogisticsAgent(),
        overwatch=OverwatchAgent(),
    )
    for minute in range(1, session.scenario.duration_minutes + 1):
        session._process_minute(minute)
        approvals = list(session.state.pending_approvals)
        for dispatch_id in approvals:
            session.logistics.approve_dispatch(session.state, dispatch_id, minute)
    return {
        "scenario_id": scenario_id,
        "fieldops_metrics": session.state.metrics.model_dump(mode="json"),
        "baseline_metrics": session.state.baseline.final_metrics.model_dump(mode="json"),
    }


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    results = [run_scenario(scenario_id) for scenario_id in ["bridge-collapse-light", "bridge-collapse-standard", "bridge-collapse-heavy"]]
    output_path = OUTPUT / "evaluation_results.json"
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()

