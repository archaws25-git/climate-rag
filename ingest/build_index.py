"""Build FAISS index from embedded chunks and upload to S3."""

import json
import os

import boto3
import faiss
import numpy as np

REGION = os.environ.get("AWS_REGION", "us-east-1")
CHUNK_DIR = os.environ.get("CHUNK_OUTPUT_DIR", "/tmp/climate-rag-chunks")
S3_BUCKET = os.environ.get("CLIMATE_RAG_BUCKET", "climate-rag-index")
INDEX_PREFIX = "index/"


def load_embedded_chunks():
    """Load all embedded chunk files."""
    embedded_dir = os.path.join(CHUNK_DIR, "embedded")
    all_chunks = []

    for filename in sorted(os.listdir(embedded_dir)):
        if not filename.endswith(".jsonl"):
            continue
        path = os.path.join(embedded_dir, filename)
        with open(path) as f:
            for line in f:
                all_chunks.append(json.loads(line))

    print(f"Loaded {len(all_chunks)} embedded chunks")
    return all_chunks


def build_faiss_index(chunks):
    """Build a FAISS index from chunk embeddings."""
    embeddings = np.array([c["embedding"] for c in chunks], dtype="float32")
    faiss.normalize_L2(embeddings)  # For cosine similarity via inner product

    dim = embeddings.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(embeddings)

    print(f"Built FAISS index: {index.ntotal} vectors, {dim} dimensions")
    return index


def save_and_upload(index, chunks):
    """Save FAISS index and metadata locally, then upload to S3."""
    local_dir = os.path.join(CHUNK_DIR, "index")
    os.makedirs(local_dir, exist_ok=True)

    # Save FAISS index
    idx_path = os.path.join(local_dir, "faiss.index")
    faiss.write_index(index, idx_path)

    # Save metadata (text + metadata, no embeddings to save space)
    meta_path = os.path.join(local_dir, "metadata.jsonl")
    with open(meta_path, "w") as f:
        for chunk in chunks:
            record = {"text": chunk["text"], "metadata": chunk["metadata"]}
            f.write(json.dumps(record) + "\n")

    # Upload to S3
    s3 = boto3.client("s3", region_name=REGION)

    for filename in ["faiss.index", "metadata.jsonl"]:
        local_path = os.path.join(local_dir, filename)
        s3_key = f"{INDEX_PREFIX}{filename}"
        print(f"Uploading {filename} to s3://{S3_BUCKET}/{s3_key}...")
        s3.upload_file(local_path, S3_BUCKET, s3_key)

    print("Upload complete.")


def main():
    chunks = load_embedded_chunks()
    index = build_faiss_index(chunks)
    save_and_upload(index, chunks)


if __name__ == "__main__":
    main()
