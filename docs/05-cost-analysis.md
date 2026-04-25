# ClimateRAG — Cost Analysis

**Date:** 2026-03-26 | **Version:** 1.0

---

## 1. Pricing Model: ON DEMAND (Free-Tier Optimized)

All estimates assume us-east-1, demo/showcase workload (~100 queries/day).

## 2. Service-by-Service Breakdown

### 2.1 Amazon Bedrock — Titan Embeddings v2

| Item | Unit Price | Usage | Cost |
|---|---|---|---|
| Input tokens | $0.00002/1K tokens | ~5M tokens (ingestion) | $0.10 |
| Free tier | First 3 months free | Covers ingestion | $0.00 |

**Monthly cost after ingestion:** ~$0.02 (query-time embeddings)

### 2.2 Amazon Bedrock — Claude Sonnet

| Item | Unit Price | Usage | Cost |
|---|---|---|---|
| Input tokens | $0.003/1K tokens | ~500K tokens/day | ~$1.50/day |
| Output tokens | $0.015/1K tokens | ~100K tokens/day | ~$1.50/day |

**Monthly cost:** ~$90 (at 100 queries/day with ~5K input + 1K output tokens each)

### 2.3 AgentCore Runtime

| Item | Pricing | Usage | Cost |
|---|---|---|---|
| Compute | Consumption-based | ~100 invocations/day | See AgentCore pricing page |

**Note:** AgentCore Runtime pricing is consumption-based with no upfront fees. Exact per-invocation cost should be verified at `aws.amazon.com/bedrock/agentcore/pricing/`.

### 2.4 AgentCore Memory

| Item | Pricing | Usage | Cost |
|---|---|---|---|
| Storage + operations | Consumption-based | ~100 sessions/day | Minimal |

### 2.5 AgentCore Gateway

| Item | Pricing | Usage | Cost |
|---|---|---|---|
| Tool invocations | Consumption-based | ~200 tool calls/day | Minimal |

### 2.6 AgentCore Code Interpreter

| Item | Pricing | Usage | Cost |
|---|---|---|---|
| Execution time | Consumption-based | ~50 chart generations/day | Minimal |

### 2.7 Amazon S3

| Item | Unit Price | Usage | Cost |
|---|---|---|---|
| Storage | $0.023/GB/month | 3 GB | $0.07/month |
| GET requests | $0.0004/1K requests | ~3K/month | $0.001/month |
| Free tier | 5 GB + 20K GETs (12 months) | Covers usage | $0.00 |

**Monthly cost:** $0.00 (within free tier)

### 2.8 AWS Lambda

| Item | Unit Price | Usage | Cost |
|---|---|---|---|
| Requests | $0.20/1M requests | ~6K/month | $0.001 |
| Compute | $0.0000166667/GB-s | ~3K GB-seconds | $0.05 |
| Free tier | 1M requests + 400K GB-s (12 months) | Covers usage | $0.00 |

**Monthly cost:** $0.00 (within free tier)

### 2.9 Amazon CloudWatch

| Item | Unit Price | Usage | Cost |
|---|---|---|---|
| Log ingestion | $0.50/GB | ~1 GB/month | $0.50 |
| Log storage | $0.03/GB/month | ~1 GB | $0.03 |
| Free tier | 5 GB ingestion + 5 GB storage | Covers usage | $0.00 |

**Monthly cost:** $0.00 (within free tier)

## 3. Monthly Cost Summary

| Service | Free Tier | Estimated Monthly Cost |
|---|---|---|
| Bedrock Titan Embeddings | Yes (3 months) | $0.02 |
| Bedrock Claude Sonnet | No | ~$90.00 |
| AgentCore Runtime | Consumption-based | ~$10-30 (estimate) |
| AgentCore Memory | Consumption-based | ~$1-5 |
| AgentCore Gateway | Consumption-based | ~$1-5 |
| AgentCore Code Interpreter | Consumption-based | ~$1-5 |
| S3 | Yes (12 months) | $0.00 |
| Lambda | Yes (12 months) | $0.00 |
| CloudWatch | Yes (12 months) | $0.00 |
| **Total** | | **~$103-135/month** |

## 4. Cost Optimization Recommendations

### Immediate

- Use Claude Haiku instead of Sonnet for simple lookups (10x cheaper)
- Implement prompt caching for repeated context
- Cache frequent queries in Memory to avoid redundant LLM calls

### Best Practices

- Monitor token usage via CloudWatch; set billing alerts
- Use Bedrock provisioned throughput if usage exceeds 1000 queries/day
- Consider Bedrock Knowledge Base (managed) if dataset grows beyond 10 GB

## 5. Assumptions

- 100 queries/day average workload
- Average 5K input tokens + 1K output tokens per query
- 50% of queries require chart generation
- 30% of queries require live API calls via Gateway
- Free tier eligibility for new AWS accounts
