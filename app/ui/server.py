"""Serve the single-page facts-only FAQ UI."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from app.query.answer import answer
from app.query.retrieve import load_manifest, check_index
from app.ingest.embed import load_model
from app.config import load_settings

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
EXAMPLES = (
    "What is the expense ratio of the Large Cap fund?",
    "What is the ELSS lock-in period?",
    "What is the minimum SIP for the Mid Cap fund?",
)

app = FastAPI(
    title="Mutual fund facts",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
NO_STORE = {"Cache-Control": "no-store"}


@app.on_event("startup")
def _warmup() -> None:
    """Preload embedding model and validate index to reduce first-request latency."""
    try:
        settings = load_settings()
        manifest = load_manifest()
        check_index(settings, manifest)
        load_model(settings.embedding_model)
    except Exception:
        # Keep server up; /ask returns explicit retrieval/generation errors.
        pass


class AskRequest(BaseModel):
    question: str


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    return TEMPLATES.TemplateResponse(
        request,
        "index.html",
        {"examples": EXAMPLES},
        headers=NO_STORE,
    )


@app.post("/ask")
def ask(payload: AskRequest) -> dict[str, str]:
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")
    return answer(question)


def serve() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    serve()
