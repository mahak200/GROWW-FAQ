"""Fetch the five ingest pages. Does not follow links on those pages."""

from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime

import httpx

from app.config import ROOT, ingest_pages

TIMEOUT_SECONDS = 30.0
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def scrape() -> None:
    pages = ingest_pages()
    fetched_at_dt = datetime.now().astimezone()
    fetched_at = fetched_at_dt.isoformat(timespec="seconds")
    records: list[dict] = []

    with httpx.Client(
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for page in pages:
            try:
                response = client.get(page.url)
            except httpx.HTTPError as exc:
                print(f"Failed to fetch {page.url}: {exc}", file=sys.stderr)
                sys.exit(1)
            if response.status_code != 200:
                print(f"{response.status_code} {page.url}", file=sys.stderr)
                sys.exit(1)
            if not response.text.strip():
                print(f"Empty page {page.url}", file=sys.stderr)
                sys.exit(1)
            records.append(
                {
                    "page_id": page.page_id,
                    "url": page.url,
                    "title": page.title,
                    "scheme_name": page.scheme_name,
                    "http_status": response.status_code,
                    "fetched_at": fetched_at,
                    "html": response.text,
                }
            )

    raw_dir = ROOT / "data" / "raw"
    temp_dir = ROOT / "data" / "raw.tmp"
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True)
    for record in records:
        path = temp_dir / f"{record['page_id']}.json"
        path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")

    if raw_dir.exists():
        shutil.rmtree(raw_dir)
    temp_dir.rename(raw_dir)

    manifest = {
        "fetched_on": fetched_at_dt.date().isoformat(),
        "page_ids": [record["page_id"] for record in records],
        "embedding_model": None,
        "collection_name": None,
    }
    (ROOT / "data" / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    print(f"Scraped {len(records)} pages into {raw_dir}")


if __name__ == "__main__":
    scrape()
