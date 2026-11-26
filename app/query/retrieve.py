"""Embed a question and query the configured Chroma collection."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import chromadb
from chromadb.errors import NotFoundError

from app.config import ROOT, Settings
from app.ingest.embed import embed_query
from app.query.gate import scheme_id, terms


class RetrievalError(Exception):
    """The index is missing or does not match the current config."""


@dataclass(frozen=True)
class Hit:
    chunk_id: str
    text: str
    url: str
    title: str
    scheme_name: str
    page_id: str
    distance: float


def load_manifest() -> dict:
    path = ROOT / "data" / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def check_index(settings: Settings, manifest: dict | None = None) -> None:
    manifest = manifest if manifest is not None else load_manifest()
    if not settings.chroma_path.exists() or not manifest.get("page_ids"):
        raise RetrievalError("Ingestion has not been run. Run python -m app.ingest.pipeline first.")
    if manifest.get("embedding_model") != settings.embedding_model:
        raise RetrievalError("Embedding model changed. Re-run python -m app.ingest.pipeline.")
    if manifest.get("collection_name") != settings.collection_name:
        raise RetrievalError("Collection changed. Re-run python -m app.ingest.pipeline.")


def retrieve(question: str, settings: Settings, manifest: dict | None = None) -> list[Hit]:
    manifest = manifest if manifest is not None else load_manifest()
    check_index(settings, manifest)

    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    try:
        collection = client.get_collection(
            name=settings.collection_name,
            embedding_function=None,
        )
    except NotFoundError as exc:
        raise RetrievalError("Ingestion has not been run. Run python -m app.ingest.pipeline first.") from exc

    result = collection.query(
        query_embeddings=[embed_query(question, settings.embedding_model)],
        n_results=max(settings.top_k, 20),
        include=["documents", "metadatas", "distances"],
    )
    ids = result["ids"][0]
    documents = result["documents"][0]
    metadatas = result["metadatas"][0]
    distances = result["distances"][0]

    question_terms = terms(question)
    hits: list[Hit] = []
    for chunk_id, text, metadata, distance in zip(ids, documents, metadatas, distances):
        lowered = (text or "").lower()
        supported = sum(1 for word in question_terms if word in lowered)
        lexical_ok = bool(question_terms) and supported / len(question_terms) >= 0.6
        if distance > settings.max_distance and not lexical_ok:
            continue
        hits.append(
            Hit(
                chunk_id=chunk_id,
                text=text,
                url=metadata.get("url", ""),
                title=metadata.get("title", ""),
                scheme_name=metadata.get("scheme_name", ""),
                page_id=metadata.get("page_id", ""),
                distance=distance,
            )
        )
    preferred = scheme_id(question)
    if preferred in {"large_cap", "flexi_cap", "elss", "mid_cap"}:
        hits = [hit for hit in hits if hit.page_id == preferred]
    hits.sort(key=lambda hit: (-_fact_score(hit, question), hit.distance))
    return hits[: settings.top_k]


FACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("expense ratio", re.compile(r"\bexpense\s+ratio\b", re.IGNORECASE)),
    ("exit load", re.compile(r"\bexit\s+load\b", re.IGNORECASE)),
    ("minimum sip", re.compile(r"\b(?:minimum\s+sip|min\.?\s+for\s+sip|min\s+for\s+sip|sip)\b", re.IGNORECASE)),
    ("lock-in", re.compile(r"\b(?:lock[\s-]?in|elss)\b", re.IGNORECASE)),
    ("riskometer", re.compile(r"\b(?:riskometer|very\s+high\s+risk|high\s+risk|moderate\s+risk|low\s+risk)\b", re.IGNORECASE)),
    ("benchmark", re.compile(r"\bbenchmark\b", re.IGNORECASE)),
)
VALUE_PATTERN = re.compile(r"(?:₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?%?|\b(?:nil|n\.?a\.?|not applicable)\b", re.IGNORECASE)


def _fact_score(hit: Hit, question: str) -> int:
    """Prefer chunks that contain the asked fact label and a concrete value."""
    asked = [name for name, pattern in FACT_PATTERNS if pattern.search(question)]
    if not asked:
        return 0
    lowered = hit.text.lower()
    score = 0
    for name in asked:
        pattern = dict(FACT_PATTERNS)[name]
        match = pattern.search(hit.text)
        if not match:
            continue
        score += 3
        window = hit.text[match.start() : match.start() + 220].lower()
        if VALUE_PATTERN.search(window):
            score += 6
        # Avoid definition-only chunks like "Expense ratio\nA fee payable..."
        if "fee payable" in window or "a percentage of your capital" in window:
            score -= 4
        # Prefer concise fact chunks over giant mixed chunks when both have value.
        if len(hit.text) < 1200:
            score += 1
    return score
