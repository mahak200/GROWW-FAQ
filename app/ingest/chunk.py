"""Split scraped pages into chunks. Reads data/raw only."""

from __future__ import annotations

import json
import re
import shutil
import sys
from dataclasses import dataclass

from bs4 import BeautifulSoup, NavigableString, Tag

from app.config import INGEST_IDS, ROOT, load_settings

FACT_LABELS = (
    "expense ratio",
    "exit load",
    "minimum sip",
    "min. for sip",
    "min for sip",
    "lock-in",
    "lock in",
    "riskometer",
    "benchmark",
    "statement",
    "download",
    "very high risk",
    "low to moderate risk",
    "moderately high risk",
    "moderate risk",
    "low risk",
    "high risk",
)
VALUE_LIKE = re.compile(r"(?:₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?%?|\bnil\b|\bn\.?a\.?\b|\bnot applicable\b", re.IGNORECASE)
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
DROP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer"}


@dataclass(frozen=True)
class Block:
    text: str
    kind: str  # heading | fact | text


def chunk_pages() -> None:
    settings = load_settings()
    raw_dir = ROOT / "data" / "raw"
    missing = [page_id for page_id in INGEST_IDS if not (raw_dir / f"{page_id}.json").exists()]
    if missing:
        print(f"Missing raw page: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)

    chunks_dir = ROOT / "data" / "chunks"
    if chunks_dir.exists():
        shutil.rmtree(chunks_dir)
    chunks_dir.mkdir(parents=True)

    for page_id in INGEST_IDS:
        record = json.loads((raw_dir / f"{page_id}.json").read_text(encoding="utf-8"))
        blocks = extract_blocks(record["html"])
        texts = pack_blocks(
            blocks,
            settings.chunk_max_chars,
            settings.chunk_overlap_chars,
        )
        chunks = [
            {
                "chunk_id": f"{page_id}-{index}",
                "page_id": page_id,
                "url": record["url"],
                "title": record["title"],
                "scheme_name": record["scheme_name"],
                "text": text,
            }
            for index, text in enumerate(texts, start=1)
        ]
        (chunks_dir / f"{page_id}.json").write_text(
            json.dumps(chunks, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"{page_id}: {len(chunks)} chunks")


def extract_blocks(html: str) -> list[Block]:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(DROP_TAGS):
        tag.decompose()

    blocks: list[Block] = []
    for element in soup.find_all(True):
        if not isinstance(element, Tag):
            continue
        text = _direct_text(element)
        if len(text) < 2:
            continue
        if element.name in HEADING_TAGS and not _is_fact_label(text):
            blocks.append(Block(text, "heading"))
        elif _is_fact_label(text):
            blocks.append(Block(text, "fact"))
        elif element.name in {"p", "li", "td", "th"} or _is_leaf_block(element):
            blocks.append(Block(text, "text"))
    return _glue_facts(blocks)


def _direct_text(element: Tag) -> str:
    parts: list[str] = []
    for child in element.children:
        if isinstance(child, NavigableString):
            parts.append(str(child))
    return _normalize(" ".join(parts))


def _is_leaf_block(element: Tag) -> bool:
    return element.name in {"div", "span"} and element.find(HEADING_TAGS | {"p", "li", "div"}) is None


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _is_fact_label(text: str) -> bool:
    normalized = text.lower()
    if len(normalized) > 80:
        return False
    return any(
        normalized == label or normalized.startswith(label) or f" {label}" in f" {normalized}"
        for label in FACT_LABELS
    )


def _glue_facts(blocks: list[Block]) -> list[Block]:
    glued: list[Block] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        has_value = bool(VALUE_LIKE.search(block.text)) or "risk" in block.text.lower()
        nxt = blocks[index + 1] if index + 1 < len(blocks) else None
        nxt2 = blocks[index + 2] if index + 2 < len(blocks) else None

        if block.kind == "fact" and not has_value and nxt:
            # Pair label with a nearby short value block, skipping obvious non-value noise.
            for offset, candidate in enumerate((nxt, nxt2), start=1):
                if candidate is None or candidate.kind in {"heading", "fact"}:
                    continue
                if _looks_like_value(candidate.text):
                    glued.append(Block(f"{block.text}\n{candidate.text.strip()}", "fact"))
                    # Keep skipped non-value block (e.g. "Fund size (AUM)") as context.
                    if offset == 2 and not _looks_like_value(nxt.text):
                        glued.append(nxt)
                    index += 1 + offset
                    break
            else:
                if nxt.kind not in {"heading", "fact"}:
                    glued.append(Block(f"{block.text}\n{nxt.text}", "fact"))
                    index += 2
                    continue
                glued.append(block)
                index += 1
            continue

        glued.append(block)
        index += 1
    return glued


def _looks_like_value(text: str) -> bool:
    t = text.strip()
    if not t or len(t) > 40:
        return False
    if _is_fact_label(t):
        return False
    return bool(VALUE_LIKE.search(t))


def pack_blocks(blocks: list[Block], max_chars: int, overlap_chars: int) -> list[str]:
    chunks: list[list[Block]] = []
    current: list[Block] = []

    def joined_length(items: list[Block]) -> int:
        if not items:
            return 0
        return sum(len(item.text) for item in items) + len(items) - 1

    for block in blocks:
        pieces = [block]
        if block.kind != "fact" and len(block.text) > max_chars:
            pieces = [Block(part, "text") for part in _split_long(block.text, max_chars)]
        for piece in pieces:
            extra = len(piece.text) if not current else len(piece.text) + 1
            if current and joined_length(current) + extra > max_chars:
                chunks.append(current)
                current = _overlap_tail(current, overlap_chars)
            current.append(piece)
    if current:
        chunks.append(current)

    texts: list[str] = []
    for chunk in chunks:
        text = "\n".join(item.text for item in chunk).strip()
        if text and (not texts or texts[-1] != text):
            texts.append(text)
    return texts


def _split_long(text: str, max_chars: int) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if not sentences:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                parts.append(current)
                current = ""
            for start in range(0, len(sentence), max_chars):
                parts.append(sentence[start : start + max_chars])
            continue
        candidate = f"{current} {sentence}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def _overlap_tail(blocks: list[Block], overlap_chars: int) -> list[Block]:
    if overlap_chars <= 0:
        return []
    chosen: list[Block] = []
    total = 0
    for block in reversed(blocks):
        extra = len(block.text) if not chosen else len(block.text) + 1
        if total + extra > overlap_chars:
            if not chosen and block.kind == "fact":
                return [block]
            break
        chosen.append(block)
        total += extra
    chosen.reverse()
    return chosen


if __name__ == "__main__":
    chunk_pages()
