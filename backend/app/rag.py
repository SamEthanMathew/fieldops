from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .models import ProtocolCitation


ROOT = Path(__file__).resolve().parents[2]
RAG_DIR = ROOT / "data" / "rag"


@dataclass
class RagDocument:
    name: str
    lines: list[str]


class LocalProtocolRag:
    def __init__(self) -> None:
        self.documents = self._load_documents()
        self.backend = "local_keyword"
        try:
            import llama_index  # type: ignore  # noqa: F401

            self.backend = "llamaindex_available"
        except Exception:
            self.backend = "local_keyword"

    def _load_documents(self) -> list[RagDocument]:
        docs = []
        for path in sorted(RAG_DIR.glob("*.md")):
            lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            docs.append(RagDocument(name=path.name, lines=lines))
        return docs

    def query(self, question: str, preferred_sources: list[str] | None = None) -> ProtocolCitation:
        keywords = {token.lower().strip(".,:;!?") for token in question.split() if len(token) > 2}
        candidates: list[tuple[int, str, str]] = []
        preferred_sources = preferred_sources or []
        for doc in self.documents:
            preference_bonus = 4 if any(source.lower() in doc.name.lower() for source in preferred_sources) else 0
            for line in doc.lines:
                score = sum(1 for keyword in keywords if keyword in line.lower()) + preference_bonus
                if score:
                    candidates.append((score, doc.name, line))
        if not candidates:
            fallback = self.documents[0]
            return ProtocolCitation(source=fallback.name, excerpt=fallback.lines[0])
        best = max(candidates, key=lambda item: item[0])
        return ProtocolCitation(source=best[1], excerpt=best[2])
