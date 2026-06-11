---
inclusion: always
---

# AWS Resource Provisioning Policy (MANDATORY)

## Provisioning (Create/Update)

You MAY autonomously create or update AWS resources, but you MUST:

1. **Estimate costs BEFORE deploying.** Show a table with:
   - Resource type
   - Pricing tier (free tier eligible? on-demand? per-request?)
   - Estimated monthly cost
   - Any ongoing charges (storage, compute hours, etc.)

2. **State the total estimated monthly cost** clearly before proceeding.

3. **Only proceed if estimated cost is under $10/month.** If over $10, stop and ask for explicit approval with the breakdown.

4. **Use CDK or IaC** for all provisioning — never create resources via raw CLI unless debugging.

## Deletion (Destroy)

You MUST NOT delete or destroy AWS resources without explicit user approval. This includes:
- `cdk destroy`
- `aws ... delete-*`
- `aws ... remove-*`
- Any CloudFormation stack deletion
- S3 bucket deletion or object removal
- IAM role/policy deletion

When a deletion is needed:
1. Explain WHAT will be deleted
2. Explain if it's REVERSIBLE or permanent
3. List any dependent resources that will break
4. WAIT for the user to say "yes" or "approved" before proceeding

## Tagging

All created resources MUST include these tags:
- `Project: climate-rag`
- `ManagedBy: kiro-cdk`
- `Environment: dev`
