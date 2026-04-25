# ClimateRAG — Security & Compliance Specification

**Date:** 2026-03-26 | **Version:** 1.0

---

## 1. Security Architecture

| Layer | Mechanism |
|---|---|
| Streamlit → AgentCore | IAM SigV4 via boto3 |
| AgentCore → Bedrock | IAM role attached to Runtime |
| AgentCore → S3 | Scoped IAM read-only permissions |
| Gateway → Lambda | IAM invocation role |
| Lambda → External APIs | HTTPS TLS 1.2+ (public APIs, no credentials) |
| Policy enforcement | Cedar deny-by-default on Gateway |
| Data at rest | S3 SSE-S3; CloudWatch default encryption |
| Data in transit | TLS 1.2+ on all connections |
| Agent isolation | microVM per session in AgentCore Runtime |

## 2. IAM Roles

### 2.1 AgentCore Runtime Role

```json
{
  "Effect": "Allow",
  "Action": [
    "bedrock:InvokeModel",
    "s3:GetObject",
    "bedrock-agentcore:*",
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ],
  "Resource": [
    "arn:aws:bedrock:us-east-1::foundation-model/*",
    "arn:aws:s3:::climate-rag-index-*/*",
    "arn:aws:bedrock-agentcore:us-east-1:*:*",
    "arn:aws:logs:us-east-1:*:*"
  ]
}
```

### 2.2 Lambda Execution Role

```json
{
  "Effect": "Allow",
  "Action": [
    "logs:CreateLogGroup",
    "logs:CreateLogStream",
    "logs:PutLogEvents"
  ],
  "Resource": "arn:aws:logs:us-east-1:*:*"
}
```

No additional permissions needed — Lambdas only make outbound HTTPS calls to public APIs.

## 3. Cedar Policy (Gateway)

```cedar
permit(
    principal,
    action == Action::"InvokeTool",
    resource
) when {
    resource.toolName in ["nasa_power_query", "noaa_ncei_query"]
};

forbid(
    principal,
    action == Action::"InvokeTool",
    resource
) when {
    resource.toolName not in ["nasa_power_query", "noaa_ncei_query"]
};
```

## 4. Data Classification

| Data | Classification | Handling |
|---|---|---|
| NOAA GHCN v4 | Public | No restrictions |
| NASA GISTEMP v4 | Public (NASA public domain) | No restrictions |
| NASA POWER | Public | No restrictions |
| Researcher queries | Internal | Stored in AgentCore Memory; encrypted at rest |
| Agent traces | Internal | CloudWatch with default encryption |

## 5. FedRAMP-High Gap Analysis

| Component | FedRAMP Status | Gap |
|---|---|---|
| AgentCore Runtime | GA — NOT FedRAMP-authorized | **GAP** |
| AgentCore Memory | GA — NOT FedRAMP-authorized | **GAP** |
| AgentCore Gateway | GA — NOT FedRAMP-authorized | **GAP** |
| Amazon Bedrock | Available in GovCloud (FedRAMP-High) | OK |
| S3 | FedRAMP-High authorized | OK |
| Lambda | FedRAMP-High authorized | OK |
| CloudWatch | FedRAMP-High authorized | OK |
| IAM | FedRAMP-High authorized | OK |

### Mitigation Plan

For production FedRAMP-High deployment:
1. Deploy agent logic on ECS Fargate in GovCloud
2. Use Bedrock APIs directly (not via AgentCore Runtime)
3. Replace AgentCore Memory with DynamoDB-backed session store
4. Replace AgentCore Gateway with API Gateway + Lambda
5. Use CloudWatch OTEL collector directly
6. Current AgentCore deployment serves as demo/showcase only

## 6. Network Security

- All components in us-east-1
- AgentCore Runtime: AWS-managed VPC (no customer VPC required)
- Lambda: default VPC with outbound internet for NASA/NOAA APIs
- S3: VPC endpoint recommended for production
- No inbound internet exposure except Streamlit UI
