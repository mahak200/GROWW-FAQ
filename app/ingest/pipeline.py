"""Run scrape, chunk, embed, and index in order."""

from app.ingest.chunk import chunk_pages
from app.ingest.embed import embed_chunks
from app.ingest.index import index_chunks
from app.ingest.scrape import scrape


def run_pipeline() -> None:
    scrape()
    chunk_pages()
    embed_chunks()
    index_chunks()


if __name__ == "__main__":
    run_pipeline()
