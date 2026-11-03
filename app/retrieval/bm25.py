"""A small BM25 keyword ranker (no external dependency).

BM25 scores a passage by how many of the query's words it contains, giving more weight
to rare words and less to very long passages. A light stemmer makes "days" match "day".
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, List, Sequence

STOPWORDS = frozenset(
    "a an the of to in on at by for from with and or but if is are was were be been am do does did "
    "i me my we our you your it its this that these those what which who whom how many much can could "
    "should would will shall may might get got have has had there their them they as so than then "
    "about into per any some tell please".split()
)
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 5 and word.endswith("ing"):
        return word[:-3]
    if len(word) > 4 and word.endswith("ed"):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def tokenize(text: str) -> List[str]:
    return [stem(w) for w in _WORD.findall((text or "").lower()) if w not in STOPWORDS]


class BM25:
    def __init__(self, documents: Sequence[Sequence[str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.term_freqs: List[Counter] = [Counter(doc) for doc in documents]
        self.lengths = [len(doc) for doc in documents]
        self.count = len(documents)
        self.avg_length = (sum(self.lengths) / self.count) if self.count else 0.0
        doc_freq: Counter = Counter()
        for tf in self.term_freqs:
            doc_freq.update(tf.keys())
        self.idf: Dict[str, float] = {
            term: math.log(1 + (self.count - n + 0.5) / (n + 0.5)) for term, n in doc_freq.items()
        }

    def score(self, query_terms: Sequence[str], index: int) -> float:
        tf = self.term_freqs[index]
        length = self.lengths[index] or 1
        total = 0.0
        for term in set(query_terms):
            freq = tf.get(term, 0)
            if not freq:
                continue
            norm = freq + self.k1 * (1 - self.b + self.b * length / (self.avg_length or 1))
            total += self.idf.get(term, 0.0) * freq * (self.k1 + 1) / norm
        return total
