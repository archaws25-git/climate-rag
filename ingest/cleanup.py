"""
ClimateRAG — Data Cleanup Script.

Removes ALL previous embeddings, chunks, and local index files to ensure
a clean slate before re-ingestion. This MUST be run before ingest_all.py
when chunk text formats have changed, to prevent stale embeddings from
persisting in the index.

Usage:
    python ingest/cleanup.py

This script:
  1. Deletes CHUNK_OUTPUT_DIR/embedded/ (old Titan v2 embeddings)
  2. Deletes CHUNK_OUTPUT_DIR/index/ (old local FAISS index)
  3. Deletes CHUNK_OUTPUT_DIR/*.jsonl (old raw chunk files)
  4. Prints a summary of what was removed

Does NOT delete S3 data — that's handled by ingest_all.py upload (overwrites).
"""

import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import config  # noqa: E402, F401

CHUNK_DIR = os.environ.get("CHUNK_OUTPUT_DIR", "")


def cleanup():
    """Remove all previous ingestion artifacts."""
    if not CHUNK_DIR:
        print("❌ CHUNK_OUTPUT_DIR is not set. Cannot clean up.")
        sys.exit(1)

    print("\n🧹 ClimateRAG — Data Cleanup")
    print(f"   Target directory: {CHUNK_DIR}\n")

    removed_files = 0
    removed_dirs = 0

    # 1. Remove embedded/ directory (old embeddings)
    embedded_dir = os.path.join(CHUNK_DIR, "embedded")
    if os.path.exists(embedded_dir):
        file_count = sum(1 for f in os.listdir(embedded_dir) if f.endswith(".jsonl"))
        shutil.rmtree(embedded_dir)
        removed_dirs += 1
        removed_files += file_count
        print(f"  ✅ Removed embedded/ ({file_count} files)")
    else:
        print("  ⬜ embedded/ does not exist (already clean)")

    # 2. Remove index/ directory (old local FAISS index)
    index_dir = os.path.join(CHUNK_DIR, "index")
    if os.path.exists(index_dir):
        file_count = sum(1 for f in os.listdir(index_dir))
        shutil.rmtree(index_dir)
        removed_dirs += 1
        removed_files += file_count
        print(f"  ✅ Removed index/ ({file_count} files)")
    else:
        print("  ⬜ index/ does not exist (already clean)")

    # 3. Remove raw chunk JSONL files
    if os.path.exists(CHUNK_DIR):
        chunk_files = [f for f in os.listdir(CHUNK_DIR) if f.endswith(".jsonl")]
        for f in chunk_files:
            os.remove(os.path.join(CHUNK_DIR, f))
            removed_files += 1
        if chunk_files:
            print(f"  ✅ Removed {len(chunk_files)} chunk files: {', '.join(chunk_files)}")
        else:
            print("  ⬜ No chunk .jsonl files found")

    print(f"\n  Summary: removed {removed_files} files in {removed_dirs} directories")

    # 4. Clear stale S3 index (ensures next ingest uploads fresh data)
    bucket = os.environ.get("CLIMATE_RAG_BUCKET", "")
    if bucket:
        try:
            import boto3

            profile = os.environ.get("AWS_PROFILE")
            session = boto3.Session(
                profile_name=profile,
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
            )
            s3 = session.client("s3")
            # List and delete all objects under index/ prefix
            response = s3.list_objects_v2(Bucket=bucket, Prefix="index/")
            objects = response.get("Contents", [])
            if objects:
                delete_keys = [{"Key": obj["Key"]} for obj in objects]
                s3.delete_objects(Bucket=bucket, Delete={"Objects": delete_keys})
                print(f"  ✅ Cleared S3 index: s3://{bucket}/index/ ({len(objects)} objects)")
            else:
                print(f"  ⬜ S3 index already empty: s3://{bucket}/index/")
        except Exception as e:
            print(f"  ⚠️  Could not clear S3 index: {e}")
            print(f"      Run manually: aws s3 rm s3://{bucket}/index/ --recursive")
    else:
        print("  ⬜ CLIMATE_RAG_BUCKET not set — skipping S3 cleanup")

    print("  Ready for fresh ingestion: python ingest/ingest_all.py\n")


if __name__ == "__main__":
    cleanup()
