# Design notes

**Principle.** The language model understands and writes; plain code decides. Eligibility, precedence,
permissions, working days, balances and the confirmation step never depend on a prompt.

## 1. Ingestion: tables and the scanned document
`ingestion/pipeline.py::run_ingestion` reads `manifest.json` (authoritative for metadata) and parses each file
with `readers/` (PyMuPDF for PDF, python-docx, BeautifulSoup, Markdown). A bad file is reported and the rest load. **Tables** are detected (`page.find_tables()`, DOCX/HTML/MD tables) and each row
becomes one self-describing line, "Header: value; Header: value", so a retrieved row still says what its numbers
mean. Tables that only repeat metadata (Document ID, Version...) and repeated page headers/footers are dropped;
HTML hidden elements, comments, navigation and footers are dropped (a place where injected text hides).
**Scanned document:** `pdf_reader.py` takes the text layer first; a page with fewer than 20 characters is
rendered at 200 dpi and read by Tesseract (`ocr.py`, a subprocess; the Docker image installs it). **Holidays:** `holidays.py` reads dates and names from `calendar` documents'
tables into a `holidays` table (public vs restricted), re-created at every start.

## 2. Chunking and retrieval
Chunks follow headings (at most 350 tokens; long sections split by sentence); every chunk starts with its heading,
and the locator is that heading, or `p. N` for headingless documents. Retrieval is **filter, then
rank, then trim**: `retrieval/eligibility.py` removes any chunk the requester's role, region or reference date excludes
*before* BM25 (`retriever.py`, hand-written, light stemmer) scores anything, so an unreadable document is never a candidate.
Documents effective after the reference date are kept as "upcoming" candidates only when readable and regional. The result is
trimmed to 2,800 tokens, counted with tiktoken `cl100k_base` on the exact rendered prompt text. BM25 was chosen over
embeddings for determinism, no start-up dependency on an API (so `/health` cannot fail because of one), and a corpus of
only 146 chunks; the planner adds synonyms to the query to compensate.

## 3. Section 5 rules in code
Three model calls: (1) `planner.py` turns the message into intent and slots (no corpus text); (2)
`rag/answering.py::extract_claims` reads the passages and returns claims `{rule, value, doc_id, locator}`; claims
naming a document that was not retrieved are discarded; (3) a writer turns the *resolved facts* into prose.
`rag/resolver.py` decides: for each rule, `pick_winners` applies authority (`_authority`), then scope (`_scope`), then
recency (`_recency`), each keeping only the best; distinct values left over are a **conflict** (both values, both cited).
An **upcoming change** is checked by re-running the same resolution as of the future document's effective date and is
mentioned only if that document wins and its value differs. For a past question, later documents are not retrieved at all.
`citations_for` builds citations from the winning claims, so exactly the documents used are cited. No eligible claim gives
`no_answer`. Equal values written differently are normalised before comparing.

## 4. Where access control is enforced
- **Identity:** `main.py::chat` loads the requester from the header via `repository.get_employee`; unknown is 401;
  `orchestrator/session.py::SessionStore.claim` returns 403 when a session belongs to another employee.
- **Documents:** `retrieval/eligibility.py::can_read / is_eligible / is_upcoming`, called from `Retriever.retrieve` before scoring;
  `answering.extract_claims` drops claims about documents that were not retrieved. Nothing that is filtered out reaches an LLM
  (a test inspects every prompt sent).
- **Leave data:** `tools/permissions.py::can_view_employee`, called inside `tools/leave_read.py` (`get_leave_balance`,
  `list_leave_requests`); `get_team_leave` checks `is_manager` and queries only the requester's direct reports;
  `apply_leave` / `cancel_leave` use only `ctx.requester` (`leave_apply.py`, `leave_cancel.py`); a request that belongs to someone
  else is reported as not found. The requester is built from the header and database, never from model output.
- **Refusal text** is one constant (`tools/results.py::FORBIDDEN_EMPLOYEE_MESSAGE`), identical for real, unknown and misspelt
  targets. Names are resolved only among employees the requester may view. Bulk requests are refused by the planner's
  `bulk_request` intent and no tool returns many employees except `get_team_leave`.
- **Writes:** `engine.py::_propose_apply` / `_propose_cancel` run a no-write dry run, store one pending proposal per session, and
  `_execute_pending` runs only after a clear confirmation in the same session; any other message discards the proposal.
  The tool re-checks every rule inside its database transaction (`BEGIN IMMEDIATE`).
- **Token limit:** `llm/client.py::check_corpus_budget` counts the corpus text of every call and refuses more than 3,000.

## 5. Personal data
Logs contain employee IDs only: user messages and answers are not logged, and `privacy.py::PersonalDataFilter` masks any
email or phone in every log record. `Employee` hides name, email and phone from `repr`. Answers pass through
`privacy.sanitize` (emails become `r***@domain`; phone numbers are removed). The model sees: the user's own message (needed to
understand it), the requester's role, and database results as employee IDs without names; names of permitted employees are put
back by code after the model has written the answer. The system prompts contain no corpus text. `tool_calls` args hold IDs and dates only.

## 6. Failure modes found
Fixed: hidden/commented HTML text (injection carrier) is dropped at parse time; an outdated FAQ that contradicts the policy (authority
rule); the same fact worded differently producing a false conflict (canonical values, normalisation); a heading separated from its answer
in HTML (whitespace collapsed before chunking); PyMuPDF 2.x pulling in `onnxruntime` (pinned `<2`); the tiktoken vocabulary download being
blocked (vendored); a model outage turning into a 500 (now a polite answer); a slow provider breaking the 30-second limit (one deadline per request, shared by all calls).
**Not fixed:** keyword retrieval misses paraphrases with no shared words; inconsistent rule names from the model; OCR errors; sessions lost on restart;
the choice of holiday calendar is an assumption; non-OpenAI providers are untested against live APIs.

## 7. What breaks first with 10,000 documents
Start-up ingestion is sequential and in memory: 30 documents take about 4 s, so 10,000 would take over 20 minutes and miss the 10-minute health
window, and the BM25 index would be rebuilt at every start and scanned linearly per query. Fix: parse in parallel, persist chunks and the index keyed by
file hash (re-ingest only changes), serve readiness per batch; use an inverted index or a vector store (FAISS/Qdrant) with metadata filters
(role, region, date) applied inside the query, plus a reranker. Sessions move to Redis and SQLite to Postgres.
