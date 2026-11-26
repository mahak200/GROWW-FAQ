# Product Requirements Document

## Mutual Fund FAQ Assistant (Facts-Only Q&A)

| Field | Value |
| --- | --- |
| Product | Groww Mutual Fund FAQ Assistant |
| Type | Working RAG prototype |
| Audience | Retail users comparing schemes; support and content teams |
| Status | Draft for implementation |
| Source brief | `Doc/ProblemStatement.txt` |

## 1. Problem

Retail users and support teams repeatedly ask the same factual questions about mutual fund schemes: expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, benchmark, and how to download statements. Answers today are scattered across public pages, and a general chatbot is likely to add opinion, performance claims, or unsourced numbers.

This prototype answers those facts from a small, explicit corpus of official public pages. Every answer cites one source. Opinionated or portfolio questions are refused. The system is a demonstration of retrieval-augmented generation, so each pipeline stage stores its output and can be inspected.

## 2. Goals

1. Answer factual questions about the scoped AMC and four schemes using only the approved public pages.
2. Attach exactly one citation link to every factual answer.
3. Refuse advice, opinions, and return comparisons with a short, polite, facts-only message and one relevant educational link.
4. Keep answers to three sentences or fewer, and stamp each answer with when the sources were last read.
5. Implement RAG in explicit phases so loading, chunking, embedding, storage, and retrieval can each be shown.

## 3. Non-goals

- Investment advice, buy/sell recommendations, or portfolio construction.
- Computing, ranking, or comparing returns or other performance metrics.
- Scraping pages linked from the five seed URLs. Only those five pages are ingested.
- Screenshots of the application back end, or citations to third-party blogs.
- Collecting or storing personal data: PAN, Aadhaar, account numbers, OTPs, email addresses, or phone numbers.
- A production support tool, authentication, or multi-AMC coverage beyond this brief.

## 4. Users

| User | Need |
| --- | --- |
| Retail investor | Look up a scheme fact while comparing options, without being told what to buy. |
| Support / content team | Reuse short, cited answers to repetitive mutual-fund questions. |
| Reviewer of this demo | See each RAG stage’s stored data and confirm citations come from the corpus. |

## 5. Scope

### 5.1 Corpus

Ingest only these five public pages. Do not follow links on them.

| # | Page | URL |
| --- | --- | --- |
| 1 | AMC overview — Aditya Birla Sun Life AMC Ltd | https://groww.in/stocks/aditya-birla-sun-life-amc-ltd |
| 2 | Large Cap — Aditya Birla Sun Life Large Cap Fund Direct Growth | https://groww.in/mutual-funds/aditya-birla-sun-life-large-cap-direct-fund-growth |
| 3 | Flexi Cap — Aditya Birla Sun Life Flexi Cap Direct Plan Growth | https://groww.in/mutual-funds/birla-sun-life-equity-fund-direct-growth |
| 4 | ELSS — Aditya Birla Sun Life ELSS Tax Saver Fund Direct Plan Growth | https://groww.in/mutual-funds/aditya-birla-sun-life-elss-tax-saver-direct-growth |
| 5 | Mid Cap — Aditya Birla Sun Life Mid Cap Fund Direct Growth | https://groww.in/mutual-funds/birla-sun-life-mid-cap-fund-plan-a-direct-growth |

The submitted source list is 15–25 URLs. The five pages above are the only pages scraped into the knowledge base. Additional URLs in that list are citation or educational targets used in answers and refusals (for example an official factsheet, or a public page on statements or risk labels). They are not crawled as extra corpus pages.

### 5.2 Question types in scope

- Expense ratio of a named scheme.
- Exit load.
- Minimum SIP.
- ELSS lock-in.
- Riskometer and benchmark.
- How to download a capital-gains statement (procedure as stated on the official page, with a link).
- Other facts that appear on the five ingested pages.

### 5.3 Question types out of scope (refuse)

- “Should I buy or sell?”
- “Which fund is better?”
- “What returns will I get?” and any request to compute or compare performance.
- Requests that include or ask the assistant to store PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers.

If the user asks about returns or performance, do not calculate or compare. Point them to the official factsheet.

## 6. User experience

Tiny single-screen UI:

- A welcome line that names the assistant and the AMC in scope.
- Three example questions the user can click or send.
- A persistent note: **Facts-only. No investment advice.**
- A text input and a way to submit a question.
- The answer: at most three sentences, one citation link, and the line `Last updated from sources: <date>`.
- A refusal uses the same shape: a polite facts-only message, one relevant educational link, and the same disclaimer context already visible on the page.

No account, no history that stores personal data, and no back-end screenshots in the submission.

## 7. Answer contract

Every response follows one of two shapes.

**Factual answer**

1. State only the fact that was asked. If the page does not contain it, say so and do not invent a number.
2. At most three sentences.
3. Exactly one source link, pointing at the page the fact came from.
4. Closing line: `Last updated from sources: <YYYY-MM-DD>` using the date the corpus was last loaded.

**Refusal**

1. Polite, short, and free of advice.
2. State that the assistant answers facts only and does not recommend investments or compare performance.
3. Exactly one relevant educational link (official page, factsheet, or in-corpus page). Do not use a third-party blog.
4. Same length cap and last-updated line.

Personal data in the question is not stored. The assistant asks the user not to share it and does not echo it back.

## 8. RAG architecture

Each stage writes its output to disk (or to Chroma, for vectors) so the demo can show the pipeline, not only the final answer. Models and the vector database are read from configuration, not hard-coded in application logic. Secrets are read from a `.env` file and are never committed.

### Phase 1 — Data loading

- Fetch the five URLs in section 5.1 over HTTP.
- Store the raw fetch (URL, HTTP status, fetch timestamp, and page content) as an explicit artifact.
- Record the fetch date; answers use it as `Last updated from sources`.
- Fail clearly if a page cannot be fetched. Do not substitute a blog or a cached third-party copy.

### Phase 2 — Chunking

- Chunk from the loaded pages only.
- Choose the chunking strategy from the page structure (scheme fact blocks such as expense ratio, exit load, SIP, lock-in, riskometer, and benchmark should stay intact when the HTML allows it).
- Persist chunks with stable IDs, source URL, scheme or page name, and the text used for embedding.

### Phase 3 — Embedding

- Model: `sentence-transformers/all-MiniLM-L6-v2` (Hugging Face).
- The model name lives in the config file so it can be changed.
- The same model is used for ingestion and for query embedding.
- Persist embeddings with their chunk IDs.

### Phase 4 — Vector database

- Database: ChromaDB.
- The database choice and persistence path live in the config file so they can be changed.
- Collection metadata includes source URL, page title, scheme name, and chunk ID so a retrieved hit can be cited.

### Phase 5 — Retrieval and answer

- Embed the user question with `sentence-transformers/all-MiniLM-L6-v2`.
- Retrieve the nearest chunks from the same Chroma collection used at ingestion.
- Decide answer versus refuse before generating: identify the exact fact asked; refuse advice, portfolio, and performance questions.
- Generate with the Groq API.
- Model ID is taken from `.env` (the brief names `qwen/qwen3.8-27b`; use the ID in the demo `.env`, and confirm it against the current Groq model list).
- The API key is read only from `.env`. It is not written into source, the README, sample Q&A, or this PRD.
- The prompt instructs the model to stay inside retrieved text, stay within three sentences, emit one citation URL from the retrieved chunk’s source, and refuse when the question is advice or the fact is absent.

## 9. Configuration

| Setting | Requirement |
| --- | --- |
| Embedding model | Config file. Default `sentence-transformers/all-MiniLM-L6-v2`. |
| Vector database | Config file. Default ChromaDB, with a local persistence path. |
| LLM provider | Groq, via environment variable. |
| LLM model | `.env`. Brief value `qwen/qwen3.8-27b`, overridden by the demo `.env` if it differs. |
| API key | `.env` only. Never logged or committed. |
| Corpus URLs | Config or a checked-in source list limited to the five pages for ingestion. |
| Top-k and chunk size | Config file, with the chosen defaults documented in the README. |

## 10. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-1 | The loader fetches exactly the five URLs in section 5.1 and does not fetch linked pages. |
| FR-2 | Raw pages, chunks, and embeddings are stored as inspectable artifacts. Vectors live in Chroma. |
| FR-3 | A factual question about an in-scope scheme returns the fact, one citation, and the last-updated line. |
| FR-4 | Answers are at most three sentences. |
| FR-5 | If the fact is not in the retrieved chunks, the assistant says it does not have that fact. It does not guess. |
| FR-6 | Advice, buy/sell, and “which is better” questions return the refusal shape in section 7. |
| FR-7 | Performance and return questions are not calculated or compared. The reply links to the official factsheet. |
| FR-8 | Inputs that contain PAN, Aadhaar, account numbers, OTPs, emails, or phone numbers are not persisted. |
| FR-9 | The UI shows a welcome line, three example questions, and the note “Facts-only. No investment advice.” |
| FR-10 | Embedding model and vector database are changeable from the config file. LLM model and API key come from `.env`. |
| FR-11 | Query embedding uses the same model as ingestion, and retrieval uses the same Chroma collection. |

## 11. Deliverables

| Deliverable | Contents |
| --- | --- |
| Working prototype | Hosted app or notebook link, or a demo video of three minutes or less if hosting is not possible. |
| Source list | CSV or Markdown of the 15–25 URLs used, marking which five were ingested and which are citation or educational links only. |
| README | Setup steps, scope (AMC and schemes), config and `.env` variables, and known limits. |
| Sample Q&A | 5–10 queries with the assistant’s answers and links, covering both facts and at least one refusal. |
| Disclaimer | The exact UI snippet: facts-only, no investment advice. |
| Pipeline artifacts | Stored outputs for load, chunk, embed, and the Chroma collection, sufficient to walk through the demo. |

## 12. Acceptance criteria

- Asking for expense ratio, exit load, minimum SIP, ELSS lock-in, riskometer, or benchmark of an in-scope scheme returns a value present on the cited page, with that page’s URL.
- A statement-download question returns the documented steps (or states they are not on the page) and one official link.
- “Should I buy this fund?” and “Which of these has better returns?” are refused, with no recommendation and no computed return.
- A fact that is not on the five pages is not invented.
- Changing the embedding model name or the vector-database setting in config is the only edit required to point those components elsewhere.
- The repository contains no API key and no personal data.
- A reviewer can open the stored artifacts and see raw pages, chunks, and vectors separately from the final answer.

## 13. Known limits

- Coverage is one AMC (Aditya Birla Sun Life) and the four schemes listed above, plus the AMC overview page.
- Facts go stale when Groww updates a page. The last-updated line is the fetch date, not a live quote.
- The assistant does not interpret scheme suitability, tax situations beyond the published ELSS lock-in fact, or anything that requires an account login.
- Groq model availability can change; the running model is whatever `.env` sets.

## 14. Implementation order

1. Config and `.env.example` (no secrets), plus the five-URL source list.
2. Phase 1 data loading and stored raw pages.
3. Phase 2 chunking and stored chunks.
4. Phase 3 embeddings with `all-MiniLM-L6-v2`.
5. Phase 4 ChromaDB index.
6. Phase 5 retrieval, answer-versus-refuse logic, Groq generation, and citation formatting.
7. Tiny UI with welcome line, three examples, and the disclaimer.
8. README, source list (15–25 URLs), and sample Q&A file.
