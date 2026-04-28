"""
ClimateRAG — DataStack

Provisions the S3 bucket that stores the FAISS vector index and chunk
metadata.  This stack is intentionally long-lived: it should rarely be
destroyed because rebuilding the FAISS index requires re-running the full
ingestion pipeline (ingest_gistemp.py / ingest_ghcn.py / ingest_power.py /
embeddings.py / build_index.py), which takes significant time and incurs
Bedrock Titan embedding costs.

Resources provisioned:
  - S3 bucket  (climate-rag-index-{account_id})
  - SSE-S3 encryption configuration
  - Public access block (all four settings enabled)
  - Lifecycle rule to transition old index versions to IA after 30 days

Exports (consumed by ComputeStack and AgentCoreStack):
  - index_bucket   (aws_s3.IBucket)   — passed directly as a construct ref
                                        so cross-stack wiring stays type-safe
"""

import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_s3 as s3,
    CfnOutput,
)
from constructs import Construct


class DataStack(Stack):
    """Long-lived S3 storage for the FAISS vector index."""

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── S3 Bucket ────────────────────────────────────────────
        # RemovalPolicy.RETAIN is deliberate: even if this stack is destroyed,
        # the bucket (and the FAISS index inside it) is preserved.  You must
        # manually empty and delete the bucket if you truly want it gone.
        #
        # For a clean full teardown run:
        #   aws s3 rb s3://climate-rag-index-<account_id> --force
        #   cdk destroy ClimateRagDataStack
        self.index_bucket = s3.Bucket(
            self,
            "IndexBucket",
            bucket_name=f"climate-rag-index-{self.account}",
            encryption=s3.BucketEncryption.S3_MANAGED,       # SSE-S3 (AES-256)
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=False,                                   # Index is rebuilt wholesale
            removal_policy=RemovalPolicy.RETAIN,               # ← Protect FAISS index
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="TransitionOldIndexToIA",
                    enabled=True,
                    prefix="index/",
                    transitions=[
                        s3.Transition(
                            storage_class=s3.StorageClass.INFREQUENT_ACCESS,
                            transition_after=cdk.Duration.days(30),
                        )
                    ],
                )
            ],
        )

        # ── Outputs ───────────────────────────────────────────────
        CfnOutput(
            self,
            "IndexBucketName",
            value=self.index_bucket.bucket_name,
            description="S3 bucket name for the FAISS vector index",
            export_name="ClimateRag-IndexBucketName",
        )

        CfnOutput(
            self,
            "IndexBucketArn",
            value=self.index_bucket.bucket_arn,
            description="S3 bucket ARN for the FAISS vector index",
            export_name="ClimateRag-IndexBucketArn",
        )
