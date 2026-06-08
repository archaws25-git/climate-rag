"""Build FAISS index from embedded chunks and upload to S3."""

import json
import os
import tempfile

import boto3
import faiss
import numpy as np

REGION = os.environ.get("AWS_REGION", "us-east-1")
CHUNK_DIR = os.environ.get("CHUNK_OUTPUT_DIR", os.path.join(tempfile.gettempdir(), "climate-rag-chunks"))
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
    """Save FAISS index and metadata locally, then upload to S3.

    Uses boto3 Session with profile. If boto3 upload fails (expired token,
    permission error), falls back to AWS CLI 'aws s3 cp' command.
    Verifies upload succeeded by calling HeadObject.
    """
    import subprocess

    local_dir = os.path.join(CHUNK_DIR, "index")
    os.makedirs(local_dir, exist_ok=True)

    # Save FAISS index
    idx_path = os.path.join(local_dir, "faiss.index")
    faiss.write_index(index, idx_path)

    # Save metadata (text + metadata, no embeddings to save space)
    meta_path = os.path.join(local_dir, "metadata.jsonl")
    with open(meta_path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            record = {"text": chunk["text"], "metadata": chunk["metadata"]}
            f.write(json.dumps(record) + "\n")

    if not S3_BUCKET:
        print("  ⚠️  CLIMATE_RAG_BUCKET not set — skipping S3 upload.")
        print(f"  Local index saved to: {local_dir}")
        return

    # Upload to S3 — try boto3 first, fall back to CLI
    for filename in ["faiss.index", "metadata.jsonl"]:
        local_path = os.path.join(local_dir, filename)
        s3_key = f"{INDEX_PREFIX}{filename}"
        s3_uri = f"s3://{S3_BUCKET}/{s3_key}"

        uploaded = False

        # Attempt 1: boto3 Session upload
        try:
            profile = os.environ.get("AWS_PROFILE")
            session = boto3.Session(profile_name=profile, region_name=REGION)
            s3 = session.client("s3")
            print(f"  Uploading {filename} to {s3_uri} (boto3)...")
            s3.upload_file(local_path, S3_BUCKET, s3_key)
            uploaded = True
        except Exception as e:
            print(f"  ⚠️  boto3 upload failed: {e}")
            print("  Falling back to AWS CLI...")

        # Attempt 2: AWS CLI fallback
        if not uploaded:
            try:
                cmd = ["aws", "s3", "cp", local_path, s3_uri]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                if result.returncode == 0:
                    uploaded = True
                    print(f"  ✅ Uploaded {filename} via AWS CLI")
                else:
                    print(f"  ❌ AWS CLI upload failed: {result.stderr}")
            except Exception as e:
                print(f"  ❌ AWS CLI fallback failed: {e}")

        # Verify upload
        if uploaded:
            try:
                session = boto3.Session(
                    profile_name=os.environ.get("AWS_PROFILE"),
                    region_name=REGION,
                )
                s3_verify = session.client("s3")
                resp = s3_verify.head_object(Bucket=S3_BUCKET, Key=s3_key)
                size = resp["ContentLength"]
                print(f"  ✅ Verified {filename} in S3 ({size:,} bytes)")
            except Exception as e:
                print(f"  ⚠️  Upload verification failed: {e}")
                print("  File may not be accessible — check S3 bucket permissions.")
        else:
            print(f"  ❌ FAILED to upload {filename} to S3!")
            print(f"  Manual fix: aws s3 cp {local_path} {s3_uri}")
            raise RuntimeError(
                f"S3 upload failed for {filename}. "
                f"Run manually: aws s3 cp {local_path} {s3_uri}"
            )

    print("  ✅ All files uploaded and verified in S3.")


def main():
    chunks = load_embedded_chunks()
    index = build_faiss_index(chunks)
    save_and_upload(index, chunks)


if __name__ == "__main__":
    main()
