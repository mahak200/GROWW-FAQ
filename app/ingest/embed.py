"""Embed chunks locally with sentence-transformers and queries with bundled ONNX."""

from __future__ import annotations

import json
import shutil
import sys

from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2

from app.config import INGEST_IDS, ROOT, load_settings

ONNXMiniLM_L6_V2.DOWNLOAD_PATH = ROOT / "data" / "onnx_models" / "all-MiniLM-L6-v2"

_model = None
_model_name: str | None = None
_onnx_ef = None


def load_model(model_name: str):
    """Load the configured model once and reuse it for chunk ingestion."""
    global _model, _model_name
    if _model is None or _model_name != model_name:
        from sentence_transformers import SentenceTransformer

        _model = SentenceTransformer(model_name)
        _model_name = model_name
    return _model


def embed_texts(texts: list[str], model_name: str) -> list[list[float]]:
    """Return normalized embeddings in input order."""
    if not texts:
        return []
    model = load_model(model_name)
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [vector.tolist() for vector in vectors]


def embed_query(text: str, model_name: str) -> list[float]:
    """Embed one query with the ONNX model matching the indexed vectors."""
    global _onnx_ef
    if _onnx_ef is None:
        _onnx_ef = ONNXMiniLM_L6_V2()
    return [float(value) for value in _onnx_ef([text])[0]]


def embed_chunks() -> None:
    settings = load_settings()
    chunks_dir = ROOT / "data" / "chunks"
    missing = [page_id for page_id in INGEST_IDS if not (chunks_dir / f"{page_id}.json").exists()]
    if missing:
        print(f"Missing chunks for page: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    records: list[tuple[str, str, str]] = []
    for page_id in INGEST_IDS:
        chunks = json.loads((chunks_dir / f"{page_id}.json").read_text(encoding="utf-8"))
        if not chunks:
            print(f"No chunks for page: {page_id}", file=sys.stderr)
            sys.exit(1)
        records.extend((page_id, chunk["chunk_id"], chunk["text"]) for chunk in chunks)

    vectors = embed_texts([text for _, _, text in records], settings.embedding_model)

    by_page: dict[str, list[dict]] = {page_id: [] for page_id in INGEST_IDS}
    for (page_id, chunk_id, _), vector in zip(records, vectors):
        by_page[page_id].append({"chunk_id": chunk_id, "vector": vector})

    temp_dir = ROOT / "data" / "embeddings.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    for page_id, entries in by_page.items():
        (temp_dir / f"{page_id}.json").write_text(
            json.dumps(entries, ensure_ascii=False),
            encoding="utf-8",
        )

    embeddings_dir = ROOT / "data" / "embeddings"
    if embeddings_dir.exists():
        shutil.rmtree(embeddings_dir)
    temp_dir.rename(embeddings_dir)

    manifest_path = ROOT / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["embedding_model"] = settings.embedding_model
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Embedded {len(records)} chunks into {embeddings_dir}")


if __name__ == "__main__":
    embed_chunks()
