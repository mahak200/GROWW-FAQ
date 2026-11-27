"""Guardrail regression tests. No live Groq calls."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import chromadb
import httpx
from fastapi.testclient import TestClient

from app.config import INGEST_IDS, ROOT, CatalogEntry, ingest_pages, load_catalog, load_settings
from app.ingest import chunk as chunk_module
from app.ingest import scrape as scrape_module
from app.query import answer as answer_module
from app.query.answer import answer
from app.query.gate import classify, scheme_id
from app.query.retrieve import RetrievalError, check_index, load_manifest, retrieve
from app.ui import server as server_module
from app.ui.server import app as ui_app

FACT_CASES = (
    ("Expense ratio of the Large Cap fund?", "large_cap"),
    ("Exit load of the Flexi Cap fund?", "flexi_cap"),
    ("Minimum SIP for the Mid Cap fund?", "mid_cap"),
    ("ELSS lock-in period?", "elss"),
    ("Riskometer and benchmark of the Large Cap fund?", "large_cap"),
)
REFUSAL_CASES = (
    ("Should I buy the ELSS fund?", "advice"),
    ("Which fund is better?", "advice"),
    ("What is better: ELSS or Flexi Cap?", "advice"),
    ("ELSS vs Flexi Cap", "advice"),
    ("Which fund has better returns?", "performance"),
    ("What is the expense ratio, and should I buy it?", "advice"),
    ("My PAN is ABCDE1234F, what should I do?", "pii"),
    ("Send it to test@example.com", "pii"),
    ("My phone is 9876543210", "pii"),
)


def page_url(page_id: str) -> str:
    return next(
        entry.url
        for entry in load_catalog()
        if entry.role == "ingest" and entry.page_id == page_id
    )


class GateTests(unittest.TestCase):
    def test_classification(self) -> None:
        for question, _ in FACT_CASES:
            with self.subTest(question=question):
                self.assertEqual(classify(question), "fact")
        for question, expected in REFUSAL_CASES:
            with self.subTest(question=question):
                self.assertEqual(classify(question), expected)

    def test_named_scheme(self) -> None:
        self.assertEqual(scheme_id("ELSS lock-in period?"), "elss")
        self.assertEqual(scheme_id("Expense ratio of HDFC Top 100?"), None)


class AnswerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = load_settings()
        self.manifest = load_manifest()
        groq_guard = patch.object(
            answer_module,
            "_generate",
            side_effect=AssertionError("Groq was called"),
        )
        groq_guard.start()
        self.addCleanup(groq_guard.stop)

    @staticmethod
    def first_line(payload: dict[str, str]) -> str:
        return payload["text"].splitlines()[0]

    def test_refusals_never_call_groq(self) -> None:
        for question, _ in REFUSAL_CASES:
            with self.subTest(question=question):
                payload = answer(question)
                self.assertIn("Last updated from sources:", payload["text"])
                self.assertTrue(payload["url"].startswith("https://"))
                self.assertFalse(any(character.isdigit() for character in self.first_line(payload)))
        pii = answer("My PAN is ABCDE1234F, what should I do?")
        for value in ("ABCDE1234F", "test@example.com", "9876543210"):
            self.assertNotIn(value, pii["text"])

    def test_refusal_links(self) -> None:
        self.assertIn("elss-tax-saver-direct-growth", answer("Should I buy the ELSS fund?")["url"])
        self.assertIn("factsheets", answer("Which fund has better returns?")["url"])
        self.assertEqual(page_url("amc"), answer("My PAN is ABCDE1234F, what should I do?")["url"])

    def test_fact_links_stay_in_named_scheme(self) -> None:
        for question, page_id in FACT_CASES:
            with self.subTest(question=question):
                hits = retrieve(question, self.settings, self.manifest)
                self.assertTrue(hits)
                self.assertTrue(all(hit.page_id == page_id for hit in hits))
                with patch.object(answer_module, "_generate", return_value="One fact. Another detail."):
                    payload = answer(question)
                self.assertEqual(page_url(page_id), payload["url"])
                self.assertEqual(payload["url"], hits[0].url)
                self.assertTrue(any(character.isdigit() for character in hits[0].text))

    def test_model_output_is_sanitized(self) -> None:
        output = "The expense ratio is 1.03%. Second. Third. Fourth. See https://example.com"
        with patch.object(answer_module, "_generate", return_value=output):
            payload = answer(FACT_CASES[0][0])
        body = self.first_line(payload)
        self.assertNotIn("example.com", body)
        self.assertLessEqual(len(re.split(r"(?<=[.!?])\s+", body)), 3)

    def test_absent_fact_uses_corpus_wording(self) -> None:
        with patch.object(answer_module, "_generate", return_value="NOT_IN_SOURCES"):
            payload = answer("Expense ratio of HDFC Top 100?")
        self.assertIn("not in this corpus", payload["text"])
        self.assertEqual(page_url("amc"), payload["url"])

    def test_statement_uses_official_link(self) -> None:
        question = "How do I download a capital gains statement?"
        self.assertEqual("fact", classify(question))
        with patch.object(answer_module, "_generate", return_value="Open the statements page and choose download."):
            payload = answer(question)
        self.assertIn("how-to-download-capital-gain-report", payload["url"])
        with patch.object(answer_module, "_generate", return_value="NOT_IN_SOURCES"):
            payload = answer(question)
        self.assertIn("how-to-download-capital-gain-report", payload["url"])
        self.assertIn("not in this corpus", payload["text"])

    def test_groq_failure_does_not_invent_fact(self) -> None:
        with patch.object(answer_module, "_generate", return_value=None):
            payload = answer(FACT_CASES[0][0])
        self.assertIn("could not be generated", self.first_line(payload))

    def test_index_errors(self) -> None:
        with self.assertRaises(RetrievalError):
            check_index(replace(self.settings, chroma_path=ROOT / "data" / "missing_chroma"), self.manifest)
        with self.assertRaises(RetrievalError):
            check_index(self.settings, {**self.manifest, "embedding_model": "other/model"})
        with patch.object(answer_module, "retrieve", side_effect=RetrievalError("Ingestion has not been run.")):
            payload = answer(FACT_CASES[0][0])
        self.assertIn("Ingestion has not been run", self.first_line(payload))


class IngestionTests(unittest.TestCase):
    def test_extra_ingest_row_rejected(self) -> None:
        entries = [
            CatalogEntry(role="ingest", title="page", url=f"https://example.com/{index}", page_id=f"page_{index}")
            for index in range(len(INGEST_IDS) + 1)
        ]
        with self.assertRaises(ValueError):
            ingest_pages(entries)

    def test_scrape_stops_on_non_200(self) -> None:
        page = CatalogEntry(
            role="ingest",
            title="page",
            url="https://example.com/page",
            page_id="amc",
        )
        response = httpx.Response(500, request=httpx.Request("GET", page.url))
        with (
            patch.object(scrape_module, "ingest_pages", return_value=[page]),
            patch.object(httpx.Client, "get", return_value=response),
        ):
            with self.assertRaises(SystemExit):
                scrape_module.scrape()

    def test_chunk_ids_stable_across_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data" / "raw").mkdir(parents=True)
            for page_id in INGEST_IDS:
                shutil.copyfile(
                    ROOT / "data" / "raw" / f"{page_id}.json",
                    root / "data" / "raw" / f"{page_id}.json",
                )
            with patch.object(chunk_module, "ROOT", root):
                chunk_module.chunk_pages()
                first = {
                    page_id: json.loads((root / "data" / "chunks" / f"{page_id}.json").read_text(encoding="utf-8"))
                    for page_id in INGEST_IDS
                }
                chunk_module.chunk_pages()
                second = {
                    page_id: json.loads((root / "data" / "chunks" / f"{page_id}.json").read_text(encoding="utf-8"))
                    for page_id in INGEST_IDS
                }
        self.assertEqual(first, second)
        for page_id in INGEST_IDS:
            expected = [f"{page_id}-{index}" for index in range(1, len(first[page_id]) + 1)]
            self.assertEqual([chunk["chunk_id"] for chunk in first[page_id]], expected)


class UiTests(unittest.TestCase):
    def test_page_contract(self) -> None:
        client = TestClient(ui_app)
        response = client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        html = response.text
        self.assertIn("Mutual fund facts for Aditya Birla Sun Life schemes.", html)
        self.assertIn("Facts-only. No investment advice.", html)
        self.assertEqual(html.count('class="example"'), 3)
        self.assertEqual(html.count("<a "), 1)
        self.assertIn("fetch('/ask'", html)
        self.assertIn("data.text", html)
        self.assertIn("data.url", html)
        self.assertIn("data.fetched_on", html)
        self.assertNotIn("chunk_id", html.lower())
        self.assertEqual(client.get("/docs").status_code, 404)

    def test_stitch_ui_contract(self) -> None:
        html = TestClient(ui_app).get("/").text
        for expected in (
            "Aditya Birla Fund Facts",
            "Approved Groww source pages",
            "Reading approved sources...",
            "Last updated from sources:",
            'id="answer-card-template"',
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, html)
        for forbidden in ("stockKnowledge", "Groww Live", "₹", "52-week", "arrow_drop_up"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, html)

    def test_ask_returns_answer_fields(self) -> None:
        payload = {
            "text": "The expense ratio is 1.03%.\nLast updated from sources: 2026-11-25",
            "url": page_url("large_cap"),
            "fetched_on": "2026-11-25",
        }
        question = "Expense ratio of the Large Cap fund?"
        with patch.object(server_module, "answer", return_value=payload) as mocked:
            response = TestClient(ui_app).post("/ask", json={"question": question})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), payload)
        mocked.assert_called_once_with(question)


class ArtifactTests(unittest.TestCase):
    def test_index_count_matches_chunks(self) -> None:
        settings = load_settings()
        count = sum(
            len(json.loads((ROOT / "data" / "chunks" / f"{page_id}.json").read_text(encoding="utf-8")))
            for page_id in INGEST_IDS
        )
        client = chromadb.PersistentClient(path=str(settings.chroma_path))
        collection = client.get_collection(name=settings.collection_name, embedding_function=None)
        self.assertEqual(collection.count(), count)

    def test_empty_question_rejected_by_ui(self) -> None:
        response = TestClient(ui_app).post("/ask", json={"question": "   "})
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
