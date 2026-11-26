"""Turn a question into a fact, refusal, or error."""

from __future__ import annotations

import re

from app.config import Settings, load_catalog, load_settings
from app.query.gate import classify, is_statement, scheme_id
from app.query.retrieve import Hit, RetrievalError, load_manifest, retrieve

PII_TEXT = (
    "Please do not share personal data such as PAN, Aadhaar, account numbers, OTPs, "
    "email addresses, or phone numbers. I answer only fund facts and do not store or repeat personal data."
)
ADVICE_TEXT = (
    "I answer facts only and do not recommend investments, give buy or sell advice, or compare funds. "
    "Please check the official page for details."
)
PERFORMANCE_TEXT = (
    "I do not calculate or compare returns or performance. Please check the official factsheet for the scheme."
)
ABSENT_TEXT = "That fact is not in this corpus. Please check the official page for details."
FAILURE_TEXT = "An answer could not be generated from the retrieved text. Please try again or check the official scheme page."
SYSTEM_PROMPT = (
    "Answer the single factual question using only the supplied source text. "
    "Reply in at most three sentences. If the fact is not in the text, reply exactly NOT_IN_SOURCES. "
    "Give no advice, no performance comparison, and no URLs."
)
URL_PATTERN = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def answer(question: str) -> dict[str, str]:
    settings = load_settings()
    manifest = load_manifest()
    fetched_on = manifest.get("fetched_on", "")
    kind = classify(question)
    if kind != "fact":
        text, url = _refusal(kind, question)
        return _payload(text, url, fetched_on)

    try:
        hits = retrieve(question, settings, manifest)
    except RetrievalError as exc:
        return _payload(str(exc), _url_for_page("amc"), fetched_on)
    if not hits:
        return _payload(ABSENT_TEXT, _absent_url(question), fetched_on)

    source = _best_source(question, hits)
    generated = _generate(question, [source] + [h for h in hits if h.chunk_id != source.chunk_id][:2], settings)
    if generated is None:
        return _payload(FAILURE_TEXT, source.url, fetched_on)
    generated = _limit(generated)
    if "NOT_IN_SOURCES" in generated.upper():
        return _payload(ABSENT_TEXT, _absent_url(question), fetched_on)
    return _payload(generated, source.url, fetched_on)


def _refusal(kind: str, question: str) -> tuple[str, str]:
    page_id = scheme_id(question)
    if kind == "pii":
        return PII_TEXT, _url_for_page("amc")
    if kind == "performance":
        return PERFORMANCE_TEXT, _url_for_use("factsheet", page_id)
    if page_id in {"large_cap", "flexi_cap", "elss", "mid_cap"}:
        return ADVICE_TEXT, _url_for_page(page_id)
    return ADVICE_TEXT, _url_for_page("amc")


def _absent_url(question: str) -> str:
    if is_statement(question):
        return _url_for_use("statement", None)
    return _url_for_page(scheme_id(question) or "amc")


FACT_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("expense ratio", re.compile(r"\bexpense\s+ratio\b", re.IGNORECASE)),
    ("exit load", re.compile(r"\bexit\s+load\b", re.IGNORECASE)),
    ("minimum sip", re.compile(r"\b(?:minimum\s+sip|min\.?\s+for\s+sip|min\s+for\s+sip|sip)\b", re.IGNORECASE)),
    ("lock-in", re.compile(r"\b(?:lock[\s-]?in|elss)\b", re.IGNORECASE)),
    ("riskometer", re.compile(r"\b(?:riskometer|risk)\b", re.IGNORECASE)),
    ("benchmark", re.compile(r"\bbenchmark\b", re.IGNORECASE)),
)
VALUE_RE = re.compile(r"(?:₹|rs\.?\s*)?\d[\d,]*(?:\.\d+)?%?|\bnil\b", re.IGNORECASE)


def _best_source(question: str, hits: list[Hit]) -> Hit:
    asked = [pattern for _, pattern in FACT_HINTS if pattern.search(question)]
    if not asked:
        return hits[0]
    for hit in hits:
        window = hit.text
        if any(pattern.search(window) for pattern in asked):
            for pattern in asked:
                m = pattern.search(window)
                if not m:
                    continue
                snippet = window[m.start() : m.start() + 220]
                if VALUE_RE.search(snippet) and "fee payable" not in snippet.lower():
                    return hit
    return hits[0]


def _url_for_page(page_id: str | None) -> str:
    target = page_id or "amc"
    for entry in load_catalog():
        if entry.role == "ingest" and entry.page_id == target:
            return entry.url
    return ""


def _url_for_use(use: str, page_id: str | None) -> str:
    scheme_name: str | None = None
    if page_id:
        for entry in load_catalog():
            if entry.role == "ingest" and entry.page_id == page_id:
                scheme_name = entry.scheme_name
                break
    for entry in load_catalog():
        if entry.role == "reference" and entry.use == use:
            if scheme_name is None or entry.scheme_name == scheme_name:
                return entry.url
    return _url_for_page("amc")


def _generate(question: str, hits: list[Hit], settings: Settings) -> str | None:
    if not settings.groq_api_key or not settings.groq_model:
        return None
    try:
        from groq import Groq

        client = Groq(api_key=settings.groq_api_key)
        response = client.chat.completions.create(
            model=settings.groq_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "Question: "
                    + question
                    + "\n\nSource text:\n"
                    + "\n\n".join(hit.text for hit in hits),
                },
            ],
            temperature=0,
        )
        content = response.choices[0].message.content or ""
    except Exception:
        return None
    return content


def _limit(text: str) -> str:
    text = URL_PATTERN.sub("", text)
    text = re.sub(r"\[([^\]]*)\]\(\s*\)", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return " ".join(SENTENCE_SPLIT.split(text)[:3]).strip()


def _payload(text: str, url: str, fetched_on: str) -> dict[str, str]:
    return {
        "text": f"{text}\nLast updated from sources: {fetched_on or 'unknown'}",
        "url": url,
        "fetched_on": fetched_on,
    }
