from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT / "backend"
OUTPUT_DIR = BACKEND_DIR / "output"
ALERTS_DIR = OUTPUT_DIR / "alerts"
EMAILS_DIR = OUTPUT_DIR / "emails"
REPORTS_DIR = OUTPUT_DIR / "reports"
MEMORY_DIR = OUTPUT_DIR / "memory"


def ensure_output_dirs() -> None:
    for path in (ALERTS_DIR, EMAILS_DIR, REPORTS_DIR, MEMORY_DIR):
        path.mkdir(parents=True, exist_ok=True)


def incident_output_dir(base_dir: Path, incident_id: str) -> Path:
    ensure_output_dirs()
    target = base_dir / incident_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def resolve_repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path.resolve())
