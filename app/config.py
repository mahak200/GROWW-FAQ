"""Load settings and the link catalog. Does not require a Groq key."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
INGEST_IDS = ("amc", "large_cap", "flexi_cap", "elss", "mid_cap")


@dataclass(frozen=True)
class Settings:
    embedding_model: str
    chroma_path: Path
    collection_name: str
    chunk_max_chars: int
    chunk_overlap_chars: int
    top_k: int
    max_distance: float
    groq_api_key: str
    groq_model: str


@dataclass(frozen=True)
class CatalogEntry:
    role: str
    title: str
    url: str
    page_id: str | None = None
    scheme_name: str | None = None
    use: str | None = None


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    with (ROOT / "config" / "settings.yaml").open(encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    chroma_path = Path(os.getenv("CHROMA_PATH") or raw["chroma_path"])
    if not chroma_path.is_absolute():
        chroma_path = ROOT / chroma_path
    return Settings(
        embedding_model=raw["embedding_model"],
        chroma_path=chroma_path,
        collection_name=raw["collection_name"],
        chunk_max_chars=int(raw["chunk_max_chars"]),
        chunk_overlap_chars=int(raw["chunk_overlap_chars"]),
        top_k=int(raw["top_k"]),
        max_distance=float(raw["max_distance"]),
        groq_api_key=os.getenv("GROQ_API_KEY", "").strip(),
        groq_model=os.getenv("GROQ_MODEL", "").strip(),
    )


def load_catalog() -> list[CatalogEntry]:
    with (ROOT / "data" / "catalog.yaml").open(encoding="utf-8") as handle:
        rows = yaml.safe_load(handle)
    return [
        CatalogEntry(
            role=row["role"],
            title=row["title"],
            url=row["url"],
            page_id=row.get("page_id") or None,
            scheme_name=row.get("scheme_name") or None,
            use=row.get("use") or None,
        )
        for row in rows
    ]


def ingest_pages(entries: list[CatalogEntry] | None = None) -> list[CatalogEntry]:
    pages = [entry for entry in (entries if entries is not None else load_catalog()) if entry.role == "ingest"]
    ids = [entry.page_id for entry in pages]
    if ids != list(INGEST_IDS):
        raise ValueError(f"Ingest pages must be {list(INGEST_IDS)}, got {ids}")
    return pages
