"""Generate embeddings for climate data chunks using Amazon Titan Embeddings v2."""

import json
import os

import boto3
import numpy as np

REGION = os.environ.get("AWS_REGION", "us-east-1")
MODEL_ID = "amazon.titan-embed-text-v2:0"
CHUNK_DIR = os.environ.get("CHUNK_OUTPUT_DIR", "/tmp/climate-rag-chunks")


def get_embedding(client, text: str) -> list[float]:
    """Get embedding vector from Titan Embeddings v2."""
    resp = client.invoke_model(
        modelId=MODEL_ID,
        body=json.dumps({"inputText": text[:8000]}),  # Titan v2 limit
    )
    return json.loads(resp["body"].read())["embedding"]


def embed_chunks(input_path: str, output_path: str):
    """Read chunks from JSONL, generate embeddings, write to output JSONL."""
    client = boto3.client("bedrock-runtime", region_name=REGION)

    chunks = []
    with open(input_path) as f:
        for line in f:
            chunks.append(json.loads(line))

    print(f"Embedding {len(chunks)} chunks from {input_path}...")

    for i, chunk in enumerate(chunks):
        embedding = get_embedding(client, chunk["text"])
        chunk["embedding"] = embedding
        if (i + 1) % 10 == 0:
            print(f"  Embedded {i + 1}/{len(chunks)}")

    with open(output_path, "w") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk) + "\n")

    print(f"  Wrote {len(chunks)} embedded chunks → {output_path}")
    return chunks


def main():
    output_dir = os.path.join(CHUNK_DIR, "embedded")
    os.makedirs(output_dir, exist_ok=True)

    for filename in ["gistemp_chunks.jsonl", "ghcn_chunks.jsonl", "power_chunks.jsonl"]:
        input_path = os.path.join(CHUNK_DIR, filename)
        if not os.path.exists(input_path):
            print(f"Skipping {filename} — not found")
            continue
        output_path = os.path.join(output_dir, filename)
        embed_chunks(input_path, output_path)


if __name__ == "__main__":
    main()
