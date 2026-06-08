"""BM25 sparse search implementation for hybrid retrieval.

Provides keyword-based search alongside FAISS vector search.
BM25 excels at exact term matching (station names, region names, decades)
where embedding models may fail due to vocabulary gaps.
"""

import math
import re
from collections import Counter


class BM25Index:
    """Simple in-memory BM25 index for chunk text search.

    Parameters:
        k1: Term frequency saturation parameter (default 1.5)
        b: Document length normalization (default 0.75)
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.documents = []      # List of tokenized documents
        self.raw_texts = []      # Original text for each doc
        self.doc_count = 0
        self.avg_doc_len = 0.0
        self.doc_freqs = {}      # term -> number of docs containing it
        self.idf_cache = {}

    def add_documents(self, texts: list[str]):
        """Index a list of document texts."""
        self.raw_texts = texts
        self.documents = [self._tokenize(t) for t in texts]
        self.doc_count = len(self.documents)

        # Calculate average document length
        total_len = sum(len(doc) for doc in self.documents)
        self.avg_doc_len = total_len / self.doc_count if self.doc_count > 0 else 0

        # Calculate document frequencies
        self.doc_freqs = {}
        for doc in self.documents:
            unique_terms = set(doc)
            for term in unique_terms:
                self.doc_freqs[term] = self.doc_freqs.get(term, 0) + 1

        # Pre-compute IDF
        self.idf_cache = {}
        for term, df in self.doc_freqs.items():
            self.idf_cache[term] = math.log(
                (self.doc_count - df + 0.5) / (df + 0.5) + 1
            )

    def search(self, query: str, top_k: int = 10) -> list[tuple[int, float]]:
        """Search the index. Returns list of (doc_index, score) tuples."""
        query_terms = self._tokenize(query)

        scores = []
        for i, doc in enumerate(self.documents):
            score = self._score_document(query_terms, doc)
            if score > 0:
                scores.append((i, score))

        # Sort by score descending
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:top_k]

    def _score_document(self, query_terms: list[str], doc: list[str]) -> float:
        """Compute BM25 score for a document given query terms."""
        doc_len = len(doc)
        term_freqs = Counter(doc)
        score = 0.0

        for term in query_terms:
            if term not in self.idf_cache:
                continue

            tf = term_freqs.get(term, 0)
            idf = self.idf_cache[term]

            # BM25 TF component
            numerator = tf * (self.k1 + 1)
            denominator = tf + self.k1 * (
                1 - self.b + self.b * doc_len / self.avg_doc_len
            )
            score += idf * (numerator / denominator)

        return score

    def _tokenize(self, text: str) -> list[str]:
        """Simple whitespace + punctuation tokenizer with lowercasing."""
        # Remove punctuation, lowercase, split on whitespace
        text = re.sub(r"[^\w\s]", " ", text.lower())
        tokens = text.split()
        # Remove very short tokens (articles, prepositions)
        return [t for t in tokens if len(t) > 2]
