"""Store chunk vectors in Chroma. Reads data/chunks and data/embeddings only."""

from __future__ import annotations

import json
import sys

import chromadb
from chromadb.errors import NotFoundError

from app.config import INGEST_IDS, ROOT, load_settings


def index_chunks() -> None:
    settings = load_settings()
    manifest_path = ROOT / "data" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("embedding_model") != settings.embedding_model:
        print(
            f"Embedding model mismatch: manifest has {manifest.get('embedding_model')!r}, "
            f"config has {settings.embedding_model!r}. Re-run python -m app.ingest.embed.",
            file=sys.stderr,
        )
        sys.exit(1)

    chunks_dir = ROOT / "data" / "chunks"
    embeddings_dir = ROOT / "data" / "embeddings"
    missing = [
        f"{kind}/{page_id}.json"
        for kind, directory in (("chunks", chunks_dir), ("embeddings", embeddings_dir))
        for page_id in INGEST_IDS
        if not (directory / f"{page_id}.json").exists()
    ]
    if missing:
        print(f"Missing file: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    records: list[tuple[dict, list[float]]] = []
    for page_id in INGEST_IDS:
        chunks = json.loads((chunks_dir / f"{page_id}.json").read_text(encoding="utf-8"))
        vectors = json.loads((embeddings_dir / f"{page_id}.json").read_text(encoding="utf-8"))
        if len(chunks) != len(vectors):
            print(f"Chunk/vector count mismatch for {page_id}", file=sys.stderr)
            sys.exit(1)
        for chunk, vector_record in zip(chunks, vectors):
            if chunk["chunk_id"] != vector_record["chunk_id"]:
                print(f"Chunk ID mismatch for {page_id}", file=sys.stderr)
                sys.exit(1)
            records.append((chunk, vector_record["vector"]))

    client = chromadb.PersistentClient(path=str(settings.chroma_path))
    names = {settings.collection_name}
    previous = manifest.get("collection_name")
    if previous:
        names.add(previous)
    for name in names:
        try:
            client.delete_collection(name)
        except NotFoundError:
            pass

    collection = client.create_collection(
        name=settings.collection_name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )
    collection.upsert(
        ids=[chunk["chunk_id"] for chunk, _ in records],
        documents=[chunk["text"] for chunk, _ in records],
        embeddings=[vector for _, vector in records],
        metadatas=[
            {
                "url": chunk["url"],
                "title": chunk["title"],
                "scheme_name": chunk["scheme_name"] or "",
                "page_id": chunk["page_id"],
            }
            for chunk, _ in records
        ],
    )

    manifest["collection_name"] = settings.collection_name
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Indexed {len(records)} chunks into {settings.chroma_path} ({settings.collection_name})")


if __name__ == "__main__":
    index_chunks()
