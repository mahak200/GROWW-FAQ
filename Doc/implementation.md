# Implementation

Build the FAQ assistant in this order. Each stage writes its own files. Do not fetch links inside the five pages. Do not call Groq while scraping or indexing.

`Doc/architecture.md` and this file are the main source of truth for the prototype. The UI is built from `stitch_aditya_birla_stock_assistant.zip`, a Google Stitch export containing `code.html`, `DESIGN.md`, and `screen.png`. It is a design input only: take its tokens and component structure, then wire the page to this app's facts-only contract in section 7. Do not copy its mock stock prices, tickers, or `stockKnowledge` table into the app.

## 1. Directory structure

```text
stitch_aditya_birla_stock_assistant.zip   # design input, not served or parsed at runtime
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
4. **Generate.** Call Groq only when the gate says fact and at least one hit remains.
   - Build the prompt context with `_ground_text`: for the asked fact labels, take line windows around each label (two lines before, four lines after). Skip windows containing definition markers such as `a fee payable` and windows with no value. Peer-fund comparison tables are not included because they are outside those windows.
   - Send that context only, not URLs. Temperature 0. At most 3 sentences. If the fact is not in the text, the model replies `NOT_IN_SOURCES`.
   - Run `_supported` on the generated text: every number in the reply must appear in the supplied context. If any number is missing, return `FAILURE_TEXT` with the source URL. Do not show a figure the retrieved text does not contain.
5. **Attach the link in code**, not from the model.
   - Fact: first hit’s `url`.
   - Fact missing: that scheme’s page, or the AMC page.
   - Advice: that scheme’s page, or the AMC page.
   - Performance: catalog factsheet for that scheme, or the AMC page.
   - Personal data: AMC page.
6. Add `Last updated from sources: {fetched_on}`.

If Groq fails, say an answer could not be generated. Do not fill in a number.

## 7. UI (Stitch-derived)

`python -m app.ui.server` serves one Jinja2 page on `127.0.0.1:8000`. The page lives in `app/ui/templates/index.html`; the server supplies `EXAMPLES` and calls `answer()`. No new runtime dependency is required beyond the existing FastAPI, Jinja2, and uvicorn stack; fonts and Tailwind are loaded by the browser from the same CDN links used in the Stitch export.

### 7.1 Port from the Stitch export

1. Unzip `stitch_aditya_birla_stock_assistant.zip`. Read `code.html` for structure and `DESIGN.md` for tokens. `screen.png` is a visual reference only.
2. Keep the Stitch Tailwind config in the template head: the full `colors`, `spacing`, `borderRadius`, `fontFamily`, and `fontSize` token sets. Keep the Inter and Material Symbols font links and the `@layer base` rules for `pb-safe`, `pt-safe`, and hidden scrollbars.
3. Keep these structures from `code.html`: fixed 480px header, mobile-first `<main>`, welcome banner, suggested-question grid, horizontally scrollable pill rail, chat feed with user and assistant bubbles, typing indicator, fixed bottom composer, and the New chat control.
4. Rebind content to the corpus:
   - Header title becomes `Aditya Birla Fund Facts`; subtitle names Aditya Birla Sun Life as the only AMC. Remove the profile avatar because there is no account.
   - Welcome heading is exactly `Mutual fund facts for Aditya Birla Sun Life schemes.` The feed label is `Approved Groww source pages`, not a live market feed.
   - Suggestions render from `{% for example in examples %}` with `data-query="{{ example }}"` and `class="example"`. The three values come from server `EXAMPLES`: Large Cap expense ratio, ELSS lock-in, Mid Cap minimum SIP.
   - The pill rail lists the five ingested pages as static labels, not as stock tickers and not as fetch triggers.
   - The empty state explains that each reply has one source link and a last-updated line, and that advice/returns questions are refused.
5. Delete the export's sample messages, the `stockKnowledge` object, `resolveStockQuery`, price cards, P/E and market-cap grids, `+/-%` badges, `Groww Live` badges, `Source: Groww` text, and buy/sell CTA styling. Those values are mock data and conflict with the no-performance-claims rule.
6. Build answer cards from a single `<template id="answer-card-template">`. Clone it per reply and set fields with `textContent`, not `innerHTML`, for user and answer text. The template owns the only source anchor.
7. Add the request flow in section 7.2 and the guardrails in section 8.

### 7.2 Request and render flow

1. Submit or suggestion click calls `ask(question)`. Trim the value; if it is empty, return without a request.
2. Append the user bubble, clear the input, disable input, submit, and examples, and show the typing indicator.
3. `POST /ask` with `{"question": "<trimmed question>"}` using `Content-Type: application/json`. The server validates the field and returns `answer()`'s `text`, `url`, and `fetched_on`.
4. On success, strip the trailing `Last updated from sources: ...` from `text`, put the remainder in `.answer-text`, and render the date from `fetched_on` in `.updated`. There is one source link per reply, shown only when `url` starts with `https://`.
5. On non-2xx or network error, append a fixed error card. Do not render a partial answer or a link.
6. Hide the typing indicator and re-enable controls in `finally`. New chat clears the client thread and restores the empty state.

The server keeps no transcript, and the page posts nothing but the one question. No chunk IDs, distances, vectors, or other debug data appear in the page.

### 7.3 Deliberate differences from the export

| Stitch export | Served app |
| --- | --- |
| Live price and 52-week-high cards | One cited fact from the five-page corpus |
| `Groww Live` and a market timestamp | `Last updated from sources: <manifest fetch date>` |
| Six stock tickers in the pill rail | Five ingested Groww page labels |
| Mock `stockKnowledge` answers | `POST /ask` to `answer()` |
| `Fetching Groww data...` typing label | `Reading approved sources...` |
| Buy/sell CTA tokens | Not used; the assistant never recommends a trade |

Verify with `python -m unittest tests.test_guardrails.UiTests`. The page-contract test checks the welcome line, the exact disclaimer, three `class="example"` buttons, one `<a ` element, the `fetch('/ask'` call, the three consumed response fields, no chunk debug output, `Cache-Control: no-store`, and a 404 for `/docs`.

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
| Definition value used | Answer quotes an `Understand terms` example (for example `1% within 90 days` as a universal rule) | Only the scheme's own fact window is sent; definitions are dropped |
| Wrong number | Generated figure is absent from the supplied window | `FAILURE_TEXT`, no invented figure in the UI |
| Model types a URL | Groq output contains a link | Link removed. The shown URL is chunk metadata |
| Stitch mock data | `stockKnowledge`, a ticker, or a price card in the page | Not served. Only corpus-backed facts appear |
| Live feed claim | `live`, `real-time`, or `Groww Live` copy in the page | Not served. Only the manifest fetch date appears |
| Client error | `/ask` returns non-2xx or the request fails | Fixed error card, no partial answer and no link |
| New chat | User clears the thread | Client DOM only; no server call and no stored history |

Also check:

- Scraper issues exactly five GETs.
- Chunk ids are stable across two runs.
- Collection count equals the number of chunks, and a second index run does not double it.
- A fact answer’s number appears in the chunk for the URL shown.
- The repo contains no API key. `GROQ_API_KEY` in `.env.example` is empty.
- The served template matches section 6.2 of `Doc/architecture.md` and contains no hard-coded scheme facts or prices.
