# Implementation

Build the FAQ assistant in this order. Each stage writes its own files. Do not fetch links inside the five pages. Do not call Groq while scraping or indexing.

## 1. Directory structure

```text
app/
  config.py
  ingest/
    scrape.py
    chunk.py
    embed.py
    index.py
  query/
    gate.py
    retrieve.py
    answer.py
  ui/
    server.py
    templates/index.html
config/settings.yaml
data/catalog.yaml
.env.example
requirements.txt
```

Created at runtime and gitignored:

```text
data/raw/<page_id>.json
data/chunks/<page_id>.json
data/embeddings/<page_id>.json
data/chroma/
data/manifest.json
```

`config/settings.yaml` holds the embedding model, Chroma path, collection name, chunk size, overlap, `top_k`, and distance cutoff. `.env` holds only `GROQ_API_KEY` and `GROQ_MODEL`. `.env.example` lists those names with a blank key.

`data/catalog.yaml` lists every URL used in the submission.

| role | Meaning |
| --- | --- |
| `ingest` | One of the five pages below. Scraped, chunked, embedded. |
| `reference` | Factsheet or educational link. Not scraped. Used only when refusing. |

Fixed `page_id` values for ingest rows: `amc`, `large_cap`, `flexi_cap`, `elss`, `mid_cap`.

## 2. Scraping

Scrape only these pages. Do not open links on them.

| page_id | URL |
| --- | --- |
| `amc` | https://groww.in/stocks/aditya-birla-sun-life-amc-ltd |
| `large_cap` | https://groww.in/mutual-funds/aditya-birla-sun-life-large-cap-direct-fund-growth |
| `flexi_cap` | https://groww.in/mutual-funds/birla-sun-life-equity-fund-direct-growth |
| `elss` | https://groww.in/mutual-funds/aditya-birla-sun-life-elss-tax-saver-direct-growth |
| `mid_cap` | https://groww.in/mutual-funds/birla-sun-life-mid-cap-fund-plan-a-direct-growth |

`python -m app.ingest.scrape`

1. Read catalog rows with `role: ingest`. Stop if that list is not exactly these five ids.
2. GET each URL once. Do not queue `href` values.
3. If a page is not HTTP 200, stop and print that URL. Do not replace it with another site.
4. On full success, write `data/raw/<page_id>.json` with `page_id`, `url`, `title`, `scheme_name`, `http_status`, `fetched_at`, and `html`.
5. Write `data/manifest.json` with `fetched_on` (`YYYY-MM-DD`), `page_ids`, `embedding_model: null`, and `collection_name: null`.

Answers later print `Last updated from sources:` using `fetched_on`.

## 3. Chunking

`python -m app.ingest.chunk`

Input is `data/raw/` only. Do not fetch again.

1. Parse HTML. Drop `script`, `style`, nav, header, and footer.
2. Split on headings and on fact labels: expense ratio, exit load, minimum SIP, lock-in, riskometer, benchmark, statement, download.
3. Keep each fact label and its value in the same chunk.
4. If a section is longer than `chunk_max_chars`, split on paragraph boundaries using `chunk_overlap_chars`. Do not split through a fact label.
5. Id chunks as `<page_id>-<n>` starting at 1.

Write `data/chunks/<page_id>.json` as a list of `chunk_id`, `page_id`, `url`, `title`, `scheme_name`, and `text`.

After the first run, check the ELSS and Large Cap files. Expense ratio, exit load, minimum SIP, lock-in, riskometer, and benchmark should each sit inside one chunk when the page contains them.

## 4. Embedding model

`python -m app.ingest.embed`

Model, from config: `sentence-transformers/all-MiniLM-L6-v2`.

1. Load that model once.
2. Embed each chunk’s `text` with normalized embeddings.
3. Write `data/embeddings/<page_id>.json` as `chunk_id` plus `vector`.
4. Set `manifest.embedding_model` to the config model name.

Query embedding must call this same function. Do not load a second model.

## 5. Vector DB

`python -m app.ingest.index`

ChromaDB, path and collection name from config. Cosine space. One collection.

For each chunk, upsert:

| Field | Value |
| --- | --- |
| id | `chunk_id` |
| document | chunk text |
| embedding | vector from the embedding file |
| metadata | `url`, `title`, `scheme_name`, `page_id` |

Re-running index replaces the collection. Set `manifest.collection_name`. If `manifest.embedding_model` does not match config, stop and re-run embed. Do not mix vectors from two models.

`python -m app.ingest.pipeline` runs scrape, chunk, embed, and index in that order.

## 6. Retrieval logic

`answer(question)` in `app/query/answer.py` does this in order.

1. **Gate.** Classify before retrieval and before Groq.
   - Personal data (PAN, Aadhaar, account number, OTP, email, phone) → refuse. Do not store or echo the value.
   - Buy, sell, “should I”, “which is better”, portfolio → refuse as advice.
   - Returns, CAGR, alpha, performance → refuse and point to the factsheet URL in the catalog. Do not calculate.
   - A question that mixes a fact with advice is advice.
   - Otherwise it is a fact question.
2. **Index check.** If Chroma is missing, or the manifest model or collection does not match config, return an error. Do not guess.
3. **Retrieve.** Embed the question with the ingest model. Query the same collection for `top_k`. Drop hits farther than `max_distance`.
4. **Generate.** Call Groq only when the gate says fact and at least one hit remains. Send chunk text only, not URLs. Temperature 0. At most 3 sentences. If the fact is not in the chunks, the model replies `NOT_IN_SOURCES`.
5. **Attach the link in code**, not from the model.
   - Fact: first hit’s `url`.
   - Fact missing: that scheme’s page, or the AMC page.
   - Advice: that scheme’s page, or the AMC page.
   - Performance: catalog factsheet for that scheme, or the AMC page.
   - Personal data: AMC page.
6. Add `Last updated from sources: {fetched_on}`.

If Groq fails, say an answer could not be generated. Do not fill in a number.

## 7. UI

`python -m app.ui.server` serves one page on `127.0.0.1:8000`.

- Welcome line: Mutual fund facts for Aditya Birla Sun Life schemes.
- Always visible: `Facts-only. No investment advice.`
- Three example buttons: expense ratio, ELSS lock-in, minimum SIP.
- One input and submit. `POST /ask` calls `answer()` and returns `text`, `url`, and `fetched_on`.
- Show the text, one link, and the last-updated line.

No login, no saved questions, and no chunk dump on the page. Reviewers look at `data/` for scrape, chunk, and embedding output.

## 8. Guardrails — edge cases and tests

The gate is code, not a prompt. Groq must not be called for a refusal. Patch the Groq client so a test fails if it is called.

| Case | Input | Expected |
| --- | --- | --- |
| Expense ratio | Expense ratio of the Large Cap fund? | Fact, Large Cap URL, number found in that page’s chunks |
| Exit load | Exit load of the Flexi Cap fund? | Fact, Flexi Cap URL |
| Minimum SIP | Minimum SIP for the Mid Cap fund? | Fact, Mid Cap URL |
| Lock-in | ELSS lock-in period? | Fact, ELSS URL |
| Risk and benchmark | Riskometer and benchmark of the Large Cap fund? | Fact, Large Cap URL |
| Statement | How do I download a capital gains statement? | Steps only if the pages say so, otherwise “not in this corpus”, one official link |
| Advice | Should I buy the ELSS fund? | Refusal, no recommendation, Groq not called |
| Comparison | Which fund is better? | Refusal, Groq not called |
| Returns | Which fund has better returns? | Refusal, factsheet link, no computed return, Groq not called |
| Mixed | What is the expense ratio, and should I buy it? | Treated as advice |
| PII | My PAN is ABCDE1234F, what should I do? | Refusal, value not stored and not repeated |
| Unknown scheme | Expense ratio of HDFC Top 100? | Absent, or a fact only if the five pages actually state it. No invented number |
| Empty | Blank question | UI does not call `/ask` |
| Missing index | Ask before ingest | Error: ingestion has not been run |
| Model mismatch | Change embedding model in config without re-indexing | Error: re-run ingestion |
| Scrape failure | One of the five URLs returns non-200 | Pipeline stops. No substitute page |
| Extra URL | Catalog has a sixth `ingest` row | Scraper refuses to run |
| Model types a URL | Groq output contains a link | Link removed. The shown URL is chunk metadata |

Also check:

- Scraper issues exactly five GETs.
- Chunk ids are stable across two runs.
- Collection count equals the number of chunks, and a second index run does not double it.
- A fact answer’s number appears in the chunk for the URL shown.
- The repo contains no API key. `GROQ_API_KEY` in `.env.example` is empty.
