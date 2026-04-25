"""RAG tool — FAISS vector search over climate data chunks stored in S3."""

import json
import os
import tempfile

import boto3
import faiss
import numpy as np
from strands import tool

S3_BUCKET = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
INDEX_PREFIX = "index/"
BEDROCK_REGION = os.environ.get("AWS_REGION", "us-east-1")

_index = None
_metadata = None


def _get_bedrock_client():
    return boto3.client("bedrock-runtime", region_name=BEDROCK_REGION)


def _embed_query(text: str) -> np.ndarray:
    client = _get_bedrock_client()
    resp = client.invoke_model(
        modelId="amazon.titan-embed-text-v2:0",
        body=json.dumps({"inputText": text}),
    )
    vec = json.loads(resp["body"].read())["embedding"]
    return np.array(vec, dtype="float32").reshape(1, -1)


def _load_index():
    global _index, _metadata
    if _index is not None:
        return

    s3 = boto3.client("s3", region_name=BEDROCK_REGION)
    tmpdir = tempfile.mkdtemp()

    idx_path = os.path.join(tmpdir, "faiss.index")
    meta_path = os.path.join(tmpdir, "metadata.jsonl")

    s3.download_file(S3_BUCKET, f"{INDEX_PREFIX}faiss.index", idx_path)
    s3.download_file(S3_BUCKET, f"{INDEX_PREFIX}metadata.jsonl", meta_path)

    _index = faiss.read_index(idx_path)

    _metadata = []
    with open(meta_path) as f:
        for line in f:
            _metadata.append(json.loads(line))


@tool
def search_climate_data(query: str, top_k: int = 5) -> str:
    """Search the climate data vector store for relevant information.

    Args:
        query: Natural language query about climate data.
        top_k: Number of results to return (default 5).

    Returns:
        Relevant climate data chunks with metadata and relevance scores.
    """
    _load_index()
    embedding = _embed_query(query)
    faiss.normalize_L2(embedding)
    scores, indices = _index.search(embedding, top_k)

    results = []
    for i, idx in enumerate(indices[0]):
        if idx == -1:
            continue
        meta = _metadata[idx]
        results.append({
            "score": float(scores[0][i]),
            "text": meta["text"],
            "source": meta["metadata"].get("dataset", "unknown"),
            "region": meta["metadata"].get("region", ""),
            "decade": meta["metadata"].get("decade", ""),
            "station_id": meta["metadata"].get("station_id", ""),
            "time_range": meta["metadata"].get("time_range", ""),
        })

    return json.dumps(results, indent=2)
