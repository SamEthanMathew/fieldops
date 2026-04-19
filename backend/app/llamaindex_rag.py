from __future__ import annotations

import logging
import os
from pathlib import Path

from .models import ProtocolCitation
from .rag import LocalProtocolRag

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
RAG_DIR = ROOT / "data" / "rag"


class LlamaIndexRag:
    """LlamaIndex-powered RAG over medical protocols using Gemini embeddings."""

    def __init__(self) -> None:
        self._index = None
        self._query_engine = None
        self._fallback = LocalProtocolRag()
        self.backend = "local_keyword"
        self._try_init()

    def _try_init(self) -> None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            logger.info("GEMINI_API_KEY not set — using local keyword RAG")
            return
        try:
            from llama_index.core import Settings, SimpleDirectoryReader, VectorStoreIndex
            from llama_index.embeddings.gemini import GeminiEmbedding
            from llama_index.llms.gemini import Gemini

            llama_cloud_key = os.environ.get("LLAMA_CLOUD_API_KEY")
            if llama_cloud_key:
                os.environ["LLAMA_CLOUD_API_KEY"] = llama_cloud_key

            embed_model = GeminiEmbedding(
                model_name="models/text-embedding-004",
                api_key=api_key,
            )
            llm = Gemini(model="models/gemini-2.0-flash", api_key=api_key)
            Settings.embed_model = embed_model
            Settings.llm = llm

            documents = SimpleDirectoryReader(str(RAG_DIR), required_exts=[".md"]).load_data()
            self._index = VectorStoreIndex.from_documents(documents)
            self._query_engine = self._index.as_query_engine(similarity_top_k=2)
            self.backend = "llamaindex_gemini"
            logger.info("LlamaIndex RAG initialized with Gemini embeddings (%d docs)", len(documents))
        except Exception as exc:
            logger.warning("LlamaIndex init failed, falling back to keyword RAG: %s", exc)
            self.backend = "local_keyword"

    def query(self, question: str, preferred_sources: list[str] | None = None) -> ProtocolCitation:
        if self._query_engine is None:
            return self._fallback.query(question, preferred_sources)
        try:
            result = self._query_engine.query(question)
            source_nodes = getattr(result, "source_nodes", [])
            if source_nodes:
                node = source_nodes[0]
                fname = getattr(node.node, "metadata", {}).get("file_name", "protocol.md")
                excerpt = node.node.get_content()[:300].strip()
                return ProtocolCitation(source=fname, excerpt=excerpt)
            return ProtocolCitation(source="llamaindex", excerpt=str(result)[:300])
        except Exception as exc:
            logger.warning("LlamaIndex query failed: %s", exc)
            return self._fallback.query(question, preferred_sources)

    def query_text(self, question: str) -> str:
        if self._query_engine is None:
            citation = self._fallback.query(question)
            return citation.excerpt
        try:
            result = self._query_engine.query(question)
            return str(result)[:500]
        except Exception as exc:
            logger.warning("LlamaIndex query_text failed: %s", exc)
            citation = self._fallback.query(question)
            return citation.excerpt
