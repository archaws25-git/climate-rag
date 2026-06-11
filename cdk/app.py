#!/usr/bin/env python3
"""
ClimateRAG CDK Application Entry Point.

Deploys three independent stacks that can be deployed or destroyed
separately to protect long-lived resources (e.g. the FAISS index in S3)
from accidental deletion during iterative development.

Deploy order:  DataStack → ComputeStack → AgentCoreStack
Destroy order: AgentCoreStack → ComputeStack → DataStack

Usage:
    cdk deploy --all                          # Deploy all stacks
    cdk deploy ClimateRagAgentCoreStack       # Deploy only AgentCore resources
    cdk destroy ClimateRagAgentCoreStack      # Tear down only AgentCore resources
    cdk destroy --all                         # Tear down everything (be careful!)
"""

import aws_cdk as cdk
from stacks.data_stack import DataStack
from stacks.compute_stack import ComputeStack
from stacks.agentcore_stack import AgentCoreStack

app = cdk.App()

env = cdk.Environment(region="us-east-1")

# ── Stack 1: Data ────────────────────────────────────────────────
# S3 bucket for the FAISS index.  Deployed once; rarely destroyed.
data_stack = DataStack(
    app,
    "ClimateRagDataStack",
    env=env,
    description="ClimateRAG — S3 bucket for FAISS vector index (long-lived)",
)

# ── Stack 2: Compute ─────────────────────────────────────────────
# IAM roles + Lambda proxy functions.
# Depends on DataStack only for the bucket name/ARN export.
compute_stack = ComputeStack(
    app,
    "ClimateRagComputeStack",
    bucket=data_stack.index_bucket,
    env=env,
    description="ClimateRAG — IAM roles and Lambda proxy functions",
)
compute_stack.add_dependency(data_stack)

# ── Stack 3: AgentCore ───────────────────────────────────────────
# AgentCore Memory, Code Interpreter, and Gateway (+ targets).
# Safe to destroy and redeploy independently while keeping S3/Lambda intact.
agentcore_stack = AgentCoreStack(
    app,
    "ClimateRagAgentCoreStack",
    nasa_lambda=compute_stack.nasa_lambda,
    noaa_lambda=compute_stack.noaa_lambda,
    gateway_role=compute_stack.gateway_role,
    env=env,
    description="ClimateRAG — AgentCore Memory, Code Interpreter, and Gateway",
)
agentcore_stack.add_dependency(compute_stack)

app.synth()
