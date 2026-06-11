"""Index versioning — S3 key with content hash and rollback capability.

Each index upload is versioned with a content hash. Previous versions
are retained in S3 for rollback. A 'current' pointer file indicates
which version is active.

S3 structure:
    s3://{bucket}/index/current.json        ← pointer to active version
    s3://{bucket}/index/v_{hash}/faiss.index
    s3://{bucket}/index/v_{hash}/metadata.jsonl
    s3://{bucket}/index/v_{hash}/manifest.json
"""

import hashlib
import json
import os
import time

import boto3

REGION = os.environ.get("AWS_REGION", "us-east-1")


def compute_index_hash(index_path: str, metadata_path: str) -> str:
    """Compute SHA256 hash of index + metadata for versioning."""
    hasher = hashlib.sha256()
    for path in [index_path, metadata_path]:
        with open(path, "rb") as f:
            while chunk := f.read(8192):
                hasher.update(chunk)
    return hasher.hexdigest()[:12]  # Short hash for readability


def upload_versioned_index(
    bucket: str,
    local_index_path: str,
    local_metadata_path: str,
    prefix: str = "index",
) -> str:
    """Upload index to S3 with version hash. Returns version ID.

    Also updates the 'current' pointer to the new version.
    Retains previous versions for rollback.
    """
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=REGION)
    s3 = session.client("s3")

    # Compute version hash
    version_hash = compute_index_hash(local_index_path, local_metadata_path)
    version_prefix = f"{prefix}/v_{version_hash}"

    # Upload index files
    s3.upload_file(local_index_path, bucket, f"{version_prefix}/faiss.index")
    s3.upload_file(local_metadata_path, bucket, f"{version_prefix}/metadata.jsonl")

    # Upload manifest
    manifest = {
        "version": version_hash,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "files": ["faiss.index", "metadata.jsonl"],
    }
    s3.put_object(
        Bucket=bucket,
        Key=f"{version_prefix}/manifest.json",
        Body=json.dumps(manifest, indent=2),
        ContentType="application/json",
    )

    # Update current pointer
    pointer = {"active_version": version_hash, "prefix": version_prefix}
    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/current.json",
        Body=json.dumps(pointer, indent=2),
        ContentType="application/json",
    )

    # Also upload to the flat path for backward compatibility
    s3.upload_file(local_index_path, bucket, f"{prefix}/faiss.index")
    s3.upload_file(local_metadata_path, bucket, f"{prefix}/metadata.jsonl")

    print(f"  Uploaded index version: v_{version_hash}")
    return version_hash


def rollback_index(bucket: str, version_hash: str, prefix: str = "index"):
    """Rollback to a previous index version.

    Copies the specified version's files to the active location.
    """
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=REGION)
    s3 = session.client("s3")

    version_prefix = f"{prefix}/v_{version_hash}"

    # Verify version exists
    try:
        s3.head_object(Bucket=bucket, Key=f"{version_prefix}/manifest.json")
    except Exception:
        raise ValueError(f"Version v_{version_hash} not found in s3://{bucket}/{prefix}/")

    # Copy to active location
    for filename in ["faiss.index", "metadata.jsonl"]:
        s3.copy_object(
            Bucket=bucket,
            Key=f"{prefix}/{filename}",
            CopySource={"Bucket": bucket, "Key": f"{version_prefix}/{filename}"},
        )

    # Update pointer
    pointer = {"active_version": version_hash, "prefix": version_prefix}
    s3.put_object(
        Bucket=bucket,
        Key=f"{prefix}/current.json",
        Body=json.dumps(pointer, indent=2),
        ContentType="application/json",
    )

    print(f"  Rolled back to version: v_{version_hash}")


def list_versions(bucket: str, prefix: str = "index") -> list[dict]:
    """List all available index versions."""
    profile = os.environ.get("AWS_PROFILE")
    session = boto3.Session(profile_name=profile, region_name=REGION)
    s3 = session.client("s3")

    versions = []
    response = s3.list_objects_v2(Bucket=bucket, Prefix=f"{prefix}/v_", Delimiter="/")
    for cp in response.get("CommonPrefixes", []):
        version_dir = cp["Prefix"]
        try:
            manifest_resp = s3.get_object(Bucket=bucket, Key=f"{version_dir}manifest.json")
            manifest = json.loads(manifest_resp["Body"].read())
            versions.append(manifest)
        except Exception:
            pass

    return sorted(versions, key=lambda x: x.get("timestamp", ""), reverse=True)
