from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .runtime import MEMORY_DIR, ensure_output_dirs

logger = logging.getLogger(__name__)


class TriageMemoryStore:
    def __init__(self) -> None:
        ensure_output_dirs()
        self.path = MEMORY_DIR / "triage_memory.jsonl"
        self.entries: list[dict[str, Any]] = []
        self._index = None
        self._retriever = None
        self.backend = "local_keyword"
        self.total_queries: int = 0
        self.llamaindex_hits: int = 0
        self._load_entries()
        self._try_build_index()

    def _load_entries(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                self.entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Skipping invalid triage memory row")

    def _try_build_index(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key or not self.entries:
            return
        try:
            from llama_index.core import Document, Settings, VectorStoreIndex
            from llama_index.embeddings.gemini import GeminiEmbedding
            from llama_index.llms.gemini import Gemini

            Settings.embed_model = GeminiEmbedding(model_name="models/text-embedding-004", api_key=api_key)
            Settings.llm = Gemini(model="models/gemini-2.0-flash", api_key=api_key)
            docs = [
                Document(
                    text=self._entry_text(entry),
                    metadata={
                        "patient_id": entry.get("patient_id"),
                        "incident_id": entry.get("incident_id"),
                        "triage_category": entry.get("triage_category"),
                    },
                )
                for entry in self.entries
            ]
            self._index = VectorStoreIndex.from_documents(docs)
            self._retriever = self._index.as_retriever(similarity_top_k=3)
            self.backend = "llamaindex_memory"
        except Exception as exc:
            logger.warning("Falling back to keyword triage memory: %s", exc)
            self._index = None
            self._retriever = None
            self.backend = "local_keyword"

    @staticmethod
    def _entry_text(entry: dict[str, Any]) -> str:
        notes = ", ".join(entry.get("special_notes", [])) or "none"
        injuries = ", ".join(entry.get("injuries", [])) or "none"
        return (
            f"Patient {entry.get('patient_id', 'UNKNOWN')} "
            f"report: {entry.get('report', '')}\n"
            f"Category: {entry.get('triage_category', 'UNKNOWN')}\n"
            f"Notes: {notes}\n"
            f"Injuries: {injuries}\n"
            f"Reasoning: {entry.get('reasoning', '')}"
        )

    _MAX_ENTRIES = 500

    def record_decision(self, payload: dict[str, Any]) -> None:
        self.entries.append(payload)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
        if len(self.entries) > self._MAX_ENTRIES:
            self.entries = self.entries[-self._MAX_ENTRIES :]
            self.path.write_text(
                "\n".join(json.dumps(e, ensure_ascii=True) for e in self.entries) + "\n",
                encoding="utf-8",
            )

    def query_similar(self, report: str, special_notes: list[str] | None = None, k: int = 3) -> list[dict[str, Any]]:
        special_notes = special_notes or []
        self.total_queries += 1
        if self._retriever is not None:
            try:
                query = f"report: {report}\nnotes: {', '.join(special_notes)}"
                nodes = self._retriever.retrieve(query)
                hits: list[dict[str, Any]] = []
                for node in nodes[:k]:
                    text = node.node.get_content()
                    metadata = getattr(node.node, "metadata", {})
                    hits.append(
                        {
                            "patient_id": metadata.get("patient_id"),
                            "incident_id": metadata.get("incident_id"),
                            "triage_category": metadata.get("triage_category"),
                            "reasoning": text[:220],
                            "_retriever": "llamaindex",
                        }
                    )
                if hits:
                    self.llamaindex_hits += 1
                    return hits
            except Exception as exc:
                logger.warning("LlamaIndex memory query failed, falling back locally: %s", exc)
        return self._local_query(report, special_notes, k)

    def _local_query(self, report: str, special_notes: list[str], k: int) -> list[dict[str, Any]]:
        tokens = {
            token.lower().strip(".,:;!?")
            for token in report.split()
            if len(token) > 2
        }
        scored: list[tuple[float, dict[str, Any]]] = []
        for entry in self.entries:
            entry_tokens = {
                token.lower().strip(".,:;!?")
                for token in str(entry.get("report", "")).split()
                if len(token) > 2
            }
            overlap = len(tokens & entry_tokens)
            note_bonus = len(set(special_notes) & set(entry.get("special_notes", []))) * 2
            if overlap or note_bonus:
                scored.append((overlap + note_bonus, entry))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [entry for _, entry in scored[:k]]

    @staticmethod
    def summarize_hits(hits: list[dict[str, Any]]) -> str | None:
        if not hits:
            return None
        fragments = []
        for hit in hits[:3]:
            patient_id = hit.get("patient_id", "unknown")
            triage_category = hit.get("triage_category", "UNKNOWN")
            reasoning = str(hit.get("reasoning", "")).replace("\n", " ").strip()
            fragments.append(f"{patient_id} -> {triage_category} ({reasoning[:60]})")
        return f"Based on {len(hits[:3])} similar past cases: " + "; ".join(fragments) + "."
