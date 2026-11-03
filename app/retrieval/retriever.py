"""Retrieval: filter by access, region and date FIRST, then rank, then trim to the budget.

The access filter runs before any ranking, so a document the requester may not read is
never a candidate and can never reach the LLM. Removing it afterwards would not be safe.

The result is limited to a corpus-token budget (default 2,800, safely under the brief's
3,000), measured on the exact text that will be placed in the prompt.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import List, Optional, Sequence

from app.data.models import Employee
from app.ingestion.models import Chunk
from app.retrieval.bm25 import BM25, tokenize
from app.retrieval.eligibility import is_eligible, is_upcoming
from app.tokens import count_tokens

DEFAULT_BUDGET_TOKENS = 2800   # the hard limit is 3,000 tokens of corpus text per LLM call
DEFAULT_TOP_K = 12


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    score: float
    status: str     # "applicable" (in force) | "upcoming" (effective after the reference date)


def render_chunk(item: RetrievedChunk) -> str:
    """The exact text of one passage as it appears in a prompt."""
    meta = item.chunk.meta
    label = f"[{meta.doc_id} | {item.chunk.locator} | {meta.doc_type} | effective {meta.effective_date}"
    if item.status == "upcoming":
        label += " | NOT YET IN FORCE"
    return f"{label}]\n{item.chunk.text}"


def render_chunks(items: Sequence[RetrievedChunk]) -> str:
    return "\n\n".join(render_chunk(i) for i in items)


@dataclass
class RetrievalResult:
    items: List[RetrievedChunk]
    corpus_tokens: int       # tokens of corpus text this result puts in a prompt

    def prompt_text(self) -> str:
        return render_chunks(self.items)

    @property
    def applicable(self) -> List[RetrievedChunk]:
        return [i for i in self.items if i.status == "applicable"]

    @property
    def upcoming(self) -> List[RetrievedChunk]:
        return [i for i in self.items if i.status == "upcoming"]


class Retriever:
    def __init__(self, chunks: Sequence[Chunk]):
        self._chunks = list(chunks)
        # Title and heading are indexed with the text, so "sick leave" finds a "7. Sick leave" section.
        self._bm25 = BM25([
            tokenize(f"{c.meta.title} {c.locator} {c.text}") for c in self._chunks
        ])

    def retrieve(
        self,
        query: str,
        requester: Employee,
        reference_date: date,
        budget_tokens: int = DEFAULT_BUDGET_TOKENS,
        top_k: int = DEFAULT_TOP_K,
        include_upcoming: bool = True,
        doc_types: Optional[Sequence[str]] = None,
    ) -> RetrievalResult:
        terms = tokenize(query)
        candidates = []
        for index, chunk in enumerate(self._chunks):
            if doc_types is not None and chunk.meta.doc_type not in doc_types:
                continue
            if is_eligible(chunk.meta, requester, reference_date):
                status = "applicable"
            elif include_upcoming and is_upcoming(chunk.meta, requester, reference_date):
                status = "upcoming"
            else:
                continue   # not readable, wrong region, or not a candidate: never scored
            score = self._bm25.score(terms, index)
            if score > 0:
                candidates.append((score, chunk.chunk_id, chunk, status))
        candidates.sort(key=lambda c: (-c[0], c[1]))

        chosen: List[RetrievedChunk] = []
        for score, _, chunk, status in candidates:
            if len(chosen) >= top_k:
                break
            trial = chosen + [RetrievedChunk(chunk, score, status)]
            if count_tokens(render_chunks(trial)) > budget_tokens:
                continue   # too big to fit; a smaller passage further down may still fit
            chosen = trial
        return RetrievalResult(items=chosen, corpus_tokens=count_tokens(render_chunks(chosen)))
