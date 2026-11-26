"""Classify a question before any retrieval or generation."""

from __future__ import annotations

import re

PII_PATTERNS = (
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"),
    re.compile(r"\b\d{4}[\s-]?\d{4}[\s-]?\d{4}\b"),
    re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    re.compile(r"\b(?:\+91[\s-]?)?[6-9]\d{4}[\s-]?\d{5}\b"),
    re.compile(
        r"\b(?:pan(?:\s+card)?|aadhaar|account\s+number|bank\s+account|otp)\b",
        re.IGNORECASE,
    ),
)
ADVICE_PATTERNS = (
    re.compile(
        r"\b(?:buy|sell|should\s+i|shall\s+i|recommend(?:ation)?|portfolio)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bwhich\s+(?:fund|scheme|one)?\s*(?:is\s*)?better\b", re.IGNORECASE),
    re.compile(r"\b(?:what|which)\s+is\s+better\b", re.IGNORECASE),
    re.compile(r"\bbetter\s+(?:fund|scheme|investment)\b", re.IGNORECASE),
    re.compile(r"\bbetter\b\s*(?:[:,?]|$)", re.IGNORECASE),
    re.compile(r"\b(?:vs\.?|versus|compare|comparison|compared)\b", re.IGNORECASE),
)
PERFORMANCE_PATTERNS = (
    re.compile(
        r"\b(?:returns?|cagr|alpha|performance|perform(?:ed|s)?|growth\s+rate)\b",
        re.IGNORECASE,
    ),
)
SCHEME_PATTERNS = (
    ("large_cap", re.compile(r"\blarge[\s-]?cap\b", re.IGNORECASE)),
    ("flexi_cap", re.compile(r"\bflexi[\s-]?cap\b", re.IGNORECASE)),
    ("elss", re.compile(r"\b(?:elss|tax[\s-]?saver|tax[\s-]?saving)\b", re.IGNORECASE)),
    ("mid_cap", re.compile(r"\bmid[\s-]?cap\b", re.IGNORECASE)),
    ("amc", re.compile(r"\b(?:amc|aditya\s+birla\s+sun\s+life|birla\s+capital)\b", re.IGNORECASE)),
)
STATEMENT_PATTERN = re.compile(r"\b(?:statement|capital\s+gains?)\b", re.IGNORECASE)
WORD_PATTERN = re.compile(r"[a-z]+(?:[-'][a-z]+)?")
STOPWORDS = {
    "what", "which", "the", "of", "for", "is", "are", "do", "does", "how",
    "i", "my", "a", "an", "in", "on", "to", "and", "or", "with", "it",
}


def classify(question: str) -> str:
    """Return pii, advice, performance, or fact without calling a model."""
    if any(pattern.search(question) for pattern in PII_PATTERNS):
        return "pii"
    if any(pattern.search(question) for pattern in ADVICE_PATTERNS):
        return "advice"
    if any(pattern.search(question) for pattern in PERFORMANCE_PATTERNS):
        return "performance"
    return "fact"


def scheme_id(question: str) -> str | None:
    """Return the catalog page id named in the question, if any."""
    for page_id, pattern in SCHEME_PATTERNS:
        if pattern.search(question):
            return page_id
    return None


def is_statement(question: str) -> bool:
    return bool(STATEMENT_PATTERN.search(question))


def terms(question: str) -> set[str]:
    """Return content words used to keep lexically supported hits."""
    return {
        word
        for word in WORD_PATTERN.findall(question.lower())
        if len(word) > 2 and word not in STOPWORDS
    }
