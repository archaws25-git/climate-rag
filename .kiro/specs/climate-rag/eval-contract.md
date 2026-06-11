# Evaluation Contract: ClimateRAG

**Version:** 1.0
**Locked Date:** 2026-06-06
**Status:** Active — thresholds MUST NOT be lowered without domain justification

---

## Purpose

This document defines the formal evaluation specification for ClimateRAG.
It was written BEFORE the system was built to production quality and serves
as the immutable quality gate. Changes to this document require explicit
justification tied to domain requirements, not to system performance.

---

## 1. Retrieval Contract

### Thresholds

| Metric | Threshold | Justification |
|---|---|---|
| Recall@K | 0.9 | Missing relevant climate data leads researchers to wrong conclusions |
| Precision@K | 0.9 | Irrelevant data introduces noise in scientific analysis |
| MRR | 0.9 | Correct source MUST be the #1 result for citation reliability |
| NDCG@K | 0.9 | Ranking quality matters when researchers scan multiple results |

### Rationale

These thresholds are set at 90% because:
1. Scientific applications demand high fidelity — incorrect data leads to wrong research conclusions
2. NOAA researchers will lose trust if irrelevant stations appear in results
3. The corpus has ~340 chunks — at this scale, 90% retrieval is achievable with good embeddings
4. Lower thresholds would allow the system to return Southeast data for Alaska queries (unacceptable)

### Ground Truth Specification

Each retrieval query specifies:
- `expected_source`: The dataset that MUST appear (GHCN_v4, GISTEMP_v4, NASA_POWER)
- `expected_metadata_matches`: Metadata field values that define "relevant" (region, station_id, decade)
- `top_k_override` (optional): Per-query top_k when corpus has fewer relevant docs than default K

---

## 2. Generation Contract (LLM-as-Judge)

### Thresholds

| Dimension | Threshold (1-5) | Weight | Justification |
|---|---|---|---|
| Correctness | 4.5 | 30% | Hallucinated temperature values invalidate research findings |
| Source attribution | 4.5 | 20% | Every claim must trace to a retrievable document for verification |
| Relevance | 4.5 | 20% | Off-topic padding wastes researcher time and obscures findings |
| Confidence appropriate | 4.5 | 15% | Overconfident wrong answers are worse than honest uncertainty |
| Citation | 4.5 | 10% | Dataset name must be referenced for provenance |
| Tool use | 4.5 | 5% | Correct retrieval path validates system architecture |

### Composite Threshold: 0.9

### Rationale

- **Correctness at 4.5**: A single hallucinated temperature value in a research report could propagate through peer review. The system has "I don't know" fallback — fabrication is never justified.
- **Source attribution at 4.5**: NOAA researchers need `[SOURCE: Dataset | Station | Period]` format to cross-reference against original datasets. Uncited claims are scientifically useless.
- **Confidence at 4.5**: A system that says "the warming rate is exactly 0.52°C/decade" without qualifying data coverage is dangerous. Appropriate hedging is mandatory.

---

## 3. Multi-Turn Contract

### Thresholds

| Metric | Threshold | Justification |
|---|---|---|
| Per-turn correctness | 4.0/5 | Each individual answer must be accurate |
| Context resolution | 80% pass rate | "That station" / "same period" must resolve correctly |
| Session coherence | 4.0/5 | No contradictions between turns in same session |
| Progressive quality | Binary pass | More context should improve answers, not degrade them |

### Rationale

Multi-turn thresholds are slightly lower (4.0 vs 4.5) because:
1. Context resolution is inherently harder than single-turn retrieval
2. The agent uses in-process message history (not Memory) — context window limits apply
3. Real researcher sessions are forgiving of minor context misses if corrected on clarification

### Conversation Flows (5 required)

1. **Progressive Drill-Down**: Region → specific station → decade-by-decade data
2. **Comparison with Follow-Up**: Two cities → add third → plot all together
3. **Clarification and Correction**: Ambiguous query → temporal refinement → comparison
4. **Cross-Dataset Query**: GISTEMP global → NASA POWER regional → consistency check
5. **Memory Persistence**: State research topic → query data → summarize session

---

## 4. Contract Rules

1. **Thresholds are locked.** If the system doesn't meet them, fix the system — not the threshold.
2. **Ground truth is immutable per version.** If a query is wrong, create a new version of the contract.
3. **New queries can be ADDED** but existing queries cannot be modified or removed.
4. **Metric calculations must be unit-tested** with known inputs before running against the system.
5. **Results must be timestamped and persisted** for regression detection.
6. **Eval must run against LOCAL index** (not S3) to guarantee freshness.
