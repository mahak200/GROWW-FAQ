# Mutual Fund FAQ Assistant

Facts-only RAG prototype for Aditya Birla Sun Life AMC scheme questions. Answers are grounded in a small approved corpus, cite one source, and refuse advice/performance requests.

## Scope

- **AMC in scope**: Aditya Birla Sun Life AMC Ltd
- **Ingested scheme pages (5)**:
  - AMC overview: https://groww.in/stocks/aditya-birla-sun-life-amc-ltd
  - Large Cap Direct Growth: https://groww.in/mutual-funds/aditya-birla-sun-life-large-cap-direct-fund-growth
  - Flexi Cap Direct Growth: https://groww.in/mutual-funds/birla-sun-life-equity-fund-direct-growth
  - ELSS Tax Saver Direct Growth: https://groww.in/mutual-funds/aditya-birla-sun-life-elss-tax-saver-direct-growth
  - Mid Cap Direct Growth: https://groww.in/mutual-funds/birla-sun-life-mid-cap-fund-plan-a-direct-growth
- **Out of scope**: investment advice, buy/sell recommendations, fund comparisons, return/performance calculation, PII collection/storage.

## Setup

### 1. Create environment and install dependencies

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

### 2. Configure environment variables

Copy `.env.example` to `.env` and set values:

```env
GROQ_API_KEY=your_groq_api_key
GROQ_MODEL=qwen/qwen3.8-27b
```

- `GROQ_API_KEY`: required for LLM answer generation.
- `GROQ_MODEL`: Groq model ID used for generation.
- `.env` is ignored by git; never commit secrets.

### 3. Configuration

Main settings are in `config/settings.yaml`:

| Setting | Default | Purpose |
| --- | --- | --- |
| `embedding_model` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model for chunks and queries |
| `chroma_path` | `data/chroma` | Chroma persistence directory |
| `collection_name` | `mf_faq` | Chroma collection name |
| `chunk_max_chars` | `1200` | Max chunk size |
| `chunk_overlap_chars` | `150` | Overlap for long non-fact splits |
| `top_k` | `4` | Retrieved chunks returned |
| `max_distance` | `0.55` | Distance threshold for semantic hits |

The corpus/catalog is in `data/catalog.yaml`. Only `role: ingest` entries are scraped/indexed; `role: reference` entries are used for educational/factsheet/refusal links.

## Run the RAG pipeline

Run stages in order (or rerun after config/content changes):

```powershell
.\.venv\Scripts\python.exe -m app.ingest.scrape
.\.venv\Scripts\python.exe -m app.ingest.chunk
.\.venv\Scripts\python.exe -m app.ingest.embed
.\.venv\Scripts\python.exe -m app.ingest.index
```

Artifacts produced:

- `data/raw/` - fetched page HTML + metadata
- `data/chunks/` - chunked text with source metadata
- `data/embeddings/` - embedding vectors by chunk ID
- `data/chroma/` - Chroma vector index
- `data/manifest.json` - fetch date, page IDs, embedding/collection metadata

## Run the UI

```powershell
.\.venv\Scripts\python.exe -m app.ui.server
```

Open http://127.0.0.1:8000

UI behavior:
- Facts-only disclaimer: **Facts-only. No investment advice.**
- Max 3-sentence answers
- Exactly one citation link
- `Last updated from sources: <date>` line
- Advice/performance/PII requests are refused politely

## Deploy to Vercel

- The Vercel entrypoint is the root `index.py`; runtime dependencies are in `requirements.txt`, while `sentence-transformers` is only needed locally for ingestion (`requirements-dev.txt`).
- Commit the tracked artifacts `data/chroma/`, `data/manifest.json`, and `data/onnx_models/` so the deployed function can answer without rebuilding the index.
- Set project environment variables `GROQ_API_KEY` and `GROQ_MODEL`.
- Set `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` if your project is not already enrolled in Large Functions and the build reports a bundle-size error.
- `vercel.json` excludes `.venv`, tests, docs, and raw/chunk/embedding artifacts from the function bundle.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_guardrails
```

## Known limits

- Coverage limited to the 5 ingested Groww pages for one AMC.
- Facts can become stale; `Last updated from sources` reflects corpus fetch date.
- If a fact is not in retrieved corpus text, the assistant should say so rather than guess.
- Groq model availability depends on the configured `GROQ_MODEL`.
- Reference/factsheet URLs in catalog are citation targets only; they are not ingested.

## Disclaimer

Facts-only. No investment advice.