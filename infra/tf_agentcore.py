"""
Helper script called by Terraform null_resource provisioners to manage
AgentCore resources that don't have native Terraform provider support.

Usage (called by Terraform, not directly):
  python tf_agentcore.py create_memory --region us-east-1 --name NAME --out FILE
  python tf_agentcore.py delete_memory --region us-east-1 --id-file FILE
  python tf_agentcore.py create_code_interpreter --region us-east-1 --name NAME --out FILE
  python tf_agentcore.py delete_code_interpreter --region us-east-1 --id-file FILE
  python tf_agentcore.py create_gateway --region us-east-1 --name NAME --role-arn ARN
                         --nasa-arn ARN --noaa-arn ARN --out FILE
  python tf_agentcore.py delete_gateway --region us-east-1 --id-file FILE
"""

import argparse
import boto3
import json
import os
import sys
import time


def get_client(region):
    return boto3.client("bedrock-agentcore-control", region_name=region)


def wait_active(poll_fn, resource_id, label, timeout=600):
    print(f"  Waiting for {label} to become ACTIVE...")
    for _ in range(timeout // 10):
        status = poll_fn(resource_id)
        print(f"    status: {status}")
        if status == "ACTIVE":
            return
        if status in ("FAILED", "DELETED"):
            raise RuntimeError(f"{label} entered {status} state")
        time.sleep(10)
    raise TimeoutError(f"{label} did not become ACTIVE within {timeout}s")


# ── Memory ───────────────────────────────────────────────────────

def create_memory(args):
    client = get_client(args.region)
    name = args.name

    existing = [m for m in client.list_memories().get("memorySummaries", [])
                if m["name"] == name]
    if existing:
        memory_id = existing[0]["memoryId"]
        print(f"Memory already exists: {memory_id}")
    else:
        resp = client.create_memory(
            name=name,
            description="Climate research memory for researcher context and findings",
            eventExpiryDuration=30,
            memoryStrategies=[{
                "semanticMemoryStrategy": {
                    "name": "climateSemanticMemory",
                    "namespaceConfiguration": {
                        "namespaceTemplates": [
                            "/strategies/{memoryStrategyId}/actors/{actorId}/"
                        ]
                    }
                }
            }]
        )
        memory_id = resp["memoryId"]
        print(f"Created memory: {memory_id}")
        wait_active(
            lambda mid: client.get_memory(memoryId=mid)["status"],
            memory_id, "Memory"
        )

    with open(args.out, "w") as f:
        f.write(memory_id)
    print(f"Memory ID written to {args.out}")


def delete_memory(args):
    if not os.path.exists(args.id_file):
        print(f"ID file not found: {args.id_file} — skipping")
        return
    memory_id = open(args.id_file).read().strip()
    if not memory_id:
        print("Empty ID file — skipping")
        return

    client = get_client(args.region)
    try:
        client.delete_memory(memoryId=memory_id)
        print(f"Deleted memory: {memory_id}")
    except client.exceptions.ResourceNotFoundException:
        print(f"Memory not found (already deleted): {memory_id}")
    except Exception as e:
        print(f"Warning: {e}")

    os.remove(args.id_file)


# ── Code Interpreter ─────────────────────────────────────────────

def create_code_interpreter(args):
    client = get_client(args.region)
    name = args.name

    existing = [c for c in client.list_code_interpreters().get("codeInterpreterSummaries", [])
                if c["name"] == name]
    if existing:
        ci_id = existing[0]["codeInterpreterId"]
        print(f"Code Interpreter already exists: {ci_id}")
    else:
        resp = client.create_code_interpreter(
            name=name,
            description="Sandboxed Python for climate data chart generation",
            networkConfiguration={"networkMode": "PUBLIC"}
        )
        ci_id = resp["codeInterpreterId"]
        print(f"Created Code Interpreter: {ci_id}")
        wait_active(
            lambda cid: client.get_code_interpreter(
                codeInterpreterIdentifier=cid)["status"],
            ci_id, "Code Interpreter"
        )

    with open(args.out, "w") as f:
        f.write(ci_id)
    print(f"Code Interpreter ID written to {args.out}")


def delete_code_interpreter(args):
    if not os.path.exists(args.id_file):
        print(f"ID file not found: {args.id_file} — skipping")
        return
    ci_id = open(args.id_file).read().strip()
    if not ci_id:
        print("Empty ID file — skipping")
        return

    client = get_client(args.region)
    try:
        client.delete_code_interpreter(codeInterpreterIdentifier=ci_id)
        print(f"Deleted Code Interpreter: {ci_id}")
    except client.exceptions.ResourceNotFoundException:
        print(f"Code Interpreter not found (already deleted): {ci_id}")
    except Exception as e:
        print(f"Warning: {e}")

    os.remove(args.id_file)


# ── Gateway ──────────────────────────────────────────────────────

def create_gateway(args):
    client = get_client(args.region)
    name = args.name

    existing = [g for g in client.list_gateways().get("gatewaySummaries", [])
                if g["name"] == name]
    if existing:
        gw_id = existing[0]["gatewayId"]
        print(f"Gateway already exists: {gw_id}")
    else:
        # Small delay to ensure IAM role has propagated
        time.sleep(15)
        resp = client.create_gateway(
            name=name,
            description="Gateway for climate data APIs (NASA POWER, NOAA NCEI)",
            protocolType="MCP",
            authorizerType="NONE",
            roleArn=args.role_arn,
            protocolConfiguration={"mcp": {"searchType": "SEMANTIC"}},
            exceptionLevel="DEBUG",
        )
        gw_id = resp["gatewayId"]
        print(f"Created Gateway: {gw_id}")
        wait_active(
            lambda gid: client.get_gateway(gatewayIdentifier=gid)["status"],
            gw_id, "Gateway"
        )

    # Create targets if missing
    existing_targets = {
        t["name"]
        for t in client.list_gateway_targets(
            gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
    }

    if "nasa-power-proxy" not in existing_targets:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="nasa-power-proxy",
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": args.nasa_arn,
                "toolSchema": {"inlinePayload": [{
                    "name": "nasa_power_query",
                    "description": "Query NASA POWER API for climate data",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "latitude":   {"type": "number"},
                            "longitude":  {"type": "number"},
                            "start":      {"type": "string"},
                            "end":        {"type": "string"},
                            "parameters": {"type": "string"}
                        },
                        "required": ["latitude", "longitude", "start", "end"]
                    }
                }]}
            }}},
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ]
        )
        print("Created Gateway target: nasa-power-proxy")
    else:
        print("Gateway target already exists: nasa-power-proxy")

    if "noaa-ncei-proxy" not in existing_targets:
        client.create_gateway_target(
            gatewayIdentifier=gw_id,
            name="noaa-ncei-proxy",
            targetConfiguration={"mcp": {"lambda": {
                "lambdaArn": args.noaa_arn,
                "toolSchema": {"inlinePayload": [{
                    "name": "noaa_ncei_query",
                    "description": "Query NOAA NCEI for historical climate observations",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "dataset":   {"type": "string"},
                            "stations":  {"type": "string"},
                            "startDate": {"type": "string"},
                            "endDate":   {"type": "string"},
                            "dataTypes": {"type": "string"}
                        },
                        "required": ["dataset", "startDate", "endDate"]
                    }
                }]}
            }}},
            credentialProviderConfigurations=[
                {"credentialProviderType": "GATEWAY_IAM_ROLE"}
            ]
        )
        print("Created Gateway target: noaa-ncei-proxy")
    else:
        print("Gateway target already exists: noaa-ncei-proxy")

    with open(args.out, "w") as f:
        f.write(gw_id)
    print(f"Gateway ID written to {args.out}")


def delete_gateway(args):
    if not os.path.exists(args.id_file):
        print(f"ID file not found: {args.id_file} — skipping")
        return
    gw_id = open(args.id_file).read().strip()
    if not gw_id:
        print("Empty ID file — skipping")
        return

    client = get_client(args.region)

    # Delete targets first
    try:
        targets = client.list_gateway_targets(
            gatewayIdentifier=gw_id).get("gatewayTargetSummaries", [])
        for t in targets:
            client.delete_gateway_target(
                gatewayIdentifier=gw_id,
                targetId=t["targetId"]
            )
            print(f"Deleted Gateway target: {t['name']}")
    except Exception as e:
        print(f"Warning deleting targets: {e}")

    # Delete gateway
    try:
        client.delete_gateway(gatewayIdentifier=gw_id)
        print(f"Deleted Gateway: {gw_id}")
    except client.exceptions.ResourceNotFoundException:
        print(f"Gateway not found (already deleted): {gw_id}")
    except Exception as e:
        print(f"Warning: {e}")

    os.remove(args.id_file)


# ── CLI ──────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command")

    # create_memory
    p = sub.add_parser("create_memory")
    p.add_argument("--region", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--out", required=True)

    # delete_memory
    p = sub.add_parser("delete_memory")
    p.add_argument("--region", required=True)
    p.add_argument("--id-file", required=True, dest="id_file")

    # create_code_interpreter
    p = sub.add_parser("create_code_interpreter")
    p.add_argument("--region", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--out", required=True)

    # delete_code_interpreter
    p = sub.add_parser("delete_code_interpreter")
    p.add_argument("--region", required=True)
    p.add_argument("--id-file", required=True, dest="id_file")

    # create_gateway
    p = sub.add_parser("create_gateway")
    p.add_argument("--region", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--role-arn", required=True, dest="role_arn")
    p.add_argument("--nasa-arn", required=True, dest="nasa_arn")
    p.add_argument("--noaa-arn", required=True, dest="noaa_arn")
    p.add_argument("--out", required=True)

    # delete_gateway
    p = sub.add_parser("delete_gateway")
    p.add_argument("--region", required=True)
    p.add_argument("--id-file", required=True, dest="id_file")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    dispatch = {
        "create_memory":           create_memory,
        "delete_memory":           delete_memory,
        "create_code_interpreter": create_code_interpreter,
        "delete_code_interpreter": delete_code_interpreter,
        "create_gateway":          create_gateway,
        "delete_gateway":          delete_gateway,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
