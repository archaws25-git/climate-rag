# ClimateRAG — Documentation Index

**Project:** ClimateRAG — Production-Grade RAG Pipeline for Historical Climate Trend Analysis
**Date:** 2026-03-26 | **Updated:** 2026-04-28

---

## Documents

| # | Document | Description |
|---|---|---|
| 01 | [Requirements](01-requirements.md) | Functional and non-functional requirements, stakeholders, constraints |
| 02 | [Architecture Design](02-architecture-design.md) | System context, component architecture, data flow, security |
| 03 | [Architecture Decision Records](03-architecture-decision-records.md) | 10 ADRs covering framework, model, vector store, deployment choices |
| 04 | [Data Flow & Integration](04-data-flow-integration.md) | Ingestion pipeline, runtime query flow, API specs, data schemas |
| 05 | [Cost Analysis](05-cost-analysis.md) | Service-by-service cost breakdown, free-tier optimization |
| 06 | [Security & Compliance](06-security-compliance.md) | IAM roles, Cedar policies, FedRAMP gap analysis, network security |
| 07 | [Observability & Evaluation](07-observability-evaluation.md) | OTEL trace structure, CloudWatch metrics, evaluation framework |
| 08 | [Implementation Plan](08-implementation-plan.md) | 8-hour timeline, project structure, dependencies, risk register |
| 09 | [Deployment Runbook](09-deployment-runbook.md) | Step-by-step deployment, health checks, troubleshooting, cleanup |
| 10 | [Dataset Reference](10-dataset-reference.md) | GHCN v4, GISTEMP v4, NASA POWER — details, APIs, citations |
| 11 | [CDK Infrastructure Guide](11-cdk-infrastructure-guide.md) | CDK architecture decisions, stack reference, deploy/destroy runbook |

---

## Infrastructure

| Approach | Location | Status |
|---|---|---|
| CDK (Python) | `cdk/` | ✅ Active — use this |
| Terraform | `terraform/` | ⚠️ Deprecated — null_resource workarounds; replaced by CDK |
| Manual setup scripts | `infra/` | ⚠️ Reference only — superseded by CDK |
